"""AppFrontend: turns core events into updates of the chat page."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from ... import config
from ...app import mentions
from ...cancel import CancelToken
from ...events import Frontend
from ...host import images as host_images
from ...tools.base import FilePreview
from ...tools.describe import describe_call, shorten
from ...types import Block, Todo, Usage
from . import icons, render

if TYPE_CHECKING:
    from ...app.reports import ContextUsage
    from ...state.settings import SettingSpec

RENDER_EVERY = 0.12  # seconds between page updates while text streams in (more if rendering is slow)
RENDER_SHARE = 0.25  # at most this share of the time goes to re-rendering the reply's last blocks
ANSWER_POLL = (0.15, 0.5)  # seconds between looks for a tap on a card: at first, and after a while
HISTORY_REQUESTS = 20  # a resumed conversation shows this many latest requests; the rest on a tap
PROGRESS_EVERY = 0.3  # seconds between progress updates of a tool card
HISTORY_OUTPUT = 4000  # characters of a saved tool's output shown when unfolded
TIME_GAP = 5 * 60  # show the time again after this many seconds without a message
AVATAR_ME, AVATAR_CLAUDE = '我', icons.icon('spark')


class Page(Protocol):
    def eval_js(self, code: str) -> str: ...


def js(fn: str, *args: object) -> str:
    """A call of a function of the page, with its arguments as JSON."""
    return '%s(%s)' % (fn, ', '.join(json.dumps(a) for a in args))


class _Streaming:
    """A text block streaming in. Its blocks that can't change any more are rendered once and
    added to the page; only the rest (the tail) is rendered again as text comes in."""

    def __init__(self, element: str) -> None:
        self.element = element
        self.parts: list[str] = []
        self.done = 0  # characters of the text rendered for good
        self.last = 0.0  # when the page was last updated
        self.every = RENDER_EVERY

    def text(self) -> str:
        if len(self.parts) > 1:
            self.parts[:] = [''.join(self.parts)]
        return self.parts[0] if self.parts else ''


def _row(side: str, inner: str) -> str:
    avatar = AVATAR_ME if side == 'me' else AVATAR_CLAUDE
    return f'<div class="row {side}"><div class="avatar">{avatar}</div>{inner}</div>'


# what the buttons under a message open; ChatView acts on them
LINK = 'pycoder://'


def _button(action: str, turn: int, name: str, label: str, extra: str = '') -> str:
    return (
        f'<a href="{LINK}{action}/{turn}" title="{label}" aria-label="{label}"{extra}>{icons.icon(name)}</a>'
    )


def request_actions(turn: int) -> str:
    return (
        '<div class="request-actions"><span class="actions">'
        + _button('copy-request', turn, 'copy', 'Copy')
        + _button('rewind', turn, 'rewind', 'Rewind to here')
        + _button('fork', turn, 'fork', 'Fork from here')
        + '</span></div>'
    )


def reply_actions(turn: int, pinned: bool = False) -> str:
    on = ' class="on"' if pinned else ''
    return (
        '<span class="actions">'
        + _button('copy-reply', turn, 'copy', 'Copy')
        + _button('fork', turn, 'fork', 'Fork from here')
        + _button('pin', turn, 'thumbtack', 'Pin as chapter', f' id="pin-{turn}"{on}')
        + '</span>'
    )


_COMMANDS = ('run_python', 'run_c', 'git', 'install_package')
_READS = ('read_file', 'list_files', 'pythonista_docs', 'python_code')
_EDITS = ('write_file', 'edit_file', 'move_file', 'delete_file')
_SEARCHES = ('search', 'web_search', 'web_fetch')
_ONE_TOOL = {
    'run_python': 'Ran a command',
    'run_c': 'Ran a command',
    'git': 'Ran git',
    'install_package': 'Installed a package',
    'read_file': 'Read a file',
    'list_files': 'Listed files',
    'pythonista_docs': 'Read the docs',
    'write_file': 'Wrote a file',
    'edit_file': 'Edited a file',
    'move_file': 'Moved a file',
    'delete_file': 'Deleted a file',
    'search': 'Searched',
    'python_code': 'Looked up code',
    'web_search': 'Searched the web',
    'web_fetch': 'Fetched a page',
    'task': 'Ran a subagent',
    'todo_write': 'Updated the plan',
    'todo_update': 'Updated the plan',
    'todo_add': 'Updated the plan',
    'use_screen': 'Used the screen',
    'look_at_screen': 'Looked at the screen',
}


def tools_label(names: Sequence[str], target: str = '') -> str:
    """One line for tool calls made in a row, as in 'Ran 2 commands, read 3 files'."""
    if len(names) == 1:
        one = _ONE_TOOL.get(names[0], f'Used {names[0]}')
        return f'{one} · {shorten(target, 60)}' if target else one
    kinds = (
        (_COMMANDS, 'ran {} command'),
        (_READS, 'read {} file'),
        (_EDITS, 'edited {} file'),
        (_SEARCHES, 'made {} search'),
        (('task',), 'ran {} subagent'),
    )
    parts = []
    for kind, words in kinds:
        count = sum(n in kind for n in names)
        if count:
            parts.append(words.format(count) + ('' if count == 1 else 'es' if words.endswith('h') else 's'))
    known = sum(n in kind for kind, _ in kinds for n in names)
    other = sum(not n.startswith('todo_') for n in names) - known
    if other > 0:
        parts.append(f'used {other} tool' + ('' if other == 1 else 's'))
    text = ', '.join(parts) or f'used {len(names)} tools'
    return text[0].upper() + text[1:]


def queued_actions(number: int) -> str:
    return (
        f'<span class="actions"><a href="{LINK}queue-cancel/{number}" title="Cancel and edit message" '
        f'aria-label="Cancel and edit message">{icons.icon("close")}</a>'
        f'<a class="words" href="{LINK}queue-now/{number}">Send now</a></span>'
    )


def chapter_line(turn: int, title: str) -> str:
    return f'<div class="chapter" id="ch-{turn}"><span>{render.escape(title)}</span></div>'


def user_bubble(text: str, images: Sequence[Block] = (), attached: Sequence[str] = ()) -> str:
    """The user's message: thumbnails of its images, its text, and chips for the @files that went
    with it."""
    shown = (
        host_images.thumbnail(str(source.get('media_type')), str(source.get('data')))
        for source in (b.get('source') or {} for b in images)
        if source.get('type') == 'base64'
    )
    thumbs = ''.join(f'<img src="data:{render.escape(kind)};base64,{data}">' for kind, data in shown)
    chips = ''.join(f'<span>{icons.icon("paperclip")} {render.escape(name)}</span>' for name in attached)
    return (
        f'<div class="avatar">{AVATAR_ME}</div><div class="bubble">'
        + (f'<div class="thumbs">{thumbs}</div>' if thumbs else '')
        + render.escape(text)
        + (f'<div class="attach">{chips}</div>' if chips else '')
        + '</div>'
    )


def shell_card(command: str, output: str, ok: bool = True) -> str:
    return (
        f'<div class="{"shell" if ok else "shell failed"}"><div class="cmd">$ {render.escape(command)}</div>'
        f'<pre>{render.escape(output)}</pre></div>'
    )


_SHELL_NOTE = re.compile(
    r'<shell-command>(.*?)</shell-command>\s*<shell-output>\n?(.*?)\n?</shell-output>', re.S
)
_FILE_NOTE = re.compile(r'^<(?:file|folder) path="([^"]*)">')


@dataclass
class _Subagent:
    description: str
    started: float
    step: str = ''  # what it did last


class AppFrontend(Frontend):
    def __init__(
        self,
        page: Page,
        cancel: CancelToken,
        ask_text: Callable[[str, str, bool], str | None],
        choose: Callable[[str, Sequence[str], int | None], int | None],
        on_change: Callable[[], None],
        header: Callable[[], list[str]] = list,
        cover_input: Callable[[bool], None] = lambda covered: None,
        side: Callable[[str, str], None] | None = None,
        session_pane: Callable[[], None] = lambda: None,
        files_pane: Callable[[], None] = lambda: None,
        on_activity: Callable[[], None] = lambda: None,
        add_to_input: Callable[[str], None] = lambda text: None,
    ) -> None:
        self.page = page
        self.side = side  # shows a /btw exchange in the side chat
        self.session_pane = session_pane  # opens the session pane (/session)
        self.files_pane = files_pane  # opens the files pane (/files)
        self.turn_number = 0  # the request being answered
        self._add_to_input = add_to_input
        self.on_activity = on_activity  # subagents or background jobs started or ended
        self.todos: list[Todo] = []
        self.running: dict[str, _Subagent] = {}  # task call id -> the subagent running for it
        self.cover_input = cover_input
        self.cancel = cancel
        self._ask_text = ask_text
        self._choose = choose
        self.on_change = on_change  # settings may have changed (bypass); refresh the controls
        self.header = header  # lines for the session header
        self.seq = 0
        self.id_lock = threading.Lock()  # subagents running at once add to the page from their threads
        self.stream_mark = 0
        self.turn = ''  # the column of the current assistant turn
        self.group = ''  # the fold around the tool calls being made in a row, if any
        self.group_tools: list[tuple[int, str, str]] = []  # in it: (id number, name, target)
        self.thinking = ''  # id of the open thinking block
        self.thought: list[str] = []  # thinking not yet shown
        self.thought_at = 0.0  # when thinking was last shown
        self.thought_text = ''  # all of the open block's thinking so far
        self.thought_line = ''  # the line standing for it on the page
        self.thought_since = 0.0  # when the open block began
        self.texts: dict[int, _Streaming] = {}  # stream index -> text block streaming in
        self.tools: dict[int, _ToolInput] = {}  # stream index -> card state while input streams
        self.cards: dict[str, str] = {}  # tool_use id -> card id
        self.card = ''  # card of the tool currently running
        self.shown: set[str] = set()  # cards that already show the tool's output, a diff or an error
        self.subagents: dict[str, str] = {}  # task call id -> the body of its subagent's progress
        self.last_time = 0.0  # when the last time divider was shown
        self.previewed: set[str] = set()  # cards whose approval already showed the file change

    # ---- page access

    def call(self, fn: str, *args: object) -> None:
        self.page.eval_js(js(fn, *args))

    def run(self, *calls: str) -> None:
        """Several calls (from js()) in one trip to the page."""
        self.page.eval_js(';'.join(calls))

    def new_id(self, prefix: str) -> str:
        with self.id_lock:
            self.seq += 1
            return f'{prefix}{self.seq}'

    def _ensure_turn(self) -> str:
        if not self.turn:
            self.turn = self.new_id('turn')
            self.call(
                'add',
                'chat',
                self.new_id('row'),
                'row c',
                f'<div class="avatar">{AVATAR_CLAUDE}</div><div class="col" id="{self.turn}"></div>',
            )
        return self.turn

    def request(
        self, text: str, images: Sequence[Block] = (), attached: Sequence[str] = (), turn: int = 0
    ) -> None:
        now = time.time()
        self.turn_number = turn
        self._close_group()
        calls = []
        if now - self.last_time > TIME_GAP:
            calls.append(js('add', 'chat', self.new_id('t'), 'time', f'<span>{clock(now)}</span>'))
        self.last_time = now
        row = f'req-{turn}' if turn else self.new_id('u')
        calls.append(js('add', 'chat', row, 'row me', user_bubble(text, images, attached)))
        if turn:
            calls.append(
                js('add', 'chat', self.new_id('a'), 'request-actions', _inner(request_actions(turn)))
            )
        calls.append(js('toBottom'))  # sending a message brings the reply into view, wherever the user was
        self.run(*calls)
        self.turn = ''
        self._ensure_turn()

    def _close_thinking(self) -> None:
        if self.thinking:
            took = render.elapsed(time.time() - self.thought_since)
            self.run(*self._thought(), js('endThinking', self.thinking, f'Thought for {took}'))
            self.thinking = ''

    def _thought(self) -> list[str]:
        """The call that shows the thinking received since it was last shown, if any."""
        if not self.thought:
            return []
        text = ''.join(self.thought)
        self.thought.clear()
        self.thought_at = time.time()
        self.thought_text += text
        calls = [js('appendText', self.thinking + 't', text)]
        line = render.thought_line(self.thought_text)
        if line and line != self.thought_line:
            self.thought_line = line
            calls.append(js('setHtml', self.thinking + 'l', render.escape(line)))
        return calls

    # ---- streaming

    def thinking_start(self) -> None:
        self._close_thinking()
        self.thinking = self.new_id('th')
        self.thought_text = self.thought_line = ''
        self.thought_since = time.time()
        self.call(
            'add',
            self.group + '-b' if self.group else self._ensure_turn(),
            self.thinking,
            'thinking live',
            f'<details><summary>{icons.icon("spark")}<span class="what" id="{self.thinking}l">Thinking</span>'
            f'<span class="secs" data-since="{int(self.thought_since * 1000)}">0s</span></summary>'
            f'<div id="{self.thinking}t"></div></details>',
        )

    def thinking_delta(self, text: str) -> None:
        if not self.thinking:
            self.thinking_start()
        self.thought.append(text)
        if time.time() - self.thought_at >= RENDER_EVERY:
            self.run(*self._thought())

    def text_delta(self, index: int, text: str) -> None:
        self._close_thinking()
        self._close_group()
        entry = self.texts.get(index)
        if entry is None:
            entry = self.texts[index] = _Streaming(self.new_id('t'))
            self.call('add', self._ensure_turn(), entry.element, 'bubble text', '')
        entry.parts.append(text)
        if time.time() - entry.last >= entry.every:
            self._render_streaming(entry)

    def _render_streaming(self, entry: _Streaming) -> None:
        """Show the text so far: render the blocks finished since last time, once, and the tail; and
        wait longer before the next update when that took long (a big table or code block)."""
        started = time.perf_counter()
        text = entry.text()
        cut = render.settled(text, entry.done)
        done = render.md_to_html(text[entry.done : cut]) if cut > entry.done else ''
        entry.done = cut
        self.call('streamHtml', entry.element, done, render.md_to_html(text[cut:]))
        entry.every = max(RENDER_EVERY, (time.perf_counter() - started) / RENDER_SHARE)
        entry.last = time.time()

    def _finish_text(self, entry: _Streaming) -> None:
        """The whole text rendered at once, as a saved conversation shows it."""
        self.call('setHtml', entry.element, render.md_to_html(entry.text()))

    def text_done(self, index: int) -> None:
        entry = self.texts.pop(index, None)
        if entry:
            self._finish_text(entry)

    def tool_start(self, index: int, block: Block) -> None:
        self._close_thinking()
        cid = self.new_id('tool')
        self.tools[index] = _ToolInput(cid)
        if block['type'] == 'tool_use':
            self.cards[block['id']] = cid
        name = block['name']
        if not self.group:
            self.group = self.new_id('g')
            self.group_tools = []
            self.call(
                'add',
                self._ensure_turn(),
                self.group,
                'tools',
                f'<details open id="{self.group}-d"><summary id="{self.group}-s"></summary>'
                f'<div id="{self.group}-b"></div></details>',
            )
        self.group_tools.append((int(cid[len('tool') :]), name, ''))
        self._label_group()
        self.call(
            'add',
            self.group + '-b',
            cid,
            'card',
            f'<div class="head"><span class="icon">{icons.tool_icon(name)}</span>'
            f'<span class="name">{render.escape(name)}</span><span class="target" id="{cid}-target"></span>'
            f'<span class="meta" id="{cid}-meta"></span></div>',
        )

    def _label_group(self) -> None:
        tools = self.group_tools
        target = tools[0][2] if len(tools) == 1 else ''
        self.call('setHtml', self.group + '-s', render.escape(tools_label([t[1] for t in tools], target)))

    def _close_group(self) -> None:
        """The tool calls in a row are over: fold them into their one line."""
        if self.group:
            self.call('closeDetails', self.group + '-d')
            self.group = ''

    def tool_input(self, index: int, chunk: str) -> None:
        t = self.tools.get(index)
        if not t:
            return
        t.size += len(chunk.encode())
        if not t.target:
            t.head.append(chunk)
        if time.time() - t.last < PROGRESS_EVERY:
            return
        t.last = time.time()
        calls = []
        if not t.target:  # the input's start, until it names what the tool works on
            raw = ''.join(t.head)
            t.head[:] = [raw]
            for key in ('path', 'query', 'url', 'pattern', 'description', 'command'):
                marker = f'"{key}"'
                if marker in raw:
                    parts = raw.split(marker, 1)[1].split('"')
                    if len(parts) >= 3:
                        t.target = True
                        t.head.clear()
                        calls.append(js('setHtml', f'{t.id}-target', render.escape(shorten(parts[1], 60))))
                    break
        calls.append(js('setHtml', f'{t.id}-meta', 'writing… ' + _size(t.size)))
        self.run(*calls)

    def tool_input_done(self, index: int, block: Block) -> None:
        t = self.tools.pop(index, None)
        if not t:
            return
        inp = block.get('input') or {}
        for i, (number, name, _) in enumerate(self.group_tools):
            if t.id == f'tool{number}':
                self.group_tools[i] = (number, name, describe_call(block['name'], inp))
                self._label_group()
        body = inp.get('content') or inp.get('code') or inp.get('new_str') or ''
        meta = _size(t.size) + (f' · {len(body.splitlines())} lines' if body else '') if t.size > 300 else ''
        self.run(
            js('setHtml', f'{t.id}-target', render.escape(describe_call(block['name'], inp))),
            js('setHtml', f'{t.id}-meta', meta),
        )

    def server_result(self, kind: str, count: int) -> None:
        self.call('add', self._ensure_turn(), self.new_id('r'), 'footer', f'↳ {kind}: {count} result(s)')

    def stream_start(self) -> None:
        self.stream_mark = self.seq  # ids above this belong to the response now streaming

    def stream_discarded(self) -> None:
        """A failed attempt is retried: what it showed goes, so the retry isn't shown twice."""
        self.call('removeAfter', self._ensure_turn(), self.stream_mark)
        if self.group:
            if int(self.group[1:]) > self.stream_mark:  # it went with the rest
                self.group = ''
            else:
                self.call('removeAfter', self.group + '-b', self.stream_mark)
                self.group_tools = [t for t in self.group_tools if t[0] <= self.stream_mark]
                self._label_group()
        self.texts.clear()
        self.tools.clear()
        self.thinking = ''
        self.thought.clear()

    def stream_end(self) -> None:
        self._close_thinking()
        for entry in self.texts.values():
            self._finish_text(entry)
        self.texts.clear()
        self.tools.clear()

    # ---- tools running

    def tool_run(self, block: Block) -> None:
        """Only the tool that is running shows the progress line (the page shows it only if the
        tool takes a moment, so quick reads don't flicker)."""
        self.card = self.cards.get(block['id'], '')
        if self.card:
            self.call('add', self.card, self.card + '-bar', 'bar', '<div></div>')

    def tools_run(self, blocks: Sequence[Block]) -> None:
        """Calls that run at the same time (subagents): each card shows it is running."""
        for block in blocks:
            self.tool_run(block)
        self.card = ''

    def tool_done(self, block: Block, result: str = '') -> None:
        """What a tool returned, when it showed nothing itself: a short answer on one line, a long
        one folded away (as saved conversations show it)."""
        self.card = self.cards.get(block['id'], self.card)
        if self.running.pop(block['id'], None):  # a subagent that ended without its report
            self.on_activity()
        self._card_done()
        if not self.card or self.card in self.shown or not result.strip():
            return
        text = result.strip()
        if '\n' not in text and len(text) <= 100:
            self._card_add('sub', '→ ' + render.escape(text))
        else:
            self._card_add('', _folded_output(text))

    def _card_add(self, cls: str, html: str) -> None:
        self.call('add', self.card or self._ensure_turn(), self.new_id('r'), cls, html)

    def _card_done(self) -> None:
        if self.card:
            self.call('remove', self.card + '-bar')

    def confirm(
        self, name: str, inp: Block, change: FilePreview | None = None, rule: str = ''
    ) -> tuple[str, str | None]:
        self._card_done()  # waiting for the user, not running
        qid = self.new_id('ask')
        preview = ''
        if change is not None:
            path, old, new = change
            preview = render.code_html(new, path) if old is None else render.diff_html(old, new, path)
        if name == 'run_python' and inp.get('code'):
            preview = f'<details open><summary>code</summary>{render.code_html(inp["code"])}</details>'
        if change is not None and self.card:
            self.previewed.add(self.card)
        self._card_add(
            '',
            preview + f'<div class="ask" id="{qid}">'
            f'<button class="yes" onclick="answer(\'{qid}\',\'yes\')">Allow</button>'
            + (
                f'<button class="always" onclick="answer(\'{qid}\',\'always\')">Always allow '
                f'{render.escape(rule)}</button>'
                if rule
                else ''
            )
            + f'<button class="no" onclick="answer(\'{qid}\',\'no\')">Deny</button></div>',
        )
        answer = self._wait_answer(qid)
        if not answer:  # stopped
            self.call('remove', qid)
            return 'no', None
        if answer == 'no':
            return 'no', self._ask_text('Denied', 'Tell Claude what to do instead (optional)', False) or None
        if answer == 'always':
            self.on_change()
        if self.card:  # approved: now it runs
            self.call('add', self.card, self.card + '-bar', 'bar', '<div></div>')
        return answer, None

    def approve_plan(self, plan: str) -> tuple[str, str | None]:
        qid = self.new_id('plan')
        self._card_add(
            'plan',
            f'<div class="plan-title">Plan</div><div class="text">{render.md_to_html(plan)}</div>'
            f'<div class="ask" id="{qid}">'
            f'<button class="yes" onclick="answer(\'{qid}\',\'acceptEdits\')">Yes, auto-accept edits</button>'
            f'<button class="always" onclick="answer(\'{qid}\',\'default\')">Yes, ask each change</button>'
            f'<button class="always" onclick="answer(\'{qid}\',\'keep\')">Keep planning</button></div>',
        )
        answer = self._wait_answer(qid)
        if not answer:  # stopped
            self.call('remove', qid)
            return 'keep', None
        if answer == 'keep':
            return 'keep', self._ask_text(
                'Keep planning', 'What should change in the plan? (optional)', False
            )
        self.on_change()
        return answer, None

    def _wait_answer(self, qid: str) -> str:
        """The user's tap on a card ('' if stopped first): looked for often at first, then less, as
        the page can only be asked."""
        delay, slowest = ANSWER_POLL
        while not self.cancel.cancelled:
            answer = self.page.eval_js(js('takeAnswer', qid))
            if answer:
                return answer
            time.sleep(delay)
            delay = min(slowest, delay * 1.5)
        return ''

    def file_written(self, path: str, old: str | None, new: str) -> None:
        self._card_done()
        self.shown.add(self.card)
        if self.card and self.card in self.previewed:
            return  # the approval card already shows this change
        if old is None:
            self._card_add(
                '',
                f'<details><summary>created · {len(new.splitlines())} lines</summary>'
                f'{render.code_html(new, path)}</details>',
            )
        else:
            self._card_add('', render.diff_html(old, new, path))

    def run_output(self, text: str) -> None:
        self._card_done()
        self.shown.add(self.card)
        lines = text.splitlines()
        body = f'<pre class="out">{render.escape(text)}</pre>'
        if len(lines) > 12:
            body = f'<details><summary>output · {len(lines)} lines</summary>{body}</details>'
        self._card_add('', body)

    def tool_error(self, message: str, level: str = 'error') -> None:
        self._card_done()
        self.shown.add(self.card)
        self._card_add('denied' if level == 'denied' else 'err', '✗ ' + render.escape(message))

    def todos_updated(self, todos: Sequence[Todo]) -> None:
        """Shown natively, above the input and in the session pane: a pinned layer in the web page
        was left over the content while the page scrolled."""
        self._card_done()
        self.todos = list(todos)
        self.on_activity()

    def shell_output(self, command: str, output: str, ok: bool) -> None:
        sid = self.new_id('sh')
        self.call('add', 'chat', sid, 'shell-row', shell_card(command, output, ok))
        self.turn = ''

    def subagent_start(self, description: str, key: str = '') -> None:
        self.running[key] = _Subagent(description, time.time())
        self.on_activity()
        body = self.new_id('sub')
        self.subagents[key] = body
        card = self.cards.get(key) or self.card
        self.call('add', card or self._ensure_turn(), self.new_id('r'), '', f'<div id="{body}"></div>')

    def subagent_progress(self, text: str, key: str = '') -> None:
        if key in self.running:
            self.running[key].step = text
        body = self.subagents.get(key)
        if body:
            self.call('add', body, self.new_id('s'), 'sub', render.escape('· ' + shorten(text, 80)))

    def subagent_done(self, summary: str, key: str = '') -> None:
        card = self.cards.get(key) or self.card
        if card:
            self.call('remove', card + '-bar')
            self.shown.add(card)
        self.call(
            'add',
            card or self._ensure_turn(),
            self.new_id('r'),
            '',
            f'<details><summary>report · {len(summary)} characters</summary>'
            f'<div class="text">{render.md_to_html(summary)}</div></details>',
        )
        self.subagents.pop(key, None)
        self.running.pop(key, None)
        self.on_activity()

    def jobs_changed(self) -> None:
        self.on_activity()

    def show_session(self) -> None:
        self.session_pane()

    def show_files(self) -> None:
        self.files_pane()

    # ---- session

    def notice(self, text: str, level: str = 'info') -> None:
        """A short note as a centred line; a report (several lines) as a card."""
        block = ' block' if '\n' in text else ''
        # during a reply the note goes in its place among the reply's cards, not below them all
        self.call(
            'add',
            self.turn or 'chat',
            self.new_id('n'),
            f'notice {level}{block}',
            f'<span>{render.escape(text)}</span>',
        )

    def side_answer(self, question: str, answer: str) -> None:
        if self.side is not None:
            self.side(question, answer)
        else:
            super().side_answer(question, answer)

    def turn_done(self, model: str, usage: Usage, cost: float, turn_cost: float = 0.0) -> None:
        for cid in self.cards.values():
            self.call('remove', cid + '-bar')
        info = config.MODEL_BY_ID.get(model)
        short = info.short if info else model
        details = (
            f'{model} · in {usage.get("input_tokens", 0)}'
            f' · cache read {usage.get("cache_read_input_tokens", 0)}'
            f' · out {usage.get("output_tokens", 0)} · session ${cost:.2f}'
        )
        self.call(
            'add',
            self._ensure_turn(),
            self.new_id('f'),
            'footer',
            (reply_actions(self.turn_number) if self.turn_number else '')
            + f'<span title="{render.escape(details)}">{short} · ${turn_cost:.3f}</span>',
        )
        self._close_group()
        self.cards.clear()
        self.card = ''
        self.turn = ''  # the reply is over: notes from commands go below it, not into it

    def compacting(self) -> None:
        self.notice('Summarizing the conversation…')

    def compacted(self, summary: str) -> None:
        self.notice(f'Conversation summarized ({len(summary)} characters)')

    def session_cleared(self) -> None:
        self.todos = []
        self.on_activity()
        self.turn = ''
        self.last_time = 0.0
        self.show_header()

    def settings_changed(self) -> None:
        self.on_change()

    def edit_settings(
        self,
        specs: Sequence[SettingSpec],
        current: dict[str, Any],
        tabs: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    ) -> dict[str, Any] | None:
        self.call('showSettings', render.settings_html(specs, current, tabs))
        self.cover_input(True)  # the sheet is in the page; the native input bar would stay usable
        try:
            return self._wait_for_settings()
        finally:
            self.cover_input(False)

    def _wait_for_settings(self) -> dict[str, Any] | None:
        self.cancel.reset()
        answer = self._wait_answer('settings')
        if not answer:  # Stop closes the sheet
            self.call('closeSettings', False)
            self.page.eval_js("takeAnswer('settings')")
            return {}
        if answer == 'cancel':
            return {}
        values: dict[str, Any] = json.loads(answer)
        return values

    def show_context(self, usage: ContextUsage, text: str) -> None:
        self.call('add', 'chat', self.new_id('ctx'), 'context', render.context_html(usage))

    def show_header(self) -> None:
        """The start-of-session block: version, model, workspace, skills."""
        lines = self.header()
        if not lines:
            self.call('clearChat', '')
        else:
            # the second line (model · effort) is kept current by the view as settings change
            rows = ''.join(
                f'<div{" id=header-model" if i == 1 else ""}>{render.escape(line)}</div>'
                for i, line in enumerate(lines[1:], 1)
            )
            html = (
                f'<div class="header"><div class="logo">✻</div><div><b>{render.escape(lines[0])}</b>'
                f'{rows}</div></div>'
            )
            self.call('clearChat', html)

    def add_to_input(self, text: str) -> None:
        self._add_to_input(text)

    def queued(self, text: str) -> int:
        """Show a message waiting for this reply to end. Returns the number to refer to it by."""
        row = self.new_id('q')
        number = int(row[1:])
        self.run(
            js('add', 'chat', row, 'row me queued', user_bubble(text)),
            js('add', 'chat', f'qa{number}', 'request-actions', queued_actions(number)),
            js('toBottom'),
        )
        return number

    def unqueued(self, number: int) -> None:
        self.run(js('remove', f'q{number}'), js('remove', f'qa{number}'))

    def chapter_changed(self, turn: int, title: str) -> None:
        self.call('setChapter', turn, f'<span>{render.escape(title)}</span>' if title else '')

    def show_chapter(self, turn: int) -> None:
        self.call('toChapter', turn)

    def session_loaded(
        self,
        title: str,
        messages: Sequence[Block],
        times: Mapping[int, float] | None = None,
        turns: Mapping[int, int] | None = None,
        chapters: Mapping[int, str] | None = None,
    ) -> None:
        self.turn = ''
        self.turn_number = 0
        self.group = ''
        self.last_time = max(times.values()) if times else 0.0
        start = _latest_requests(messages, HISTORY_REQUESTS)
        html = _title_html(title)
        if start:
            more = sum(1 for m in messages[:start] if _said(m))
            html += (
                f'<div class="notice" id="earlier"><span><a href="#" onclick="showEarlier();return false">'
                f'Show {more} earlier request{"s" if more != 1 else ""}</a></span></div>'
            )
        self.run(
            js('clearChat', html + _history(messages, times, start, None, turns, chapters)), js('toBottom')
        )
        if start:  # rendered after the latest ones are on screen; the page keeps it until asked
            self.call('setEarlier', _history(messages, times, 0, start, turns, chapters))

    # ---- questions

    def choose(self, title: str, options: Sequence[str], current: int | None = None) -> int | None:
        return self._choose(title, options, current)

    def ask_text(self, title: str, message: str = '', secret: bool = False) -> str | None:
        return self._ask_text(title, message, secret)


class _ToolInput:
    """A tool call's input streaming in, for its card's progress line."""

    def __init__(self, card: str) -> None:
        self.id = card
        self.size = 0  # bytes so far
        self.head: list[str] = []  # the input until it names what the tool works on
        self.target = False  # the card shows that already
        self.last = 0.0  # when the card was last updated


def _size(n: int) -> str:
    return f'{n} B' if n < 1024 else f'{n / 1024:.1f} KB'


def clock(t: float) -> str:
    """WeChat-style time: 14:05 today, 10-30 14:05 on another day."""
    same_day = time.strftime('%Y%m%d', time.localtime(t)) == time.strftime('%Y%m%d')
    return time.strftime('%H:%M' if same_day else '%m-%d %H:%M', time.localtime(t))


def history_html(title: str, messages: Sequence[Block], times: Mapping[int, float] | None = None) -> str:
    """A saved conversation as static HTML, laid out like it was live: one Claude row per reply
    (however many messages its tool calls took), bubbles for text, cards for tool calls with their
    output folded away."""
    return _title_html(title) + _history(messages, times)


def _title_html(title: str) -> str:
    return f'<div class="notice"><span>{render.escape(title)}</span></div>'


def _said(message: Block) -> bool:
    """Whether a message shows as a request (as _user_history shows it): typed text, an image or
    a `!` command, not only tool results and pycoder's notes."""
    if message['role'] != 'user':
        return False
    content = message['content']
    blocks: list[Block] = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
    for b in blocks:
        text = str(b.get('text') or '')
        if b.get('type') == 'image':
            return True
        note = _FILE_NOTE.match(text) or mentions.is_context(b)
        if b.get('type') == 'text' and text and (_SHELL_NOTE.fullmatch(text.strip()) or not note):
            return True
    return False


def _latest_requests(messages: Sequence[Block], count: int) -> int:
    """Where the latest `count` requests start in messages (0: there are no more than that)."""
    seen = 0
    for i in range(len(messages) - 1, 0, -1):
        if _said(messages[i]):
            seen += 1
            if seen == count:
                return i
    return 0


def _inner(html: str) -> str:
    """What is inside a one-element piece of HTML, for add(), which makes the element itself."""
    return html[html.index('>') + 1 : html.rindex('</')]


def _history(
    messages: Sequence[Block],
    times: Mapping[int, float] | None,
    start: int = 0,
    stop: int | None = None,
    turns: Mapping[int, int] | None = None,
    chapters: Mapping[int, str] | None = None,
) -> str:
    """messages[start:stop] as HTML (they start with a request, so no reply is cut in two)."""
    parts: list[str] = []
    results = _tool_results(messages)  # all: a request can share a message with the results before it
    reply: list[str] = []  # the reply being collected, until the user says something
    number = 0  # the request it answers
    chapters = chapters or {}
    tools: list[tuple[str, str, str]] = []  # the calls in a row being collected: name, target, card

    def end_tools() -> None:
        if tools:
            label = tools_label([t[0] for t in tools], tools[0][1] if len(tools) == 1 else '')
            cards = ''.join(t[2] for t in tools)
            reply.append(
                f'<div class="tools"><details><summary>{render.escape(label)}</summary>'
                f'<div>{cards}</div></details></div>'
            )
            tools.clear()

    def end_reply() -> None:
        end_tools()
        if reply:
            parts.append(_row('c', '<div class="col">%s</div>' % ''.join(reply)))
            if number:
                parts.append(f'<div class="footer">{reply_actions(number, number in chapters)}</div>')
            reply.clear()

    shown = 0.0
    for i in range(start, len(messages) if stop is None else stop):
        message = messages[i]
        content = message['content']
        blocks: list[Block] = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
        if message['role'] == 'user':
            said = _user_history(blocks)
            if not said:
                continue  # tool results: part of the reply
            end_reply()
            when = (times or {}).get(i)
            if when and when - shown > TIME_GAP:
                parts.append(f'<div class="time"><span>{clock(when)}</span></div>')
                shown = when
            number = (turns or {}).get(i, 0)
            if number:
                said[-1] = said[-1].replace(
                    '<div class="row me">', f'<div class="row me" id="req-{number}">', 1
                )
                if number in chapters:
                    said.insert(-1, chapter_line(number, chapters[number]))
                said.append(request_actions(number))
            parts += said
            continue
        for b in blocks:
            if b.get('type') == 'text' and b.get('text'):
                end_tools()
                reply.append(f'<div class="bubble text">{render.md_to_html(b["text"])}</div>')
            elif b.get('type') in ('tool_use', 'server_tool_use'):
                name = str(b['name'])
                target = describe_call(name, b.get('input') or {})
                card = (
                    f'<div class="card"><div class="head"><span class="icon">{icons.tool_icon(name)}</span>'
                    f'<span class="name">{render.escape(name)}</span>'
                    f'<span class="target">{render.escape(target)}</span></div>'
                    f'{_folded_output(results.get(str(b.get("id")), ""))}</div>'
                )
                tools.append((name, target, card))
            elif b.get('type') == 'compaction':
                end_reply()
                summary = str(b.get('content') or '')
                parts.append(
                    '<div class="card summary"><details><summary>Earlier turns were summarized</summary>'
                    f'<div class="text">{render.md_to_html(summary)}</div></details></div>'
                    if summary
                    else '<div class="notice"><span>Earlier turns were summarized</span></div>'
                )
    end_reply()
    return ''.join(parts)


def _tool_results(messages: Sequence[Block]) -> dict[str, str]:
    """What each tool call returned, by its id (text only)."""
    out: dict[str, str] = {}
    for message in messages:
        content = message['content']
        if message['role'] != 'user' or isinstance(content, str):
            continue
        for b in content:
            if b.get('type') == 'tool_result':
                c = b.get('content')
                text = (
                    c
                    if isinstance(c, str)
                    else '\n'.join(x.get('text', '') for x in c or [] if x.get('type') == 'text')
                )
                out[str(b.get('tool_use_id'))] = text
    return out


def _folded_output(text: str) -> str:
    text = text.strip()
    if not text:
        return ''
    lines = text.splitlines()
    if len(text) > HISTORY_OUTPUT:
        text = text[:HISTORY_OUTPUT] + '\n…'
    return (
        f'<details><summary>output · {len(lines)} line{"s" if len(lines) != 1 else ""}</summary>'
        f'<pre class="out">{render.escape(text)}</pre></details>'
    )


def _user_history(blocks: Sequence[Block]) -> list[str]:
    """A saved user message: `!` commands as shell cards, typed text as bubbles with their
    attachments; tool results and pycoder's own notes are left out."""
    out: list[str] = []
    texts: list[str] = []
    images: list[Block] = []
    attached: list[str] = []

    def flush() -> None:
        if texts or images:
            out.append(f'<div class="row me">{user_bubble(chr(10).join(texts), images, attached)}</div>')
        texts.clear()
        attached.clear()
        images.clear()

    for b in blocks:
        kind, text = b.get('type'), str(b.get('text') or '')
        if kind == 'image':
            images.append(b)
        elif kind != 'text' or not text:
            continue
        elif (shell := _SHELL_NOTE.fullmatch(text.strip())) is not None:
            flush()
            out.append(f'<div class="shell-row">{shell_card(shell.group(1), shell.group(2))}</div>')
        elif (file := _FILE_NOTE.match(text)) is not None:
            attached.append(file.group(1))
        elif not mentions.is_context(b):
            texts.append(text)
    flush()
    return out

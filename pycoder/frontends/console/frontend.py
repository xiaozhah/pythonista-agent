"""ConsoleFrontend: how each core event looks in the console."""

from __future__ import annotations

import difflib
import json
import re
import time
from collections.abc import Mapping, Sequence

from ...app import mentions
from ...events import Frontend
from ...host.env import IN_PYTHONISTA
from ...tools.base import FilePreview
from ...tools.describe import describe_call, shorten
from ...tools.todos import format_todos
from ...types import Block, Todo, Usage
from .markdown import MarkdownStream
from .output import ask, out


def fmt_size(n: int) -> str:
    return f'{n} B' if n < 1024 else f'{n / 1024:.1f} KB'


class ToolProgress:
    """A tool call's line, printed the moment the call starts and extended while its input streams in.

    A whole file for write_file can take minutes to generate; dots and the running size show it is
    still moving. Everything is appended to one line, so the console needs no \\r support.
    """

    TARGET = re.compile(r'"(?:path|query|url|pattern|description)"\s*:\s*"((?:[^"\\]|\\.)*)"')
    DOT_EVERY = 0.5  # seconds between dots
    SIZE_EVERY = 10  # show the running size after this many dots

    def __init__(self, block: Block) -> None:
        self.name = block['name']
        self.color = 'magenta' if block['type'] == 'tool_use' else 'blue'
        self.raw = ''
        self.target_shown = False
        self.dots = 0
        self.last = time.time()
        out('⏺ ' + self.name, self.color, end='')

    def feed(self, chunk: str) -> None:
        self.raw += chunk
        if not self.target_shown:
            m = self.TARGET.search(self.raw)
            if m:
                try:
                    target = json.loads(f'"{m.group(1)}"')
                except ValueError:
                    target = m.group(1)
                out(f'({shorten(target, 60)})', self.color, end='')
                self.target_shown = True
        now = time.time()
        if now - self.last >= self.DOT_EVERY:
            self.last = now
            self.dots += 1
            out(' ' if self.dots == 1 else '', end='')
            out('·', 'dim', end='')
            if self.dots % self.SIZE_EVERY == 0:
                out(f' {fmt_size(len(self.raw.encode()))} ', 'dim', end='')

    def finish(self, inp: Block) -> None:
        if not self.target_shown:
            out(f'({describe_call(self.name, inp)})', self.color, end='')
        if self.dots:
            body = inp.get('content') or inp.get('code') or inp.get('new_str') or ''
            lines = f', {len(body.splitlines())} lines' if body else ''
            out(f' {fmt_size(len(self.raw.encode()))}{lines}', 'dim', end='')
        out()


def print_diff(old: str, new: str, path: str, limit: int = 60) -> None:
    lines = list(
        difflib.unified_diff(old.splitlines(), new.splitlines(), 'a/' + path, 'b/' + path, n=2, lineterm='')
    )[2:]
    if not lines:
        out('  (no changes)', 'dim')
        return
    colors = {'+': 'green', '-': 'red', '@': 'blue'}
    for line in lines[:limit]:
        out('  ' + line, colors.get(line[:1], 'dim'))
    if len(lines) > limit:
        out(f'  ... {len(lines) - limit} more diff lines', 'dim')


class ConsoleFrontend(Frontend):
    def __init__(self) -> None:
        self.mode: str | None = None  # what the current console line belongs to, for line breaks
        self.renderers: dict[int, MarkdownStream] = {}
        self.progress: dict[int, ToolProgress] = {}

    def _switch(self, kind: str | None) -> None:
        if self.mode != kind:
            if self.mode is not None:
                out()
            self.mode = kind

    # ---- streaming

    def thinking_delta(self, text: str) -> None:
        self._switch('thinking')
        out(text, 'dim', end='')

    def text_delta(self, index: int, text: str) -> None:
        self._switch('text')
        self.renderers.setdefault(index, MarkdownStream()).feed(text)

    def text_done(self, index: int) -> None:
        if index in self.renderers:
            self.renderers.pop(index).finish()

    def tool_start(self, index: int, block: Block) -> None:
        self._switch(None)
        self.progress[index] = ToolProgress(block)

    def tool_input(self, index: int, chunk: str) -> None:
        if index in self.progress:
            self.progress[index].feed(chunk)

    def tool_input_done(self, index: int, block: Block) -> None:
        if index in self.progress:
            self.progress.pop(index).finish(block['input'])

    def server_result(self, kind: str, count: int) -> None:
        self._switch(None)
        out(f'  ↳ {kind} returned {count} result(s)', 'dim')

    def stream_end(self) -> None:
        for renderer in self.renderers.values():
            renderer.finish()
        self.renderers.clear()
        self.progress.clear()
        self._switch(None)

    # ---- tools

    def confirm(
        self, name: str, inp: Block, preview: FilePreview | None = None, rule: str = ''
    ) -> tuple[str, str | None]:
        if preview is not None:
            path, old, new = preview
            if old is None:
                out(f'  new file {path}:', 'dim')
                for line in new.splitlines()[:40]:
                    out('  + ' + line, 'green')
            else:
                print_diff(old, new, path)
        if name == 'run_python' and inp.get('code'):
            for line in inp['code'].splitlines()[:30]:
                out('  > ' + line, 'dim')
        always = f' / [a]lways allow {rule}' if rule else ''
        # only a typed yes allows: Return alone, or no input at all (EOF), is a no
        answer = ask(f'  Allow? [y]es / [N]o{always}: ').strip().lower()
        if answer in ('a', 'always') and rule:
            return 'always', None
        if answer in ('y', 'yes'):
            return 'yes', None
        return 'no', ask('  Tell Claude what to do instead (optional): ').strip() or None

    def approve_plan(self, plan: str) -> tuple[str, str | None]:
        out('── plan ──', 'magenta')
        renderer = MarkdownStream()
        renderer.feed(plan)
        renderer.finish()
        out()
        answer = ask(
            '  Go ahead? [a]uto-accept edits / [y]es, ask before each change / [N]o, keep planning: '
        )
        answer = answer.strip().lower()
        if answer in ('a', 'auto'):
            return 'acceptEdits', None
        if answer in ('y', 'yes'):
            return 'default', None
        return 'keep', ask('  What should change in the plan? ').strip() or None

    def file_written(self, path: str, old: str | None, new: str) -> None:
        if old is None:
            out(f'  created {path} ({len(new.splitlines())} lines)', 'dim')
        else:
            print_diff(old, new, path)

    def run_output(self, text: str) -> None:
        lines = text.splitlines()
        for line in lines[:15]:
            out('  │ ' + line, 'dim')
        if len(lines) > 15:
            out(f'  │ ... {len(lines)} lines total', 'dim')

    def tool_error(self, message: str, level: str = 'error') -> None:
        out('  ✗ ' + message, 'yellow' if level == 'denied' else 'red')

    def todos_updated(self, todos: Sequence[Todo]) -> None:
        if todos:
            for line in format_todos(list(todos)).splitlines():
                out('  ' + line, 'cyan')

    def shell_output(self, command: str, output: str, ok: bool) -> None:
        out('$ ' + command, 'cyan')
        if output:
            out(output, None if ok else 'red')

    def subagent_start(self, description: str, key: str = '') -> None:
        out(f'  ↳ subagent: {description}', 'blue')

    def subagent_progress(self, text: str, key: str = '') -> None:
        out(f'    · {shorten(text, 80)}', 'dim')

    def subagent_done(self, summary: str, key: str = '') -> None:
        out(f'    done ({len(summary)} characters reported)', 'dim')

    # ---- session

    def notice(self, text: str, level: str = 'info') -> None:
        self._switch(None)
        out(text, {'warn': 'yellow', 'error': 'red'}.get(level, 'dim'))

    def turn_done(self, model: str, usage: Usage, cost: float, turn_cost: float = 0.0) -> None:
        out(
            f'  [{model} · input {usage.get("input_tokens", 0)}'
            f' / cache read {usage.get("cache_read_input_tokens", 0)}'
            f' / cache write {usage.get("cache_creation_input_tokens", 0)}'
            f' / output {usage.get("output_tokens", 0)} tokens · ${turn_cost:.4f} · session ${cost:.4f}]',
            'dim',
        )

    def compacting(self) -> None:
        out('(summarizing the conversation…)', 'dim')

    def compacted(self, summary: str) -> None:
        out(f'(conversation summarized: {len(summary)} characters replace the earlier turns)', 'dim')

    def session_loaded(
        self,
        title: str,
        messages: Sequence[Block],
        times: Mapping[int, float] | None = None,
        turns: Mapping[int, int] | None = None,
        chapters: Mapping[int, str] | None = None,
    ) -> None:
        out(f'── {title} ──', 'magenta')
        for message in list(messages)[-12:]:
            content = message['content']
            blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
            for block in blocks:
                if block.get('type') == 'text' and block.get('text') and not mentions.is_context(block):
                    if message['role'] == 'user':
                        out('› ' + shorten(block['text'], 200), 'cyan')
                    else:
                        renderer = MarkdownStream()
                        renderer.feed(block['text'])
                        renderer.finish()
                        out()
                elif block.get('type') == 'compaction':
                    out('(earlier turns were summarized)', 'dim')

    def session_cleared(self) -> None:
        out('── new session ──', 'magenta')

    # ---- questions

    def choose(self, title: str, options: Sequence[str], current: int | None = None) -> int | None:
        options = [o + (' ✓' if i == current else '') for i, o in enumerate(options)]
        if IN_PYTHONISTA:
            import dialogs

            items = [{'title': option, 'index': i} for i, option in enumerate(options)]
            picked = dialogs.list_dialog(title, items)
            return int(picked['index']) if picked else None
        out(title)
        for i, option in enumerate(options, 1):
            out(f'  {i}. {option}')
        answer = ask('  Number: ').strip()
        return int(answer) - 1 if answer.isdigit() and 1 <= int(answer) <= len(options) else None

    def ask_text(self, title: str, message: str = '', secret: bool = False) -> str | None:
        if IN_PYTHONISTA:
            import console

            try:
                if secret:
                    return console.password_alert(title, message)
                return console.input_alert(title, message)
            except KeyboardInterrupt:
                return None
        if secret:
            import getpass

            return getpass.getpass(f'{title}: ') or None
        return ask(f'{title}: ') or None

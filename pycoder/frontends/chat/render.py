"""HTML for the chat page: Markdown, diffs, code previews, todos. Pure functions, no ui."""

from __future__ import annotations

import difflib
import html
import itertools
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any

import markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound

from ...types import Todo
from . import icons

if TYPE_CHECKING:
    from ...app.reports import ContextUsage
    from ...state.settings import SettingSpec

MAX_DIFF_LINES = 400
MAX_PREVIEW_LINES = 300
_EXTENSIONS = [
    # full module paths: Pythonista's bundled markdown has no entry points for the short names
    'markdown.extensions.fenced_code',
    'markdown.extensions.tables',
    'markdown.extensions.codehilite',
    'markdown.extensions.sane_lists',
    'markdown.extensions.nl2br',  # a line break in the text stays a line break, as on GitHub
]
_LIST_ITEM = re.compile(r'^( *)(?:[-*+]|\d+[.)]) +')
_FENCE = re.compile(r'^ *(```|~~~)')


def gfm_to_markdown(text: str) -> str:
    """Adapt GitHub-style Markdown, which Claude writes, to Python-Markdown: a list or table may
    follow a line of text directly, and nested lists may be indented by 2 or 3 spaces (Python-
    Markdown needs a blank line first and 4 spaces per level). Code blocks are left alone."""
    out: list[str] = []
    fenced = False
    indents: list[int] = []  # the indentation of each list level seen in the current list
    for line in text.split('\n'):
        if _FENCE.match(line):
            fenced = not fenced
        if fenced or _FENCE.match(line):
            out.append(line)
            continue
        item = _LIST_ITEM.match(line)
        previous = out[-1] if out else ''
        starts_block = item or line.lstrip().startswith('|')
        if starts_block and previous.strip():
            continuing = (
                _LIST_ITEM.match(previous)
                or previous.startswith(' ')
                or (line.lstrip().startswith('|') and previous.lstrip().startswith('|'))
            )
            if not continuing:
                out.append('')
        if item:
            indent = len(item.group(1))
            while indents and indents[-1] > indent:
                indents.pop()
            if not indents or indents[-1] < indent:
                indents.append(indent)
            line = ' ' * (4 * (len(indents) - 1)) + line.lstrip(' ')
        elif line.strip() and not line.startswith(' '):
            indents = []  # text at the margin ends the list
        out.append(line)
    return '\n'.join(out)


def settled(text: str, start: int = 0) -> int:
    """Where the Markdown in text[start:] can be cut so that what comes before renders the same
    whatever follows: after the last blank line outside a code block that is followed by a whole
    line starting a new block at the margin (not a list item, quote, table row or indented text,
    which could continue what came before). `start` must itself be such a place; returns it when
    there is none further on."""
    cut = start
    fenced = False
    blank = False
    pos = start
    while True:
        end = text.find('\n', pos)
        if end < 0:
            return cut  # the last line is still coming in
        line = text[pos:end]
        if not fenced and blank and line.strip() and not _CONTINUES.match(line):
            cut = pos
        if _FENCE.match(line):
            fenced = not fenced
        blank = not line.strip()
        pos = end + 1


_CONTINUES = re.compile(r'[ \t>|]|(?:[-*+]|\d+[.)])(?: |$)')


def md_to_html(text: str) -> str:
    """Markdown to HTML with raw HTML shown as text: model output must not run script in the page,
    where it could answer permission prompts."""
    if text.count('```') % 2:  # a code block still streaming in: close it so it renders as code
        text += '\n```'
    text = gfm_to_markdown(text)
    md = markdown.Markdown(
        extensions=_EXTENSIONS,
        extension_configs={'markdown.extensions.codehilite': {'guess_lang': False}},
    )
    md.preprocessors.deregister('html_block')
    md.inlinePatterns.deregister('html')
    return _UNSAFE_LINK.sub(r'\1"#"', md.convert(text))


_UNSAFE_LINK = re.compile(r'((?:href|src)=)"\s*(?:javascript|data|vbscript):[^"]*"', re.IGNORECASE)


def code_html(text: str, path: str = '', limit: int = MAX_PREVIEW_LINES) -> str:
    lines = text.splitlines()
    lang = 'python' if path.endswith('.py') or not path else ''
    body = '\n'.join(lines[:limit]).replace('```', '`​``')
    out = md_to_html(f'```{lang}\n{body}\n```')
    if len(lines) > limit:
        out += f'<div class="sub">… {len(lines) - limit} more lines</div>'
    return out


def diff_lines(old: str, new: str, path: str) -> Iterator[str]:
    """The lines of a unified diff, without its two header lines."""
    lines = difflib.unified_diff(
        old.splitlines(), new.splitlines(), 'a/' + path, 'b/' + path, n=2, lineterm=''
    )
    return itertools.islice(lines, 2, None)


def _diff_rows(lines: Sequence[str]) -> list[str]:
    rows = []
    for line in lines:
        cls = {'+': 'add', '-': 'del', '@': 'hunk'}.get(line[:1], 'ctx')
        rows.append(f'<span class="{cls}">{html.escape(line) or " "}</span>')
    return rows


def diff_rows_html(lines: Sequence[str]) -> str:
    return '<div class="diff">%s</div>' % ''.join(_diff_rows(lines))


def diff_html(old: str, new: str, path: str) -> str:
    """For a card in the chat, which shows the start: the files pane shows it all."""
    lines = list(diff_lines(old, new, path))
    if not lines:
        return '<div class="diff"><span class="ctx">(no changes)</span></div>'
    rows = _diff_rows(lines[:MAX_DIFF_LINES])
    if len(lines) > MAX_DIFF_LINES:
        rows.append(f'<span class="ctx">… {len(lines) - MAX_DIFF_LINES} more lines</span>')
    return '<div class="diff">%s</div>' % ''.join(rows)


COMPARING = '<div class="none">Comparing…</div>'
EMPTY = '<div class="none">This file is empty</div>'
UNREADABLE = '<div class="none">It can\'t be read now</div>'
NO_CHANGES = '<div class="none">No changes</div>'
NO_EARLIER = '<div class="none">The earlier version wasn\'t kept: it was too big, or isn\'t text</div>'
NO_ROOM_TO_COMPARE = '<div class="none">There isn\'t enough memory to compare these now</div>'
MORE = '<div id="more"></div>'  # the page asks for more when this comes near (wantMore)


def source_html(text: str, path: str, start: int = 1) -> str:
    """Part of a file, from line `start`, coloured by its kind and with line numbers."""
    try:
        lexer = get_lexer_for_filename(path, stripnl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False)
    formatter = HtmlFormatter(linenos='inline', linenostart=start, cssclass='codehilite')
    return str(highlight(text, lexer, formatter))


def not_text_html() -> str:
    return (
        '<div class="none">This isn\'t text</div>'
        '<button class="wide" onclick="act(\'preview\')">Preview</button>'
    )


def _crumbs_html(crumbs: Sequence[tuple[str, int]], last_is_here: bool) -> str:
    parts = []
    for i, (name, target) in enumerate(crumbs):
        here = last_is_here and i == len(crumbs) - 1
        parts.append(
            f'<b>{html.escape(name)}</b>'
            if here
            else f'<a onclick="act(\'go:{target}\')">{html.escape(name)}</a>'
        )
    return ' <i>/</i> '.join(parts)


def folder_html(
    crumbs: Sequence[tuple[str, int]],
    changed: Sequence[tuple[str, str, str, int]],
    folders: Sequence[tuple[str, int]],
    files: Sequence[tuple[str, int, str, int]],
    more: bool,
    folder_icon: str,
    file_icon: str,
) -> str:
    """A folder of the files pane. crumbs are (name, target); changed (name, folder, how, target);
    folders (name, target); files (name, bytes, how it changed, target)."""
    top = ''
    if changed:
        rows = ''.join(
            f'<div class="file" onclick="act(\'go:{target}\')"><span class="icon">{file_icon}</span>'
            f'<div class="what"><div class="name">{html.escape(name)}</div>'
            f'<div class="num">{html.escape(folder)}</div></div>'
            f'<span class="how {how}">{how}</span></div>'
            for name, folder, how, target in changed
        )
        top = f'<section class="ps"><h3>Changed in this session</h3>{rows}</section>'
    rows = ''.join(
        f'<div class="file" onclick="act(\'go:{target}\')"><span class="icon">{folder_icon}</span>'
        f'<div class="what"><div class="name">{html.escape(name)}</div></div></div>'
        for name, target in folders
    ) + ''.join(
        f'<div class="file" onclick="act(\'go:{target}\')"><span class="icon">{file_icon}</span>'
        f'<div class="what"><div class="name">{html.escape(name)}</div>'
        f'<div class="num">{file_size(size)}</div></div>'
        + (f'<span class="how {how}">{how}</span>' if how else '')
        + '</div>'
        for name, size, how, target in files
    )
    rows = rows or '<div class="none">Nothing here</div>'
    if more:
        rows += MORE
    return f'{top}<section class="ps"><nav class="crumbs">{_crumbs_html(crumbs, True)}</nav>{rows}</section>'


def file_page_html(
    crumbs: Sequence[tuple[str, int]], name: str, meta: str, how: str, showing: str, body: str, more: bool
) -> str:
    """A file of the files pane. `how` is how this session changed it, if it did; with `showing` ('code'
    or 'changes', nothing when the file is gone), it can be seen either way."""
    tabs = ''
    if how and showing:
        tabs = (
            '<div class="seg">'
            + ''.join(
                f'<a class="{"on" if showing == kind else ""}" onclick="act(\'show:{kind}\')">{label}</a>'
                for kind, label in (('code', 'Code'), ('changes', 'Changes'))
            )
            + '</div>'
        )
    tag = f'<span class="how {how}">{how}</span>' if how else ''
    return (
        f'<section class="ps fv"><nav class="crumbs">{_crumbs_html(crumbs, False)}</nav>'
        f'<div class="title"><b>{html.escape(name)}</b>{tag}'
        f'<span class="num">{html.escape(meta)}</span></div>'
        f'{tabs}<div class="source">{body}</div>{MORE if more else ""}</section>'
    )


def strip_steps(todos: Sequence[Todo], limit: int) -> list[tuple[str, str]]:
    """(status, text) of what shows above the input: only what is left, the step under way first,
    which also says how far the list has come. A finished step leaves at once; the session pane
    keeps the whole list."""
    left = [t for t in todos if t['status'] != 'completed']
    left.sort(key=lambda t: t['status'] != 'in_progress')
    rows = [(t['status'], t['content']) for t in left[:limit]]
    if rows:
        rows[0] = (rows[0][0], f'{len(todos) - len(left)}/{len(todos)} · {rows[0][1]}')
    return rows


def todos_html(todos: Sequence[Todo]) -> str:
    """The whole list, for the session pane."""
    return ''.join(
        f'<div class="t {t["status"]}">{icons.icon("todo-" + t["status"])}'
        f'<span>{html.escape(t["content"])}</span></div>'
        for t in todos
    )


def settings_html(
    specs: Sequence[SettingSpec],
    current: dict[str, Any],
    tabs: Mapping[str, Sequence[tuple[str, str]]] | None = None,
) -> str:
    """The /config sheet: a select for choices, a slider for numbers, a checkbox for on/off;
    read-only tabs (Status, Usage) beside the settings, as in Claude Code."""
    rows = []
    for spec in specs:
        value = current.get(spec.name)
        if spec.kind == 'choice':
            options = ''.join(
                '<option value="{0}"{1}>{0}</option>'.format(
                    html.escape(c), ' selected' if c == value else ''
                )
                for c in spec.choices
            )
            control, shown = f'<select data-name="{spec.name}">{options}</select>', ''
        elif spec.kind == 'int':
            control = (
                f'<input type="range" data-name="{spec.name}" min="{spec.minimum}" max="{spec.maximum}" '
                f'step="{spec.step}" value="{value}" oninput="el(\'{spec.name}-v\').textContent=this.value">'
            )
            shown = f'<span id="{spec.name}-v">{value}</span>'
        else:
            checked = ' checked' if value else ''
            control, shown = '', f'<input type="checkbox" data-name="{spec.name}"{checked}>'
        rows.append(
            f'<div class="field"><div class="label"><span>{html.escape(spec.label)}</span>{shown}</div>'
            f'<div class="help">{html.escape(spec.help)}</div>{control}</div>'
        )
    names = ['Config', *(tabs or {})]
    bar = ''.join(
        f'<button class="tab{" on" if i == 0 else ""}" onclick="showTab({i})">{html.escape(n)}</button>'
        for i, n in enumerate(names)
    )
    pages = [f'<div class="page">{"".join(rows)}</div>']
    for info in (tabs or {}).values():
        cells = ''.join(f'<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>' for k, v in info)
        pages.append(f'<div class="page" style="display:none"><table class="info">{cells}</table></div>')
    # Cancel and Save sit in the top bar, always in reach; only the settings below scroll
    return (
        '<div class="sheet"><div class="top">'
        '<button class="cancel" onclick="closeSettings(false)">Cancel</button>'
        f'<div class="tabs">{bar}</div>'
        '<button class="save" onclick="closeSettings(true)">Save</button></div>'
        f'<div class="body">{"".join(pages)}</div></div>'
    )


def context_html(usage: ContextUsage) -> str:
    """/context like iPhone Storage in Settings: the total, one bar split by what fills the context
    window, and a list with each part's size."""
    used = usage.used
    parts = [c for c in usage.categories if c.tokens]
    # free space and the autocompact buffer take the page's theme, not a colour of their own
    kinds = {'Free space': 'free', 'Autocompact buffer': 'buffer'}

    def swatch(c: Any, grow: bool) -> str:
        style = f'flex-grow:{c.tokens};' if grow else ''
        if c.name not in kinds:
            style += f'background:{c.color}'
        return f'<i class="{kinds.get(c.name, "")}" style="{style}" title="{html.escape(c.name)}"></i>'

    rows = ''.join(
        f'<div class="part">{swatch(c, False)}<span class="name">{html.escape(c.name)}</span>'
        f'<span class="num">{_tokens(c.tokens)}</span>'
        f'<span class="pct">{100 * c.tokens / usage.window:.1f}%</span></div>'
        for c in parts
    )
    return (
        f'<div class="head"><span class="used">{_tokens(used)}</span>'
        f'<span class="of">of {_tokens(usage.window)} tokens · '
        f'{100 * used / usage.window:.1f}% used</span></div>'
        f'<div class="sub">{html.escape(usage.model)}{"" if usage.measured else " · estimated"}</div>'
        f'<div class="bar">{"".join(swatch(c, True) for c in parts)}</div><div class="parts">{rows}</div>'
    )


_SENTENCE_BREAK = re.compile(r'(?<=[.!?])\s+|(?<=[。！？])\s*|\n+')


def thought_line(text: str) -> str:
    """The one line that stands for thinking so far: its last finished sentence, or until there is
    one, as much of the first as has come."""
    parts = _SENTENCE_BREAK.split(text)
    finished = [p for p in parts[:-1] if p.strip()]
    return (finished[-1] if finished else parts[-1]).replace('**', '').strip(' #\t')


def elapsed(seconds: float) -> str:
    seconds = int(seconds)
    return f'{seconds // 60}m {seconds % 60:02d}s' if seconds >= 60 else f'{seconds}s'


def session_html(
    usage: ContextUsage,
    subagents: Sequence[tuple[str, str, float]],
    jobs: Sequence[tuple[int, str, str, bool, str]],
    outputs: Sequence[tuple[str, str, int]],
    file_icon: str,
    todos: Sequence[Todo] = (),
) -> str:
    """The session pane: how full the context is (unfolds to /context), what runs in the background
    with what it printed, and the files made or changed. subagents are (description, latest step,
    seconds); jobs (number, label, how it stands, running, output); outputs (name, folder, bytes)."""
    share = 100 * usage.used / usage.window
    context = (
        '<section class="ps"><h3>Context</h3><div class="box"><details id="ctx"><summary><div class="line">'
        f'<b>{share:.0f}%</b><div class="meter"><i style="width:{min(share, 100):.1f}%"></i></div>'
        f'<span class="num">{_tokens(usage.used)} of {_tokens(usage.window)}</span></div></summary>'
        f'<div class="context" style="background:none;padding:10px 0 0;margin:0">{context_html(usage)}</div>'
        '</details></div></section>'
    )
    rows = [
        '<div class="box"><div class="line"><span class="name">'
        f'<b>Subagent</b> {html.escape(description)}</span>'
        f'<span class="num">{elapsed(seconds)}</span></div>'
        + (f'<div class="now">{html.escape(step)}</div>' if step else '')
        + '</div>'
        for description, step, seconds in subagents
    ]
    for number, label, status, running, output in jobs:
        stop = (
            f'<button onclick="act(\'stop:{number}\');event.preventDefault()">Stop</button>'
            if running
            else ''
        )
        rows.append(
            f'<div class="box"><details id="job{number}"><summary><div class="line"><span class="name">'
            f'<b>Job {number}</b> {html.escape(label)}</span><span class="num" id="job{number}s">'
            f'{html.escape(status)}</span>{stop}</div></summary>'
            f'<pre id="job{number}o">{html.escape(output)}</pre></details></div>'
        )
    tasks = ''.join(rows) or '<div class="none">Nothing is running</div>'
    files = ''.join(
        f'<div class="file" onclick="act(\'open:{i}\')"><span class="icon">{file_icon}</span>'
        '<div class="what">'
        f'<div class="name">{html.escape(name)}</div><div class="num">'
        f'{html.escape(folder + " · " if folder else "")}{file_size(size)}</div></div></div>'
        for i, (name, folder, size) in enumerate(outputs)
    )
    done = sum(t['status'] == 'completed' for t in todos)
    plan = (
        f'<section class="ps"><h3>Tasks {done}/{len(todos)}'
        '<button class="clear" onclick="act(\'clear-tasks\')">Clear</button></h3>'
        f'<div class="box">{todos_html(todos)}</div></section>'
        if todos
        else ''
    )
    return (
        context
        + plan
        + f'<section class="ps"><h3>Background tasks</h3>{tasks}</section>'
        + '<section class="ps"><h3>Outputs</h3>'
        + (files or '<div class="none">No files made or changed in this session</div>')
        + '</section>'
    )


def file_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f'{n / (1024 * 1024):.1f} MB'
    return f'{n / 1024:.0f} KB' if n >= 1024 else f'{n} B'


def _tokens(n: int) -> str:
    if n >= 1_000_000:
        return f'{n / 1_000_000:.2g}M'
    return f'{n / 1000:.1f}'.removesuffix('.0') + 'k' if n >= 1000 else str(n)


def escape(text: str) -> str:
    return html.escape(text)

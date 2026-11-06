"""Workspace file tools: list, read, search, write, edit."""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator

from .. import config
from ..host import env, images
from ..state.textfile import UTF8, TextFormat
from ..state.workspace import Workspace
from ..types import Block
from .base import FilePreview, Tool, ToolContext, ToolError, prop

# folders of installed or generated files: walking the workspace leaves them out (hidden ones,
# starting with a dot, are left out anyway); naming one as the path still searches or lists it
SKIP_DIRS = {'.git', '.git.nosync', '.pycoder', '__pycache__', 'node_modules', '.venv', '.mypy_cache'}
MAX_SEARCH_FILE = 1_000_000  # bytes; bigger files (data, logs, bundles) are skipped by search


def skipped_dir(name: str) -> bool:
    # Pythonista keeps installed packages in Documents/site-packages(-3, -2)
    return name in SKIP_DIRS or name.startswith('site-packages') or Workspace.is_hidden(name)


def walk(base: str) -> Iterator[tuple[str, list[str], list[str]]]:
    """os.walk in name order, without hidden files and the folders in SKIP_DIRS."""
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not skipped_dir(d))
        yield dirpath, dirnames, sorted(n for n in filenames if not Workspace.is_hidden(n))


def list_files(ctx: ToolContext, path: str = '.', recursive: bool = False) -> str:
    ws = ctx.workspace
    base = ws.resolve_readable(path)
    if not os.path.isdir(base):
        raise ToolError(f'Not a directory: {path}')
    entries: list[str] = []
    if recursive:
        for dirpath, _, filenames in walk(base):
            for name in filenames:
                full = os.path.join(dirpath, name)
                if not ctx.denied(full):
                    entries.append('%s  (%d B)' % (ws.rel(full), os.path.getsize(full)))
            if len(entries) > config.MAX_LIST_ENTRIES:
                break
    else:
        for name in sorted(os.listdir(base)):
            if ws.is_hidden(name):
                continue
            full = os.path.join(base, name)
            if ctx.denied(full):
                continue
            if os.path.isdir(full):
                entries.append(ws.rel(full) + '/')
            else:
                entries.append('%s  (%d B)' % (ws.rel(full), os.path.getsize(full)))
    if not entries:
        return '(empty directory)'
    note = ''
    if len(entries) > config.MAX_LIST_ENTRIES:
        note = '\n... too many entries, showing the first %d' % config.MAX_LIST_ENTRIES
        entries = entries[: config.MAX_LIST_ENTRIES]
    return '\n'.join(entries) + note


READ_BUDGET = config.MAX_TOOL_OUTPUT - 2000  # characters of file per read, leaving room for notes
LONG_LINE = 2000  # longer lines (minified code, data) are cut so one can't fill the budget
OUTLINE_ENTRIES = 200


def read_file(ctx: ToolContext, path: str, offset: int = 1, limit: int = 2000) -> str | list[Block]:
    """Whole lines from `offset`, as many as fit; a file too big to read at once starts with an
    outline (where its classes, functions or headings are), and every partial read says where to
    go on. So the model can find its way around a file of any size. An image is shown to the model
    as an image (a chart or a picture the code made can be checked by looking at it)."""
    full = ctx.workspace.resolve_readable(path)
    if not os.path.isfile(full):
        raise ToolError(f'File not found: {path}')
    if os.path.splitext(full)[1].lower() in images.MEDIA_TYPES:
        block = images.from_path(full)
        return [{'type': 'text', 'text': f'{path} ({images.describe(block)}):'}, block]
    text, fmt = ctx.workspace.read(full)
    lines = text.splitlines()
    start = max(1, offset)
    # too big to read at once: the first read starts with a map, and the lines fill what is left
    outline = _outline(full, text) if start == 1 and len(text) > READ_BUDGET else ''
    head = f'Outline (line: name), to choose what to read:\n{outline}\n\n' if outline else ''
    out: list[str] = []
    size = len(head)
    for number in range(start, min(len(lines), start - 1 + max(1, limit)) + 1):
        line = lines[number - 1]
        if len(line) > LONG_LINE:
            line = line[:LONG_LINE] + f' … [line cut: {len(line)} characters]'
        entry = '%5d\t%s' % (number, line)
        if out and size + len(entry) + 1 > READ_BUDGET:
            break
        out.append(entry)
        size += len(entry) + 1
    end = start + len(out) - 1
    notes = []
    if end < len(lines) or start > 1:
        more = f'; continue with offset={end + 1}' if end < len(lines) else ''
        notes.append(f"(lines {start}-{end} of {len(lines)}{more}; search finds a name's line)")
    if fmt.describe():  # edits keep it, so the model needn't do anything about it
        notes.append(f'(stored as {fmt.describe()}; edits keep that)')
    return head + ('\n'.join(out) or '(empty file)') + ''.join('\n' + n for n in notes)


def _outline(full: str, text: str) -> str:
    """Where things are in a big file: Python classes and functions, Markdown headings."""
    entries: list[str] = []
    if full.endswith('.py'):
        import ast

        try:
            tree = ast.parse(text)
        except SyntaxError:
            return ''
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = 'class' if isinstance(node, ast.ClassDef) else 'def'
                entries.append(f'{node.lineno}: {kind} {node.name}')
        entries.sort(key=lambda e: int(e.split(':')[0]))
    elif full.endswith(('.md', '.markdown', '.rst', '.txt')):
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            under = lines[i] if i < len(lines) else ''
            if line.startswith('#'):  # Markdown
                entries.append(f'{i}: {line.strip()}')
            elif line.strip() and len(under) >= 3 and len(set(under)) == 1 and under[0] in '=-~^*+#':
                entries.append(f'{i}: {line.strip()}')  # a heading underlined (reStructuredText, setext)
            elif line.startswith('.. _') and line.rstrip().endswith(':'):
                entries.append(f'{i}: {line.strip()}')  # an rst link target
    if len(entries) > OUTLINE_ENTRIES:
        entries = [*entries[:OUTLINE_ENTRIES], f'… and {len(entries) - OUTLINE_ENTRIES} more']
    return '\n'.join(entries)


def search(
    ctx: ToolContext,
    pattern: str,
    path: str = '.',
    glob: str = '*',
    context: int = 0,
    ignore_case: bool = False,
) -> str:
    ws = ctx.workspace
    if '\\n' in pattern or '\n' in pattern:
        raise ToolError('search matches one line at a time: search for one line, then read around it')
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        raise ToolError(f'Invalid regex: {e}') from e
    context = max(0, min(context, 20))
    base = ws.resolve_readable(path)
    hits: list[str] = []
    skipped = 0

    def files() -> Iterator[str]:
        nonlocal skipped
        if os.path.isfile(base):
            yield base  # named on purpose: searched whatever its size
            return
        for dirpath, _, filenames in walk(base):
            for name in filenames:
                full = os.path.join(dirpath, name)
                if not fnmatch.fnmatch(name, glob) or ctx.denied(full):
                    continue
                try:
                    big = os.path.getsize(full) > MAX_SEARCH_FILE
                except OSError:
                    continue
                if big:
                    skipped += 1
                else:
                    yield full

    for full in files():
        try:
            text = ws.read_text(full)
        except (ToolError, OSError):
            continue
        lines = text.splitlines()
        rel = ws.rel(full)
        python = full.endswith('.py')
        shown = 0  # last line already shown, so context blocks don't repeat lines
        for i, line in enumerate(lines, 1):
            if not rx.search(line):
                continue
            where = _enclosing(lines, i) if python else ''
            if context:
                start = max(i - context, shown + 1)
                if hits and start > shown + 1:
                    hits.append('--')
                for j in range(start, min(len(lines), i + context) + 1):
                    mark = ':' if j == i else '-'
                    hits.append(f'{rel}:{j}{mark} {lines[j - 1].rstrip()[:200]}' + (where if j == i else ''))
                shown = min(len(lines), i + context)
            else:
                hits.append(f'{rel}:{i}: {line.strip()[:200]}{where}')
            if len(hits) >= config.MAX_SEARCH_HITS:
                return '\n'.join(hits) + '\n... too many matches, truncated'
    out = '\n'.join(hits) or 'No matches'
    if skipped:
        out += f'\n({skipped} file(s) over 1 MB not searched; name one as the path to search it)'
    return out


_DEF = re.compile(r'^(\s*)(?:async\s+)?(def|class)\s+(\w+)')


def _enclosing(lines: list[str], number: int) -> str:
    """'  (in Class.method)': the def/class a Python line belongs to, found by indentation."""
    line = lines[number - 1]
    indent = len(line) - len(line.lstrip())
    names: list[str] = []
    for j in range(number - 2, -1, -1):
        m = _DEF.match(lines[j])
        if m and len(m.group(1)) < indent:
            names.insert(0, m.group(3))
            indent = len(m.group(1))
            if not indent:
                break
    return f'  (in {".".join(names)})' if names else ''


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    full = ctx.workspace.resolve(path)
    old, fmt = ctx.workspace.read(full) if os.path.isfile(full) else (None, UTF8)
    ctx.checkpoints.before_write(full)
    _save(full, content, fmt)  # an existing file keeps its encoding and line endings
    ctx.frontend.file_written(ctx.workspace.rel(full), old, content)
    return ('Created %s' if old is None else 'Overwrote %s') % ctx.workspace.rel(full)


def write_preview(ctx: ToolContext, path: str, content: str) -> FilePreview:
    full = ctx.workspace.resolve(path)
    old = ctx.workspace.read_text(full) if os.path.isfile(full) else None
    return ctx.workspace.rel(full), old, content


def _save(full: str, text: str, fmt: TextFormat) -> None:
    env.write_bytes(full, fmt.encode(text), text)


def _apply_edit(
    ctx: ToolContext, path: str, old_str: str, new_str: str, replace_all: bool
) -> tuple[str, str, str, int, TextFormat]:
    """(full path, old text, new text, replacements, how the file is stored) without writing anything;
    ToolError if it can't apply."""
    full = ctx.workspace.resolve(path)
    if not os.path.isfile(full):
        raise ToolError(f'File not found: {path}')
    text, fmt = ctx.workspace.read(full)
    count = text.count(old_str) if old_str else 0
    if count == 0:
        raise ToolError(
            'old_str not found in the file; read_file first to confirm the exact text (including indentation)'
        )
    if count > 1 and not replace_all:
        raise ToolError(
            'old_str appears %d times; add more context to make it unique, or set replace_all' % count
        )
    new_text = text.replace(old_str, new_str) if replace_all else text.replace(old_str, new_str, 1)
    return full, text, new_text, count if replace_all else 1, fmt


def edit_preview(
    ctx: ToolContext, path: str, old_str: str, new_str: str, replace_all: bool = False
) -> FilePreview:
    full, text, new_text, _, _ = _apply_edit(ctx, path, old_str, new_str, replace_all)
    return ctx.workspace.rel(full), text, new_text


def edit_file(ctx: ToolContext, path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
    full, text, new_text, count, fmt = _apply_edit(ctx, path, old_str, new_str, replace_all)
    ctx.checkpoints.before_write(full)
    _save(full, new_text, fmt)
    ctx.frontend.file_written(ctx.workspace.rel(full), text, new_text)
    return 'Edited %s (%d replacement(s))' % (ctx.workspace.rel(full), count)


TOOLS = [
    Tool(
        'list_files',
        'List files and subdirectories of a workspace directory (hidden files excluded).',
        {
            'path': prop('string', 'Directory path relative to the workspace, default "."'),
            'recursive': prop('boolean', 'List all files recursively'),
        },
        list_files,
    ),
    Tool(
        'read_file',
        'Read a text file and return its contents with line numbers, or look at an image (png, jpg, '
        'gif, webp), for example to check a chart or picture your code made. Always read a file before '
        'editing it. '
        'A big file comes back in parts: the first read starts with an outline (line numbers of its '
        'classes, functions or headings) and each part says the offset to continue from.',
        {
            'path': prop('string', 'File path'),
            'offset': prop('integer', 'Starting line number (1-based)'),
            'limit': prop('integer', 'Maximum number of lines to read (default: as many as fit)'),
        },
        read_file,
        required=['path'],
    ),
    Tool(
        'search',
        'Search files line by line with a Python regex; returns file:line: text, with the function or '
        'class each Python hit is in. Use context to see the lines around each hit instead of reading '
        'the file.',
        {
            'pattern': prop('string', 'Python regular expression, matched against one line at a time'),
            'path': prop('string', 'Directory or file to search, default "."'),
            'glob': prop('string', 'File name pattern (the name only, not a path), e.g. "*.py", default "*"'),
            'context': prop('integer', 'Lines to show before and after each hit (default 0, at most 20)'),
            'ignore_case': prop('boolean', 'Match regardless of letter case'),
        },
        search,
        required=['pattern'],
    ),
    Tool(
        'write_file',
        'Create a new file or overwrite a whole file. Prefer edit_file for changes to existing files.',
        {
            'path': prop('string', 'File path; parent directories are created automatically'),
            'content': prop('string', 'Full file content'),
        },
        write_file,
        required=['path', 'content'],
        preview=write_preview,
        readonly=False,
    ),
    Tool(
        'edit_file',
        'Replace old_str with new_str in a file. old_str must match the original exactly (including '
        'indentation) and be unique, unless replace_all is true.',
        {
            'path': prop('string', 'File path'),
            'old_str': prop('string', 'Text to replace'),
            'new_str': prop('string', 'Replacement text'),
            'replace_all': prop('boolean', 'Replace every occurrence'),
        },
        edit_file,
        required=['path', 'old_str', 'new_str'],
        preview=edit_preview,
        readonly=False,
    ),
]

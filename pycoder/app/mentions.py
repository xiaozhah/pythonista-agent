"""@path mentions: files and folders named in a message go along with it, as in Claude Code.

`look at @pycoder/agent/loop.py` sends the file's content with the request, so Claude needn't call
read_file first. A folder sends its listing, an image is attached as an image. Words that name
nothing in the workspace (an email address, a decorator) are left alone.
"""

from __future__ import annotations

import os
import re
import time

from ..host import images
from ..state.workspace import ToolError, Workspace
from ..tools.files import walk
from ..types import Block

MAX_CHARS = 60_000  # per file; the rest is cut and read_file can page through it
MAX_LISTING = 200
MAX_WALK = 3000  # files looked at when searching the workspace for completions
WALK_FOR = 5.0  # seconds the workspace's file names are reused while @word is being typed
_MENTION = re.compile(r'(?<![\w@])@("[^"]+"|[^\s"]+)')
CONTEXT_PREFIXES = ('<file path=', '<folder path=', '<system-reminder>')


def find(text: str) -> list[str]:
    """The paths mentioned with @, in order, without duplicates."""
    found: list[str] = []
    for m in _MENTION.finditer(text):
        path = m.group(1).strip('"').rstrip('.,;:!?)')
        if path and path not in found:
            found.append(path)
    return found


def attach(workspace: Workspace, text: str) -> tuple[list[Block], list[str]]:
    """Blocks for the mentioned paths that exist, and their workspace-relative names."""
    blocks: list[Block] = []
    names: list[str] = []
    for path in find(text):
        try:
            full = workspace.resolve_readable(path)
        except ToolError:
            continue
        rel = workspace.rel(full)
        if os.path.isdir(full):
            blocks.append({'type': 'text', 'text': _listing(full, rel)})
        elif os.path.isfile(full):
            blocks.append(_file_block(full, rel))
        else:
            continue
        names.append(rel)
    return blocks, names


def _file_block(full: str, rel: str) -> Block:
    if os.path.splitext(full)[1].lower() in images.MEDIA_TYPES:
        try:
            return images.from_path(full)
        except (images.ImageError, OSError):
            pass
    try:
        size = os.path.getsize(full)
        with open(full, 'rb') as f:
            data = f.read(MAX_CHARS * 4)  # never the whole of a huge file
    except OSError as e:
        return {'type': 'text', 'text': f'<file path="{rel}">(cannot read: {e})</file>'}
    if b'\0' in data[:4096]:
        return {'type': 'text', 'text': f'<file path="{rel}">(binary file, {size} bytes)</file>'}
    text = data.decode('utf-8', errors='replace')
    if len(text) > MAX_CHARS or size > len(data):
        text = text[:MAX_CHARS] + f'\n… (cut; the file is {size} bytes: use read_file for the rest)'
    return {'type': 'text', 'text': f'<file path="{rel}">\n{text}\n</file>'}


def _listing(full: str, rel: str) -> str:
    names = sorted(n for n in os.listdir(full) if not Workspace.is_hidden(n))
    shown = [n + '/' if os.path.isdir(os.path.join(full, n)) else n for n in names[:MAX_LISTING]]
    more = f'\n… and {len(names) - MAX_LISTING} more' if len(names) > MAX_LISTING else ''
    return f'<folder path="{rel}">\n' + '\n'.join(shown) + more + '\n</folder>'


def is_context(block: Block) -> bool:
    """Text pycoder added to a user message (attached files, reminders), not typed by the user."""
    return block.get('type') == 'text' and str(block.get('text', '')).startswith(CONTEXT_PREFIXES)


# ---- completion


def partial(text: str) -> str | None:
    """The @word being typed at the end of `text` (without the @), or None."""
    m = re.search(r'(?:^|\s)@([^\s"]*)$', text)
    return m.group(1) if m else None


def candidates(workspace: Workspace, typed: str, limit: int = 20) -> list[str]:
    """Paths for an @word: the folder's entries when it has a /, else a search of the workspace."""
    if '/' in typed:
        folder, _, start = typed.rpartition('/')
        try:
            full = workspace.resolve_readable(folder)
        except ToolError:
            return []
        if not os.path.isdir(full):
            return []
        out = []
        for name in sorted(os.listdir(full)):
            if name.startswith(start) and (start.startswith('.') or not Workspace.is_hidden(name)):
                out.append(f'{folder}/{name}' + ('/' if os.path.isdir(os.path.join(full, name)) else ''))
        return out[:limit]
    prefix, inside = [], []
    needle = typed.lower()
    for rel in _workspace_paths(workspace.root):
        name = rel.rstrip('/').rpartition('/')[2]
        if name.lower().startswith(needle):
            prefix.append(rel)
        elif needle in rel.lower():
            inside.append(rel)
    ranked = sorted(prefix, key=lambda p: (p.count('/') - p.endswith('/'), p)) + inside
    return ranked[:limit]


_walked: tuple[str, float, list[str]] = ('', 0.0, [])  # root, when, its paths (folders end in /)


def _workspace_paths(root: str) -> list[str]:
    """The first MAX_WALK paths of the workspace, walked once for the keystrokes of an @word."""
    global _walked
    if _walked[0] == root and time.monotonic() - _walked[1] < WALK_FOR:
        return _walked[2]
    paths: list[str] = []
    for dirpath, dirnames, filenames in walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        for name in [d + '/' for d in dirnames] + filenames:
            paths.append(name if rel_dir == '.' else f'{rel_dir}/{name}')
        if len(paths) > MAX_WALK:
            break
    _walked = (root, time.monotonic(), paths)
    return paths

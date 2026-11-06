"""move_file / delete_file: rename, move and remove workspace files and folders.

Every file touched is remembered by the turn's checkpoints first, so /rewind puts a moved or
deleted file back, whatever its size.
"""

from __future__ import annotations

import os
import shutil

from ..host import env
from .base import Tool, ToolContext, ToolError, prop


def _files(full: str) -> list[str]:
    """The file itself, or every file under a folder."""
    if os.path.isfile(full):
        return [full]
    return [os.path.join(folder, name) for folder, _, names in os.walk(full) for name in names]


def _existing(ctx: ToolContext, path: str) -> str:
    full = ctx.workspace.resolve(path)
    if not os.path.exists(full):
        raise ToolError(f'Not found: {path}')
    if full == ctx.workspace.root:
        raise ToolError('The workspace folder itself cannot be moved or deleted')
    return full


def move_file(ctx: ToolContext, path: str, to: str) -> str:
    full = _existing(ctx, path)
    target = ctx.workspace.resolve(to)
    if os.path.exists(target):
        raise ToolError(f'{to} already exists; delete it first or choose another name')
    if os.path.commonpath([full, target]) == full:
        raise ToolError('A folder cannot be moved into itself')
    for f in _files(full):
        ctx.checkpoints.before_write(f, removing=True)
        ctx.checkpoints.before_write(os.path.join(target, os.path.relpath(f, full)) if f != full else target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(full, target)
    env.remove_file(full)  # nothing left to remove: makes Pythonista's editor drop the old path
    return f'Moved {ctx.workspace.rel(full)} to {ctx.workspace.rel(target)}'


def delete_file(ctx: ToolContext, path: str) -> str:
    full = _existing(ctx, path)
    files = _files(full)
    for f in files:
        ctx.checkpoints.before_write(f, removing=True)
        env.remove_file(f)
    if os.path.isdir(full):
        shutil.rmtree(full)
        return f'Deleted the folder {ctx.workspace.rel(full)} ({len(files)} files)'
    return f'Deleted {ctx.workspace.rel(full)}'


TOOLS = [
    Tool(
        'move_file',
        'Move or rename a file or folder in the workspace. The destination must not exist yet; '
        'missing parent folders are created. /rewind can undo it.',
        {
            'path': prop('string', 'The file or folder to move'),
            'to': prop('string', 'Its new path'),
        },
        move_file,
        required=['path', 'to'],
        readonly=False,
    ),
    Tool(
        'delete_file',
        'Delete a file or folder in the workspace. /rewind can undo it.',
        {'path': prop('string', 'The file or folder to delete')},
        delete_file,
        required=['path'],
        readonly=False,
    ),
]

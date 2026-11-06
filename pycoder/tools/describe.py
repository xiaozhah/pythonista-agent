"""One-line descriptions of tool calls for display."""

from __future__ import annotations

from typing import Any


def shorten(text: str, limit: int = 80) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + '…'


def doing(name: str, inp: dict[str, Any]) -> str:
    """What the work is at, for the Lock Screen: the step of the plan under way, or else the tool."""
    if name == 'todo_write':
        now = [t.get('content', '') for t in inp.get('todos', []) if t.get('status') == 'in_progress']
        return shorten(now[0], 60) if now else ''
    if name in ('todo_update', 'todo_add'):
        return ''
    return shorten(f'{name.replace("_", " ")}: {describe_call(name, inp)}', 60)


def describe_call(name: str, inp: dict[str, Any]) -> str:
    if name == 'run_python':
        return str(inp.get('path') or shorten(inp.get('code', ''), 60))
    if name == 'search':
        return '{!r} in {}'.format(inp.get('pattern'), inp.get('path', '.'))
    if name in ('web_search', 'web_fetch'):
        return shorten(inp.get('query') or inp.get('url') or '', 60)
    if name == 'task':
        return str(inp.get('description', ''))
    if name == 'use_screen':
        where = inp.get('target') or (f'({inp["x"]}, {inp["y"]})' if 'x' in inp else '')
        return ' '.join(str(p) for p in (inp.get('action', 'list'), where, inp.get('text', '')) if p)
    if name == 'python_code':
        return ' '.join(str(p) for p in (inp.get('action'), inp.get('name'), inp.get('path')) if p)
    if name == 'todo_write':
        return '%d items' % len(inp.get('todos', []))
    if name == 'todo_update':
        return ' '.join(str(p) for p in ('step', inp.get('step'), inp.get('status')) if p)
    if name == 'todo_add':
        return shorten(inp.get('content', ''), 60)
    if name == 'git':
        return ' '.join(
            str(p) for p in [inp.get('command', ''), inp.get('message') or inp.get('path') or ''] if p
        )
    if name == 'install_package':
        return str(inp.get('name', ''))
    if name == 'list_files':
        return str(inp.get('path') or '.')
    if inp.get('path'):
        return str(inp['path'])
    # any other tool: its first short text argument (a skill's name, a docs query, what to speak)
    first = next((v for v in inp.values() if isinstance(v, str) and v.strip()), '')
    return shorten(first, 60)

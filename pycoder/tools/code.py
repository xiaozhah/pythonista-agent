"""python_code: what a Python name means, where it is defined and used, what a file holds, and what is
wrong with it.

An outline comes from ast, which needs nothing. The rest comes from jedi, pyflakes and mypy, pure Python
and installed on first use, run in this process: iOS can't start subprocesses. They are copies of their
own, out of the import path: Pythonista bundles far older jedi and pyflakes, whose other users newer
ones in site-packages would break.
"""

from __future__ import annotations

import ast
import gc
import io
import os
import re
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from .. import config
from ..host import env, packages
from .base import Tool, ToolContext, ToolError, prop
from .files import walk
from .python_runner import PYTHONISTA_EXIT

JEDI = 'jedi==0.19.2'
PYFLAKES = 'pyflakes==3.4.0'  # the last for Python 3.10
MYPY = 'mypy==1.18.2'  # the last without compiled parts
TOOLS_DIR = os.path.join(config.DATA_DIR, 'code-intelligence')
_LOCK: Any = env.process_wide('code_tools_lock', threading.Lock())  # while its modules stand in for others
_OURS: dict[str, Any] = env.process_wide('code_tools_modules', {})  # kept: they take time to import
LIMIT_SECONDS = 30  # a big project can take long, and these can't be interrupted
TYPES_LIMIT_SECONDS = 180  # mypy without its compiled parts is slow the first time, cached after
MAX_FILES = 2000
MAX_RESULTS = 100
MAX_DOC = 2000


def _ours(name: str) -> bool:
    """Whether a module belongs to what is installed in TOOLS_DIR."""
    return os.path.isdir(os.path.join(TOOLS_DIR, name.split('.')[0])) or os.path.isfile(
        os.path.join(TOOLS_DIR, name.split('.')[0] + '.py')
    )


@contextmanager
def _own(ctx: ToolContext, module: str, requirement: str) -> Iterator[None]:
    """Our copies under their names, for as long as this lasts; then whatever was there before."""
    with _LOCK:
        if not os.path.isdir(os.path.join(TOOLS_DIR, module)):
            ctx.frontend.run_output(f'installing {requirement} (first use)')
            try:
                packages.install(
                    requirement, log=lambda line: ctx.frontend.run_output(line), target=TOOLS_DIR
                )
            except packages.PackageError as e:
                raise ToolError(f'Could not install {requirement}: {e}') from e
        others = {name: sys.modules.pop(name) for name in list(sys.modules) if _ours(name)}
        sys.modules.update(_OURS)
        sys.path.insert(0, TOOLS_DIR)
        try:
            yield
        finally:
            sys.path.remove(TOOLS_DIR)
            _OURS.clear()
            _OURS.update({name: sys.modules.pop(name) for name in list(sys.modules) if _ours(name)})
            sys.modules.update(others)


def _jedi() -> Any:
    import jedi

    jedi.settings.cache_directory = os.path.join(TOOLS_DIR, 'jedi-cache')
    return jedi


def _project(ctx: ToolContext) -> Any:
    """The workspace, with this process as jedi's Python (the version it is pinned to reads this)."""
    from jedi.api.environment import InterpreterEnvironment

    project = _jedi().Project(ctx.workspace.root)
    project._environment = InterpreterEnvironment()
    return project


def _script(ctx: ToolContext, path: str) -> tuple[Any, list[str]]:
    full = ctx.workspace.resolve_readable(path)
    text = ctx.workspace.read_text(full)
    script = _jedi().Script(code=text, path=full, project=_project(ctx))
    return script, text.splitlines()


def _column(lines: list[str], line: int, name: str) -> int:
    """Where the name is in that line, as a word."""
    if not 1 <= line <= len(lines):
        raise ToolError(f'Line {line} is outside the file ({len(lines)} lines)')
    found = re.search(rf'\b{re.escape(name)}\b', lines[line - 1])
    if found is None:
        raise ToolError(f'{name!r} is not on line {line}: {lines[line - 1].strip()[:120]}')
    return found.start()


def _where(ctx: ToolContext, name: Any) -> str:
    """One result: path:line and its line of code, or what it is if it has no file."""
    if name.module_path is None or name.line is None:
        return f'{name.type} {name.full_name or name.name} (built in)'
    full = str(name.module_path)
    code = (name.get_line_code() or '').strip()
    return f'{ctx.workspace.rel(full)}:{name.line}: {code[:160]}'


def _listed(ctx: ToolContext, names: list[Any], nothing: str) -> str:
    shown = [_where(ctx, n) for n in names if n.module_path is None or not ctx.denied(str(n.module_path))]
    if not shown:
        return nothing
    more = f'\n… {len(shown) - MAX_RESULTS} more' if len(shown) > MAX_RESULTS else ''
    return '\n'.join(shown[:MAX_RESULTS]) + more


def _symbols(ctx: ToolContext, path: str) -> str:
    """Classes and functions, nested as they are, with their parameters."""
    full = ctx.workspace.resolve_readable(path)
    try:
        tree = ast.parse(ctx.workspace.read_text(full))
    except SyntaxError as e:
        raise ToolError(f'Line {e.lineno}: {e.msg}') from e
    lines: list[str] = []

    def walk(body: list[ast.stmt], depth: int) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                bases = ', '.join(ast.unparse(b) for b in node.bases)
                lines.append(
                    f'{"  " * depth}{node.lineno}: class {node.name}' + (f'({bases})' if bases else '')
                )
                walk(node.body, depth + 1)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lines.append(f'{"  " * depth}{node.lineno}: def {node.name}({ast.unparse(node.args)})')
                walk(node.body, depth + 1)

    walk(tree.body, 0)
    return '\n'.join(lines) or 'No classes or functions'


def _hover(ctx: ToolContext, script: Any, line: int, column: int, name: str) -> str:
    found = script.help(line, column) or script.goto(line, column, follow_imports=True)
    if not found:
        return f'Nothing known about {name} there'
    parts = []
    for item in found[:3]:
        signatures = [s.to_string() for s in item.get_signatures()]
        head = signatures[0] if signatures else f'{item.type} {item.full_name or item.name}'
        doc = item.docstring(raw=True).strip()
        parts.append(head + (f'\n{doc[:MAX_DOC]}' if doc else ''))
    return '\n\n'.join(parts)


def _python_files(ctx: ToolContext, path: str) -> list[str]:
    full = ctx.workspace.resolve_readable(path or '.')
    if os.path.isfile(full):
        return [full]
    found = [
        os.path.join(folder, name)
        for folder, _, names in walk(full)
        for name in names
        if name.endswith('.py') and not ctx.denied(os.path.join(folder, name))
    ]
    if len(found) > MAX_FILES:
        raise ToolError(f'Over {MAX_FILES} Python files here: choose a folder within')
    return found


def _problems(ctx: ToolContext, lines: list[str], checked: int) -> str:
    if not lines:
        return f'No problems found in {checked} file{"" if checked == 1 else "s"}'
    more = f'\n… {len(lines) - MAX_RESULTS} more' if len(lines) > MAX_RESULTS else ''
    return '\n'.join(lines[:MAX_RESULTS]) + more


def _check(ctx: ToolContext, path: str) -> str:
    """Syntax errors, and what pyflakes finds: undefined names, unused imports and variables, …"""
    from pyflakes import api, reporter

    files = _python_files(ctx, path)
    lines: list[str] = []
    for full in files:
        text = ctx.workspace.read_text(full)
        rel = ctx.workspace.rel(full)
        out = io.StringIO()
        api.check(text, rel, reporter.Reporter(out, out))
        lines += [line for line in out.getvalue().splitlines() if line.startswith(rel)]
    return _problems(ctx, lines, len(files))


def _types(ctx: ToolContext, path: str) -> str:
    """What mypy finds, in this process. It changes the garbage collector's settings, for a run of its
    own, and reads MYPYPATH to find the project's modules."""
    from mypy.main import main

    files = _python_files(ctx, path)
    if not files:
        return 'No Python files here'
    thresholds = gc.get_threshold()
    search = os.environ.get('MYPYPATH')
    os.environ['MYPYPATH'] = ctx.workspace.root
    try:
        out, err = io.StringIO(), io.StringIO()
        try:
            main(
                args=[
                    '--cache-dir',
                    os.path.join(TOOLS_DIR, 'mypy-cache'),
                    '--config-file=',
                    '--no-site-packages',  # it asks a subprocess where they are
                    '--ignore-missing-imports',
                    '--disable-error-code=import-untyped',  # a library without stubs is not a problem here
                    '--check-untyped-defs',  # most of what is written here has no annotations
                    '--follow-imports=silent',
                    '--explicit-package-bases',
                    '--no-error-summary',
                    '--show-error-codes',
                    '--show-absolute-path',
                    *files,
                ],
                stdout=out,
                stderr=err,
                clean_exit=True,
            )
        except SystemExit:
            pass  # it exits to say it found something: what it found is in out
        except KeyboardInterrupt as e:  # as sys.exit is in Pythonista
            if not str(e).startswith(PYTHONISTA_EXIT):
                raise
    finally:
        gc.set_threshold(*thresholds)
        if search is None:
            del os.environ['MYPYPATH']
        else:
            os.environ['MYPYPATH'] = search
    lines = []
    for line in out.getvalue().splitlines():
        where, colon, rest = line.partition(':')
        if colon and os.path.isabs(where):
            if ctx.denied(where):
                continue
            line = f'{ctx.workspace.rel(where)}:{rest}'
        lines.append(line)
    if err.getvalue().strip():
        lines.append(err.getvalue().strip()[:MAX_DOC])
    return _problems(ctx, lines, len(files))


def _limited(
    ctx: ToolContext,
    work: Callable[[], str],
    module: str = 'jedi',
    requirement: str = JEDI,
    seconds: int = LIMIT_SECONDS,
) -> str:
    result: list[str] = []
    failed: list[BaseException] = []

    def run() -> None:
        try:
            with _own(ctx, module, requirement):
                result.append(work())
        except BaseException as e:  # raised again below, on the tool's thread
            failed.append(e)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    for _ in range(seconds * 10):
        thread.join(0.1)
        if not thread.is_alive():
            break
        ctx.cancel.check()
    if thread.is_alive():
        raise ToolError(f'{module} gave no answer in {seconds} s: try a smaller part of the project')
    if failed:
        error = failed[0]
        if isinstance(error, ToolError):
            raise error
        raise ToolError(f'{module} failed: {type(error).__name__}: {error}') from error
    return result[0]


def python_code(ctx: ToolContext, action: str, path: str = '', line: int = 0, name: str = '') -> str:
    if action == 'symbols':
        if not path:
            raise ToolError('symbols needs path')
        return _symbols(ctx, path)
    if action == 'check':
        return _limited(ctx, lambda: _check(ctx, path), 'pyflakes', PYFLAKES)
    if action == 'types':
        return _limited(ctx, lambda: _types(ctx, path), 'mypy', MYPY, TYPES_LIMIT_SECONDS)
    if action == 'find':
        if not name:
            raise ToolError('find needs name')

        def find() -> str:
            return _listed(
                ctx, list(_project(ctx).search(name, all_scopes=True)), f'No definition of {name} here'
            )

        return _limited(ctx, find)
    if action not in ('definition', 'references', 'hover'):
        raise ToolError(
            f'Unknown action {action}: symbols, find, definition, references, hover, check or types'
        )
    if not (path and line and name):
        raise ToolError(f'{action} needs path, line and name')

    def work() -> str:
        script, lines = _script(ctx, path)
        column = _column(lines, line, name)
        if action == 'hover':
            return _hover(ctx, script, line, column, name)
        if action == 'definition':
            return _listed(
                ctx, script.goto(line, column, follow_imports=True), f'No definition of {name} found'
            )
        return _listed(
            ctx, script.get_references(line, column, include_builtins=False), f'No uses of {name} found'
        )

    return _limited(ctx, work)


TOOLS = [
    Tool(
        'python_code',
        "Understand Python code by meaning, not text. symbols: a file's classes and functions with their "
        'parameters. find: where a name is defined in the project. For a name on a line of a file: '
        'definition goes to where it is defined (following imports), references lists where it is used '
        'across the project, hover gives its signature and docstring. check finds syntax errors, '
        'undefined names and unused imports in a file or folder, at once; types runs mypy there, which '
        "is slow the first time and can't see inside modules without source, such as ui. Prefer it to "
        "search when a name's meaning matters, as a common word or a method name matches too much text.",
        {
            'action': prop(
                'string',
                'What to find out',
                enum=['symbols', 'find', 'definition', 'references', 'hover', 'check', 'types'],
            ),
            'path': prop(
                'string', 'The Python file; for check and types also a folder (default: all); not for find'
            ),
            'line': prop('integer', 'The line the name is on (from 1), for definition, references, hover'),
            'name': prop('string', 'The name, as it is written on that line, or to find'),
        },
        python_code,
        required=['action'],
    ),
]

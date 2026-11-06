"""run_c: compile a C program with ppci and run it in JavaScriptCore, inside Pythonista (host/cwasm).

ppci is installed on first use, like dulwich for git.
"""

from __future__ import annotations

import os
import time

from ..host import packages
from ..host.cwasm import PPCI
from .base import Tool, ToolContext, ToolError, prop

MAX_TIMEOUT = 300


def _ensure_ppci(ctx: ToolContext) -> None:
    wanted = PPCI.split('==')[1]
    if packages.installed_version('ppci') == wanted:
        return
    ctx.frontend.run_output(f'installing {PPCI} (first use of run_c)')
    try:
        packages.install(PPCI, log=lambda line: ctx.frontend.run_output(line))
    except packages.PackageError as e:
        raise ToolError(f'Could not install ppci: {e}') from e


def run_source(source: str, filename: str = 'main.c', timeout: float = 10) -> str:
    """Compile and run main(); returns what it printed and how it ended. Compile and link errors
    raise ToolError."""
    from ..host.cwasm.compiler import CompileError, compile_c, library
    from ..host.cwasm.runtime import JSError, WasmModule

    try:
        compiled = compile_c(source, filename)
    except CompileError as e:
        raise ToolError(f'Compile error:\n{e}') from None
    module = WasmModule(compiled.wasm, compiled.heap_base, time_limit=timeout)
    try:
        if module.missing:
            raise ToolError(
                "Not in run_c's C library: {}. Write them yourself; what is available: {}".format(
                    ', '.join(module.missing), library()
                )
            )
        if 'main' not in module.exports:
            raise ToolError('The program has no main() function')
        started = time.perf_counter()
        error = None
        try:
            code = int(module.call('main'))
        except JSError as e:
            code, error = None, _runtime_error(str(e), timeout)
        took = time.perf_counter() - started
        parts = [module.stdout().rstrip() or '(no output)']
    finally:
        module.close()
    if error:
        parts.append(f'[{error}]')
    elif code:
        parts.append(f'[exit {code}]')
    parts.append('[compiled in %.2fs, ran in %.2fs]' % (compiled.seconds, took))
    return '\n'.join(parts)


def _runtime_error(message: str, timeout: float) -> str:
    if 'time limit' in message or 'execution terminated' in message:
        return f'stopped: it ran longer than the time limit of {timeout:g}s'
    if 'Out of bounds memory access' in message:
        return f'{message}: a bad pointer or array index, or the 1 MB C stack overflowed'
    return message


def run_c(ctx: ToolContext, code: str | None = None, path: str | None = None, timeout: int = 10) -> str:
    if bool(code) == bool(path):
        raise ToolError('Provide exactly one of code or path')
    if not 0 < timeout <= MAX_TIMEOUT:
        raise ToolError(f'timeout must be between 1 and {MAX_TIMEOUT} seconds')
    filename = 'main.c'
    if path:
        full = ctx.workspace.resolve(path)
        if not os.path.isfile(full):
            raise ToolError(f'File not found: {path}')
        code, filename = ctx.workspace.read_text(full), os.path.basename(full)
    _ensure_ppci(ctx)
    text = run_source(code or '', filename, timeout)
    ctx.frontend.run_output(text)
    return text


TOOLS = [
    Tool(
        'run_c',
        'Compile a C program (one file, C99) and run its main() inside Pythonista; returns what it printed, '
        'the exit code and timings, or the compile error with its line. ppci (a pure-Python compiler, '
        'installed on first use) turns it into WebAssembly and JavaScriptCore runs it: a few times '
        'faster than CPython, far from native speed. For array maths use pycoder.host.accelerate from '
        'Python instead (the accelerate-maths skill). Not supported: passing structs by value, files, '
        'stdin, threads, other libraries. Headers: assert ctype limits math stdbool stddef stdint stdio '
        'stdlib string time (the common functions; a missing one is reported with the full list).',
        {
            'code': prop('string', 'C source to run (use either this or path)'),
            'path': prop('string', '.c file in the workspace to run (use either this or code)'),
            'timeout': prop(
                'integer', f'Seconds before the program is stopped, default 10, at most {MAX_TIMEOUT}'
            ),
        },
        run_c,
        readonly=False,
    ),
]

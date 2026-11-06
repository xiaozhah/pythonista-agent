"""C -> WebAssembly with ppci (pure Python, so it runs in Pythonista).

The module exports its memory as "memory", its functions by name, the C stack pointer as
"__stack_pointer" and the loop fuel counter as "__fuel". Functions the program calls but doesn't
define become imports from module "js" (runtime.js provides them); a variadic one gets one extra
i32 argument: a pointer to its packed arguments.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import re
import time
from dataclasses import dataclass

INCLUDE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'include')
STACK_SIZE = 1 << 20  # ppci's default is 1000 bytes, far too small for local arrays


class CompileError(Exception):
    pass


@dataclass
class Compiled:
    wasm: bytes
    heap_base: int  # where malloc may start: after the stack and the global variables
    seconds: float


def compile_c(source: str, filename: str = 'main.c', opt_level: int = 2) -> Compiled:
    """Compile one C translation unit; raises CompileError with a clang-style message."""
    from ppci import api
    from ppci.common import CompilerError
    from ppci.lang.c import COptions
    from ppci.lang.c.builder import CBuilder
    from ppci.utils.reporting import DummyReportGenerator
    from ppci.wasm import components
    from ppci.wasm.arch import WasmArchitecture
    from ppci.wasm.ppci2wasm import IrToWasmCompiler

    from . import fixes

    fixes.apply()
    started = time.perf_counter()
    options = COptions()
    options.add_include_path(INCLUDE)
    disabled = logging.root.manager.disable
    logging.disable(logging.WARNING)  # ppci logs warnings and prints debug noise from ppci2wasm
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            builder = CBuilder(WasmArchitecture().info, options)
            ir_module = builder.build(io.StringIO(source), filename, reporter=DummyReportGenerator())
            api.optimize(ir_module, level=opt_level)
            compiler = IrToWasmCompiler()
            compiler.STACKSIZE = STACK_SIZE
            compiler.use_fuel = True
            compiler.prepare_compilation()
            compiler.compile(ir_module)
            heap_base = (compiler.global_memory + 15) & ~15
            module = compiler.create_wasm_module()
            for definition in module.definitions:
                if isinstance(definition, components.Memory):  # ppci always asks for 10 pages
                    definition.min = max(definition.min, heap_base // 65536 + 1)
            exports = [
                ('memory', 'memory', 0),
                ('__stack_pointer', 'global', 0),
                ('__fuel', 'global', 1),
            ]
            for name, kind, index in exports:
                module.definitions.append(components.Export(name, kind, components.Ref(kind, index=index)))
            order = {name: i for i, name in enumerate(components.SECTION_IDS)}
            module.definitions.sort(key=lambda d: order[d.__name__])  # exports go before data
            wasm = module.to_bytes()
    except CompilerError as e:
        raise CompileError(_located(e, source, filename)) from None
    except Exception as e:  # ppci's own limits surface as KeyError, NotImplementedError, ...
        raise CompileError(_unsupported(e)) from None
    finally:
        logging.disable(disabled)
    return Compiled(wasm, heap_base, time.perf_counter() - started)


def library() -> str:
    """The C library programs get, header by header: 'stdio.h (printf, puts), …'."""
    parts = []
    for name in sorted(os.listdir(INCLUDE)):
        with open(os.path.join(INCLUDE, name), encoding='utf-8') as f:
            text = f.read()
        functions = [f for f in re.findall(r'(\w+)\([^()]*\);', text) if not f.startswith('_')]
        if name == 'assert.h':
            functions = ['assert']
        parts.append(name + (' ({})'.format(', '.join(functions)) if functions else ''))
    return ', '.join(parts)


def _located(error: object, source: str, filename: str) -> str:
    """A clang-style message: file:line:column, the source line and a caret under the column."""
    message = str(getattr(error, 'msg', error))
    loc = getattr(error, 'loc', None)
    if loc is None or not getattr(loc, 'row', None):
        return f'{filename}: error: {message}'
    row, col = int(loc.row), int(loc.col or 1)
    lines = source.splitlines()
    text = lines[row - 1] if 0 < row <= len(lines) else ''
    return f'{filename}:{row}:{col}: error: {message}\n    {text}\n    {" " * (col - 1)}^'


def _unsupported(error: Exception) -> str:
    detail = f'{type(error).__name__}: {error}'
    if 'blob' in str(error):
        return (
            'passing a struct by value to a function is not supported; pass a pointer to it '
            f'instead ({detail})'
        )
    return f'the compiler (ppci) cannot handle part of this program: {detail}'

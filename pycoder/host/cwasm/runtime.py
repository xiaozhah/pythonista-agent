"""Run a module from compiler.py in an in-process JavaScriptCore context.

    module = WasmModule(compiled.wasm, compiled.heap_base, time_limit=10)
    module.call('main')         # numbers in, a number out
    module.stdout()             # what printf/puts/putchar wrote

The wasm bytes reach JavaScript through a plain ArrayBuffer whose address JavaScriptCore gives us,
checked for NULL and length before the copy.
"""

from __future__ import annotations

import ctypes
import json
import os

from .jsc import Context, JSError

__all__ = ['JSError', 'WasmModule']

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runtime.js'), encoding='utf-8') as _f:
    RUNTIME_JS = _f.read()


class WasmModule:
    def __init__(self, wasm: bytes, heap_base: int, time_limit: float = 10.0) -> None:
        self.js = Context(time_limit=time_limit)  # stops runaway JS; wasm loops stop through fuel
        try:
            self.js.eval(RUNTIME_JS)
            self.js.eval(f'__cw.setLimit({float(time_limit)!r})')
            address, size = self.js.array_buffer(f'__cw.stage({max(len(wasm), 1)})')
            if size < len(wasm):
                raise JSError(f'staging buffer too small: {size} < {len(wasm)}')
            ctypes.memmove(address, wasm, len(wasm))
            info = json.loads(self.js.eval(f'__cw.load({len(wasm)}, {int(heap_base)})'))
        except BaseException:
            self.js.close()
            raise
        self.exports: list[str] = info['exports']
        self.missing: list[str] = info['missing']  # functions called but neither defined nor provided

    def close(self) -> None:
        self.js.close()

    def call(self, name: str, *args: float) -> float:
        """Call an exported function; a trap, exit() or the time limit raise JSError (exit returns)."""
        if name not in self.exports:
            raise JSError(f'no function {name}()')
        return self.js.eval_num(f'__cw.call({json.dumps(name)}, {json.dumps(list(args))})')

    def stdout(self) -> str:
        """What the program printed since the last call; C strings are bytes, read as UTF-8."""
        text = self.js.eval('__cw.stdout()')
        return text.encode('latin-1', 'replace').decode('utf-8', 'replace')

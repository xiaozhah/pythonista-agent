"""A minimal JavaScriptCore binding over ctypes: the C API only, no objc_util, no blocks, no callbacks.

Everything is synchronous and runs on the calling thread, in Pythonista (iOS and Mac) and in plain
Python on macOS. Raw memory is touched only through addresses JavaScriptCore handed out and checked:
it returns NULL for a WebAssembly memory's buffer, and copying into that crashes the app.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_bool, c_char_p, c_double, c_int, c_size_t, c_void_p
from typing import Any

FRAMEWORK = '/System/Library/Frameworks/JavaScriptCore.framework/JavaScriptCore'
_LIB: Any = None


class JSError(Exception):
    pass


def available() -> bool:
    """Whether JavaScriptCore can be loaded here (Apple platforms only)."""
    try:
        lib()
    except OSError:
        return False
    return True


def lib() -> Any:
    global _LIB
    if _LIB is None:
        library = ctypes.CDLL(FRAMEWORK)
        signatures: dict[str, tuple[Any, list[Any]]] = {
            'JSGlobalContextCreate': (c_void_p, [c_void_p]),
            'JSGlobalContextRelease': (None, [c_void_p]),
            'JSStringCreateWithUTF8CString': (c_void_p, [c_char_p]),
            'JSStringRelease': (None, [c_void_p]),
            'JSStringGetMaximumUTF8CStringSize': (c_size_t, [c_void_p]),
            'JSStringGetUTF8CString': (c_size_t, [c_void_p, c_char_p, c_size_t]),
            'JSEvaluateScript': (
                c_void_p,
                [c_void_p, c_void_p, c_void_p, c_void_p, c_int, POINTER(c_void_p)],
            ),
            'JSValueToStringCopy': (c_void_p, [c_void_p, c_void_p, POINTER(c_void_p)]),
            'JSValueToNumber': (c_double, [c_void_p, c_void_p, POINTER(c_void_p)]),
            'JSValueToObject': (c_void_p, [c_void_p, c_void_p, POINTER(c_void_p)]),
            'JSValueIsObject': (c_bool, [c_void_p, c_void_p]),
            'JSObjectGetArrayBufferBytesPtr': (c_void_p, [c_void_p, c_void_p, POINTER(c_void_p)]),
            'JSObjectGetArrayBufferByteLength': (c_size_t, [c_void_p, c_void_p, POINTER(c_void_p)]),
            'JSContextGetGroup': (c_void_p, [c_void_p]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(library, name)
            function.restype, function.argtypes = result, args
        # private API (JSContextRefPrivate.h), exported by the framework; a NULL callback terminates
        try:
            function = library.JSContextGroupSetExecutionTimeLimit
            function.restype, function.argtypes = None, [c_void_p, c_double, c_void_p, c_void_p]
        except AttributeError:
            pass
        _LIB = library
    return _LIB


class Context:
    """One JavaScript global context; close() it when done.

    Not for a parallel pool: `JSGlobalContextCreate(NULL)` contexts share JavaScriptCore's default
    group and its lock, so running several on different threads serializes and contends (measured
    0.78x on 4 threads, slower than one). A parallel WASM worker pool needs each worker in its own
    group — a per-thread `JSVirtualMachine` (ObjC) or `JSContextGroupCreate` + `JSGlobalContextCreateInGroup`
    — which does run across cores. See the `webassembly-in-javascriptcore` skill."""

    def __init__(self, time_limit: float | None = None) -> None:
        self.lib = lib()
        self.ctx = self.lib.JSGlobalContextCreate(None)
        if not self.ctx:
            raise JSError('JSGlobalContextCreate failed')
        if time_limit:
            self.set_time_limit(time_limit)

    def set_time_limit(self, seconds: float) -> bool:
        """Stop any single evaluation that runs longer than `seconds` of CPU time. JavaScript only:
        a WebAssembly loop is not interrupted (compiler.py's loop fuel handles those)."""
        if not hasattr(self.lib, 'JSContextGroupSetExecutionTimeLimit'):
            return False
        group = self.lib.JSContextGetGroup(self.ctx)
        if not group:
            return False
        self.lib.JSContextGroupSetExecutionTimeLimit(group, float(seconds), None, None)
        return True

    def close(self) -> None:
        if self.ctx:
            self.lib.JSGlobalContextRelease(self.ctx)
            self.ctx = None

    def _string(self, js_string: int) -> str:
        size = self.lib.JSStringGetMaximumUTF8CStringSize(js_string)
        buffer = ctypes.create_string_buffer(size)
        self.lib.JSStringGetUTF8CString(js_string, buffer, size)
        return buffer.value.decode('utf-8', 'replace')

    def to_str(self, value: Any) -> str:
        exception = c_void_p()
        js_string = self.lib.JSValueToStringCopy(self.ctx, value, byref(exception))
        if not js_string:
            return '<unprintable>'
        try:
            return self._string(js_string)
        finally:
            self.lib.JSStringRelease(js_string)

    def eval_raw(self, source: str) -> Any:
        """Evaluate; the JSValueRef returned is valid until the next garbage collection."""
        script = self.lib.JSStringCreateWithUTF8CString(source.encode('utf-8'))
        exception = c_void_p()
        try:
            value = self.lib.JSEvaluateScript(self.ctx, script, None, None, 1, byref(exception))
        finally:
            self.lib.JSStringRelease(script)
        if exception.value:
            raise JSError(self.to_str(exception))
        return value

    def eval(self, source: str) -> str:
        """Evaluate and return the result as a string (JSON.stringify structured data in JS)."""
        return self.to_str(self.eval_raw(source))

    def eval_num(self, source: str) -> float:
        value = self.eval_raw(source)
        exception = c_void_p()
        return float(self.lib.JSValueToNumber(self.ctx, value, byref(exception)))

    def array_buffer(self, source: str) -> tuple[int, int]:
        """(address, length) of the ArrayBuffer `source` evaluates to; raises instead of returning
        NULL. The address is valid until the buffer is replaced or detached, so ask again after
        anything that may have done that."""
        value = self.eval_raw(source)
        if not value or not self.lib.JSValueIsObject(self.ctx, value):
            raise JSError(f'{source} is not an object')
        exception = c_void_p()
        obj = self.lib.JSValueToObject(self.ctx, value, byref(exception))
        if not obj or exception.value:
            raise JSError(f'{source}: JSValueToObject failed')
        exception = c_void_p()
        address = self.lib.JSObjectGetArrayBufferBytesPtr(self.ctx, obj, byref(exception))
        if exception.value:
            raise JSError(self.to_str(exception))
        length = self.lib.JSObjectGetArrayBufferByteLength(self.ctx, obj, byref(exception))
        if not address or not length:
            raise JSError(f'{source}: no ArrayBuffer bytes (address={address!r}, length={length!r})')
        return int(address), int(length)

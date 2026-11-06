"""Calling onto the main thread without losing the call.

objc_util.on_main_thread keeps each call's function and arguments on a new Objective-C object, and the
main thread finds them again through objc_util's weak cache of objects by address. With threads busy it
may find a fresh, empty object there: the call is dropped, with only a TypeError on the console. Here
one object lives for good, and the calls wait in a queue. objc_util's name points here too, for the
programs pycoder runs and for code that imported it from there.

ui.delay and ui.cancel_delays are replaced too: a chain of the built-in ui.delay with other threads
running damages memory and takes Pythonista down in seconds, whoever calls it.
"""

from __future__ import annotations

import collections
import ctypes
import functools
import sys
import threading
import traceback
import types
from collections.abc import Callable
from typing import Any

from . import env

_shared: Any = env.process_wide(
    'main_thread_calls',
    types.SimpleNamespace(pending=collections.deque(), perform=None, is_main=None, timers=set()),
)
SELECTOR = 'performSelectorOnMainThread:withObject:waitUntilDone:'


class _Call:
    def __init__(self, func: Callable[..., Any], args: Any, kwargs: Any) -> None:
        self.func, self.args, self.kwargs = func, args, kwargs
        self.result: Any = None
        self.done = threading.Event()


def run_next() -> None:
    """On the main thread: the calls waiting, all of them: a Stop that ends a thread between queueing
    its call and performing it would otherwise leave every later call waiting for the one before. As
    in objc_util, a failure is printed and the caller gets None."""
    while _shared.pending:
        try:
            call = _shared.pending.popleft()
        except IndexError:
            return
        try:
            call.result = call.func(*call.args, **call.kwargs)
        except Exception:
            traceback.print_exc(file=sys.stderr)
        finally:
            call.done.set()


def _prepare() -> None:
    """Once per process: the one object, and one function for each thing called, never changed after,
    so that threads can share them."""
    from objc_util import c, create_objc_class, sel

    def runCall(_self, _cmd):  # type: ignore[no-untyped-def]
        run_next()

    runCall.encoding = b'v@:'  # type: ignore[attr-defined]
    dispatcher = create_objc_class('PycoderMainThreadCalls', methods=[runCall]).new()
    send = c['objc_msgSend']
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]
    send.restype = None
    selector, name = sel(SELECTOR), sel('runCall')
    is_main = ctypes.CDLL(None).pthread_main_np
    is_main.restype = ctypes.c_int
    is_main.argtypes = []
    _shared.keep = (dispatcher, runCall, send)
    _shared.is_main = lambda: bool(is_main())
    _shared.perform = lambda: send(dispatcher.ptr, selector, name, None, False)


def on_main_thread(func: Callable[..., Any]) -> Callable[..., Any]:
    if not callable(func):
        raise TypeError('expected a callable')

    @functools.wraps(func)
    def on_main(*args: Any, **kwargs: Any) -> Any:
        if _shared.perform is None:
            _prepare()
        if _shared.is_main():
            return func(*args, **kwargs)
        call = _Call(func, args, kwargs)
        _shared.pending.append(call)  # one performed for each appended: none is left waiting
        _shared.perform()
        call.done.wait()
        return call.result

    return on_main


def delay(func: Callable[[], Any], seconds: float) -> None:
    """ui.delay: func on the main thread after that many seconds."""

    def fire() -> None:
        _shared.timers.discard(timer)
        on_main_thread(func)()

    timer = threading.Timer(seconds, fire)
    timer.daemon = True
    _shared.timers.add(timer)
    timer.start()


def cancel_delays() -> None:
    """ui.cancel_delays: forget all that are still waiting."""
    for timer in list(_shared.timers):
        timer.cancel()
        _shared.timers.discard(timer)


def call_on_main(fn: Callable[..., Any], *args: Any) -> Any:
    """Call fn on the main thread, where there is one. Calls that wait for the main thread while
    holding Python's lock, like the clipboard's, freeze Pythonista for good from any other."""
    if not env.IN_PYTHONISTA:
        return fn(*args)
    return on_main_thread(fn)(*args)


def install() -> None:
    if env.IN_PYTHONISTA:
        import objc_util
        import ui

        objc_util.on_main_thread = on_main_thread  # type: ignore[assignment]
        ui.delay = delay
        ui.cancel_delays = cancel_delays

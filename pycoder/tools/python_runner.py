"""run_python: execute code inside the Pythonista process (iOS can't spawn subprocesses)."""

from __future__ import annotations
import __future__

import ctypes
import functools
import io
import os
import reprlib
import sys
import threading
import time
import traceback
import types
import warnings
from collections.abc import Sequence
from typing import Any

from .. import config
from ..cancel import CancelToken
from ..host import env
from ..host.env import available_memory
from ..state.workspace import Workspace
from .base import Tool, ToolContext, ToolError, prop

# what run_python keeps of the printed output: the start and the end, together a tool result's worth
OUTPUT_HEAD = config.MAX_TOOL_OUTPUT // 2
OUTPUT_TAIL = config.MAX_TOOL_OUTPUT // 2 - 1000  # room for the traceback and the notes after it
# iOS kills the whole app, pycoder and the session with it, when it runs out of memory; code is
# stopped (with a MemoryError) while this much is still left
MEMORY_RESERVE = 300 * 10**6
PYTHONISTA_EXIT = 'Exit: '
STOP_TRIES = 12  # times a run is told to stop
STOP_EVERY = 0.25  # seconds apart


def run_code(
    workspace: Workspace,
    code: str | None = None,
    path: str | None = None,
    args: list[str] | None = None,
    timeout: int = 60,
    cancel: CancelToken | None = None,
    reserve: int = MEMORY_RESERVE,
) -> str:
    """Run code or a workspace .py file with a timeout; returns stdout/stderr, traceback and timing.

    The Stop button (cancel) interrupts it like the timeout does, and so does memory running low
    (less than `reserve` bytes left).
    """
    run = Run(workspace, code, path, args)
    run.start()
    run.wait(timeout, cancel, reserve)
    if run.alive():
        run.interrupt('stopped' if cancel and cancel.cancelled else 'timeout', timeout)
    return run.report()


class Run:
    """Code running in a thread of its own, with what it prints captured: run_python waits for it;
    a background job (tools/jobs.py) is checked on later."""

    def __init__(
        self,
        workspace: Workspace,
        code: str | None = None,
        path: str | None = None,
        args: list[str] | None = None,
    ) -> None:
        if bool(code) == bool(path):
            raise ToolError('Provide exactly one of code or path')
        if path:
            full = workspace.resolve(path)
            if not os.path.isfile(full):
                raise ToolError(f'File not found: {path}')
            self.source, self.filename = workspace.read_text(full), full
        else:
            self.source, self.filename = code or '', '<run_python>'
        self.workspace = workspace
        self.from_file = bool(path)
        self.argv = [self.filename, *(args or [])]
        self.buf = CappedOutput()
        self.result: dict[str, Any] = {}
        self.limit = 0  # the timeout that stopped it, for the report
        self.started = self.ended = 0.0
        self.finishing = False  # its code has ended, and it is cleaning up
        self.thread = threading.Thread(target=self._target, daemon=True)

    def start(self) -> None:
        self.started = time.time()
        self.thread.start()

    def alive(self) -> bool:
        return self.thread.is_alive()

    def wait(self, seconds: float, cancel: CancelToken | None = None, reserve: int = MEMORY_RESERVE) -> None:
        """Until it ends, `seconds` pass or the user stops it; stops it first if memory runs low."""
        deadline = time.monotonic() + seconds  # not time.time(), which jumps when the device sleeps
        while self.alive() and time.monotonic() < deadline and not (cancel and cancel.cancelled):
            self.thread.join(0.2)
            left = available_memory()
            if left is not None and left < reserve:
                self.interrupt('low memory')
                return

    def interrupt(self, why: str, limit: int = 0) -> None:
        """Stop it with an exception in its thread: why is 'timeout', 'stopped' or 'low memory'."""
        if not self.alive() or self.thread.ident is None:
            return
        error = {'low memory': MemoryError, 'stopped': KeyboardInterrupt}.get(why, TimeoutError)
        for _ in range(STOP_TRIES):  # once isn't enough: `except OSError` swallows a TimeoutError, even
            if self.finishing:  # in realpath; and past this point it must not break the cleaning up
                break
            ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_ulong(self.thread.ident), ctypes.py_object(error)
            )
            self.thread.join(STOP_EVERY)
            if not self.alive():
                break
        self.thread.join(STOP_EVERY)
        self.result[why] = True
        self.limit = limit
        self.result['stuck'] = self.alive()  # blocked in C (a sleep, a socket): not interruptible
        if self.result['stuck']:
            _PROCESS_STATE.give_back(self.thread)  # it may never end: the process goes on without it

    def report(self) -> str:
        """What it printed, then its traceback and how it ended (so far, if it is still running)."""
        result = self.result
        parts = [self.buf.getvalue().rstrip() or ('' if result.get('tb') else '(no output)')]
        if result.get('tb'):
            parts.append(str(result['tb']).rstrip())
        if result.get('locals'):
            parts.append(str(result['locals']))
        if result.get('low memory'):
            parts.append(
                '[stopped: memory was almost used up, and iOS would have closed Pythonista. Use less '
                'memory: process the data in chunks, or keep fewer things in memory at once]'
            )
        if result.get('stuck'):
            why = (
                'the user stopped it'
                if result.get('stopped')
                else 'it ran low on memory'
                if result.get('low memory')
                else f'timed out after {self.limit}s'
            )
            parts.append(
                f'[{why}, but it is still running in the background: it is blocked in a call Python '
                'cannot interrupt (a long sleep, a network or file wait); its later output is lost]'
            )
        elif result.get('timeout'):
            parts.append(f'[timed out after {self.limit}s, aborted]')
        elif result.get('stopped'):
            parts.append('[stopped]')
        if 'exit' in result:
            parts.append('[exit {}]'.format(result['exit']))
        parts.append('[took %.1fs]' % ((self.ended or time.time()) - self.started))
        return '\n'.join(filter(None, parts))

    def _target(self) -> None:
        shadowed: dict[str, types.ModuleType] = {}
        root, filename = self.workspace.root, self.filename
        try:  # all of it, setup too: a stop can arrive at any point
            _OUTPUT.route(self.buf)
            shadowed = _forget_user_modules(root)
            paths = [os.path.dirname(filename) if self.from_file else root]
            src = os.path.join(root, 'src')
            if os.path.isdir(src):  # the src layout: the package lives in src/, not installed
                paths.append(src)
            _PROCESS_STATE.take(self.argv, root, paths)
            # a module of its own as __main__, as a script has: unittest.main(), pickle and doctest
            # look the script up in sys.modules
            main = types.ModuleType('__main__')
            main.__file__ = filename
            sys.modules['__main__'] = main
            exec(compile(self.source, filename, 'exec'), main.__dict__)
        except SystemExit as e:
            self.finishing = True
            self.result['exit'] = e.code
        except BaseException as e:
            self.finishing = True
            # Pythonista's sys.exit raises this instead of SystemExit (unittest.main() calls it)
            if isinstance(e, KeyboardInterrupt) and str(e).startswith(PYTHONISTA_EXIT):
                self.result['exit'] = str(e)[len(PYTHONISTA_EXIT) :]
                return
            # skip this function's frame; keep only the user code's traceback
            self.result['tb'] = ''.join(
                traceback.format_exception(type(e), e, e.__traceback__.tb_next if e.__traceback__ else None)
            )
            self.result['locals'] = failing_locals(e, root)
        finally:
            self.finishing = True
            _unshadow(shadowed)
            _PROCESS_STATE.give_back()
            self.ended = time.time()
            _OUTPUT.unroute()


class _Output(io.TextIOBase):
    """sys.stdout and sys.stderr while code runs: each run prints into its own buffer, so a job in
    the background and a run in the foreground don't mix. Threads the code starts print into the
    latest run's buffer; threads that were already there aren't its own and keep printing where they
    did. Python's own streams are back once no code runs.

    Its state is the process's (env.process_wide), not this module's: pycoder may be loaded again
    while code runs, and the newer code then acts on the same routes."""

    def __init__(self) -> None:
        self.shared = env.process_wide(
            'run_output_state', types.SimpleNamespace(lock=threading.Lock(), routes={}, saved=None)
        )
        self.shared.__dict__.setdefault('before', {})  # run's thread -> the threads there when it began

    def route(self, buf: CappedOutput) -> None:
        s = self.shared
        with s.lock:
            if not s.routes:
                s.saved = (sys.stdout, sys.stderr)
            # in place even if something swapped the streams since (pytest, when code that runs
            # tests runs code)
            sys.stdout = sys.stderr = self
            s.routes[threading.get_ident()] = buf
            s.before[threading.get_ident()] = {t.ident for t in threading.enumerate()}

    def unroute(self) -> None:
        s = self.shared
        with s.lock:
            s.routes.pop(threading.get_ident(), None)
            s.before.pop(threading.get_ident(), None)
            if not s.routes and s.saved is not None:
                sys.stdout, sys.stderr = s.saved
                s.saved = None

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        s = self.shared
        me = threading.get_ident()
        buf = s.routes.get(me)
        if buf is None:  # started by the latest run that it wasn't already there for
            for run in reversed(list(s.routes)):
                if me not in s.before.get(run, ()):
                    buf = s.routes.get(run)
                    break
        if buf is not None:
            return int(buf.write(text))
        stream = s.saved[0] if s.saved else sys.__stdout__
        return stream.write(text) if stream is not None else len(text)


_OUTPUT = _Output()


def console_stream() -> Any:
    """Where the app's own words go on a thread that running code would take as printing for it: the
    main thread, for one."""
    saved = _OUTPUT.shared.saved
    return saved[0] if saved else sys.stdout


class _ProcessState:
    """sys.argv, sys.path, __main__ and the working directory belong to the whole process, and a run
    sets them, while runs can overlap: a background job, or a run stuck past its timeout, goes on
    during newer ones. So the runs holding them form a stack, each with what was there when it took
    them. The latest run ending gives the one before it its settings back (a job's relative paths
    keep working after a foreground run); an older run ending leaves the newer run's settings alone
    and hands down what it saved. The stack is the process's (env.process_wide), whichever load of
    pycoder started the run."""

    def __init__(self) -> None:
        self.shared = env.process_wide(
            'run_holders', types.SimpleNamespace(lock=threading.Lock(), holders=[])
        )

    def take(self, argv: list[str] | None = None, cwd: str = '', paths: Sequence[str] = ()) -> None:
        """Hold them and set them, in one step: a run starting in between would save, as what to go
        back to, a state that is neither this run's nor the one before it."""
        s = self.shared
        with s.lock:
            saved = (
                sys.argv,
                os.getcwd(),
                list(sys.path),
                sys.modules.get('__main__'),
                list(warnings.filters),
            )
            s.holders.append([threading.current_thread(), saved])
            if argv is not None:
                sys.argv = argv
            if cwd:
                os.chdir(cwd)
            sys.path[:0] = paths

    def give_back(self, thread: threading.Thread | None = None) -> None:
        """For this thread, or for a stuck run's, which is left to itself."""
        s = self.shared
        thread = thread or threading.current_thread()
        with s.lock:
            index = next((i for i, h in enumerate(s.holders) if h[0] is thread), None)
            if index is None:
                return
            _, saved = s.holders.pop(index)
            if index < len(s.holders):  # newer runs hold them: the next one restores what this saved
                s.holders[index][1] = saved
                return
            argv, cwd, path, main, filters = saved
            sys.argv, sys.path[:] = argv, path
            # code that turned warnings into errors doesn't do it for the next
            warnings.filters[:] = filters  # type: ignore[index]
            warnings._filters_mutated()  # type: ignore[attr-defined]
            if main is None:
                sys.modules.pop('__main__', None)
            else:
                sys.modules['__main__'] = main
            try:
                os.chdir(cwd)
            except OSError:
                pass


_PROCESS_STATE = _ProcessState()


class CappedOutput(io.TextIOBase):
    """What the code prints, keeping only its start and its end: a script printing millions of
    lines must not fill the memory, nor the chat page that shows the output. Writes are plain
    appends; the middle is dropped now and then, in one go."""

    def __init__(self, head: int = OUTPUT_HEAD, tail: int = OUTPUT_TAIL) -> None:
        super().__init__()
        self.head_limit, self.tail_limit = head, tail
        self.head: str | None = None  # the start, once that much has been printed
        self.parts: list[str] = []
        self.size = 0
        self.dropped = 0

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self.parts.append(text)
        self.size += len(text)
        if self.size > 4 * (self.head_limit + self.tail_limit):
            self._trim()
        return len(text)

    def _trim(self) -> None:
        rest = ''.join(self.parts)
        if self.head is None:
            if len(rest) <= self.head_limit:
                return
            self.head, rest = rest[: self.head_limit], rest[self.head_limit :]
        self.dropped += max(0, len(rest) - self.tail_limit)
        self.parts = [rest[-self.tail_limit :]] if rest else []
        self.size = len(self.parts[0]) if self.parts else 0

    def getvalue(self) -> str:
        self._trim()
        gap = f'\n… [{self.dropped} characters of output left out] …\n' if self.dropped else ''
        return (self.head or '') + gap + ''.join(self.parts)


def failing_locals(error: BaseException, root: str, limit: int = 20) -> str:
    """The variables of the innermost user-code frame of the error: what a debugger would show first.

    User code is the run_python snippet or a file in the workspace; library frames are skipped, and
    modules, functions and classes are left out as noise.
    """
    root = os.path.realpath(root)
    frame, line = None, 0
    tb = error.__traceback__
    while tb is not None:
        name = tb.tb_frame.f_code.co_filename
        if name == '<run_python>' or (
            os.path.isfile(name) and os.path.realpath(name).startswith(root + os.sep)
        ):
            frame, line = tb.tb_frame, tb.tb_lineno
        tb = tb.tb_next
    if frame is None:
        return ''
    names = [
        n
        for n, v in frame.f_locals.items()
        if not n.startswith('__')
        and not isinstance(v, (types.ModuleType, types.FunctionType, type, __future__._Feature))
    ][:limit]
    if not names:
        return ''
    lines = [f'Locals in {frame.f_code.co_name}() at line {line}:']
    for name in names:
        try:
            value = short_repr(frame.f_locals[name])
        except Exception as e:
            value = f'<repr failed: {type(e).__name__}>'
        lines.append(f'  {name} = {value[:200]}')
    return '\n'.join(lines)


_SHORT = reprlib.Repr()
_SHORT.maxstring = _SHORT.maxother = 200
_SHORT.maxlist = _SHORT.maxtuple = _SHORT.maxset = _SHORT.maxdict = 10


def short_repr(value: Any) -> str:
    """A preview of a value that never builds the whole repr: a list of 100 MB bytearrays would
    otherwise take seconds and gigabytes, after memory already ran low."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f'<{type(value).__name__} of {len(value)} bytes>'
    if isinstance(value, (list, tuple, set, frozenset, dict)) and any(
        isinstance(item, (bytes, bytearray, memoryview)) for item in list(value)[:10]
    ):
        return f'<{type(value).__name__} of {len(value)} items>'
    return _SHORT.repr(value)


def _forget_user_modules(root: str) -> dict[str, types.ModuleType]:
    """Run the code as a new process would: forget the modules earlier runs imported from user code
    (this workspace, edited since, or another folder, such as another project's tests that pytest
    imported under the same names), keeping what Python, Pythonista, installed packages and pycoder
    provide: modules found on sys.path, as it is between runs, and every compiled module (loading
    one again crashes the process; Pythonista loads numpy's from its Frameworks folder, which isn't
    on sys.path, and user code there is always Python source). Also forget modules named like the
    workspace's own, wherever they came from, such as the copy of a package Pythonista ships; those
    are returned, to be put back after the run (pycoder itself may import them)."""
    root = os.path.realpath(root)
    own = _workspace_packages(root)
    found = [config.INSTALL_DIR] + [os.path.realpath(p) for p in sys.path if p and os.path.isabs(p)]
    keep = [folder for folder in found if folder != root]
    shadowed = {}
    for name, module in list(sys.modules.items()):
        file = getattr(module, '__file__', None)
        if not file:
            continue
        file = _real_path(file)
        if _inside(file, config.PACKAGE_DIR) or not file.endswith(('.py', '.pyc')):
            continue
        installed = any(_inside(file, folder) for folder in keep)
        if name.split('.')[0] in own or not installed:
            del sys.modules[name]
            if installed:
                shadowed[name] = module
    for entry in [e for e in sys.path_importer_cache if not os.path.isabs(e)]:
        del sys.path_importer_cache[entry]  # a relative entry's finder still looks in the old folder
    return shadowed


def _unshadow(shadowed: dict[str, types.ModuleType]) -> None:
    """Put back the installed modules a run's own modules of the same name stood in for."""
    tops = {name.split('.')[0] for name in shadowed}
    for name in [n for n in sys.modules if n.split('.')[0] in tops]:
        del sys.modules[name]
    sys.modules.update(shadowed)


@functools.cache
def _real_path(file: str) -> str:
    """Every run asks this of every module imported, hundreds with mypy or jedi loaded: it took seconds."""
    return os.path.realpath(file)


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _workspace_packages(root: str) -> set[str]:
    """Top-level modules the workspace itself provides (in its root or in src/)."""
    names: set[str] = set()
    for folder in (root, os.path.join(root, 'src')):
        try:
            entries = os.listdir(folder)
        except OSError:
            continue
        for entry in entries:
            full = os.path.join(folder, entry)
            if entry.endswith('.py'):
                names.add(entry[:-3])
            elif os.path.isfile(os.path.join(full, '__init__.py')):
                names.add(entry)
    return names - {'pycoder'}


def run_python(
    ctx: ToolContext,
    code: str | None = None,
    path: str | None = None,
    args: list[str] | None = None,
    timeout: int = 60,
    background: bool = False,
) -> str:
    if background:
        from .jobs import run_in_background

        return run_in_background(ctx, code, path, args)
    text = run_code(ctx.workspace, code, path, args, timeout, ctx.cancel)
    ctx.frontend.run_output(text)
    return text


RUN_FOREGROUND = (
    'Run Python code or a workspace .py file inside Pythonista; returns stdout/stderr, the traceback and '
    'the local variables where an error was raised, so you can debug by running, reading and fixing. '
    "Runs inside pycoder's own process: a crash (ctypes/objc_util, running out of memory) ends the "
    'session. It runs on a background thread, where UIKit through objc_util (UIScreen, UIView, '
    'UIApplication…) can kill the app: put such calls in a function decorated with '
    'objc_util.on_main_thread. Do not call input() or write infinite loops. Raise timeout for long '
    'runs. UI programs (ui/scene) open a window; returning does not mean the window has closed.'
)

TOOLS = [
    Tool(
        'run_python',
        RUN_FOREGROUND
        + ' Or run long work in the background (training, a long benchmark, a server) and go on working: '
        'you are told when a background job ends, and job_output reads it.',
        {
            'code': prop('string', 'Code to run (use either this or path)'),
            'path': prop('string', '.py file to run (use either this or code)'),
            'args': prop('array', 'sys.argv arguments', items={'type': 'string'}),
            'timeout': prop('integer', 'Timeout in seconds, default 60 (not for background jobs)'),
            'background': prop('boolean', 'Run it as a background job with no time limit; returns at once'),
        },
        run_python,
        readonly=False,
        writes_anywhere=True,
    ),
]

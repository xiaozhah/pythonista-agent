"""Working on while the phone is locked, shown on the Lock Screen and in the Dynamic Island.

iOS suspends an app soon after it leaves the screen, unless it is running a continued-processing
task (BGContinuedProcessingTask, iOS 26): asked for while the app is in front, it goes on behind,
and iOS shows its title, subtitle and progress. An app has to list the identifiers of its tasks in
Info.plist, which Pythonista doesn't and nobody else can change, so a private call registers one
without that check. Where any of this isn't there, pycoder works as before: paused while locked.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import types
from collections.abc import Callable
from typing import Any

from .. import config
from . import env

TITLE = 'pycoder'
IDENTIFIER = 'com.omz-software.Pythonista3.pycoder.work'
FRAMEWORK = '/System/Library/Frameworks/BackgroundTasks.framework'
REGISTER = '_unsafe_registerForTaskWithIdentifier:usingQueue:launchHandler:bypassInfoPlistValidation:'
SUBMIT_OR_FAIL = 0  # BGContinuedProcessingTaskRequestSubmissionStrategyFail: no waiting in a queue
TICK_EVERY = 3  # seconds; iOS ends a task that stops reporting progress
MAX_NOTES = 100_000  # bytes of the record of tasks
START_TRIES = 20  # times to ask for a task, while the work goes on and it hasn't started
START_EVERY = 0.5  # seconds apart
LINGER = 10  # seconds a task outlasts the work: iOS starts no new one for some 6 s after one ends
HALF_AT = 300  # how long a turn will take isn't known: the ring is half full after this many seconds


def _shared() -> Any:
    """Of the whole process: a reload of pycoder's modules must not forget a running task."""
    return env.process_wide(
        'background',
        types.SimpleNamespace(
            lock=threading.Lock(),
            holders=0,
            task=None,
            count=0,
            said='',
            begun=0.0,
            blocks=[],
        ),
    )


def available() -> bool:
    # not on a Mac, which doesn't suspend it; and tests inside Pythonista mustn't put up cards
    if not env.IN_PYTHONISTA or env.on_mac() or 'pytest' in sys.modules:
        return False
    try:
        from objc_util import ObjCClass, sel

        ObjCClass('NSBundle').bundleWithPath_(FRAMEWORK).load()
        ObjCClass('BGContinuedProcessingTaskRequest')  # raises before iOS 26
        return bool(ObjCClass('BGTaskScheduler').sharedScheduler().respondsToSelector_(sel(REGISTER)))
    except Exception:
        return False


def hold(on: bool, text: str = '') -> None:
    """Hold (True) or release (False) the work going on: a turn and a background job each hold it.
    The device stays awake while it is held, and the first holder starts the task (`text` is what
    the card says) and the last one ends it, a little later."""
    env.keep_awake(on)
    s = _shared()
    with s.lock:
        s.holders = max(0, s.holders + (1 if on else -1))
        first, last = on and s.holders == 1, not on and s.holders == 0
    if first:
        s.said = text
        if s.task is None:
            _safely(_begin)
    elif last:
        _safely(_end_soon)
    elif on and text:
        say(text)


def say(text: str) -> None:
    """What the card says the work is doing now (nothing new, if empty)."""
    if text:
        _shared().said = text


def _safely(work: Callable[[], None]) -> None:
    try:
        work()
    except Exception as e:  # never stop the work over how it is shown
        _note(f'{type(e).__name__}: {e}')


def _begin() -> None:
    if available():
        threading.Thread(target=_keep_asking, daemon=True).start()


def _keep_asking() -> None:
    """iOS accepts a task asked for right after another has ended, then never starts it: as when a
    queued message follows a turn. So it is asked for again until one starts."""
    s = _shared()
    for _ in range(START_TRIES):
        _safely(_submit)
        time.sleep(START_EVERY)
        with s.lock:
            if s.task is not None or not s.holders:
                return
    _note('iOS did not start a task')


def _submit() -> None:
    from objc_util import ObjCBlock, ObjCClass, ObjCInstance, ns

    s = _shared()
    s.count += 1
    identifier = f'{IDENTIFIER}{s.count}'  # registering one twice would raise past Python

    def launched(_block: Any, task: Any) -> None:
        _safely(lambda: _started(ObjCInstance(task)))

    block = ObjCBlock(launched, restype=None, argtypes=[ctypes.c_void_p, ctypes.c_void_p])
    s.blocks.append(block)  # iOS keeps its address, and calls it from then on
    scheduler = ObjCClass('BGTaskScheduler').sharedScheduler()
    getattr(scheduler, REGISTER.replace(':', '_'))(
        ns(identifier),
        None,
        _address(block),
        True,
        argtypes=[ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool],  # for the address
        restype=ctypes.c_bool,
    )
    request = ObjCClass('BGContinuedProcessingTaskRequest').alloc()
    request = request.initWithIdentifier_title_subtitle_(identifier, TITLE, s.said or TITLE)
    request.setStrategy_(SUBMIT_OR_FAIL)
    scheduler.submitTaskRequest_error_(  # False (the app isn't in front, say) is one more try gone
        request, None, argtypes=[ctypes.c_void_p, ctypes.c_void_p], restype=ctypes.c_bool
    )


def _address(block: Any) -> int:
    """To pass a block by itself: objc_util would pass a copy, gone when the call returns."""
    return ctypes.addressof(block._as_parameter_)


def _started(task: Any) -> None:
    from objc_util import ObjCBlock

    s = _shared()

    def expired_now(_block: Any, reason: int) -> None:
        _expired(task, reason)

    expired = ObjCBlock(expired_now, restype=None, argtypes=[ctypes.c_void_p, ctypes.c_long])
    s.blocks.append(expired)
    task.setExpirationHandlerWithReason_(_address(expired), argtypes=[ctypes.c_void_p], restype=None)
    with s.lock:
        if not s.holders or s.task is not None:  # it ended before iOS got this far, or one is running
            task.setTaskCompletedWithSuccess_(True)
            return
        s.task, s.begun = task, time.time()
    _note('started')
    threading.Thread(target=_keep_up, args=(task,), daemon=True).start()


def units(seconds: float) -> tuple[int, int]:
    """(done, total) for the ring: it fills but never finishes, and the count always moves on."""
    done = int(seconds)
    return done, done + HALF_AT


def _keep_up(task: Any) -> None:
    s = _shared()
    shown = ''
    while s.task is task:
        done, total = units(time.time() - s.begun)
        task.progress().setTotalUnitCount_(total)
        task.progress().setCompletedUnitCount_(done)
        if s.said != shown:
            shown = s.said
            task.updateTitle_subtitle_(TITLE, shown)
        time.sleep(TICK_EVERY)


def _expired(task: Any, reason: int) -> None:
    """iOS needs the resources back, or the user tapped the card's stop button: the app will be
    suspended, and the work goes on when it comes back. The card going away says so; a task ended as
    failed would put up an alarm, when nothing has failed."""
    s = _shared()
    with s.lock:
        if s.task is task:
            s.task = None
    _note(f'expired, reason {reason}, after {time.time() - s.begun:.0f}s')
    _safely(lambda: task.setTaskCompletedWithSuccess_(True))


def _note(text: str) -> None:
    """Keep a record: why iOS ended a task can only be found out afterwards, on the phone."""
    try:
        path = os.path.join(config.DATA_DIR, 'background.log')
        if os.path.exists(path) and os.path.getsize(path) > MAX_NOTES:
            os.replace(path, path + '.old')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%m-%d %H:%M:%S")} {text}\n')
    except OSError:
        pass


def _end_soon() -> None:
    """Unless more work comes, as the next message of a queue does: it goes on under this task."""
    s = _shared()
    end = _end  # the one that goes with this `s`, whatever the name means when it wakes up

    def later() -> None:
        time.sleep(LINGER)
        with s.lock:
            idle = not s.holders
        if idle:
            _safely(end)

    threading.Thread(target=later, daemon=True).start()


def _end() -> None:
    s = _shared()
    with s.lock:
        task, s.task = s.task, None
    if task is not None:
        _note(f'ended after {time.time() - s.begun:.0f}s')
        task.setTaskCompletedWithSuccess_(True)

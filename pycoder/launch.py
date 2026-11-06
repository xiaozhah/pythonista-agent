"""Starting pycoder: install the update downloaded last time, then check for the next one.

The console's `pycoder` command calls prepare() before importing the rest of pycoder, then
check_in_background() once the chat is up.
"""

from __future__ import annotations

import faulthandler
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Callable

from . import config, updater
from .host import auth, diagnostics, env
from .state import settings

CHECK_FILE = os.path.join(config.DATA_DIR, 'update_check.json')
CRASH_FILE = os.path.join(config.DATA_DIR, 'crash.log')  # Python's stacks when the process crashes
LAST_CRASH_FILE = os.path.join(config.DATA_DIR, 'crash-last.log')
# when iOS kills the app for its memory nothing can be written then, and it reports nothing: so what
# is known is written all along
HEARTBEAT_FILE = os.path.join(config.DATA_DIR, 'last_seen.json')
LAST_RUN_FILE = os.path.join(config.DATA_DIR, 'last_run.json')  # the previous run's, for /crashes
SAMPLE_EVERY = 1  # seconds
WRITE_EVERY = 10  # seconds, or sooner when memory moved by WRITE_MOVED
WRITE_MOVED = 30 * 10**6  # bytes
KEPT_SAMPLES = 8
LOW_MEMORY = 200 * 10**6  # bytes left
SOON = 5  # seconds: falling at the last rate seen, it would run out within this


def forget_modules() -> None:
    """Pythonista keeps imported modules between runs; drop pycoder's so new code is used."""
    for name in [n for n in sys.modules if n == 'pycoder' or n.startswith('pycoder.')]:
        del sys.modules[name]


def stored_token() -> str | None:
    """A GitHub token already in the keychain; never asks (this runs without the user)."""
    try:
        return auth.get_github_token(lambda: None)
    except auth.MissingSecret:
        return None


def watch_for_crashes(path: str = CRASH_FILE, last: str = LAST_CRASH_FILE) -> list[str]:
    """Have Python write its stacks to a file if the process crashes (a crash report from iOS shows
    only C), and say what the last crash left. Returns lines to show the user."""
    notes = []
    log = env.process_wide('crash_log', None)
    if log is None:  # once per process: the file stays open for the crash, and a re-run isn't a crash
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path):
                os.replace(path, last)
                notes.append(crash_note(last))
            else:
                notes += memory_note()
            threading.Thread(target=_heartbeat, daemon=True).start()
            log = open(path, 'w', encoding='utf-8')  # noqa: SIM115
            faulthandler.enable(log, all_threads=True)
            # Apple's checks (UIKit off the main thread) end with a trap, which enable doesn't cover
            faulthandler.register(signal.SIGTRAP, log, all_threads=True, chain=True)
            sys.__dict__['_pycoder_crash_log'] = log
        except Exception as e:  # never stop pycoder from starting
            notes.append(f'Crashes will not be recorded: {type(e).__name__}: {e}')
        try:
            notes += [f'iOS reports a {line}. /crashes shows them' for line in diagnostics.collect()]
        except Exception as e:  # never stop pycoder from starting
            notes.append(f"iOS's crash reports are not available: {e}")
    return notes


def memory_note(path: str = HEARTBEAT_FILE, last: str = LAST_RUN_FILE) -> list[str]:
    """Whether the last run seems to have ended by running out of memory: little was left at the end,
    or it was falling so fast that little would have been left a moment later."""
    try:
        with open(path, encoding='utf-8') as f:
            samples = json.load(f)
        os.replace(path, last)
    except (OSError, ValueError):
        return []
    # another version's file, or a damaged one, says nothing about this
    valid = (
        isinstance(samples, list) and samples and all(isinstance(s, list) and len(s) == 2 for s in samples)
    )
    if not valid:
        return []
    when, left = samples[-1]
    if left >= LOW_MEMORY and left - falling(samples) * SOON >= LOW_MEMORY:
        return []
    clock = time.strftime('%H:%M:%S', time.localtime(when))
    return [
        f'pycoder ended last time with {left // 10**6} MB of memory left at {clock}, '
        f'falling {falling(samples) // 10**6} MB a second: iOS most likely closed it for using too '
        'much memory, which leaves no crash report.'
    ]


def falling(samples: list[list[float]]) -> int:
    """Bytes a second memory was falling by, over the samples kept."""
    first, last = samples[0], samples[-1]
    seconds = last[0] - first[0]
    return max(0, int((first[1] - last[1]) / seconds)) if seconds > 0 else 0


def _heartbeat(path: str = HEARTBEAT_FILE) -> None:
    samples: list[list[float]] = []
    written = 0.0
    written_left = None
    while True:
        now, left = time.time(), env.available_memory()
        if left is None:  # not known here (outside iOS)
            return
        samples = [*samples[-(KEPT_SAMPLES - 1) :], [now, left]]
        moved = written_left is None or abs(left - written_left) >= WRITE_MOVED
        if moved or now - written >= WRITE_EVERY:
            try:
                with open(path + '.tmp', 'w', encoding='utf-8') as f:
                    json.dump(samples, f)
                os.replace(path + '.tmp', path)
                written, written_left = now, left
            except OSError:
                pass
        time.sleep(SAMPLE_EVERY)


def crash_note(path: str) -> str:
    """Where the crashing thread was, innermost line first."""
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = f.read().splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith('Current thread')), None)
    frames = []
    for line in lines[start + 1 :] if start is not None else []:
        if not line.startswith('  File'):
            break
        frames.append(line.strip())
    where = frames[0] if frames else 'unknown'
    return f'pycoder crashed last time, at {where}. /resume brings the session back; details: {path}'


def prepare() -> list[str]:
    """Install a staged update, if there is one. Returns lines to show the user."""
    notes: list[str] = watch_for_crashes()
    try:
        result = updater.Updater(token=stored_token).apply_staged()
    except Exception as e:  # never stop pycoder from starting
        notes.append(f'The downloaded update was not installed: {e}')
        result = None
    if result is not None and not result.up_to_date:
        notes.append(
            f'Updated pycoder {result.old[:7]} → {result.new[:7]}: {len(result.changed)} file(s) changed'
            + ' (pycoder rollback undoes it)'
        )
    forget_modules()  # anything imported above may be stale now
    return notes


def check_in_background(report: Callable[[str], None], every: float = config.UPDATE_CHECK_EVERY) -> None:
    """Look for a newer version at most every `every` seconds; report() what the user should know."""
    if not settings.load(config.SETTINGS_FILE).auto_update or not _due(every):
        return

    def run() -> None:
        try:
            message = updater.Updater(token=stored_token).check_and_stage()
        except Exception:
            return  # offline, rate-limited, …: try again next time
        if message:
            report(message)

    threading.Thread(target=run, daemon=True).start()


def _due(every: float) -> bool:
    try:
        with open(CHECK_FILE, encoding='utf-8') as f:
            last = float(json.load(f)['time'])
    except (OSError, ValueError, KeyError, TypeError):
        last = 0.0
    if time.time() - last < every:
        return False
    try:
        os.makedirs(os.path.dirname(CHECK_FILE), exist_ok=True)
        with open(CHECK_FILE, 'w', encoding='utf-8') as f:
            json.dump({'time': time.time()}, f)
    except OSError:
        pass
    return True

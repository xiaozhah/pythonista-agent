"""Where pycoder runs: Pythonista detection and file writes that keep its editor in sync."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import shutil
import sys
import threading
import time
import types
from typing import Any

IN_PYTHONISTA = (
    importlib.util.find_spec('console') is not None and importlib.util.find_spec('editor') is not None
)


AWAKE_EVERY = 5  # seconds


def process_wide(name: str, default: Any) -> Any:
    """State of the whole process, which must outlive a reload of pycoder's modules (opening
    pycoder, or the dev bridge, imports them afresh): kept on sys, made once."""
    return sys.__dict__.setdefault(f'_pycoder_{name}', default)


def local_documents() -> str | None:
    """Pythonista's "This iPad" / "This iPhone" folder: storage on this device only, not synced."""
    if not IN_PYTHONISTA:
        return None
    path = os.path.realpath(os.path.expanduser('~/Documents'))
    return path if os.path.isdir(path) else None


def icloud_documents() -> str | None:
    """Pythonista's iCloud Drive folder, which syncs between devices (None when iCloud is off)."""
    if not IN_PYTHONISTA:
        return None
    try:
        from objc_util import ObjCClass

        container = ObjCClass('NSFileManager').defaultManager().URLForUbiquityContainerIdentifier_(None)
        path = os.path.join(str(container.path()), 'Documents') if container else ''
    except Exception:
        return None
    return path if os.path.isdir(path) else None


def docs_archive() -> str | None:
    """Pythonista's bundled documentation (Documentation.zip in the app), if this is Pythonista."""
    path = os.path.join(os.path.dirname(sys.executable), 'Documentation.zip')
    return path if IN_PYTHONISTA and os.path.isfile(path) else None


def describe() -> str:
    if not IN_PYTHONISTA:
        return 'desktop Python (test mode)'
    return 'Pythonista 3, the iPad app running on a Mac' if on_mac() else 'Pythonista 3 (iOS)'


def on_mac() -> bool:
    """Whether this is Pythonista's iPad app running on an Apple-silicon Mac."""
    if not IN_PYTHONISTA:
        return False
    try:
        from objc_util import ObjCClass

        process = ObjCClass('NSProcessInfo').processInfo()
        return bool(process.isiOSAppOnMac()) if process.respondsToSelector_('isiOSAppOnMac') else False
    except Exception:
        return False


def python_version() -> str:
    return sys.version.split()[0]


def keep_awake(on: bool) -> None:
    """Hold (True) or release (False) the device awake: iOS suspends Pythonista once it locks, so a
    turn and a background job each hold it. Pythonista allows auto-lock again whenever a script ends,
    so while anything holds it this is set again every few seconds."""
    if not IN_PYTHONISTA:
        return
    s = process_wide('awake', types.SimpleNamespace(lock=threading.Lock(), holders=0, watching=False))
    with s.lock:
        s.holders = max(0, s.holders + (1 if on else -1))
        if s.holders and not s.watching:
            s.watching = True
            threading.Thread(target=_stay_awake, args=(s,), daemon=True).start()


def _stay_awake(s: Any) -> None:
    import console

    while True:
        with s.lock:
            if not s.holders:
                s.watching = False
                console.set_idle_timer_disabled(False)
                return
        console.set_idle_timer_disabled(True)
        time.sleep(AWAKE_EVERY)


def available_memory() -> int | None:
    """How much more memory iOS lets this process take (os_proc_available_memory), or None where
    that isn't known."""
    try:
        available = ctypes.CDLL(None).os_proc_available_memory
    except (AttributeError, OSError):
        return None
    available.restype = ctypes.c_size_t
    return int(available()) or None


def write_text(path: str, content: str) -> None:
    write_bytes(path, content.encode('utf-8'), content)


def write_bytes(path: str, data: bytes, text: str | None = None) -> None:
    """Write atomically, then make the Pythonista editor show the new content (`text`, if it is text).

    Pythonista saves its editor buffer back to disk (always for the active tab when you tap
    Run), which would overwrite a file changed behind its back. reload_files() refreshes the
    background tabs; the active tab's text is replaced directly.
    """
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.pycoder-tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)
    _sync_editor(path, text)


def move_in(source: str, path: str) -> None:
    """Move a file to `path`, replacing what is there, and make the editor show it."""
    shutil.move(source, path)
    _sync_editor(path, None)


def notify_if_away(message: str, title: str = 'pycoder') -> bool:
    """Post a notification when Pythonista is in the background (iOS hides them in front anyway)."""
    if not IN_PYTHONISTA:
        return False
    try:
        import notification
        from objc_util import ObjCClass, on_main_thread

        @on_main_thread
        def in_front() -> bool:  # UIKit state may only be read on the main thread
            return int(ObjCClass('UIApplication').sharedApplication().applicationState()) == 0

        if in_front():
            return False
        notification.schedule(message=message, title=title, sound_name='default')
        return True
    except Exception:
        return False


def remove_file(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)
    _sync_editor(path, None)


def _sync_editor(path: str, content: str | None) -> None:
    if not IN_PYTHONISTA:
        return
    try:
        import editor

        active = editor.get_path()
        if content is not None and active and os.path.realpath(active) == os.path.realpath(path):
            text = editor.get_text() or ''
            if text != content:
                editor.replace_text(0, len(text), content)
        editor.reload_files()
    except Exception:
        pass  # the file on disk is already right; a stale editor view is cosmetic

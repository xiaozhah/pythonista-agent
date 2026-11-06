"""File checkpoints for rewind: remember each file's content before a turn first changes it.

The file tools say which file they are about to change (before_write). Running code or git can
change any file, so for those the workspace is scanned before and after (scan / record): file
sizes and times show what changed, and the copies taken before the tool ran hold the originals.
"""

from __future__ import annotations

import base64
import ctypes
import os
import shutil
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

from .. import config
from ..host import env
from .session import Session
from .workspace import Workspace

_BINARY = 'base64:'  # prefix for content that isn't UTF-8 text, kept byte for byte
_NOT_KEPT = 'not-kept:'  # a file changed by code or git that was too big to keep a copy of
_SET_ASIDE = 'set-aside:'  # a file kept on disk rather than in the session: where, in SET_ASIDE_DIR

# What a scan keeps a copy of: files up to KEEP_FILE bytes, KEEP_TOTAL bytes in all, in up to
# MAX_FILES files (the rest of a larger workspace is not watched)
KEEP_FILE = 1_000_000
KEEP_TOTAL = 20_000_000
MAX_FILES = 20_000
SKIP_DIRS = ('.git', '.pycoder', '__pycache__')  # git's data and pycoder's own: never put back

# Moved and deleted files, and big files about to be replaced, stay on disk (config.SET_ASIDE_DIR): a
# clone takes no time or space whatever the size, until one of the two changes. So they hold their
# space for KEEP_DAYS.
KEEP_DAYS = 7


def clone(source: str, kept: str) -> None:
    """A copy of a file, of any size at once where the disk can (APFS): not a hard link, which is
    the same file, so that appending to a moved file would change what is kept of it."""
    try:
        clonefile = ctypes.CDLL(None).clonefile
        clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        if clonefile(os.fsencode(source), os.fsencode(kept), 0) == 0:
            return
    except (OSError, AttributeError):
        pass
    shutil.copy2(source, kept)


def own_set_aside(session: Session) -> None:
    """Give a fork copies of what its parent set aside: either can be rewound or deleted alone."""
    for files in session.checkpoints.values():
        for rel, content in files.items():
            if content and content.startswith(_SET_ASIDE) and os.path.exists(_kept_file(content)):
                name = os.path.join(session.id, uuid.uuid4().hex)
                kept = os.path.join(config.SET_ASIDE_DIR, name)
                os.makedirs(os.path.dirname(kept), exist_ok=True)
                clone(_kept_file(content), kept)
                files[rel] = _SET_ASIDE + name


def _remove_empty_folders(folder: str) -> None:
    for path, _, _ in os.walk(folder, topdown=False):
        try:
            os.rmdir(path)
        except OSError:
            pass


def _snapshot(full: str) -> str:
    with open(full, 'rb') as f:
        data = f.read()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return _BINARY + base64.b64encode(data).decode('ascii')
    if text.startswith((_BINARY, _NOT_KEPT, _SET_ASIDE)):  # text that would read as a marker
        return _BINARY + base64.b64encode(data).decode('ascii')
    return text


def _kept_file(content: str) -> str:
    return os.path.join(config.SET_ASIDE_DIR, content[len(_SET_ASIDE) :])


def _lost(content: str | None) -> bool:
    """A file changed by code too big to copy, or set aside longer ago than is kept."""
    if content is None:
        return False
    return content == _NOT_KEPT or (
        content.startswith(_SET_ASIDE) and not os.path.exists(_kept_file(content))
    )


def forget_old_set_aside(days: int = KEEP_DAYS) -> None:
    """Give back the space of what was moved or deleted long ago."""
    forget_old(config.SET_ASIDE_DIR, days)


def forget_old(directory: str, days: int = KEEP_DAYS) -> None:
    """Remove the folders in directory not changed for that long."""
    try:
        folders = [os.path.join(directory, name) for name in os.listdir(directory)]
    except OSError:
        return
    for folder in folders:
        try:
            if time.time() - os.path.getmtime(folder) > days * 86400:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


Stat = tuple[int, int]  # (mtime in ns, size)


@dataclass
class Scan:
    """The workspace before a tool ran: every file's stat, and copies of the small ones."""

    stats: dict[str, Stat] = field(default_factory=dict)
    kept: dict[str, str] = field(default_factory=dict)
    complete: bool = True  # False when the workspace had more than MAX_FILES files


class Checkpoints:
    def __init__(self, session: Session, workspace: Workspace) -> None:
        self.session = session
        self.workspace = workspace
        self.turn = 0  # the turn file changes are recorded against
        self._copies: dict[str, tuple[Stat, str]] = {}  # the last scan's copies, reused while unchanged
        self.stuck: list[str] = []  # what the last restore could not put back where it was

    def before_write(self, full: str, removing: bool = False) -> None:
        """Call before changing a file, or moving or deleting it (`removing`); only the first change
        in a turn is remembered. The session keeps small files being edited, the disk all others."""
        if not self.turn:
            return
        snapshot = self.session.checkpoints.setdefault(str(self.turn), {})
        rel = self.workspace.rel(full)
        if rel in snapshot:
            return
        if not os.path.isfile(full):
            snapshot[rel] = None
        elif removing or os.path.getsize(full) > KEEP_FILE:
            snapshot[rel] = self._set_aside(full)
        else:
            snapshot[rel] = _snapshot(full)

    def _set_aside(self, full: str) -> str:
        name = os.path.join(self.session.id, uuid.uuid4().hex)
        kept = os.path.join(config.SET_ASIDE_DIR, name)
        os.makedirs(os.path.dirname(kept), exist_ok=True)
        clone(full, kept)
        return _SET_ASIDE + name

    def scan(self) -> Scan | None:
        """Before a tool that may change any file: what is there now (None outside a turn)."""
        if not self.turn:
            return None
        known = self.session.checkpoints.get(str(self.turn), {})
        result = Scan()
        copies: dict[str, tuple[Stat, str]] = {}
        budget = KEEP_TOTAL
        for rel, full, stat in self._files(result):
            result.stats[rel] = stat
            if rel in known or stat[1] > min(KEEP_FILE, budget):
                continue  # already remembered this turn, or too big to keep
            cached = self._copies.get(rel)
            if cached and cached[0] == stat:
                content = cached[1]
            else:
                try:
                    content = _snapshot(full)
                except OSError:
                    continue
            copies[rel] = (stat, content)
            result.kept[rel] = content
            budget -= stat[1]
        self._copies = copies
        return result

    def record(self, before: Scan | None) -> None:
        """After that tool: remember the original of every file it created, changed or deleted."""
        if before is None or not self.turn:
            return
        after = Scan()
        for rel, _, stat in self._files(after):
            after.stats[rel] = stat
        snapshot = self.session.checkpoints.get(str(self.turn), {})
        changes: dict[str, str | None] = {}
        for rel in sorted(before.stats.keys() | after.stats.keys()):
            old, new = before.stats.get(rel), after.stats.get(rel)
            if rel in snapshot or old == new:
                continue
            if old is None:  # new, unless it was only beyond what the first scan reached
                if before.complete:
                    changes[rel] = None
            elif new is not None or after.complete:
                changes[rel] = before.kept.get(rel, _NOT_KEPT)
        if changes:
            self.session.checkpoints.setdefault(str(self.turn), {}).update(changes)

    def _files(self, scan: Scan) -> Iterator[tuple[str, str, Stat]]:
        """(workspace-relative path, full path, stat) of the files in the workspace, in a fixed order."""
        root, count = self.workspace.root, 0
        for folder, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(files):
                if count >= MAX_FILES:
                    scan.complete = False
                    return
                full = os.path.join(folder, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                count += 1
                yield os.path.relpath(full, root), full, (st.st_mtime_ns, st.st_size)

    def modified_since(self, when: float, limit: int = 50) -> list[tuple[str, str, Stat]]:
        """Files of the workspace modified since `when`, newest first: (path in it, full path, stat)."""
        found = [entry for entry in self._files(Scan()) if entry[2][0] >= when * 1e9]
        return sorted(found, key=lambda entry: -entry[2][0])[:limit]

    def changed_since(self, turn: int) -> list[str]:
        paths: set[str] = set()
        for number, snapshot in self.session.checkpoints.items():
            if int(number) >= turn:
                paths.update(snapshot)
        return sorted(paths)

    def session_changes(self) -> list[tuple[str, str]]:
        """The files this session changed: (path in the workspace, 'new', 'changed' or 'deleted')."""
        changes = []
        for rel, content in sorted(self._earliest(0).items()):
            if not os.path.exists(os.path.join(self.workspace.root, rel)):
                if content is not None:  # one made and deleted again isn't anything
                    changes.append((rel, 'deleted'))
            else:
                changes.append((rel, 'new' if content is None else 'changed'))
        return changes

    def earlier_size(self, rel: str) -> int:
        """About how many bytes earlier_text would give, without reading them."""
        content = self._earliest(0).get(rel) or ''
        if content.startswith(_SET_ASIDE) and not _lost(content):
            return os.path.getsize(_kept_file(content))
        return len(content)

    def earlier_text(self, rel: str) -> str | None:
        """What the file held before this session first changed it: '' if it is new, None if that can't
        be told (it was too big to keep a copy of, or isn't text)."""
        content = self._earliest(0).get(rel, '')
        if content is None:
            return ''
        if _lost(content):
            return None
        try:
            if content.startswith(_SET_ASIDE):
                with open(_kept_file(content), encoding='utf-8') as f:
                    return f.read()
            if content.startswith(_BINARY):
                return base64.b64decode(content[len(_BINARY) :]).decode('utf-8')
        except (OSError, ValueError):  # UnicodeDecodeError is a ValueError
            return None
        return content

    def not_restorable(self, turn: int) -> list[str]:
        """Files changed in `turn` or later whose earlier content was too big to keep."""
        return sorted(rel for rel, content in self._earliest(turn).items() if _lost(content))

    def restore(self, turn: int) -> list[str]:
        """Put every file changed in `turn` or later back as it was before `turn`. Returns the paths
        put back (not_restorable lists the ones that can't be, and self.stuck those a folder or file
        in the way kept out). What is new goes first: a file may have become a folder, or the reverse."""
        restored = []
        self.stuck = []
        items = sorted(self._earliest(turn).items(), key=lambda item: item[1] is not None)
        for rel, content in items:
            if _lost(content):
                continue
            full = self.workspace.resolve(rel)
            try:
                if os.path.isdir(full):
                    _remove_empty_folders(full)  # what was in it, made since, has just gone
                    if os.path.isdir(full):
                        raise IsADirectoryError(rel)
                if content is None:
                    env.remove_file(full)
                else:
                    os.makedirs(os.path.dirname(full), exist_ok=True)  # its folder may be gone too
                    if content.startswith(_SET_ASIDE):
                        env.move_in(_kept_file(content), full)
                    elif content.startswith(_BINARY):
                        env.write_bytes(full, base64.b64decode(content[len(_BINARY) :]))
                    else:
                        env.write_text(full, content)
            except OSError:
                self.stuck.append(rel)
                continue
            restored.append(rel)
        for number in list(self.session.checkpoints):
            if int(number) >= turn:
                del self.session.checkpoints[number]
        return sorted(restored)

    def _earliest(self, turn: int) -> dict[str, str | None]:
        earliest: dict[str, str | None] = {}
        for number in sorted(self.session.checkpoints, key=int):  # the files pane reads while a turn runs
            if int(number) >= turn:
                for rel, content in list(self.session.checkpoints.get(number, {}).items()):
                    earliest.setdefault(rel, content)
        return earliest

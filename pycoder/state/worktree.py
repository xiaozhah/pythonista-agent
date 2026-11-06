"""A subagent's own copy of the workspace, so that several can change code at once.

It holds what the workspace was at the start (base) and what the subagent makes of it (work), as
clones, which take no time or space until changed. dulwich has no git worktrees and a workspace need
not be a repository, so this is plain files. When the subagent is done its changes are merged back:
a file only it changed is taken as it is, one the workspace changed too is merged line by line, and
what can't be merged stays in the copy, for the main agent to deal with.
"""

from __future__ import annotations

import difflib
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from .. import config
from ..host import env
from .checkpoints import clone, forget_old

SKIP_DIRS = ('.git', '.pycoder', '.bridge', '__pycache__')
MAX_FILES = 20_000


class WorktreeError(Exception):
    pass


Hunk = tuple[int, int, list[str]]  # base[start:end] becomes these lines


def _hunks(base: list[str], other: list[str]) -> list[Hunk]:
    matcher = difflib.SequenceMatcher(None, base, other, autojunk=False)
    return [(i, j, other[k:m]) for tag, i, j, k, m in matcher.get_opcodes() if tag != 'equal']


def merge3(base: str, ours: str, theirs: str) -> str | None:
    """Both sides' changes to base, or None where they touch the same lines differently."""
    lines = base.splitlines(keepends=True)
    hunks = sorted(
        _hunks(lines, ours.splitlines(keepends=True)) + _hunks(lines, theirs.splitlines(keepends=True)),
        key=lambda h: h[:2],
    )
    out: list[str] = []
    at = 0
    last: Hunk | None = None
    for hunk in hunks:
        if hunk == last:  # both made the same change
            continue
        start, end, new = hunk
        if last is not None and (start < last[1] or start == last[0]):
            return None
        out += lines[at:start] + new
        at = end
        last = hunk
    return ''.join(out + lines[at:])


@dataclass
class Merged:
    applied: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)  # changed in both, in the same places
    refused: list[str] = field(default_factory=list)  # a rule keeps them from being changed


def _read(path: str) -> bytes | None:
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


def _text(data: bytes | None) -> str | None:
    try:
        return None if data is None else data.decode('utf-8')
    except UnicodeDecodeError:
        return None


class Worktree:
    def __init__(self, root: str, directory: str | None = None) -> None:
        self.root = root
        self.directory = directory or os.path.join(config.WORKTREES_DIR, uuid.uuid4().hex)
        self.base = os.path.join(self.directory, 'base')
        self.work = os.path.join(self.directory, 'work')

    def _files(self, top: str) -> list[str]:
        found = []
        for folder, dirs, names in os.walk(top):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            found += [os.path.relpath(os.path.join(folder, n), top) for n in names]
        return found

    def create(self, leave_out: Callable[[str], bool] = lambda rel: False) -> str:
        """Copy the workspace, without what leave_out says. Returns where the copy to change is."""
        files = self._files(self.root)
        if len(files) > MAX_FILES:
            raise WorktreeError(f'The workspace has over {MAX_FILES} files: too many to copy for a subagent')
        for rel in files:
            if leave_out(rel) or os.path.islink(os.path.join(self.root, rel)):
                continue
            for top in (self.base, self.work):
                target = os.path.join(top, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                clone(os.path.join(self.root, rel), target)
        os.makedirs(self.work, exist_ok=True)
        return self.work

    def changed(self) -> list[str]:
        """What the subagent changed, added or removed."""
        paths = set(self._files(self.base)) | set(self._files(self.work))
        return sorted(
            rel for rel in paths if _read(os.path.join(self.base, rel)) != _read(os.path.join(self.work, rel))
        )

    def merge(
        self,
        before_change: Callable[[str, bool], None],
        allowed: Callable[[str], bool] = lambda rel: True,
    ) -> Merged:
        """Bring the changes into the workspace. before_change(full path, removing) comes first, for
        the checkpoints, so that /rewind undoes them like any other."""
        result = Merged()
        for rel in self.changed():
            if not allowed(rel):
                result.refused.append(rel)
                continue
            full = os.path.join(self.root, rel)
            base = _read(os.path.join(self.base, rel))
            work = _read(os.path.join(self.work, rel))
            now = _read(full)
            if now == work:
                continue  # the same change was made here too
            if now != base:
                merged = None
                texts = (_text(base), _text(now), _text(work))
                if None not in texts:
                    merged = merge3(*texts)  # type: ignore[arg-type]
                if merged is None:
                    result.conflicts.append(rel)
                    continue
                work = merged.encode('utf-8')
            before_change(full, work is None)
            if work is None:
                env.remove_file(full)
            else:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                env.write_bytes(full, work)
            result.applied.append(rel)
        return result

    def remove(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def forget_old_worktrees() -> None:
    """Give back the space of copies kept for conflicts long ago."""
    forget_old(config.WORKTREES_DIR)

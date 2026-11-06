"""The folder the agent works in: path resolution that never leaves it."""

from __future__ import annotations

import os
from collections.abc import Sequence

from . import textfile
from .textfile import TextFormat


class ToolError(Exception):
    """A tool failed in a way the model should hear about (bad path, missing file, ...)."""


class Workspace:
    """Paths are relative to `root`. Nothing outside `limit` can be changed: by default the root
    itself (the agent's workspace); the shell allows the whole home and the device's local
    storage, so `cd ..` and `cp ~/a /local/` work. `readable` adds places that may be read but not
    changed (the agent reads other projects in the home). `~` is pycoder's home, as in the shell,
    not Pythonista's app folder."""

    def __init__(
        self,
        root: str,
        limit: str | Sequence[str] | None = None,
        readable: Sequence[str] = (),
        home: str | None = None,
    ) -> None:
        self.root = os.path.realpath(root)
        limits = [limit] if isinstance(limit, str) else list(limit or [root])
        self.limits = tuple(os.path.realpath(p) for p in limits)
        self.readable = self.limits + tuple(os.path.realpath(p) for p in readable if p)
        self.home = os.path.realpath(home) if home else None

    def resolve(self, path: str | None) -> str:
        """Absolute path for a relative one, for changing it; refuse anything outside the limits."""
        return self._resolve(path, self.limits, 'Path is outside the workspace (it can be read, not changed)')

    def resolve_readable(self, path: str | None) -> str:
        """Absolute path for reading: the workspace, or anywhere in `readable`."""
        return self._resolve(path, self.readable, 'Path is outside the places pycoder can read')

    def _resolve(self, path: str | None, places: Sequence[str], refusal: str) -> str:
        path = path or '.'
        if self.home and (path == '~' or path.startswith('~/')):
            path = self.home + path[1:]
        full = os.path.realpath(os.path.join(self.root, os.path.expanduser(path)))
        if not any(os.path.commonpath([place, full]) == place for place in places):
            raise ToolError(f'{refusal}: {path}')
        return full

    def rel(self, full: str) -> str:
        """How a path reads to the model: relative inside the workspace, ~/… elsewhere in the home."""
        inside = os.path.commonpath([self.root, full]) == self.root
        if not inside and self.home and os.path.commonpath([self.home, full]) == self.home:
            return '~/' + os.path.relpath(full, self.home)
        return os.path.relpath(full, self.root)

    def read_text(self, full: str) -> str:
        return self.read(full)[0]

    def read(self, full: str) -> tuple[str, TextFormat]:
        """A text file's text (with \\n line endings) and how it is stored on disk."""
        with open(full, 'rb') as f:
            data = f.read()
        try:
            return textfile.decode(data)
        except textfile.BinaryFile:
            raise ToolError(f'Looks like a binary file, cannot read as text: {self.rel(full)}') from None

    @staticmethod
    def is_hidden(name: str) -> bool:
        return name.startswith('.') or name == '__pycache__'

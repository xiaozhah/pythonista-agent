"""Stopping a running turn from another thread (a Stop button) or from the console's stop key."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class Cancelled(KeyboardInterrupt):
    """Raised inside a turn when the user stops it.

    A KeyboardInterrupt subclass, so Pythonista's own stop key and the Stop button take the same path.
    """


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._on_cancel: list[Callable[[], object]] = []
        self._closed = False

    def cancel(self) -> None:
        self._event.set()
        for callback in list(self._on_cancel):
            try:
                callback()  # e.g. close a connection that is blocked waiting for data
            except Exception:
                pass

    def reset(self) -> None:
        if not self._closed:
            self._event.clear()

    def close(self) -> None:
        """Stop for good: the screen has gone, so no later request may start again."""
        self._closed = True
        self.cancel()

    def wait(self, seconds: float) -> None:
        """Sleep, but end at once (raising Cancelled) when the user stops."""
        if self._event.wait(seconds):
            self.check()

    @contextmanager
    def on_cancel(self, callback: Callable[[], object]) -> Iterator[None]:
        """While inside, a Stop also calls callback (from the stopping thread)."""
        self._on_cancel.append(callback)
        try:
            yield
        finally:
            self._on_cancel.remove(callback)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        """Raise Cancelled after a Stop. It stays stopped until the next request (reset), so every
        subagent running in parallel sees it."""
        if self._event.is_set():
            raise Cancelled()

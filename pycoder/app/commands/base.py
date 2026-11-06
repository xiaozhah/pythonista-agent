"""What a slash command is."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..controller import Controller


@dataclass
class Command:
    name: str
    help: str
    run: Callable[[Controller, str], bool | None]  # return False to quit
    args: str = ''
    complete: Callable[[Controller], list[str]] = field(default=lambda c: [])

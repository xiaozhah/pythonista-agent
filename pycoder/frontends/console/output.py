"""Colored, styled text in the Pythonista console (ANSI codes elsewhere, for testing on a Mac)."""

from __future__ import annotations

import sys
from typing import Any

from ...host.env import IN_PYTHONISTA

COLORS: dict[str, tuple[tuple[float, float, float], str]] = {
    'dim': ((0.55, 0.55, 0.55), '\033[90m'),
    'red': ((0.85, 0.25, 0.25), '\033[31m'),
    'green': ((0.20, 0.65, 0.30), '\033[32m'),
    'yellow': ((0.80, 0.60, 0.10), '\033[33m'),
    'blue': ((0.25, 0.50, 0.90), '\033[34m'),
    'magenta': ((0.70, 0.35, 0.80), '\033[35m'),
    'orange': ((0.85, 0.45, 0.15), '\033[38;5;208m'),
    'cyan': ((0.10, 0.55, 0.60), '\033[36m'),
}


def write(text: str, color: str | None = None, bold: bool = False, stream: Any = None) -> None:
    stream = stream or sys.stdout
    if IN_PYTHONISTA:
        import console

        if color:
            console.set_color(*COLORS[color][0])
        if bold:
            try:
                console.set_font('Menlo-Bold')
            except Exception:
                bold = False
        stream.write(text)
        if bold:
            console.set_font()
        if color:
            console.set_color()
    else:
        prefix = ('\033[1m' if bold else '') + (COLORS[color][1] if color else '')
        stream.write(prefix + text + '\033[0m' if prefix else text)
    stream.flush()


def out(text: str = '', color: str | None = None, end: str = '\n', stream: Any = None) -> None:
    write(text + end, color, stream=stream)


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ''

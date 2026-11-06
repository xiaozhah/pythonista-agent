"""The icons of the bars at the top and bottom of the chat, drawn so they share one line and size.
Black here: a button shows them in its tint, so they follow the theme."""

from __future__ import annotations

from collections.abc import Callable

import ui

SIZE = 24
LINE = 1.6
_made: dict[str, ui.Image] = {}


def _stroke(*lines: tuple[float, float, float, float]) -> None:
    path = ui.Path()
    path.line_width = LINE
    path.line_cap_style = ui.LINE_CAP_ROUND
    for x0, y0, x1, y1 in lines:
        path.move_to(x0, y0)
        path.line_to(x1, y1)
    path.stroke()


def _close() -> None:
    _stroke((6, 6, 18, 18), (18, 6, 6, 18))


def _plus() -> None:
    _stroke((12, 5, 12, 19), (5, 12, 19, 12))


def _more() -> None:
    for x in (5, 12, 19):
        ui.Path.oval(x - 1.5, 10.5, 3, 3).fill()


def _more_small() -> None:
    for x in (8, 12, 16):
        ui.Path.oval(x - 1, 11, 2, 2).fill()


def _stop() -> None:
    ui.Path.rounded_rect(6, 6, 12, 12, 2.5).fill()


def _folder() -> None:
    path = ui.Path()
    path.line_width = LINE
    path.line_join_style = ui.LINE_JOIN_ROUND
    path.move_to(4, 18.5)
    for x, y in ((4, 6), (9.5, 6), (11.5, 8.5), (20, 8.5), (20, 18.5)):
        path.line_to(x, y)
    path.close()
    path.stroke()


_DRAW: dict[str, Callable[[], None]] = {
    'close': _close,
    'folder': _folder,
    'plus': _plus,
    'more': _more,
    'stop': _stop,
}


def todo_mark(status: str, fg: str, dim: str, paper: str) -> ui.Image:
    """A step of the plan: a filled tick when done, dots while running, a dashed ring while waiting."""
    key = f'{status} {fg} {dim} {paper}'
    if key not in _made:
        with ui.ImageContext(SIZE, SIZE) as ctx:
            if status == 'completed':
                ui.set_color(dim)
                ui.Path.oval(2.5, 2.5, 19, 19).fill()
                ui.set_color(paper)
                _stroke((7.5, 12.5, 10.5, 15.5), (10.5, 15.5, 16.5, 9))
            elif status == 'in_progress':
                ui.set_color(fg)
                ring = ui.Path.oval(3, 3, 18, 18)
                ring.line_width = LINE
                ring.stroke()
                _more_small()
            else:
                ui.set_color(dim)
                ring = ui.Path.oval(3, 3, 18, 18)
                ring.line_width = LINE
                ring.set_line_dash([3, 3])
                ring.stroke()
            _made[key] = ctx.get_image()
    return _made[key]


def glyph(name: str) -> ui.Image:
    if name not in _made:
        with ui.ImageContext(SIZE, SIZE) as ctx:
            ui.set_color('black')
            _DRAW[name]()
            _made[name] = ctx.get_image()
    return _made[name]

"""The controls the screens share, so that they look alike: the bar at the top and the input box."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import ui
from objc_util import ObjCInstance

from ..host import env
from . import glyphs, theme

BAR_FONT = 16  # all the words in the bars at the top and bottom
TOP_HEIGHT = 44
SIDE = 12  # from the edge of the screen to what is in a bar
FIELD_HEIGHT = 50  # one line; the input grows with its text up to MAX_FIELD_HEIGHT, then scrolls
MAX_FIELD_HEIGHT = 150
FIELD_PAD = 6  # between the box around the input and its text, above and below
SEND_SIZE = 32


def glyph_button(name: str, action: Callable[[Any], object], label: str) -> ui.Button:
    button = ui.Button(action=action)
    button.image = glyphs.glyph(name)
    theme.label(button, label)
    return button


def word_button(title: str, action: Callable[[Any], object]) -> ui.Button:
    return ui.Button(title=title, font=('<system>', BAR_FONT), action=action)


def safe_top(view: ui.View) -> float:
    """The height the status bar takes at the top of an iPhone screen. A Mac reports one too, but has
    none: its window's own title bar is above all this."""
    if env.on_mac():
        return 0.0
    try:
        return float(ObjCInstance(view).safeAreaInsets().top)
    except Exception:
        return 0.0


class TopBar(ui.View):
    """Buttons on the left, a title, buttons on the right, along its bottom edge: it may be taller
    than the row, to fill the space under an iPhone's status bar."""

    def __init__(self, left: list[ui.Button], right: list[ui.Button]) -> None:
        self.left = left
        self.right = right
        self.title_label = ui.Label(font=('<system>', BAR_FONT))
        for view in [*left, self.title_label, *right]:
            self.add_subview(view)

    def layout(self) -> None:
        y = self.height - TOP_HEIGHT
        x = float(SIDE - 6)
        for button in self.left:
            width = self._width(button)
            button.frame = (x, y, width, TOP_HEIGHT)
            x += width
        end = self.width - SIDE + 6
        for button in reversed(self.right):
            end -= self._width(button)
            button.frame = (end, y, self._width(button), TOP_HEIGHT)
        self.title_label.frame = (x + 8, y, max(0, end - x - 16), TOP_HEIGHT)

    @staticmethod
    def _width(button: ui.Button) -> float:
        if button.image is not None:
            return TOP_HEIGHT
        return float(ui.measure_string(button.title or '', font=button.font)[0]) + 24  # a button's margins

    def style(self, t: dict[str, str]) -> None:
        self.background_color = t['bg']
        self.title_label.text_color = t['fg']
        for button in [*self.left, *self.right]:
            button.tint_color = t['fg']


class InputBox(ui.View):
    """A round box: optionally ＋, then the text, then send, which stay level with the last line as
    the text grows. The owner is the field's delegate, and calls changed() when its text changes."""

    def __init__(
        self,
        on_send: Callable[[Any], object],
        on_plus: Callable[[Any], object] | None = None,
        hint: str = '↵ to send',
    ) -> None:
        self.field_height = float(FIELD_HEIGHT)
        self.on_resize: Callable[[], object] = lambda: None
        self.field_look: str | None = None  # the colours the text was last given
        self.box = ui.View(corner_radius=FIELD_HEIGHT / 2)
        self.add_subview(self.box)
        self.plus = None
        if on_plus is not None:
            self.plus = glyph_button('plus', on_plus, 'Attach')
            self.add_subview(self.plus)
        self.field = ui.TextView(
            font=('<system>', 17),
            autocapitalization_type=ui.AUTOCAPITALIZE_NONE,
            autocorrection_type=False,
            spellchecking_type=False,
        )
        self.add_subview(self.field)
        self.hint = ui.Label(font=('<system>', 17), text=hint, touch_enabled=False)
        self.add_subview(self.hint)
        self.send = ui.Button(title='↵', action=on_send, corner_radius=SEND_SIZE / 2, font=('<system>', 22))
        theme.label(self.send, 'Send')
        self.add_subview(self.send)

    def layout(self) -> None:
        w, h = self.width, self.field_height
        self.box.frame = (0, 0, w, h)
        left = 4.0
        if self.plus is not None:
            self.plus.frame = (left, h - FIELD_HEIGHT, 40, FIELD_HEIGHT)
            left += 40
        else:
            left += 10
        self.send.frame = (w - 9 - SEND_SIZE, h - (FIELD_HEIGHT + SEND_SIZE) / 2, SEND_SIZE, SEND_SIZE)
        # inside the box, so its round corners show around the text
        self.field.frame = (left, FIELD_PAD, self.send.x - 4 - left, h - 2 * FIELD_PAD)
        self.hint.frame = (left + 5, 0, self.field.width - 5, FIELD_HEIGHT)

    def changed(self) -> None:
        self.show_hint()
        self.fit()

    def show_hint(self) -> None:
        """Only if it changes: anything set or laid out when nothing else did makes the text shake."""
        hidden = bool(self.field.text)
        if self.hint.hidden != hidden:
            self.hint.hidden = hidden

    def fit(self) -> None:
        """Size the input to its text: it grows instead of scrolling (scrolling a box that fits its
        text only makes the text jump), and scrolls only past MAX_FIELD_HEIGHT."""
        try:
            text_view = ObjCInstance(self.field)
            needed = float(text_view.sizeThatFits_((self.field.width, 10_000.0)).height) + 2 * FIELD_PAD
        except Exception:
            return
        scrolls = needed > MAX_FIELD_HEIGHT
        if bool(text_view.isScrollEnabled()) != scrolls:
            text_view.setScrollEnabled_(scrolls)
        height = min(MAX_FIELD_HEIGHT, max(FIELD_HEIGHT, needed))
        if abs(height - self.field_height) > 0.5:
            self.field_height = height
            self.on_resize()

    def style(self, t: dict[str, str]) -> bool:
        """Colours from the theme. Whether the text's changed: that wipes the colours within it, so it
        is only done when the theme did."""
        self.box.background_color = t['field']
        # without it a white box vanishes into the white around it
        self.box.border_color = theme.mix(t['line'], t['bg'], 0.7)
        self.box.border_width = 0.5
        self.hint.text_color = t['dim']
        self.send.tint_color = t['fg']
        if self.plus is not None:
            self.plus.tint_color = t['fg']
        if self.field_look == t['fg']:
            return False
        self.field_look = t['fg']
        self.field.background_color = t['field']
        self.field.text_color = t['fg']
        self.field.tint_color = t['fg']
        return True

"""Colours for the native controls (input bar, buttons, palette): the same tokens as the chat
page's CSS (chat/page.py), so the screen reads as one design in light and dark."""

from __future__ import annotations

from typing import Any

# Text colours reach 4.5:1 on what they sit on (WCAG AA). The accent itself (3.1:1 on white) is for
# marks; white text and icons go on accent_fill.
LIGHT = {
    'bg': '#ffffff',
    'bar': '#f6f6f8',
    'field': '#ffffff',
    'surface': '#f4f4f6',
    'surface_2': '#e9e9ee',
    'fg': '#1c1c1e',
    'dim': '#66666b',
    'line': '#c6c6c8',  # also the field's outline: a white field on a light bar needs one
    'accent': '#d97757',
    'accent_fill': '#ad5133',
    'accent_fg': '#ffffff',
    'command': '#2f6fd6',  # a slash command in the input
}
DARK = {
    'bg': '#000000',
    'bar': '#1c1c1e',
    'field': '#000000',
    'surface': '#1c1c1e',
    'surface_2': '#2c2c2e',
    'fg': '#f2f2f7',
    'dim': '#98989f',
    'line': '#38383a',
    'accent': '#d97757',
    'accent_fill': '#ad5133',
    'accent_fg': '#ffffff',
    'command': '#6aa2ff',
}


def colors(dark: bool) -> dict[str, str]:
    return DARK if dark else LIGHT


def mix(color: str, base: str, amount: float) -> str:
    """color laid over base at `amount` opacity, as a hex colour (for tinted pills)."""
    a = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(base[i : i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x * amount + y * (1 - amount)):02x}' for x, y in zip(a, b, strict=True))


def _navigation(view: object) -> Any:
    """What holds the title bar of the screen `view` is on, if it has one."""
    from objc_util import ObjCInstance

    responder = ObjCInstance(view).nextResponder()
    while responder is not None and not (
        responder.respondsToSelector_('navigationController') and responder.navigationController()
    ):
        responder = responder.nextResponder()
    return responder.navigationController() if responder is not None else None


def style_title_bar(view: object, colors: dict[str, str]) -> None:
    """Colour the title bar of the screen `view` is on. Call it on the main thread."""
    try:
        from objc_util import ObjCClass

        navigation = _navigation(view)
    except ImportError:
        return
    if navigation is None:
        return  # not presented with a title bar

    def color(hex_color: str) -> object:
        r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
        return ObjCClass('UIColor').colorWithRed_green_blue_alpha_(r, g, b, 1.0)

    look = ObjCClass('UINavigationBarAppearance').alloc().init()
    look.configureWithOpaqueBackground()
    look.setBackgroundColor_(color(colors['bar']))
    bar = navigation.navigationBar()
    bar.setTintColor_(color(colors['fg']))
    look.setTitleTextAttributes_(
        ObjCClass('NSDictionary').dictionaryWithObject_forKey_(color(colors['fg']), 'NSColor')
    )
    bar.setStandardAppearance_(look)
    bar.setScrollEdgeAppearance_(look)
    bar.setCompactAppearance_(look)


def label(button: object, text: str) -> None:
    """What VoiceOver says for a button drawn as an icon or a symbol (＋, an arrow, ^C). The whole
    view becomes one element with the button trait, so it reads the same whatever ui puts inside."""
    try:
        from objc_util import ObjCInstance
    except ImportError:
        return
    try:
        view = ObjCInstance(button)
        view.setIsAccessibilityElement_(True)
        view.setAccessibilityLabel_(text)
        view.setAccessibilityTraits_(1)  # UIAccessibilityTraitButton
    except Exception:  # never worth breaking the screen for
        pass

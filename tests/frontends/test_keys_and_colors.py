"""The pure parts of the keyboard handling, and the colour contrast of the design tokens."""

from __future__ import annotations

import re

import pytest

from pycoder.frontends import keys, theme
from pycoder.frontends.chat.page import CSS


def test_tab_completes_at_the_caret_and_keeps_the_rest() -> None:
    # '/mo| and more' completed to '/model ': only the missing letters go in, at the caret
    assert keys.completion_edit('/mo and more', 3, 3, '/model ') == (3, 3, 'del ')
    # a selection is replaced by what the completion adds
    assert keys.completion_edit('/moXX', 3, 5, '/model ') == (3, 5, 'del ')
    # the completer normalized a full-width slash: the whole head is replaced
    assert keys.completion_edit('／mo', 2, 2, '/model ') == (0, 2, '/model ')
    # nothing to add: an empty edit
    assert keys.completion_edit('hello', 5, 5, 'hello') == (5, 5, '')


def test_utf16_positions() -> None:
    text = 'a😀b'
    assert keys.utf16_len(text) == 4
    assert keys.utf16_to_index(text, 3) == 2  # after the emoji (two UTF-16 units)
    assert keys.utf16_to_index(text, 4) == 3


def test_modifiers_are_forgotten() -> None:
    keys.forget_modifiers()
    assert not keys.newline_held()


def _luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize('colors', [theme.LIGHT, theme.DARK])
def test_native_text_colors_reach_aa(colors: dict[str, str]) -> None:
    for background in ('bg', 'bar', 'surface', 'surface_2'):
        assert contrast(colors['dim'], colors[background]) >= 4.5, background
    assert contrast(colors['accent_fg'], colors['accent_fill']) >= 4.5


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r'--([\w-]+):\s*(#[0-9a-f]{6})\b', block))


def test_page_text_colors_reach_aa() -> None:
    light = _tokens(CSS.split('@media', 1)[0])
    dark = {**light, **_tokens(CSS.split(':root[data-theme=dark]', 1)[1].split('}', 1)[0])}
    for tokens in (light, dark):
        for text in ('dim', 'bad', 'warn', 'fg-2'):
            for background in ('bg', 'surface'):
                assert contrast(tokens[text], tokens[background]) >= 4.5, (text, background)
        assert contrast(tokens['accent-fg'], tokens['accent-fill']) >= 4.5
        assert contrast(tokens['accent-text'], tokens['group-bg']) >= 4.5

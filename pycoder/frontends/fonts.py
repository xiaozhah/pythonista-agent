"""The code font: one setting for code, diffs and commands in the chat.

SF Mono is Apple's system monospace font (Xcode, Terminal, the Claude app's code). Web pages get
it as `ui-monospace`; native views through UIFont, since iOS hides its name from font lookups.
"""

from __future__ import annotations

from typing import Any

_CSS = {
    'SF Mono': 'ui-monospace, Menlo, monospace',
    'Menlo': 'Menlo, monospace',
    'Courier': "'Courier New', Courier, monospace",
}


def css(name: str) -> str:
    """The CSS font-family for a code font."""
    return _CSS.get(name, _CSS['SF Mono'])


def apply_native(view: Any, name: str, size: float) -> None:
    """Set a ui.Label or ui.TextView in the code font."""
    if name != 'SF Mono':
        view.font = (name if name != 'Courier' else 'Courier', size)
        return
    from objc_util import ObjCClass, ObjCInstance

    font = ObjCClass('UIFont').monospacedSystemFontOfSize_weight_(float(size), 0.0)
    ObjCInstance(view).setFont_(font)

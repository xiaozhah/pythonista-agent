"""Keys a focused text field keeps to itself, offered to Python first.

With a hardware keyboard (and always in the iPad app on a Mac) a focused text view takes ↑, ↓,
Return and Tab before any key command sees them, even one that asks for priority. So the field's
Objective-C object gets a small subclass whose presses… methods offer those keys to a Python
handler first; whatever the handler leaves goes on to the field as usual (the caret still moves
between lines, Return still types). Esc is not among them: a key command on the screen takes it
first, before Pythonista's own (which would close the screen).

Everything runs on the main thread, synchronously, inside UIKit's own key handling.

Also here: small things done to such a field through UIKit (edits that keep undo, where the caret
is, an input method's composition) and whether a screen should focus its field when it opens.
"""

from __future__ import annotations

import ctypes
import sys
import weakref
from collections.abc import Callable
from typing import Any

# HID usage codes of UIKey.keyCode
ON_DRAG = 1  # UIScrollViewKeyboardDismissModeOnDrag
KEYS = {82: 'up', 81: 'down', 40: 'return', 88: 'return', 43: 'tab'}
SHIFT, CONTROL, OPTION, COMMAND = 1 << 17, 1 << 18, 1 << 19, 1 << 20  # UIKeyModifierFlags
# the keys that make Return add a line: left and right Shift, left and right Option
NEWLINE_MODIFIERS = {225: SHIFT, 229: SHIFT, 226: OPTION, 230: OPTION}
# the class name carries this: bump it when the list of Objective-C methods changes
VERSION = 3

Handler = Callable[[str, bool], bool]  # (key, Shift held) -> True when it took the key


def _shared(name: str, default: Any) -> Any:
    """State kept on sys rather than in this module: opening pycoder again reloads it, but
    an Objective-C class made by the earlier load lives on and must reach the current code."""
    return sys.__dict__.setdefault(f'_pycoder_keys_{name}', default)


def intercept(field: Any, handler: Handler) -> None:
    """Offer field's ↑ ↓ Return Tab to handler(key, shift) first; a bound method is held weakly,
    so a closed screen is not kept alive. Call on the main thread; does nothing outside Pythonista."""
    try:
        from objc_util import ObjCClass, ObjCInstance, c
    except ImportError:
        return
    text_view = _text_view(ObjCInstance(field), ObjCClass('UITextView'))
    if text_view is None:
        return
    ref = weakref.WeakMethod(handler) if hasattr(handler, '__self__') else (lambda: handler)
    _shared('handlers', {})[int(text_view.ptr)] = ref
    # the methods of the class call whatever this module (as loaded now) says
    _shared('dispatch', {}).update(began=_began, ended=_ended)
    subclass = _subclass(text_view)
    if subclass is not None:
        c.object_setClass.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        c.object_setClass.restype = ctypes.c_void_p
        c.object_setClass(text_view.ptr, subclass.ptr)


def newline_held() -> bool:
    """Whether Shift or Option is down right now (⇧↩ and ⌥↩ add a line). On a Mac the line break
    of Return reaches the field as typed text before the key press does, so it is told apart by this."""
    return bool(_shared('held', set()))


def forget_modifiers() -> None:
    """Call when the field gains or loses the focus: a key released elsewhere never reaches it."""
    _shared('held', set()).clear()


def focus_on_open() -> bool:
    """Whether a screen should put the caret in its field when it opens: yes on an iPad or a Mac,
    where typing usually comes from a keyboard; not on an iPhone, where it would raise the on-screen
    keyboard over half the screen before anything is asked."""
    try:
        from objc_util import ObjCClass
    except ImportError:
        return False
    try:
        return int(ObjCClass('UIDevice').currentDevice().userInterfaceIdiom()) != 0  # 0: phone
    except Exception:
        return False


def utf16_len(text: str) -> int:
    """Length in UTF-16 units, as UIKit counts text positions."""
    return len(text.encode('utf-16-le')) // 2


def utf16_to_index(text: str, units: int) -> int:
    """A text field position (UTF-16 units) as an index into the Python string."""
    return len(text.encode('utf-16-le')[: units * 2].decode('utf-16-le', errors='ignore'))


def completion_edit(text: str, start: int, end: int, completed: str) -> tuple[int, int, str]:
    """Tab at the caret: text[:start] completed to `completed` (by a completer that may also have
    normalized it, say ／ to /). Returns the edit (from, to, insert) that keeps what both share,
    replaces the selection and leaves everything after the caret alone."""
    head = text[:start]
    same = 0
    while same < min(len(head), len(completed)) and head[same] == completed[same]:
        same += 1
    return same, end, completed[same:]


def replace(field: Any, start: int, end: int, text: str) -> None:
    """Replace field.text[start:end] (string indices) with text, through UIKit so ⌘Z undoes it,
    and put the caret after it. Falls back to setting the whole text."""
    old = field.text
    a, b = utf16_len(old[:start]), utf16_len(old[:end])
    try:
        view = _ui_text_view(field)
        begin = view.beginningOfDocument()
        span = view.textRangeFromPosition_toPosition_(
            view.positionFromPosition_offset_(begin, a), view.positionFromPosition_offset_(begin, b)
        )
        view.replaceRange_withText_(span, text)
        caret = view.positionFromPosition_offset_(begin, a + utf16_len(text))
        view.setSelectedTextRange_(view.textRangeFromPosition_toPosition_(caret, caret))
        return
    except Exception:
        pass
    field.text = old[:start] + text + old[end:]
    caret = a + utf16_len(text)
    try:  # set once the field has taken the new text in; set now, it lands at the start
        import ui

        def place() -> None:  # the text may have changed meanwhile (typing on, another ↑)
            at = min(caret, utf16_len(field.text))
            field.selected_range = (at, at)

        ui.delay(place, 0.01)
    except ImportError:
        pass


def caret_on_edges(field: Any, text: str, start: int, end: int) -> tuple[bool, bool]:
    """Whether the selection starts on the field's first visual line and ends on its last one: a
    wrapped paragraph is several lines here, so ↑ ↓ move the caret through it before history."""
    first, last = '\n' not in text[:start], '\n' not in text[end:]
    try:
        view = _ui_text_view(field)
        selection = view.selectedTextRange()

        def same_line(a: Any, b: Any) -> bool:
            ra, rb = view.caretRectForPosition_(a), view.caretRectForPosition_(b)
            return abs(float(ra.origin.y) - float(rb.origin.y)) < float(ra.size.height) / 2

        first = first and same_line(selection.start(), view.beginningOfDocument())
        last = last and same_line(selection.end(), view.endOfDocument())
    except Exception:
        pass
    return first, last


def color_start(field: Any, length: int, color: str, rest: str) -> None:
    """Show the first length characters of field in color and the others, and what is typed next, in
    rest. Not while an input method composes: changing the text then would break the composition."""
    try:
        from objc_util import NSRange, ObjCClass

        def ui_color(hex_color: str) -> Any:
            r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
            return ObjCClass('UIColor').colorWithRed_green_blue_alpha_(r, g, b, 1.0)

        view = _ui_text_view(field)
        if view.markedTextRange() is not None:
            return
        storage = view.textStorage()
        total = int(storage.length())
        length = min(length, total)
        storage.addAttribute_value_range_('NSColor', ui_color(rest), NSRange(0, total))
        if length:
            storage.addAttribute_value_range_('NSColor', ui_color(color), NSRange(0, length))
        typing = view.typingAttributes().mutableCopy()
        typing.setObject_forKey_(ui_color(rest), 'NSColor')
        view.setTypingAttributes_(typing)
    except Exception:  # never worth breaking the input for
        pass


def cancel_composition(field: Any) -> bool:
    """Drop what an input method (pinyin, kana) is composing in field, as Esc does in a text editor.
    True when there was something to drop."""
    try:
        view = _ui_text_view(field)
        marked = view.markedTextRange()
        if marked is None:
            return False
        view.unmarkText()  # keeps the letters typed so far as text, then they go
        view.replaceRange_withText_(marked, '')
        return True
    except Exception:
        return False


def _ui_text_view(field: Any) -> Any:
    from objc_util import ObjCClass, ObjCInstance

    view = _text_view(ObjCInstance(field), ObjCClass('UITextView'))
    if view is None:
        raise LookupError('no UITextView')
    return view


def hide_keyboard_on_drag(web: Any) -> None:
    """Dragging the page hides the keyboard, until the field is tapped again (as in Messages)."""
    try:
        from objc_util import ObjCClass, ObjCInstance
    except ImportError:
        return  # not on iOS
    scroller = _text_view(ObjCInstance(web), ObjCClass('UIScrollView'))
    if scroller is not None:
        scroller.setKeyboardDismissMode_(ON_DRAG)


def _text_view(view: Any, text_view_class: Any) -> Any:
    """The first view of that class in `view`: ui.TextView may wrap its UITextView in a plain view,
    and ui.WebView keeps its page's scroll view inside."""
    if view.isKindOfClass_(text_view_class):
        return view
    for sub in view.subviews():
        found = _text_view(sub, text_view_class)
        if found is not None:
            return found
    return None


def _subclass(text_view: Any) -> Any:
    """The key-catching subclass of text_view's class, made once per process."""
    from objc_util import ObjCClass, c, create_objc_class, sel

    base_name = text_view._get_objc_classname().decode()
    if base_name.startswith('Pycoder'):
        return None  # already caught
    name = f'Pycoder{base_name}Keys{VERSION}'
    try:
        return ObjCClass(name)  # made by an earlier load of pycoder in this process
    except ValueError:
        pass
    c.class_getMethodImplementation.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    c.class_getMethodImplementation.restype = ctypes.c_void_p
    base = ObjCClass(base_name)
    signature = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    began, ended, cancelled = (
        signature(c.class_getMethodImplementation(base.ptr, sel(f'presses{what}:withEvent:')))
        for what in ('Began', 'Ended', 'Cancelled')
    )
    dispatch = _shared('dispatch', {})

    # Thin trampolines into the current code. No annotations: create_objc_class reads the arguments
    # with inspect.getargspec, which refuses them.
    def pressesBegan_withEvent_(_self, _cmd, presses, event):  # type: ignore[no-untyped-def]
        if not dispatch['began'](_self, presses):
            began(_self, _cmd, presses, event)

    def pressesEnded_withEvent_(_self, _cmd, presses, event):  # type: ignore[no-untyped-def]
        if not dispatch['ended'](presses):
            ended(_self, _cmd, presses, event)

    def pressesCancelled_withEvent_(_self, _cmd, presses, event):  # type: ignore[no-untyped-def]
        if not dispatch['ended'](presses):
            cancelled(_self, _cmd, presses, event)

    methods = [pressesBegan_withEvent_, pressesEnded_withEvent_, pressesCancelled_withEvent_]
    for method in methods:
        method.encoding = b'v@:@@'  # type: ignore[attr-defined]
    subclass = create_objc_class(name, base, methods=methods)
    _shared('classes', []).append((subclass, began, ended, cancelled, methods))
    return subclass


def _began(text_view: int, presses: int) -> bool:
    """True when the handler took every key of these presses (then the field never sees them).
    A failing handler never breaks typing."""
    from objc_util import ObjCInstance

    try:
        held: set[int] = _shared('held', set())
        taken = _shared('taken', set())
        composing = ObjCInstance(text_view).markedTextRange() is not None  # pinyin etc. own the keys
        ref = _shared('handlers', {}).get(int(text_view))
        handler = ref() if ref is not None else None
        all_taken = True
        for press in ObjCInstance(presses).allObjects():
            key = press.key()
            code = int(key.keyCode()) if key else 0
            flags = int(key.modifierFlags()) if key else 0
            if code in NEWLINE_MODIFIERS:
                held.add(code)
            else:  # the live flags say which are up: a release may have gone elsewhere
                held.difference_update([k for k in held if not flags & NEWLINE_MODIFIERS[k]])
            name = KEYS.get(code)
            # with Cmd, Option or Ctrl (or Shift, except on Return) a key keeps its usual meaning
            modified = bool(flags & (CONTROL | OPTION | COMMAND)) or (
                name != 'return' and bool(flags & SHIFT)
            )
            if handler and name and not composing and not modified and handler(name, bool(flags & SHIFT)):
                taken.add(int(press.ptr))
            else:
                all_taken = False
        return all_taken
    except Exception:
        return False


def _ended(presses: int) -> bool:
    """True when every press here was taken when it began: the field never saw them start."""
    from objc_util import ObjCInstance

    try:
        held = _shared('held', set())
        taken = _shared('taken', set())
        all_taken = True
        for press in ObjCInstance(presses).allObjects():
            key = press.key()
            if key is not None and int(key.keyCode()) in NEWLINE_MODIFIERS:
                held.discard(int(key.keyCode()))
            if int(press.ptr) in taken:
                taken.discard(int(press.ptr))
            else:
                all_taken = False
        return all_taken
    except Exception:
        _shared('held', set()).clear()
        return False

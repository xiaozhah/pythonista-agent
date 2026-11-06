---
name: pythonista-keyboard-scripts
description: "Use when writing a Pythonista custom-keyboard script (keyboard module): reading and replacing text at the cursor, a view in the keyboard, sending typed keys to its own box, or testing it without a keyboard."
---

The keyboard itself can't be run from pycoder: test the logic, preview the view, and tell the user what only the device can show.

## Text
- `before, after = keyboard.get_input_context()`, `keyboard.get_selected_text()`, `keyboard.insert_text(s)`, `keyboard.backspace(times=n)`, `keyboard.play_input_click()`.
- `keyboard.move_cursor(offset)` counts UTF-16 units, so an emoji is 2: `len(s.encode('utf-16-le')) // 2`.
- Whether before/after exclude the selection isn't documented: show both on the device.
- Keep the logic pure: functions from the text before the cursor to (characters to delete, text to insert).
- Scanning backwards for "what is before the cursor": don't start in the middle of a word or number, or `1,000+1` is read from `000+1`. Test such inputs in the pure logic.

## A view in the keyboard
- `keyboard.set_view(view, 'minimized')` keeps the letter keys, `'expanded'` hides them; `set_view(None)` closes it.
- Call `super().__init__(frame=...)` before adding subviews; lay out in `layout()`.
- Live updates: `kb_text_changed(self)`, with `update_interval = 0.2` and `update()` as a fallback.
- Outside the keyboard `keyboard.is_keyboard()` is False: show a preview with `view.present('sheet')`, so the user sees something there (set its frame: see pythonista-ui-apps).

## Typing into your own box (search, notes, code)
- `kb_should_insert(self, text)`: add it to your buffer and return `''`, so nothing reaches the document. `kb_should_delete(self)`: trim your buffer and return `False`.
- While your own `keyboard.insert_text` runs, set a flag and return `text`, or it comes back to your buffer.
- Whether Return arrives as `'\n'` isn't documented: handle it, but keep a button too.
- Show the buffer in a `ui.TextView` with `editable = False`. To follow the newest line: `tv.content_offset = (0, max(0, tv.content_size[1] - tv.height))`, in `layout()` too.
- Closing and reopening the view runs the script again: keep state in `builtins` under a private name.

## Controls
- `ui.SegmentedControl` ignores `tint_color` for unselected text on a dark theme: two buttons as a toggle read better.
- Pasteboard writes need Full Access: check `keyboard.has_full_access()` first.

## Testing without a keyboard
Load the file and fake `module.keyboard` as pythonista-testing says: a fake holding a text and a cursor (insert_text, backspace, get_input_context, set_view, is_keyboard, get_appearance, play_input_click).
- Fake `set_view` by adding the view to a test window, so use_screen can operate it.
- Keys can't reach a preview: call the view's `kb_should_insert(text)` and `kb_should_delete()` from run_python, and use use_screen for its buttons. use_screen `type` replaces a TextField's text.

A statement that never ends blocks the keyboard, with no way to interrupt it there: say so if the script runs user code.

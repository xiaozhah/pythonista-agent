---
name: pythonista-keys-and-touches
description: Use when a Pythonista ui.View or scene needs hardware keyboard keys, swipes or drags, or its drawing checked without a screen.
---

## Logic
Keep the logic in a module that does not import `ui`, so it can be tested anywhere. `run_python` runs a test file with `unittest.main()` directly.

## Hardware keys
- Override `get_key_commands()` to return dicts like `{'input': 'up', 'title': '上移'}` (input 'up'/'down'/'left'/'right', 'esc', '\r', '\b'; optional 'modifiers' such as 'cmd'), and implement `key_command(self, sender)`: `sender['input']` says which key. It works once the view is presented.
- With views inside each other, a key goes to the first of them in the chain that has `key_command`, even if another one listed that key: list and handle a key on the same view.
- use_screen `key` reaches `key_command`, not a TextField.

## Swipes and drags
- `touch_began(touch)`, `touch_moved(touch)`, `touch_ended(touch)` on a View subclass; `touch.location` has y growing downward, so a swipe up has dy < 0. In a scene y grows upward.
- Use a threshold (about 30 points) so short taps are not moves.
- A drag with use_screen reaches `touch_moved`: check a score or counter after it before deciding it failed. The real gesture still needs a person.

## Checking draw() without a screen
Set `view.frame`, then `with ui.ImageContext(w, h) as ctx: view.draw(); img = ctx.get_image()`. This catches exceptions in drawing code.

---
name: pythonista-shortcuts-and-urls
description: "Use when a script should run from the Shortcuts app or Siri, return a result to a shortcut, be started by a pythonista3:// URL or a home screen icon, act as an editor action, or open another app."
---

The share sheet and widgets are in `pythonista-share-extensions-and-widgets`, the keyboard in `pythonista-keyboard-scripts`.

## In a shortcut

A script can run as an action in the Shortcuts app, without opening Pythonista.

- `shortcuts.is_running_shortcut()`: False when run any other way, so a script can show its own screen then, and return a result here.
- What it returns: `set_output_data(data, filename, uti=None)` (bytes, typed by the file name), `set_output_image(image)` (a path, a PIL image or a `ui.Image`), `set_output_files([{'path': ...}])` (or `{'data': ..., 'filename': ...}` for a file in memory).
- `set_result_html(html)` shows a result inside the shortcut.
- `open_shortcuts_app(name=None, shortcut_input='')` goes the other way: it runs a shortcut of the user's and leaves this app.

Keep the work in a function that takes its input and returns its output, and test that. A real shortcut can't be run from here: say so, and give the steps to add the action.

## URLs

`shortcuts.pythonista_url(path='', action='run', args=None, argv=None)` builds a `pythonista3://` URL. `'run'` runs the script with no question asked, `'open'` opens it for editing, `'exec'` embeds the source and lets the person decide. `argv` arrives in `sys.argv`, so a script can be told what to do.

- Paths are relative to the script library.
- `shortcuts.open_url(url)` opens a URL, including other apps' schemes. It leaves Pythonista and stops the test: from a test, check the URL string instead of opening it.
- A notification's `action_url` is one of these, and so is a home screen icon: a program can come back to the right screen.

## Editor actions

A script in the wrench menu acts on what is being edited, through the `editor` module: `editor.get_path()`, `get_text()`, `get_selection()`, `replace_text(start, end, text)`, `set_selection(start, end)`. It is set up by hand in the wrench menu's Edit: say so. Test by giving the function a text and a selection: calling `replace_text` from a test changes whatever the user has open.

## From Python to the rest of the app

`console.hud_alert(text)` shows a short message and doesn't wait. `console.open_in(path)` offers a file to other apps and waits for a person, so it goes behind a button and tests replace it.

## Notifications

`notification.schedule(message, delay=0, sound_name=None, action_url=None, title=None, subtitle=None, attachments=None, trigger=None, actions=None, identifier=None)` returns an identifier. `cancel(identifier)`, `get_scheduled()`, `remove_delivered(identifier)`. Give yours an identifier and cancel only those: `cancel_all()` also removes what other scripts scheduled. `action_url` can be a `pythonista_url(...)`, to come back to the program. Not available in extensions.

---
name: pythonista-share-extensions-and-widgets
description: "Use when writing a Pythonista share-sheet extension or Today widget (appex module): reading what was shared, showing a result, testing without the share sheet, or when asked for a home or lock screen widget."
---

## Widgets: say this first
Pythonista's only widget is a legacy Today widget, not WidgetKit: it lives in the Today view, not as a home or lock screen widget of today's kind, and reports say iOS 18 disabled this kind. On a current iOS tell the user it can probably only be previewed in the app, before building it.
- `appex.set_widget_view(view)`, run in the app, shows a simulated widget.
- Height at most 120 means compact only. The system shrinks the view to 120 when collapsed: lay out with fixed sizes, and check that nothing is cut off below.
- No dialogs, `console.alert` or `present` in a widget.
- After setting a widget view's frame, lay it out yourself.
- Don't press "Use in Today" in the preview from a test: it changes the user's Pythonista settings.

## Share extensions
- Outside the extension `appex.is_running_extension()` is False: show the steps to use it, and return.
- `appex.get_text()`, `get_url()`, `get_file_paths()`, `get_image_data()`. A bare link in the text is a URL. `notification` isn't available in extensions.
- Show the result with `present('full_screen')`, and a button that calls `self.close()` then `appex.finish()`. A `'sheet'` needs its frame set first (pythonista-ui-apps).
- `console.alert(title, msg, 'OK', hide_cancel_button=True)` avoids the KeyboardInterrupt from Cancel.

## Testing without the share sheet
See pythonista-testing: load the file under another name and replace `appex`, `console` and `clipboard` on it with recorders. In the app `is_running_extension()` is False, so `main()` only shows the usage: the result view needs the fake.

## What's shared
- Fetching a page: `urllib.request` with a browser User-Agent, a timeout and a size limit. Charset: the header, then `<meta charset>`, then utf-8 with replacement.
- EXIF GPS (Pillow 9): `Image.open(io.BytesIO(data)).getexif().get_ifd(0x8825)`; 1/2 latitude, 3/4 longitude; `float()` the values, S and W are negative, and (0, 0) means no fix. HEIC doesn't open: show a message.
- Markdown: short extension names like `'extra'` fail here. Use full ones: `markdown.extensions.fenced_code`, `tables`, `footnotes`.

---
name: pythonista-ui-drawing-and-web
description: "Use when a ui screen draws for itself, shows rich content in a WebView, or loads or writes a .pyui file."
---

## Drawing and images

Custom drawing: override `draw()`, use `ui.set_color` and `ui.Path`, and call `set_needs_display()` to redraw. Off-screen images: `with ui.ImageContext(w, h) as ctx: …`, then `ctx.get_image()`.

## Web views

- `ui.WebView` with `load_html(html)` is often the easiest way to show rich content: Markdown, code, tables, charts. It has no WebGL2.
- `eval_js(code)` runs JavaScript and returns the result as a string.
- Page to Python: the page stores an answer in a JS variable that Python polls with `eval_js`, or navigates to a custom URL that the delegate's `webview_should_start_load` catches.
- Escape anything inserted into the page: `html.escape`, and `json.dumps` for JS arguments.

## `.pyui` files

Made in Pythonista's UI editor, and loaded with `ui.load_view('name')`. They are JSON, so a program can write one: a list with one root, each node `{"class": "View", "attributes": {...}, "frame": "{{x, y}, {w, h}}", "nodes": [...]}`, with classes such as `Slider`, `Label`, `Button`. Give a child's `attributes` a `name`, and an `action` naming a function:

```python
view = ui.load_view(path_without_extension, bindings={'on_slide': on_slide})
view['s1'].value
```

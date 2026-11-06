---
name: checking-a-ui
description: "Use when a screen has been built and needs checking: rendering it to an image, looking at it presented, and pressing, dragging and typing in it with use_screen."
---

Tests of the logic can't see a broken screen, and you can. Don't ask the user for a screenshot.

## Without presenting it

```python
view = MyView()
view.frame = (0, 0, 390, 700)
view.layout()
with ui.ImageContext(view.width, view.height) as ctx:
    view.draw_snapshot()
    png = ctx.get_image().to_png()
with open('look.png', 'wb') as f:
    f.write(png)
# read_file('look.png'), then delete it
```

Do this for every screen, at the size it will really have: for a sheet, the size it has before present; otherwise a phone (390x700) and a Mac or iPad (1000x700).

## As it really appears

`present()` it from run_python, call look_at_screen, and when done call look_at_screen with close=true, so your windows don't stay over pycoder. Look for what is cut off, overlapping, too small or empty.

## Using it

`use_screen` with `list` shows the controls and marks what is hidden or cut off; `tap` presses one, `drag` touches, `type` fills a field or moves a slider, `key` sends a hardware key. Each returns what changed in the list and any error your code raised; call look_at_screen only when how it looks matters. Press what a user would, in the order they would: a button that does nothing is a bug no picture shows. Scenes take taps and drags at a point.

It calls what a finger would reach, one finger at a time: no pinch, no held press, no system dialogs, no judging how it feels. Say so. To fake what a program touches, read `pythonista-testing`.

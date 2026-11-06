---
name: testing-a-live-screen
description: "Use when a test drives a window or scene: what use_screen can't reach, fake touches and their coordinates, timing, theme and rotation."
---

To fake what the program touches, see `pythonista-testing`.

## What use_screen can't do
- Console dialogs: a real one holds the program until someone answers, and the tool gives up. Replace `console.alert` and `console.input_alert` with recorders.
- Taps come seconds apart, and those sent together run back to back: a scene still animating ignores the second. For a time window (a combo within 2 s), call the methods with fake touches in one run_python.
- It reports text: wait about a second after an animation, and call look_at_screen when the picture matters.

## Touches and coordinates
- use_screen's points have y growing down. A scene's `touch.location` and `node.position` have y growing up: `screen_y = scene.size.h - scene_y`.
- Fake touches call the object's methods directly, with its own coordinates: an object with `location` (x, y) and `touch_id`. Send began, several moved, ended.

## Theme and rotation
- Theme: replace `ui.get_ui_style` with a function returning what you choose; the program must look it up when called, not import the name. Put it back afterwards.
- Rotation: nothing here can turn the device. Put the SceneView in a plain view presented as a popover at a chosen size, set both frames to a new size, and check that `did_change_size` ran. In a fullscreen root, changing the frame doesn't reach `scene.size`.

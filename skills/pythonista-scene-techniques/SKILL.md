---
name: pythonista-scene-techniques
description: "Use when building with Pythonista's scene module: nodes that misplace or draw wrongly, dials and rotation, tilt control, grid or collision games, shaders, generated sounds, or testing a scene without touching the screen."
---

For hardware keys and swipes see scene-game-with-keys-and-swipes; to drive a scene in a test, pythonista-testing.

## Nodes
- `LabelNode('')` makes a "ValueError: Could not load image" banner: give labels text from the start.
- `SpriteNode(None, color=(0,0,0,0.5))` draws opaque: use `node.alpha`. `SpriteNode(None, size=..., color=...)` is a plain rectangle.
- A ShapeNode centres the bounding box of its path on its position: build paths around (0, 0). For a limb, rotate a plain `Node` joint and make the shape its child at `(0, -len/2)`.
- A hand from its pivot: `anchor_point = (0.5, 0)`. Rotation is counter-clockwise: `math.radians(-clock_degrees)`.
- A SceneView in a ui.View: set `self.sv.frame = self.bounds` in `layout()`, or the bottom is cut off.
- Fit any screen: everything under one `Node`, with `position` and `scale` set from a layout function called from `setup()` and `did_change_size()`.
- CJK text may not render in labels with Menlo or Helvetica.

## Games
- Rules in a module without ui or scene, with unittest. Animate from a small state machine in `update()`, with `dt` clamped, rather than chained `Action.call`.
- A fast ball: sub-step so no step is longer than a brick. Physics returns events ('hit', 'lost'); the scene turns them into sound and particles.
- Menus: store hit rectangles yourself and test them in `touch_began`.
- Timing from `time.monotonic()` in `update()` stays accurate; actions drift.
- `Action.remove()` is used in the guide though the reference omits it: `Action.sequence(Action.fade_to(0, 0.3), Action.remove())`.

## Tilt
`motion.start_updates()`, `motion.get_gravity()` each frame; `stop_updates` in `will_close`. A Mac reports a fixed pose (see `pythonista-motion-sensors`). Take the pose at start as level: with `dx, dy` the unit vector of it, right is `(-dy, dx)`, and portrait and landscape need no special case. Use a dead zone of about 0.05, full at about 0.35. Keep keys and finger as fallbacks.

## Shaders
Full-screen `SpriteNode` with `sprite.shader = Shader(src)`; size it in `did_change_size()`, called from `setup()` too. Uniforms: `u_sprite_size`, `u_texture`, `v_tex_coord`, and yours with `set_uniform`. For an endless scroll, make the noise periodic (`mod(i, 256.0)`) and keep time terms whole numbers.
- Check a seam numerically: port the noise to numpy, and compare the step across the wrap with an ordinary frame's step.

## Sound
`sound.play_effect(name_or_path, volume, pitch)` takes a built-in name or a file: write a WAV with `wave` to `tempfile.gettempdir()`. It returns None for an unknown name, without raising. Tell the user you can't hear it.

## Testing without a finger
- `scene.run(s)` returns at once. Sleep a moment, then call `s.touch_began(fake)` with a fake having `.location` and `.touch_id`, and check the state. A later run_python can't reach the scene unless it's kept in `builtins`.
- For speed: `sv.paused = True`, then call `update()` in a loop with `dt = 1/60`, and check that `len(s.children)` stays flat.
- Delete the save files tests write. A screenshot seconds later misses short effects: check for the node instead.

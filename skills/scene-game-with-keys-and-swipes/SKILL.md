---
name: scene-game-with-keys-and-swipes
description: Use when building a Pythonista scene (scene module) game that needs hardware arrow keys and swipes together, or a classic draw() loop with a pure-logic module.
---

## Pattern
- Keep game rules in a module that imports neither ui nor scene; test it with unittest via run_python (see pythonista-keys-and-touches).
- Hardware arrow keys need a ui.View that is presented. Put the SceneView inside it:
```python
class GameView(ui.View):
    def __init__(self, scene_obj):
        super().__init__()
        self.flex = 'WH'
        self.sv = SceneView()
        self.sv.flex = 'WH'
        self.sv.scene = scene_obj
        self.add_subview(self.sv)

    def get_key_commands(self):
        return [{'input': k} for k in ('up', 'down', 'left', 'right', '\r', 'r')]

    def key_command(self, sender):
        scene_obj.handle_key(sender['input'])


# main: GameView(SnakeScene()).present('fullscreen')
```
- Scene touches: `touch_began(touch)` / `touch_ended(touch)` (one argument). Scene y grows upward, so dy > 0 is a swipe up. Use a ~30 point threshold; a short touch counts as a tap.
- Classic loop: override `draw()` with scene_drawing functions (background, fill, rect, ellipse, text(txt, font, size, x, y, alignment)); `update()` advances the logic using `self.dt`. Clamp dt (for example to 0.25 s) so returning from the background does not replay many steps.
- Keep a turn queue in the logic (max 2) and reject reversals, so two quick key presses in one tick cannot make the snake reverse into itself.

CJK text in scene `text()` may not render with Menlo or Helvetica. Drawing and gestures need a person to check.

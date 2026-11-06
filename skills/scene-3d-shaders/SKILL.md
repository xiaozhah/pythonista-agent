---
name: scene-3d-shaders
description: "Use when a scene should show a 3D world drawn by a fragment shader: raymarching tunnels, terrain or fractals, and feeding game state to the GPU."
---

A whole world from a formula, with scene nodes as the HUD. For real objects with lights and shadows see `scenekit-models`; for thousands of independent things, `metal-compute`.

```python
SRC = """
precision highp float;
varying vec2 v_tex_coord;
uniform float u_time;
uniform vec2 u_sprite_size;
uniform vec3 camera;
float map(vec3 p) { vec3 q = mod(p + 1.0, 2.0) - 1.0; return min(length(q) - 0.45, p.y + 1.2); }
void main() {
    vec2 uv = (v_tex_coord - 0.5) * vec2(u_sprite_size.x / u_sprite_size.y, 1.0);
    vec3 rd = normalize(vec3(uv, 1.0));
    float t = 0.0;
    for (int i = 0; i < 48; i++) { float d = map(camera + rd * t); if (d < 0.002 || t > 20.0) break; t += d; }
    vec3 p = camera + rd * t; vec2 e = vec2(0.002, 0.0);
    vec3 n = normalize(vec3(map(p + e.xyy) - map(p - e.xyy), map(p + e.yxy) - map(p - e.yxy), map(p + e.yyx) - map(p - e.yyx)));
    float l = max(dot(n, normalize(vec3(0.5, 0.8, -0.4))), 0.0);
    gl_FragColor = vec4(vec3(0.2, 0.8, 1.0) * l * exp(-0.12 * t), 1.0);
}"""
node = SpriteNode(None, size=self.size, position=self.size / 2, parent=self)
node.shader = Shader(SRC)
node.shader.set_uniform('camera', (1.0, 1.0, z))  # each frame, from update()
```

- A flat single colour usually means the camera started inside a shape: every ray stops at once. Start where `map(camera)` is positive.
- Game rules can't read the GPU. Write the same distance function in Python for collisions, and test the two against each other at a few points.
- Size the sprite in `did_change_size()` too. Cost follows pixels: when the frame rate falls, scale the sprite down and back up. Measure it on the device you run on, by counting frames in `update()`.

## Giving the shader game state

- `set_uniform('name', 0.5)` and `set_uniform('name', (x, y, z))` for floats and vectors.
- For many values, a data texture: a small RGBA image from numpy and PIL, then `scene.Texture(ui.Image.from_data(png))`, `set_uniform('data', texture)` and `texture2D(data, uv)`. A new one each frame costs a PNG encode: keep it small, and update it less often than the screen.
- A uniform array isn't a way in: a tuple on `uniform vec3 pts[2]` sets `pts[0]` only. Declare separate names, or use a texture.

`look_at_screen` sees scene shaders.

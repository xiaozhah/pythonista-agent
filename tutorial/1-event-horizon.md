# Event Horizon

**The goal:** a 140-second film about a spinning black hole, drawn live on the GPU in real physics, with an organ score,
that a finger can take over at any moment. Tap Run on `blackhole.py` and it plays. About 10 small files.

This project is about native-speed graphics from Python: Metal compute kernels compiled at run time, a `CAMetalLayer` in a
`ui.View`, general relativity in a shader, a camera that moves like a film's, and a program that a person can interrupt.

Skills: `metal-compute`, `pythonista-objc-recipes`, `pythonista-screen-video`, `pythonista-sound-and-midi`, `pythonista-ui-apps`,
`pythonista-ui-drawing-and-web`, `pythonista-keys-and-touches`, `testing-a-live-screen`, `checking-a-ui`, `pythonista-testing`.

**You write all of it, from nothing, except the music.** This folder holds `midi_notes.py`, `organ_render.py` and `grand_organ.py`: use those three as they are,
so the organ plays the same notes. The music itself is a file the person who runs it supplies, `music.mid`, a MIDI file 140 seconds long. Everything else exists only as the description
below. It is long because the look of the film is in its details: every number here was found by looking at the result, so use
each one exactly, and don't replace a formula with something simpler. This file is longer than one read: keep reading to the end
before you start. Don't look for other copies of this film on the device, in `~/demos` or anywhere else: whether this brief is
enough is part of what this run finds out.

## What the viewer sees

Black, then a spark that grows into a black hole seen nearly edge-on: a golden disk, its far side bent up over the shadow and under
it, and a thin bright ring around the shadow. The title **EVENT HORIZON** fades in beneath it. The camera comes on for 40 seconds in
one unbroken move, circling as it comes, until the hole nearly fills the frame. A tiny ship crosses in silhouette, with a small
red light blinking at its tail.

The music opens and the film cuts: down at the disk's edge, a thin slanted line of gold, then up over it in one sweep until you
look down on swirling gas. Everything plays: a long push in, a run along the disk with the gold rushing beneath you, and out again.
The disk is amber on the side turning away and burns white on the side turning towards you, with a thin red rim at its inner edge
on the far side. All of this is real: redshift, beaming and frame dragging, not a colour choice.

Then the last climb, a turn back towards it, and the fall. From 128 seconds a line counts `1 second here  =  1.1 seconds on Earth`, and the
number climbs. The camera rumbles, cuts at the edge, and looks back: the whole universe shrinks to a small bright circle as the
horizon closes in, and at 135 seconds it cuts to black, with the organ ringing on. *Time stops at the edge.* At 140 seconds the film
hands over to free flight.

At any moment: drag to turn, tap the disk to drop matter on it, pinch to fly closer. **GPU race** measures the same step in Python, numpy
and Metal. **Free flight** stays with the viewer. **Close** ends everything.

## What has to be true

- `blackhole.py`, run with Pythonista's Run button, does all of this with nothing else open. **Nothing that plays the film may import `pycoder`**: it can't be
  imported on an iPhone from the Run button. Only making the video file may use `pycoder.host.screen_video`. So write your own small Metal helper, not `pycoder.host.metal`.
- The music is built from `music.mid`, which the person who runs it supplies, the first time it runs, and kept as `film_grand.wav` next to the program.
- It picks the best picture the device can draw on time, and it stays in step with the music.
- The physics is checked against exact answers, not by eye (milestone 3).

## Files

| File | What's in it |
| --- | --- |
| `kernels.metal` | every kernel of Part 2, with the placeholder words of Part 2.1 left in |
| `shots.py` | no `ui`, no `objc_util`: the hole's numbers and the camera, Part 1 and Part 4 |
| `gpu.py` | `MTLSize`, `owned`, `encoding`, `GPU`, `Pool`, Part 3.1 |
| `engine.py` | `Engine`: the stars, the textures at each size, one frame, the exposure, Part 3 |
| `words.py` | words as native views live, and burned into the frame for the video, Part 5.5 |
| `film.py` | `film_frame`, `stills`, `render_film`, `build_music` |
| `blackhole.py` | choosing the picture, `play`, the `Hole` view, Part 5. It puts its own folder on `sys.path` first, then imports the others |
| `midi_notes.py`, `organ_render.py`, `grand_organ.py` | given, already here |
| `music.mid` | supplied by the person who runs it, a MIDI file 140 seconds long |
| `demo.py` | makes `demo.mp4` |
| `tests/`, `run_tests.py` | the logic's tests and the physics |

## Traps that cost days

Each of these happened while this film was made. Read them before writing anything.

1. **Never use `objc_util.autoreleasepool`.** The collector later releases a pool that is gone, and the app crashes. Use paired push and pop through ctypes (Part 3.1).
2. **`new...` methods hand over one reference more than `ObjCInstance` gives back.** Call `.release()` once on each result (buffers, textures, queues, libraries, functions, pipelines). Without it nothing is ever freed, each run leaks about 70 MB, and iOS closes Pythonista after a few.
3. **An unended compute encoder aborts the whole app**, later, when the collector frees it after any exception. Make every encoder through a context manager whose `finally` calls `endEncoding`.
4. **Set `multitouch_enabled = True` on the view**, or a second finger never arrives and pinching silently does nothing.
5. **Stop the music yourself.** `will_close`, the end of the render loop and a second run must all stop it: a `shut_down()` that is safe to call twice. Keep the view in `builtins._event_horizon`, so running again closes the last one first. A leftover film also eats the GPU and spoils every measurement after it: check for one when numbers look odd.
6. **`console.set_idle_timer_disabled(True)` while it plays, `False` in `shut_down`.** Nobody touches a screen during a film, the phone locks, and the picture freezes.
7. **The camera must not sway.** No sine waves on the camera, ever. A sine on a low camera moves the whole horizon, and it reads as a boat, not a film.
8. **Trace light in unit vectors, not angles.** Spherical coordinates break down at the spin axis and draw a dotted vertical seam through the picture (Part 2.7).
9. **Reset each ray's speed from what it conserves, every step.** Without that, errors in the fast outer steps swamp the turning point and the shadow comes out four times too big, whatever the spin.
10. **Long steps through the disk must saturate:** what a step adds is limited by what it absorbs (Part 2.9). A plain `tau` overshoots on grazing rays, and the disk flickers with bright grain.
11. **A step's detail must fade with the step's length too** (Part 2.9), or the same flicker comes back.
12. **The photon ring needs 8 rays evenly across its width**, averaged with highlights squeezed (Part 2.11). Scattered rays break it into dashes; a plain average turns one bright ray into a white pixel.
13. **Blend frames, and clear them at a cut.** A slightly different sub-pixel offset each frame, while the camera is slow, is what smooths the slanted line of the disk. Don't blend across a cut or a change of size.
14. **Don't make a dolly zoom by accident.** Distance falling while focal length falls cancels out, and the opening looks frozen.
15. **The tail light is a dim point about a pixel across, added to the picture.** A light scaled with the ship falls between pixels and vanishes; anything brighter or with a glow looks like a warning lamp.
16. **On a phone `ui.get_window_size()` may be portrait before the view turns.** Take the longer side as the width. Get the scale from `ObjCClass('UIScreen').mainScreen().scale()`: `ui` has no such function.
17. **Don't render the whole film to check something.** Look at a few stills, and jump around the live film with `view.player.current_time = 85`: the film's time follows the music.
18. **Don't leave a file open in the editor while another program changes it.** `editor.open_file` in tests leaves a tab that saves over your work.

## Milestones

Each one works, is checked and is committed before the next starts.

1. **The Metal plumbing** (`gpu.py`). Read `metal-compute` and `pythonista-objc-recipes` first. Compile a tiny kernel and run it. Prove trap 2: make and delete a large buffer several times, and show that memory doesn't grow, reading `task_info`'s `phys_footprint` or `os_proc_available_memory`. Prove trap 3: raise an exception halfway through an encoder, run `gc.collect()`, and show the app is still alive.

2. **The shots, no GPU** (`shots.py`, `tests/`). Part 1 and Part 4. Tests: `kerr(0)` is `(0, 1, 3)`; `kerr(0.6)` is about `(0.3, 0.9, 1.915)`. `time_factor(10)` is about 1.05, `time_factor(3)` 1.22, `time_factor(1.5)` 1.69, and at the horizon times 1.0005 about 52.7. `cam_at(130)['dist']` is 2.6 and `cam_at(128)['dist']` about 5.195. Position and its rate of change are continuous across the keys within an act. There is no clock line at 127, and at 128 it says `1.1`. Between 0 and 40 seconds `focal / dist` grows about 8 times.

3. **The shadow, checked against the exact answer.** Write `kernels.metal`'s ray tracing and `Engine`'s compile step. For this test compile a variant in which a ray returns black if it fell in and white if not, with the disk's crossing switched off. At 1920×804, with `dist=60, focal=3.2, el=0, roll=0, orbit=0.7, sx=sy=0`, walk the middle row out from its centre to the first bright pixel on each side. Compare with Kerr's own curve, over `r` around the photon orbits, with `M=0.5`, `a=spin·M`: λ = −(r³ − 3Mr² + a²r + a²M) / (a(r − M)), q = −r³(r³ − 6Mr² + 9M²r − 4a²M) / (a²(r − M)²). The shadow's edges in the plane are at −λ where q = 0, and an edge α is `focal · tan(asin(α/dist)) · 804` pixels out.

   | spin | Must measure, in pixels | Exact |
   | --- | --- | --- |
   | 0 | −111 to 110 | ±111.5 |
   | 0.6 | −135 to 81 | −135.6 to 82.3 |
   | 0.9 | −146 to 60 | −146.7 to 61.0 |

   Search r from just above M to 2.2, and take the two ends of −λ among the r with q ≥ 0 (at spin 0 the edges are ±2.598). For spin 0.6 that gives −82.3 to 135.6: the screen shows it mirrored, and the wider side, at the left, is where light goes against the spin. Count a pixel as dark when all its channels are below 40, and draw with no stars and no blending, so that only this is measured. Don't go on until this holds. Afterwards the film uses spin 0.6.

4. **The disk and the stars.** The rest of Part 2 up to `accumulate`, and Part 3.3. Stills at 22, 60, 85, 112 and 128 seconds at 1280×536; say what you see in each. At 22: an edge-on hole with the bent arcs above and below. At 60: gas seen from above around a slightly off-round shadow. At 85: a low run with a bright horizon and the arc rising above it. On every frame, white on one side and amber with a thin red inner rim on the other. There must be no vertical seam above the hole, no slanted stripes and no broken ring.

5. **Stable in motion.** Add the blending and the sub-pixel offset. Draw a few frames along the moving camera at 44, 85 and 126 seconds, and measure the average change between consecutive frames in a crop of the disk: below about 1 in 255. Crop and enlarge the slanted line at 45 seconds: no staircase, no grain. Compare with the offset off, to show what it buys.

6. **On screen, in time** (`blackhole.py`, `words.py`). Part 5, without music at first. It keeps to the film's time, not a frame count. Measure frames per second by shot with a frame counter. Look at it with `look_at_screen`: the Metal layer is in that picture.

7. **The music** (`build_music`, called at the start of `play` when sound is on). If `film_grand.wav` exists or `music.mid` doesn't, it does nothing. Otherwise it puts its folder on `sys.path`, prints `Building the organ from the MIDI, just this once...`, runs `grand_organ.render(midi, wav + '.tmp', 136.0)`, then `os.replace`, so that an interrupted run leaves nothing half made. That takes about 15 seconds, once. The file is 140 seconds at 44100 Hz, stereo, 24,696,044 bytes. You can't hear it, so plot its STFT with matplotlib, as `pythonista-screen-video` says: quiet early, full near the climax. Now `sound.Player` drives the film's time. While testing, `sound.set_volume(0.0)`, restored in `finally`.

8. **Choosing the picture.** Part 5.1. Print what was picked. On a slow device it must fall to a lower quality and still give the far shots more pixels.

9. **Every control, operated for real.** With `use_screen`: `Free flight` changes the mode and its title. A drag changes `free_orbit`. `GPU race` shows its result, it's still there 10 seconds later, and a second press hides it. `Close` stops the music, the thread ends and the view is off screen. A second run closes the first. A pinch can't be done by `use_screen`: call `touch_began`, `touch_began`, `touch_moved`, `touch_ended`, `touch_ended` with fake touches having `touch_id`, `location` and `prev_location`, and check that fingers spreading from 100 to 200 points halve `free_distance`, and pinching back restores it. A tap on the disk raises `drops`; a tap on the sky doesn't. Then the whole first run, alone: delete the WAV, set `sys.modules['pycoder.host.metal'] = None`, and play. Check for a leftover view afterwards.

10. **The video and the report.** This replaces the 30-second `demo.py` of the rules: people should see the film itself. `demo.py` renders all of it at 1280×536 with a million stars, frame by frame, with `pycoder.host.screen_video.FrameWriter` and `film_grand.wav`. It takes minutes and up to 150 MB is fine, so run it as a background job, keep `PROGRESS.md` current and don't wait in `run_python`. Check its result: no error, about 4200 frames, 140 seconds, `sound_seconds` 140. Then `REPORT.md`, with frame rates by shot, the shadow table, and what's left for a person to judge.

**Stretch, only when all of that is done:** a spin picker in free flight; lens flare as the fall begins.

---

# Part 1: the hole

Units: the hole's mass M = 0.5, so a hole with no spin has its horizon at radius 1. y is the spin axis, and the disk lies in the plane y = 0, turning the way φ = atan2(z, x) increases. The spin s = 0.6, and a = s·M.

- z1 = 1 + (1 − s²)^(1/3) · ((1 + s)^(1/3) + (1 − s)^(1/3)), z2 = √(3s² + z1²)
- Horizon r₊ = M(1 + √(1 − s²)). Innermost stable orbit R_in = M(3 + z2 − √((3 − z1)(3 + z1 + 2·z2))). `kerr(s)` returns (a, r₊, R_in).
- For the stars, which move in a simpler pseudo-Newtonian pull: r_g = R_in/3. Below R_min = 0.73·R_in matter is gone.
- A circular orbit at cylindrical radius R: r = √max(R² − a², r₊²), Ω = √M / (r√r + a√M).

Time, for someone not turning with the hole at `r` and elevation `el`: with c² = sin²(el), Δ = r² − r + a², A = (r² + a²)² − a²Δ(1 − c²), `time_factor` = √(A / ((r² + a²c²)Δ)), taking r at least r₊·1.0000001.

# Part 2: the kernels

## 2.1 The file

`kernels.metal` has placeholder words that `Engine` replaces before compiling: `DENSITY_N` (the star count, as `12345.0`), `TEMP_K` (10500.0), `BLOOM` (0.350), `SMEAR` (0.0060), `SPIN_A`, `HORIZON`, `ISCO` (from `kerr`, six decimals). At the top, as `constant float`: M, a, r₊, R_in, r_g, R_min. The compiled library's every function name becomes a pipeline.

Structures, whose layout `Engine` must match byte for byte:

- `P`, a star: `float4 pos; float4 vel;`
- `S`, a step: `float dt; uint frame; float span; uint grid;`
- `I`, a drop: `float2 at; uint first; uint count; float spread; uint seed; float2 pad;`
- `C`, a camera: `float4 eye, right, up, fwd; uint2 size; uint grid; float span; float time; float frameno; float2 shift; float2 jit;` Metal rounds this to 112 bytes, so send 112.
- `T`, the tone: `float exposure; float fade; float aspect; uint frame; float4 ship; float light; float3 pad;` The pad is never read, and 48 bytes are enough.
- `B`, a blur: `float2 step; float2 pad;`

Samplers: `lin` normalized, clamp to edge, linear. `wrap` repeats in s, clamps in t, linear. `wrapfine` repeats in s, mirrored repeat in t, linear.

## 2.2 Noise

- `rnd(uint n)`: n = (n<<13) ^ n, then n = n·(n·n·15731 + 789221) + 1376312589, all wrapping uint; return (n & 0x7fffffff) / 2147483647.
- `h31(float3 p)` = fract(sin(dot(p, (127.1, 311.7, 74.7))) · 43758.5453).
- `vn(float3 x)`: value noise, trilinear between `h31` at the 8 corners of floor(x), with f = fract(x), f = f²(3 − 2f).
- `fbm(p)`: 4 octaves: amplitude from 0.5 halving, summing amplitude·vn(p), then p = 2.03p + (3.1, 1.7, 2.3).
- `flow(R, φ, Ω, time, period)`, noise carried along the orbits that never winds up into rings: two copies, each restarted, crossfaded. A = fract(time/period), B = fract(time/period + 0.5), w = |2A − 1|. φa = φ − Ω·A·period, φb = φ − Ω·B·period. l = ln R, k = 24·l.
  - bend_a = (vn(1.7cos φa, 1.7sin φa, 2.4·l) − 0.5)·14 + (vn(4.3cos φa + 7, 4.3sin φa + 7, 5·l + 7) − 0.5)·5
  - bend_b = (vn(1.7cos φb, 1.7sin φb, 2.4·l + 9) − 0.5)·14 + (vn(4.3cos φb + 3, 4.3sin φb + 3, 5·l + 3) − 0.5)·5
  - result = mix(fbm(k + bend_a, 3.6cos φa, 3.6sin φa), fbm(k + bend_b + 17, 3.6cos φb, 3.6sin φb), w)

Radius is bent by slow noise and azimuth runs at 3.6: with azimuth any lower, the disk breaks into concentric rings.

## 2.3 Colour

`planck(T)`, a black body through red, green and blue relative to a white at 6500 K: λ = (0.61, 0.55, 0.45) microns. b = 1 / (λ⁵(exp(14388/(λT)) − 1)), w is the same at 6500, c = b/w, and return c / max(c.g, 1e-6).

## 2.4 Baked once

- `bakesky`, 2048×1024: uv = (pixel + 0.5)/size, θ = (uv.x − 0.5)·2π, ϕ = uv.y·π, v = (sin ϕ cos θ, cos ϕ, sin ϕ sin θ). Colour = (0.10, 0.13, 0.24)·fbm(3.1v + (4, 1, 2))³·0.20 + (0.16, 0.08, 0.09)·fbm(5.7v)⁴·0.18.
- `bakefine`, 4096×1024: θ = 2π·uv.x, ring = (cos θ, sin θ). bend = (vn(2.2·ring, 7·uv.y) − 0.5)·9. Value = 0.65·fbm(7·ring, 70·uv.y + bend) + 0.35·fbm(19·ring.x + 5, 19·ring.y + 5, 190·uv.y + 2·bend + 5), written to all channels.

## 2.5 The stars

- `pstep`, for each star: r = |x|. If r < R_min or r > span, it starts again: angle = rnd(i + frame·7)·6.2832, R = 8 + rnd(i·3 + frame)·5.5, x = (R cos, 0, R sin), speed = √(0.5R)/(R − r_g)·0.985, v tangent = (−sin, 0, cos)·speed, r = R. Then v += −(x/r)·0.5/(r − r_g)²·dt, v *= 1 − 0.004·dt, x += v·dt.
- `inject`, for k in 0..count: star i = first + k. angle = rnd(3k + seed)·6.2832, d = √(−2·ln max(rnd(7k + seed), 1e-5))·spread·0.5, q = at + d·(cos, sin), R = max(|q|, 2.6), speed = √(0.5R)/(R − r_g)·0.9, position (q.x, 0, q.y), velocity tangent (−q.y, q.x)/R·speed.
- `clear`: every cell of an atomic uint grid to 0. `deposit`: cell = floor((pos.xz/span·0.5 + 0.5)·grid), skip if outside, atomically add 1.
- `smooth`, into a float grid: weights 4 at the centre, 2 at the four sides, 1 at the corners, over 16, with x and y clamped to 1..grid−2 for the lookup. The grid is 512: at 2048, shot noise in the grid is drawn out by grazing light into slanted stripes.

## 2.6 The disk's map

`diskmap`, into a 2048×2048 texture: xz = ((pixel + 0.5)/2048·2 − 1)·span, R = |xz|. Density 0, unless R_min < R < span. There: scale = (2000000/N)·(grid/1024)². n = the mean of 5 bilinear lookups in the float grid (lookup coordinate (xz/span·0.5 + 0.5)·grid − 0.5, 0 outside), at xz rotated by a·SMEAR radians for a = −2..2, times scale. cloud = smoothstep(0.30, 0.68, flow(R, atan2(xz.y, xz.x), Ω(R), time, 14)). edge = smoothstep(0.973R_in, 1.017R_in, R)·(1 − smoothstep(7.5, 13.8, R)). Density = (1 − exp(−0.22n))·(0.32 + 1.45·cloud)·edge.

## 2.7 Starting a ray

`trace(at, pixel)`: uv = (at − size/2)/size.y − shift, p = eye, d = normalize(fwd + uv.x·right − uv.y·up). `col` = 0, `through` = 1.

**Far from the hole** light hardly bends, and that little is known exactly, so don't march it. REACH = 24. h² = |p × d|², b = √h², r0 = |p|, cosStart = −p·d/r0, towards = −normalize(p − (p·d)d).

- b ≥ REACH: d = normalize(d + towards·(cosStart + 1)/b), and no marching.
- r0 > REACH and b < 0.01: p += d·(r0 − REACH), then march.
- r0 > REACH, cosStart > 0: jump = −p·d − √(REACH² − h²), p += jump·d, d = normalize(d + towards·(cosStart − √(1 − h²/REACH²))/b), then march.
- r0 > REACH otherwise: leaving, d = normalize(d + towards·(cosStart + 1)/b), and no marching.
- Otherwise march from where it is.

**Into the hole's coordinates, as seen by someone not turning with it.** The ray starts at p, going along d. From p: w² = |p|² − a², r = √(0.5(w² + √(w⁴ + 4a²p.y²))). c = clamp(p.y/r, −1, 1), s = √max(1 − c², 1e-6), ρ = max(√(p.x² + p.z²), 1e-5), cp = p.x/ρ, sp = p.z/ρ, W = √(r² + a²).

- e_r = normalize(r/W·s·cp, c, r/W·s·sp), e_θ = normalize(W·c·cp, −r·s, W·c·sp), e_φ = (−sp, 0, cp). n_r, n_θ, n_φ are d's parts along them.
- Σ = r² + a²c², Δ = max(r² − 2Mr + a², 1e-7), A = (r² + a²)² − a²Δs².
- α = √(ΣΔ/A), ω = 2Mar/A, X = √(A/Σ)·s, den = α − n_φ·X·ω.
- If den ≤ 1e-5, this light couldn't have come from outside (inside the ergoregion only): the pixel is the hole.
- λ = −n_φ·X/den is the photon's angular momentum per unit of energy. The sign is because the photon really travels against d. e = (1 − ωλ)/α.
- r' = e·n_r·√(ΣΔ), θ' = e·n_θ·√Σ, q = θ'² + c²(λ²/s² − a²) is Carter's constant, K = q + (λ − a)².
- The direction is a unit vector, because angles break down at the axis: n = (s·cp, c, s·sp), its rate v = θ'·(c·cp, −s, c·sp) − (λ/s)·e_φ.

## 2.8 The march

Mino time, in which the hole's equations come apart. Up to 260 steps; a ray still winding round when they run out is the hole. Each step:

1. If r < r₊·1.0002, or r < r₊·1.002 and r' < 0: it fell in.
2. If r > REACH and r' > 0: it got away. With d the unit direction of its last step, tw = −normalize(p − (p·d)d), cc = p × d: d = normalize(d + tw·(1 − √max(1 − |cc|²/|p|², 0))/max(|cc|, 0.1)), and stop.
3. Step size: Δ0 = max(r² − 2Mr + a², 1e-6), vv = v·v, turn = a − a(r² + a² − aλ)/Δ0. dl = min(0.14/r, max(0.25Δ0/(r² + a²), 0.0004), 0.25/max(√vv + |turn|, 1e-3)). So it never goes far round in one step.
4. Half a step, a whole one, half a step: r_m = r + r'·dl/2, n_m = normalize(n + v·dl/2), c_m = n_m.y, Δ_m = max(r_m² − 2Mr_m + a², 1e-6).
   - r'' : r' += 0.5·(4r_m(r_m² + a² − aλ) − (2r_m − 2M)K)·dl.
   - On the sphere: v_new = v + (−vv·n_m + a²c_m((0, 1, 0) − c_m·n_m))·dl, then remove its part along n_m.
   - The hole drags the light round the axis: angle τ = (a − a(r_m² + a² − aλ)/Δ_m)·dl. Rotate n_m and v_new by τ: x' = x cos τ − z sin τ, z' = x sin τ + z cos τ.
   - r = r_m + r'·dl/2, n = normalize(n_m + v_new·dl/2), v = v_new.
5. **The steps only decide which way it's going; how fast is known exactly, so errors can't build up.** R = (r² + a² − aλ)² − (r² − 2Mr + a²)K: if R > 0, r' = ±√R keeping its sign. And v *= √(max(q + λ² + a²n.y², 1e-8)/max(v·v, 1e-8)).
6. New position: W = √(r² + a²), Q = (W·n.x, r·n.y, W·n.z). Direction d = normalize(Q − p).
7. If through > 0.015 and p.y·Q.y < 0, it crossed the disk's plane: Part 2.9.
8. p = Q.

If it wasn't the hole, add the sky (Part 2.10).

## 2.9 Through the disk

One integration at each crossing, nearest part first, so the cost is bounded however grazing the ray is. Per frame, from the eye's distance E = |eye|: closeby = 1 − smoothstep(16, 60, E), veryclose = 1 − smoothstep(9, 24, E), opaque = 0.9 + 2.6·veryclose. A per-pixel offset, different each frame: g = pixel + 5.588238·(frameno mod 64), jitter = fract(52.9829189·fract(g·(0.06711056, 0.00583715))).

At the crossing: centre = mix(p, Q, p.y/(p.y − Q.y)), Rc = cylindrical radius of it, thin = 1 − 0.6·veryclose, band = 3.2·thin·(0.008Rc + 0.005Rc²/13), reach = min(band/max(|d.y|, 0.03), 0.35Rc + 0.2), samples = 5 + int(7·veryclose), seg = 2·reach, ds = seg/samples.

For j in 0..samples, stopping once through < 0.015: m = centre + d·(−reach + seg·(j + jitter)/samples), R = cylindrical radius. Skip if R < R_min or R > span. h = thin·(0.008R + 0.005R²/13), it flares towards the rim. vert = exp(−0.5(m.y/h)²); skip if vert < 0.02. rho = disk texture at (m.xz/span·0.5 + 0.5), with `lin`, times vert.

**Fine threads, only if closeby > 0.01**, carried with the orbits and restarted so they never wind up:

- Ω = Ω(R), ϕ = atan2(m.z, m.x)/2π, v = ln(R/R_min)/ln(span/R_min). pa = fract(time/9), pb = fract(time/9 + 0.5), wf = |2pa − 1|. ua = (ϕ − Ω·pa·9/2π, v), ub = (ϕ − Ω·pb·9/2π + 0.37, v).
- threads = mix of the fine texture at ua and ub by wf, with `wrap`.
- How much of the disk one pixel covers, because detail smaller than that only shimmers: pixel = |m − eye|/(size.y·|fwd|)/max(|d.y|, 0.02). Nor can detail finer than the steps along the ray be seen: pixel = max(pixel, ds·√(d.x² + d.z²)).
- keep0, keep1, keep2 = 1 − smoothstep(0.5, 1.4, pixel/(R·w)) with w = 0.026, 0.0044, 0.0016.
- rho *= mix(1, 0.25 + 1.9·smoothstep(0.28, 0.72, threads), closeby·keep0).
- If veryclose > 0.01: finer = mix of the fine texture at ua·(2, 6) and ub·(2, 6) by wf, with `wrapfine`. finest = fine texture at ua·(3, 17) + 0.3, with `wrapfine`. rho *= mix(1, 0.5 + 1.15·smoothstep(0.30, 0.70, finer), veryclose·keep1)·mix(1, 0.75 + 0.55·smoothstep(0.32, 0.68, finest), veryclose·keep2).

**The light.** A thin disk's temperature: T = TEMP·(R_in/R)^0.75·max(1 − √(R_in/R), 0.0004)^0.25. The exact shift for light from a circular orbit, with the photon's own angular momentum: r_e = √max(R² − a², r₊²), o = r_e√r_e + a√M, Ω_e = √M/o, u^t = o/(√(r_e√r_e)·√max(r_e√r_e − 3M√r_e + 2a√M, 0.01)), g = 1/(u^t·max(1 − Ω_e·λ, 0.08)).

hot = T/(0.49·TEMP). emit = hot^3.4·g³·(0.22 + 1.5·smoothstep(0.05, 1.25, rho/max(vert, 0.05))). tau = rho·ds/h·0.28. **took = 1 − exp(−tau·opaque)**: what a step gives is limited by what it can absorb, however long the step. col += through·planck(T·g)·emit·(4.4/0.9)·took. through *= 1 − took.

The red inner rim comes from this: on the far side T falls towards 0 at R_in and g is about 0.33, so what's seen is about 1000 K. The near side there is about 7000 K, white.

## 2.10 The sky

v = normalize(d), cell = floor(300v), f = fract(300v) − 0.5, h = h31(cell). star = step(0.9925, h)·(1 − smoothstep(0.05, 0.42, |f|))·fract(97h)³·3.5, colour mix((1, 0.8, 0.65), (0.7, 0.82, 1), fract(53h)). sky uv = (atan2(v.z, v.x)/2π + 0.5, acos(clamp(v.y, −1, 1))/π), with `wrap`. col += through·(colour·star + sky).

## 2.11 One pixel

`render`, writing to the HDR texture: at = pixel + 0.5 + jit, uv and ray as in 2.7, pix = |eye|/(size.y·|fwd|).

The photon ring is thinner than a pixel. Find how far this ray is from the critical one. Start the ray from the eye as in 2.7, without the far handling, for λ and K. Find the top of the barrier light must pass, by 4 Newton steps from r_c = 2, kept ≥ r₊: f = 4r_c(r_c² + a² − aλ) − (2r_c − 1)K, f' = 12r_c² + 4(a² − aλ) − 2K (dividing by max(f', 1e-3)). Then Δ_c = max(r_c² − r_c + a², 1e-4), top = r_c² + a² − aλ, off = −(top² − Δ_c·K)/(2√max(K, 1e-4)·Δ_c).

If the start was real and −2·pix < off < 0.02 + 2·pix, take 8 rays evenly spaced across the ring, since its width is what's thin, over the neighbours too. across = normalize(at − size/2 − shift·size.y + (0.001, 0)), along = its perpendicular. For i in 0..8: t = 2·fract((i + 0.5)/8 + frameno·0.6180340) − 1, weight 1 − |t| + 0.02, offset across·1.4t + along·(fract(0.7548777i + 0.3819660·frameno) − 0.5). Average `squeeze(c) = c/(1 + c·(0.3, 0.5, 0.2))`, by weight, and undo it: col = avg/max(1 − avg·(0.3, 0.5, 0.2), 0.02). Otherwise one ray.

## 2.12 After the rays

- `accumulate(now, before, out, keep)`: c = now's pixel. lo and hi are the min and max of c and now's pixels 2 away in x and in y, clamped to the edges. h = before's pixel clamped to lo − (hi − lo)/2 .. hi + (hi − lo)/2, so what has really changed isn't kept as a ghost. out = mix(c, h, keep). Use `read` access.
- `bright`, at quarter size: c sampled with `lin`, l = max of its channels, out = c·smoothstep(1.2, 3.0, l).
- `blur`: the sum for i in −16..16 of s(uv + step·i)·exp(−i²/90), over the sum of weights.
- `compose(hdr, b1, b2, streak, out buffer, T)`, at full size, into a buffer of 4 bytes a pixel: uv = (pixel + 0.5)/size, c = uv − 0.5.
  1. All textures here are read with `lin`. A little colour fringe: h = (hdr(uv + 0.0007c).r, hdr(uv).g, hdr(uv − 0.0007c).b).
  2. x = h + b1(uv)·0.10·BLOOM + b2(uv)·0.12·BLOOM + streak(uv)·(0.5, 0.68, 1.0)·0.10·BLOOM.
  3. ACES: x *= exposure, x = clamp(x(2.51x + 0.03)/(x(2.43x + 0.59) + 0.14), 0, 1).
  4. l = x·(0.2126, 0.7152, 0.0722). x = clamp(mix(l, x, 0.94), 0, 1). x = x^0.4545. x = mix(x, x²(3 − 2x), 0.6). x += (1 − l)⁶·(0, 0.010, 0.018).
  5. a = c·(size.x/size.y, 1). **The ship**, if ship.w > 0: q = (a − ship.xy)/ship.z, rotated by 0.12 radians: q = (q.x cos − q.y sin, q.x sin + q.y cos). With the box distance sbox(p, b) = |max(|p| − b, 0)| + min(max(|p.x| − b.x, |p.y| − b.y), 0), d is the smallest of: hull at the centre, half-size (1, 0.07). An arm at (−0.55, 0), half-size (0.03, 0.32). Two pods at (−0.55, ±0.32), half-size (0.26, 0.05). Engines at (0.82, 0), half-size (0.16, 0.13). x *= 1 − ship.w·(1 − smoothstep(0, 0.012, d)). **The tail light:** lamp = 0.8/(size.y·max(ship.z, 1e-4)), lq = q − (0.98, 0). x += (1, 0.2, 0.12)·light·ship.w·0.55·exp(−lq·lq/max(0.0016, lamp²)).
  6. Vignette: x *= 1 − 0.5·smoothstep(0.35, 1.15, |a|). Grain, so slight it can't flicker: x += (rnd(pixel.x + pixel.y·4093 + (frame/2)·7919) − 0.5)·0.006·(0.35 + l).
  7. x = clamp(x·fade, 0, 1)·255, stored as bytes in the order b, g, r, 255.
- `show(buffer, size, drawable texture)`: to the screen's own pixels, as the layer's own scaling blurs. at = (pixel + 0.5)·size/texture size − 0.5, f = fract(at), b = floor(at). Catmull-Rom over 4×4 buffer pixels, clamped to the edges, with weights w0 = f(−0.5 + f(1 − 0.5f)), w1 = 1 + f²(−2.5 + 1.5f), w2 = f(0.5 + f(2 − 1.5f)), w3 = f²(−0.5 + 0.5f). The buffer holds b, g, r: write r, g, b to the texture, clamped to 0..1.

# Part 3: the engine

## 3.1 The helpers

- `MTLSize`: a ctypes structure of three `c_ulong`.
- `GPU`: the device from `MTLCreateSystemDefaultDevice` in `ctypes.CDLL('/System/Library/Frameworks/Metal.framework/Metal')` (restype `c_void_p`, wrapped in `ObjCInstance`). `newCommandQueue`. `compile(source)` with `newLibraryWithSource_options_error_` and a `ctypes.byref(c_void_p(0))` for the error, then a function and a compute pipeline for each of `functionNames`, kept by name; raise with `localizedDescription` if it fails. Release each result once. `buffer(array)`: `newBufferWithBytes_length_options_`, returning the buffer and a numpy view over `contents()`, using `getattr(pointer, 'value', pointer)` for the address.
- `Pool`: a context manager. `ctypes.CDLL('/usr/lib/libobjc.A.dylib')`, `objc_autoreleasePoolPush` with restype `c_void_p`, `objc_autoreleasePoolPop` with argtypes `[c_void_p]`, restype None.
- Dispatching a kernel: set the pipeline, `setBytes_length_atIndex_` for bytes and `setBuffer_offset_atIndex_` for buffers, by position, `setTexture_atIndex_` by position, and `dispatchThreads_threadsPerThreadgroup_` with `MTLSize(*grid)` and `MTLSize(min(threadExecutionWidth, grid[0]), 1, 1)`, passing `argtypes=[MTLSize, MTLSize], restype=None`.

## 3.2 The engine's state

`Engine(width, height, count, seed=3, grid=512, temp=10500.0, bloom=0.35, smear=0.006)`. SPAN = 14.

- Stars, from a numpy generator with this seed: radius uniform in R_in..13, angle uniform 0..6.2832, position (R cos, 0, R sin), speed √(0.5R)/(R − R_in/3), velocity (−sin, 0, cos)·speed, as float32, eight numbers each.
- Buffers: the stars, a uint grid and a float grid, 512² each.
- Textures: format 115 (RGBA16Float), usage 3 (read and write): map 2048², sky 2048×1024, fine 4096×1024. Bake the last two once.
- **Sizes:** `resize(w, h)` rounds both down to even numbers and keeps a set for each size, made the first time it's asked for: the output buffer of h×w×4 bytes with its numpy view `pixels`, an HDR texture, two history textures, and at a quarter of the size `bright`, `tmp`, `tmp2`, `b1`, `b2`, `streak`. Changing size clears `last_eye`. `base` and `far` both start as the first size.
- `auto` = 1, `frame_no` = 0, `time` = 0, `next_inject` = 0, a list of pending drops under a lock. `drop(x, z, spread, share)` queues `(x, z, spread, int(N·share))`.
- `warm(frames, dt=0.05)` runs `pstep` alone, one command buffer each, waiting.

## 3.3 One frame

`draw(cam, dt, fade=1, ship=(0,0,1,0), light=0, yaw=0, pitch=0, show=None)`:

1. `time += dt`. Camera vectors, kept as `last_camera` with `cam`, for tapping.
2. moved = |eye − last_eye|/max(dist, 1), or 9 if there's no last eye (a cut, or a jump, starts the history again). Keep the eye.
3. While little moves on screen, far away or with the camera nearly still, more frames can be kept, each looking through a slightly different point of its pixels. slowly = clamp((0.2 − moved/max(dt, 1/120))/0.1, 0, 1) if dist > 18, otherwise 0. calm = max(clamp((dist − 25)/20, 0, 1), slowly). jit = calm·(entry frame_no mod 16 of a table: for i in 1..16, (halton(i, 2) − 0.5, halton(i, 3) − 0.5), where halton(i, base) writes i in that base and mirrors its digits about the point: f = 1, x = 0; while i: f /= base, x += f·(i mod base), i = i div base).
4. Pack `C`, `S`, `T`. `C`'s `frameno` is frame_no mod 64. `T`'s exposure is cam's exposure·auto.
5. One command buffer, one encoder, in this order:
   - each pending drop: first = next_inject, next_inject = (first + count) mod max(1, N − count), `inject` over count with seed frame_no·31 + 7;
   - `pstep` over N; `clear` over grid²; `deposit` over N; `smooth` over grid×grid; `diskmap` over 2048²;
   - `render` over the size, with textures (hdr, map, sky, fine), and `C` at buffer index 1;
   - keep = 0 if moved > 0.12, otherwise exp(−max(dt, 1/120)/(0.045 + 0.13·calm)); `accumulate` from hdr and the older history into the newer, then swap them;
   - at quarter size, with `step` = (x/QW, y/QH): `bright` from the newer; `blur` (0.6, 0) bright→tmp; (0, 0.6) tmp→b1; (1.6, 0) b1→tmp; (0, 1.6) tmp→b2; (0.8, 0) bright→tmp; (3, 0) tmp→tmp2; (9, 0) tmp2→streak;
   - `compose` at full size; if `show`: `show` over the drawable texture's own size.
6. `frame_no` += 1. With `show`: `presentDrawable_`, commit, return 0 without waiting. Otherwise commit, wait, raise on `error()`, and return `GPUEndTime − GPUStartTime`.

`adapt(dt, target=50, rate=1.4)`, a camera's auto exposure: seen = the mean of `pixels[::16, ::16, :3]`. If seen > 2: auto = clamp(auto·exp(ln(target/seen)·min(1, dt·rate)), 0.22, 1.5).

# Part 4: the film

## 4.1 The camera

`camera_vectors(c, yaw, pitch)`: orbit = c.orbit + yaw, el = clamp(c.el + pitch, ±1.45), D = c.dist. D is the hole's own r: its surfaces of equal r are flattened, so W = √(D² + a²) and eye = (W cos el cos orbit, D sin el, W cos el sin orbit). fwd = normalize(eye) if the shot looks back, otherwise −normalize(eye). right = normalize(fwd × (0, 1, 0)), up = right × fwd. Roll: right' = right cos + up sin, up' = up cos − right sin. fwd' = fwd·focal.

## 4.2 The shots

Each act is one unbroken move, and it only cuts where the music turns. Keys, for `(time, dist, orbit, el, roll, focal, exposure, sx, sy)`:

| Act | t | dist | orbit | el | roll | focal | exposure | sx | sy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| The approach | 0 | 160 | 0.0 | 0.02 | 0 | 1.9 | 0.72 | 0 | 0 |
| | 14 | 90 | 0.35 | 0.03 | 0 | 3.0 | 0.76 | 0 | 0 |
| | 28 | 52 | 0.75 | 0.06 | 0 | 3.1 | 0.80 | 0 | 0 |
| | 40 | 30 | 1.25 | 0.10 | 0 | 3.0 | 0.82 | 0 | 0 |
| The organ opens: down to the edge, up over it | 40 | 26 | 1.25 | 0.014 | 0.10 | 1.45 | 0.82 | 0.05 | 0.02 |
| | 47 | 22 | 1.60 | 0.03 | 0.08 | 1.3 | 0.80 | 0.04 | 0.015 |
| | 54 | 20 | 2.25 | 0.30 | 0.05 | 1.2 | 0.78 | 0.02 | 0.008 |
| | 60 | 18 | 2.85 | 0.68 | 0.02 | 1.12 | 0.76 | 0 | 0 |
| | 66 | 16 | 3.35 | 0.85 | 0 | 1.05 | 0.74 | 0 | 0 |
| Everything playing: a push in, a run along the disk, and out | 66 | 36 | 4.0 | 0.10 | 0 | 3.0 | 0.8 | 0 | 0 |
| | 72 | 19 | 4.1 | 0.09 | 0.03 | 1.7 | 0.82 | 0 | 0 |
| | 78 | 12.5 | 4.35 | 0.075 | 0.12 | 0.95 | 0.85 | 0.03 | 0 |
| | 85 | 11.0 | 5.4 | 0.062 | 0.20 | 0.80 | 0.88 | 0.05 | 0 |
| | 92 | 12 | 6.25 | 0.09 | 0.14 | 0.85 | 0.86 | 0.02 | 0 |
| | 100 | 13.5 | 6.75 | 0.13 | 0.08 | 0.92 | 0.84 | 0 | 0 |
| | 108 | 15 | 7.2 | 0.17 | 0.03 | 1.0 | 0.82 | 0 | 0 |
| The last climb, the turn back, the fall | 108 | 9.5 | 1.8 | 0.50 | 0 | 0.78 | 0.74 | 0 | 0 |
| | 115 | 15 | 2.35 | 0.32 | 0 | 0.95 | 0.78 | 0 | 0 |
| | 122 | 22 | 2.95 | 0.14 | 0.02 | 1.3 | 0.84 | 0 | 0 |
| | 127 | 7.0 | 3.2 | 0.11 | 0.12 | 0.85 | 0.95 | 0 | 0 |
| | 130 | 2.6 | 3.35 | 0.10 | 0.25 | 0.46 | 1.1 | 0 | 0 |
| | 131 | 1.7 | 3.42 | 0.10 | 0.34 | 0.30 | 1.3 | 0 | 0 |
| Inside, **looking back** | 131 | 1.7 | 3.42 | 0.14 | 0 | 0.42 | 1.1 | 0 | 0 |
| | 135 | r₊·1.0005 | 3.5 | 0.14 | 0.5 | 0.42 | 1.6 | 0 | 0 |

The cuts are at 40, 66, 108 and 131. `cam_at(t)` takes the latest act that has begun, and clamps t to its keys.

**Between keys**, a curve whose acceleration never jumps, so that no key can be felt. Work with ln(dist), and exp it at the end. For each act and each value, the slopes m at the keys solve a tridiagonal system. With h_i the gaps between keys:

- first row: 2m₀ + m₁ = 3(y₁ − y₀)/h₀; last row: m_(n−1) + 2m_n = 3(y_n − y_(n−1))/h_(n−1).
- each inner row: h_i·m_(i−1) + 2(h_(i−1) + h_i)·m_i + h_(i−1)·m_(i+1) = 3(h_i(y_i − y_(i−1))/h_(i−1) + h_(i−1)(y_(i+1) − y_i)/h_i).
- With two keys, both slopes are the straight line's. Solve once per act with `numpy.linalg.solve`.
- Then Hermite: with u = (t − t₁)/h, y = (2u³ − 3u² + 1)y₁ + (u³ − 2u² + u)h·m₁ + (−2u³ + 3u²)y₂ + (u³ − u²)h·m₂.

## 4.3 Timed things

- **Disk's clock:** the disk's `dt` is multiplied by a factor interpolated through (0, 0.7), (40, 1.0), (66, 1.3), (78, 1.8), (92, 1.0), (108, 1.6), (122, 2.4).
- **The rumble,** only in the fall. size = interpolated through (124, 0), (128, 0.002), (132, 0.005). noise(t, seed): i = floor t, u = t − i, A and B = (sin(n·12.9898 + seed·78.233)·43758.5453) mod 1 for n = i, i + 1. Value = 2(A + (B − A)·u³(u(6u − 15) + 10)) − 1. yaw = size·(noise(5t, 1) + 0.5·noise(11t, 2)), pitch = size·(noise(6t, 3) + 0.5·noise(13t, 4)).
- **Flares, matter falling as the music calls,** `(t, radius, angle)`: (44, 6.5, 0.9), (56, 8.0, 3.4), (68, 5.5, 5.2), (72, 7.0, 1.0), (79, 6.0, 4.8), (83, 8.0, 2.6), (87, 5.0, 0.5), (94, 6.5, 2.0), (98, 7.5, 4.2), (102, 5.5, 0.2), (110, 6.0, 3.0), (114, 8.0, 5.6), (118, 5.0, 1.6). Each as `drop(radius cos, radius sin, 1.1, 1/140)` when t passes it.
- **The ship,** `(x, y, size, opacity)`, in units of the height. From 22 to 39: u = (t − 22)/17, (−0.95 + 1.2u, 0.08 − 0.05u, 0.009, min(1, (t − 22)/1.5, (39 − t)/1.5)). From 93 to 107: u = (t − 93)/14, (0.85 − 1.45u, −0.17 + 0.05u, 0.016 + 0.006u, min(1, t − 93, 107 − t)). Otherwise (0, 0, 1, 0).
- **Its light:** on while (0.8t) mod 1 < 0.14.
- **Fade:** clamp((t − 2.5)/3.5, 0, 1) before 135, then 0. FILM_END = 140.
- **Words,** `(start, end, text, x, y, style, size)`, centred, as fractions of the picture, with alpha min(1, (t − start)/1.4, (end − t)/1.2):
  - 8 to 15: `EVENT HORIZON`, at 0.5, 0.80, TITLE, 62.
  - 135.5 to 139.5: `Time stops at the edge.`, at 0.5, 0.46, LINE, 44.
  - 136.5 to 139.5: `TWO MILLION STARS  ·  REAL GRAVITY  ·  PYTHON AND METAL, ON THIS DEVICE`, at 0.5, 0.56, SMALL, 17.
- **The clock,** from 128 to 135, `1 second here  =  {time_factor(dist, el):.1f} seconds on Earth`, at 0.80, 0.92, NOTE, 22, alpha min(1, t − 128). Farther out time is only a few percent slower, which is true and looks wrong, so it starts with the fall.

# Part 5: playing it

## 5.1 Choosing the picture

- `QUALITIES` = (1920, 804, 2 million), (1280, 536, 1 million), (1120, 468, 750 thousand), (960, 402, 500 thousand).
- `pick_engine(budget=0.03)`: for each in turn, an engine, `warm(30)`, 6 draws of `cam_at(128)`, the slowest kind of shot, at `dt=1/30`; keep the first whose median fits the budget, and the last whatever it takes. Keep the median as `measured`. Drop the others.
- `play`: `build_music()` if sound is on; close the last film (`shut_down`, close on the main thread, sleep 0.5); pick; `warm(150)`.
- `across` = max(engine.W, int(the view's width in points × screen scale)). On a phone the width is `max(window)`, otherwise `window[0]`.
- `pick_far(engine, across, budget=0.026)`: far shots cost little, so they can have more pixels. For width in across, then across·3//4, while wider than base: resize, 5 draws of `cam_at(39)`, and if the median fits, that's `engine.far`, and stop. Back to base.

## 5.2 The window

A `ui.View` of the window's size, `flex='WH'`, presented `'fullscreen'` with `hide_title_bar=True`, and on a phone (`min(ui.get_screen_size()) < 500`) also `orientations=['landscape']`, with its buttons 62 points in from each side to clear the camera housing, otherwise 14. Black behind.

The picture: first `load_framework('QuartzCore')` from `objc_util`, or there is no such class. `ObjCClass('CAMetalLayer').layer()`, `setDevice_` the engine's device, `setPixelFormat_(80)` (BGRA, 8 bits), `setFramebufferOnly_(False)`, because a kernel writes to its textures, `setDrawableSize_(CGSize(across, across·H//W), argtypes=[CGSize], restype=None)`. `setFrame_(CGRect(...), argtypes=[CGRect], restype=None)`, as wide as the view and centred, height `width·H/W`, kept so in `layout`. `ObjCInstance(view).layer().insertSublayer_atIndex_(layer, 0)`. All of this on the main thread.

Buttons along the top, y 16: `Close` at the left, 72×34, closing the view. At the right `Free flight` 124×34, and 10 points to its left `GPU race` 104×34. Text white at 0.8, font `AvenirNext-Medium` 14, background white at 0.08, corner radius 8. In free flight the first says `Back to the film`.

Then `sound.Player(WAV)` and `play()` if the file exists, set the idle timer, keep the view in `builtins`, and start the render thread (a daemon). `play(quality=None, sound_on=True)` returns the view, and running the file as a script calls it.

## 5.3 The render thread

Each loop: stop if told to. If `on_screen` was true and now isn't, leave: a window can go by a route that never called `will_close`. If racing, sleep 0.01 and carry on. Everything else inside `with Pool():` take `layer.nextDrawable()` and carry on if None; now, dt = min(now − last, 0.05).

- **Film mode:** t = `player.current_time` if playing, otherwise time since the start. At FILM_END go to free flight, with `free_orbit=1.0, free_el=0.18, free_distance=15`. Three seconds after the finger leaves, `yaw` and `pitch` shrink by 0.97 a frame. Fire flares with t − dt < at ≤ t. Size: `far` before 40 seconds, otherwise `base`, so it changes at a cut, unseen. Draw `cam_at(t)` with `dt·factor(t)`, the fade, the ship, its light, `yaw + rumble` and `pitch + rumble`, and `show=drawable`. `adapt(dt)` only when fade > 0.3.
- **Free mode:** at `base`, `dict(dist=free_distance, orbit=free_orbit, el=free_el, roll=0, focal=1.1, exposure=0.8, sx=0, sy=0)`, always `adapt`. For 6 seconds a hint at 0.5, 0.94, NOTE, 21, alpha 0.85: `Drag to turn.  Pinch to zoom.  Tap the disk to drop matter.`
- If the race's result is due, a line at 0.5, 0.09, NOTE, 25. Count frames. Every third frame, or when the words change, put them up with `on_main_thread`.

`try ... finally: shut_down()` around the loop, so that however it ends, nothing keeps playing.

## 5.4 What a finger does

- **Toggling to free** starts from the film's camera: `free_orbit = orbit + yaw`, `free_el` = el + pitch clamped to ±1.4, `free_distance` = dist clamped to 5..18, and clears yaw and pitch.
- **Touch began:** store the finger. `moved` = 0 for the first, 99 for a second: a second finger is never a tap.
- **Touch moved** with two fingers down: before is the distance from this finger's `prev_location` to the other's last place, now from its `location`; update its place, and `zoom(before/now)` if both are over 1 point. With one: add |dx| + |dy| to `moved`, and turn by 3/width a point (free: `free_orbit`, and `free_el` clamped; film: `yaw`, `pitch`).
- **Touch ended:** note the time, remove the finger, and if `moved` < 12 it's a tap.
- **Zoom:** a pinch during the film goes to free flight first. `free_distance` stays in 4..45.
- **Tap:** aspect = W/H, picture = width/aspect. u = (x/width − 0.5)·aspect − sx, v = (y − (height − picture)/2)/picture − 0.5 − sy. ray = fwd + u·right − v·up, from the last camera. Where the straight ray meets y = 0, ahead of the eye: past radius 13 that's the sky, otherwise `drop(x, z, 0.5, 1/30)` and `drops` += 1.
- **Keys** (`get_key_commands` for `left`, `right`, `up`, `down`, space, `+`, `-`, and `key_command`): left and right turn the orbit by −0.15 and +0.15, up and down the elevation by +0.08 and −0.08 (free: `free_orbit`, `free_el` clamped; film: `yaw`, `pitch`), `+` and `-` zoom by 0.85 and 1.18, space toggles.
- **GPU race,** with `@ui.in_background`: if the result is showing, hide it and return. Otherwise pause drawing, sleep 0.1 so the GPU is timed alone, then one step of all the stars three ways. Pure Python on a copy of the first 20000, as lists, scaled up: with r² = |position|² + 0.02, velocity −= position·0.5·0.0333/(r²·r), position += velocity·0.0333. Numpy on a copy of up to a million, scaled up: velocity −= position/r·0.5/(r − 0.999)²·0.0333, position + velocity·0.0333. The best of 4 runs of `pstep` alone. The result stays until pressed again: `Moving 1 million stars once:   Python about 0.41 s    numpy 12 ms    GPU 0.8 ms    (the GPU is about 500 times faster than Python)`, with the real numbers.

## 5.5 Words

Native `ui.ImageView`s over the picture when live, never in the frame, made once for each text and with touches off. Each is drawn at twice the view's points with `ui.ImageContext(w, h, 2)`, letter by letter, so the tracking is real: measure each letter with `ui.measure_string`, and advance by its width plus tracking·size.

- Styles, as (font, tracking): TITLE `('Didot', 0.34)`, LINE `('Didot-Italic', 0.04)`, NOTE `('AvenirNext-Medium', 0.02)`, SMALL `('AvenirNext-Regular', 0.08)`.
- Sizes are for a picture 1920 wide: size·width/1920, at least 11 points. Colour (1.0, 0.98, 0.94). Padding 0.6·size at each side and 0.5·size above and below. Width = the letters' widths + tracking·size·letters + both side paddings; height = 1.35·size + both of the others.
- The title has a soft light around it: PIL `GaussianBlur(size/2.2)` of its alpha at half strength, combined by the maximum.
- The race's result has a dark rounded backing, black at 0.62, radius h/2.6, padding 0.9·size and 0.45·size.
- Place each at x·width, top + y·picture, where top = (height − picture)/2, with its alpha. Hide the ones not wanted.

For the video the same words are burned in: `put_text(pixels, text, x, y, style, size, alpha)`, at a size scaled to the frame, at least 9. The mask comes from a `ui.ImageContext` at scale 1, made once and kept, plus for the title a blur of radius max(2, size/5) at 0.55. Blend into the BGRA pixels with tint (236, 244, 250). Skip it if it would go off the frame. On the clock, alpha times 0.85.

## 5.6 Stills and the video

- `film_frame(engine, t, dt)`: what the live film does at t, without a drawable: fires flares, draws with the same arguments, adapts if fade > 0.3, burns in the words. Returns the GPU's seconds.
- `stills(times, path, width=1920, height=804, count=2_000_000)`: `warm()` of 300 steps, then for each t, 14 frames of `film_frame(engine, t, 0.2)` inside a `Pool`, so the exposure settles, and saves it, as RGB from `pixels[:, :, [2, 1, 0]]`.
- `render_film(path, start=0, end=140, width=1920, height=804, count=2_000_000)`: `FrameWriter(path, W, H, 30, audio=WAV)`, each frame `film_frame(engine, start + n/30, 1/30)` then `writer.add(engine.pixels)` inside a `Pool`, and `finish()`. Import `pycoder.host.screen_video` inside this function only.

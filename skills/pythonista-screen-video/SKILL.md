---
name: pythonista-screen-video
description: "Use when a program or demo should make a video file with sound on the device: recording a window, or writing frames it renders itself, plus a WAV as the sound track."
---

`pycoder.host.screen_video` writes an MP4 with no person involved. ReplayKit is no use unattended: it shows a system prompt, and saving goes through a preview a person taps. No ffmpeg is needed: iOS encodes the picture and the sound.

## A window, as it runs

```python
from pycoder.host import screen_video

view.present('fullscreen')
time.sleep(0.5)  # let it slide in
with screen_video.record(view, 'demo.mp4', fps=15, audio='track.wav') as recorder:
    show_the_best_parts()
print(recorder.result)  # Recording(path, frames, seconds, size, error, sound_seconds)
```

`view` is what you presented: scene shaders, SceneKit and `CAMetalLayer` inside it are all in the picture. Draw that window, not the whole screen, which slows the program far more. It keeps the view's first size, up to 1280 pixels on the long side. Frames carry their real time, so a slow frame makes the video jerky rather than fast.

## Frames you render yourself

Better when each frame is heavy, or the picture must be perfectly smooth: time is whatever you say it is, at any size.

```python
writer = screen_video.FrameWriter('film.mp4', 1920, 804, fps=30, audio='track.wav')
for n in range(900):
    render(n / 30)
    writer.add(bgra)  # a height x width x 4 numpy array of BGRA bytes
print(writer.finish())
```

## Sound

- `audio` is a 16-bit PCM WAV file, already made: synthesize it with numpy and `wave` (see `pythonista-sound-and-midi`). What the program plays while it runs isn't captured, and `sound.MIDIPlayer` can't write a file, so sound for a video can't come from MIDI.
- Sound starts with the first frame. A longer track stops with the picture; a shorter one just ends.
- To play the same track in the app and keep them together, start `sound.Player` as recording starts.

You can't hear it, but you can look: plot the STFT magnitude with matplotlib, with a log frequency axis and RMS below. It shows what a small speaker can't play (energy below about 100 Hz), beating, whether sections really enter when planned, and whether it builds. Also check `numpy.corrcoef` of left and right: near zero or negative, a phone's mono speaker cancels it. Then ask a person to listen.

## Checking the file

Check the result: no `error`, a frame count near `fps * seconds`, and `sound_seconds` as expected. A file far smaller than expected suggests the picture barely moved: use `look_at_screen` during a recording to see what it draws. Pythonista can stall in the background: keep it in front.

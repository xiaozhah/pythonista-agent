---
name: pythonista-sound-and-midi
description: "Use when a program makes sound: effects that change while playing, generated WAV files, MIDI music, or speech."
---

You can't hear it: check durations and that objects are playing, and say so. If nothing is heard, see `pythonista-audio`.

## Effects

`sound.play_effect(name, volume, pitch=1.0, pan=0.0, looping=False)` takes a built-in name or a file, and returns an `Effect` (None for an unknown name) whose `pitch`, `pan`, `volume` and `looping` can change while it plays: a looping engine note follows speed by setting `pitch` each frame. `sound.stop_effect(effect)`, `stop_all_effects()`. Generate effects with `wave` and numpy into `tempfile.gettempdir()`.

## MIDI

```python
from midiutil.MidiFile import MIDIFile

midi = MIDIFile(1, adjust_origin=True)
midi.addTempo(0, 0, 120)
midi.addProgramChange(0, 0, 0, 81)
midi.addNote(0, 0, 60, 0, 1, 100)  # track, channel, pitch, time, duration, volume
with open(path, 'wb') as f:
    midi.writeFile(f)
player = sound.MIDIPlayer(path)  # keep a reference, or it stops
player.play()
```

`player.duration`, `current_time` and `rate` are numbers you can check. For a loop, call `play()` again when `current_time` reaches the end: there is no looping attribute.

## Speech

`speech.say(text, language, rate)`, `speech.is_speaking()`, `speech.stop()`; `speech.get_synthesis_languages()` lists what is there. `speech.recognize(path, language)` turns a recording into text.

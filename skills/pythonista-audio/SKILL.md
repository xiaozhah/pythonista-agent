---
name: pythonista-audio
description: "Use when code records sound and then plays, when sound can't be heard, or to check where it goes: the earpiece, the silent switch and the output route."
---

You cannot hear what you build, and a silent program raises no error, so check where the sound goes. To make sound, see `pythonista-sound-and-midi`.

## After recording, sound goes to the earpiece

`sound.Recorder` switches the whole app's audio session to `PlayAndRecord`, which plays through the earpiece: on an iPhone it sounds as if nothing plays. It stays that way for every later program, until Pythonista quits. Before playing, send it to the speaker:

```python
from objc_util import ObjCClass, load_framework


def use_speaker():
    load_framework('AVFoundation')
    default_to_speaker = 8  # AVAudioSessionCategoryOptionDefaultToSpeaker
    ObjCClass('AVAudioSession').sharedInstance().setCategory_withOptions_error_(
        'AVAudioSessionCategoryPlayAndRecord', default_to_speaker, None
    )
```

## The silent switch

Sound follows the phone's silent switch by default. For a program whose point is sound, call `sound.set_honors_silent_switch(False)`.

## Check it without hearing it

```python
session = ObjCClass('AVAudioSession').sharedInstance()
print([str(o.portType()) for o in session.currentRoute().outputs()])  # 'Speaker', not 'Receiver'
print(float(session.outputVolume()))
```

Also check that a recording holds something: its size, and `sound.Player(path).duration`. Then tell the user this is as far as you can check, and ask them to listen.

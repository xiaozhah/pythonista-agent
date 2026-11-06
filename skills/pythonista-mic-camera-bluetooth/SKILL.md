---
name: pythonista-mic-camera-bluetooth
description: "Use when a program reads the microphone level or a recording's spectrum, takes a picture, or talks to Bluetooth LE devices; and how to handle their permission prompts."
---

## Permission

iOS asks the person the first time. See where things stand without asking: `AVCaptureDevice.authorizationStatusForMediaType_('soun')` (`'vide'` for the camera) is 0 undecided, 2 refused, 3 allowed, after `load_framework('AVFoundation')`.

Ask at a moment someone is there, saying why first. An unanswered prompt can hold the thread that asked: try a sensor from a thread with a time limit, not the main thread, and fall back to a replay (`sensor-recording-and-replay`).

## Microphone

There is no sample stream, only a file and a level:

```python
recorder = sound.Recorder(path)  # .wav or .m4a by extension
recorder.record(duration)
recorder.meters  # {'average': (-35.3, -30.1), 'peak': (-5.2, -8.2)} in dB; poll while recording
recorder.stop()
```

For a live level, poll `meters`. For a spectrum, record a short WAV to `tempfile.gettempdir()`, read it with `wave` and numpy, take `accelerate.fft` or `numpy.fft`, then delete the file. Recording moves sound to the earpiece: see `pythonista-audio`. `speech.recognize(path)` turns a file into text.

## Camera

`photos.capture_image(camera='rear')` shows the system camera and returns a PIL image, or None if cancelled. It waits for a person, so it goes behind a button, off the main thread, and tests replace it.

Live frames need `AVCaptureSession` through `objc_util`, with a delegate from `create_objc_class`. This is untested in pycoder: build it last, in small steps, and let it fail politely.

Analyse any image the same way wherever it came from: `vision-and-language` and `pythonista-objc-recipes`, tested on generated pictures.

## Bluetooth LE

`cb.set_central_delegate(delegate)`, then `cb.get_state()` must reach `cb.CM_STATE_POWERED_ON`, then `cb.scan_for_peripherals()`. The delegate's methods: `did_discover_peripheral(p)` (`p.name`, `p.uuid`, `p.state`, `p.manufacturer_data`), `did_connect_peripheral(p)`, `did_fail_to_connect_peripheral(p, error)`, `did_disconnect_peripheral(p, error)`, `did_discover_services(p, error)`, `did_discover_characteristics(s, error)`, `did_update_value(c, error)`. `cb.stop_scan()` and `cb.reset()` when done. Central role and LE only. Test the delegate by calling its methods with fakes.

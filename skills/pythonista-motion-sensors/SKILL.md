---
name: pythonista-motion-sensors
description: "Use when a program reads motion, the compass, the barometer, or device state such as battery, brightness, thermal state and proximity."
---

The accelerometer, gyroscope and magnetic field are read without asking. To keep traces of them, see `sensor-recording-and-replay`.

## Motion

`motion.start_updates()`, wait about 0.2 s, then `get_gravity()`, `get_user_acceleration()`, `get_attitude()` (roll, pitch, yaw), `get_magnetic_field()` (x, y, z, accuracy). `stop_updates()` when done. Poll from `update()` or a thread, at most about 60 times a second.

A Mac gives made-up values rather than none: a fixed gravity, zero user acceleration, and a magnetic field of `(0, 0, 0, -1)`. So magnitude doesn't tell whether a sensor exists: it is real only if readings change, or the accuracy isn't -1. For tests, replace `motion.get_gravity` with a function, and put it back afterwards.

Compass heading comes from the magnetic field and gravity. Accuracy -1 means uncalibrated: show that instead of a wrong number.

## Barometer and pedometer

There is no module. `CMAltimeter` and `CMPedometer` from CoreMotion report through blocks: read the block rule in `pythonista-objc-recipes`, since a block iOS keeps can crash the app when it isn't kept alive. iOS may ask for Motion & Fitness permission.

Check `ObjCClass('CMAltimeter').isRelativeAltitudeAvailable()` and `CMPedometer.isStepCountingAvailable()` first: both are False on a Mac. This is untested in pycoder: build it last, in a small file. Near the ground, pressure falls about 0.12 hPa a metre.

`CMMotionManager` can be polled without blocks.

## Device state

```python
from objc_util import ObjCClass

device = ObjCClass('UIDevice').currentDevice()
device.setBatteryMonitoringEnabled_(True)
device.batteryLevel(), device.batteryState()  # 0-1, 0 unknown / 1 unplugged / 2 charging / 3 full
ObjCClass('NSProcessInfo').processInfo().thermalState()  # 0 nominal to 3 critical
ObjCClass('NSProcessInfo').processInfo().isLowPowerModeEnabled()
ObjCClass('UIScreen').mainScreen().brightness()
```

`batteryLevel` isn't reliable on a Mac. On a phone, `device.setProximityMonitoringEnabled_(True)` and `proximityState()` turn the screen off when the sensor is covered: do it only when the person asks. Put back any brightness you change.

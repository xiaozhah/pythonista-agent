---
name: sensor-recording-and-replay
description: "Use when a program records sensor data, analyses it, or must work on a device lacking a sensor: one interface with a real source and a replay of a trace."
---

Each sensor sits behind one small class: a real source, and a replay of a trace. The screen says which it is showing, and a report says which really ran.

```python
class Replay:
    """A trace: rows of (seconds, values...), played back on the same clock."""

    def __init__(self, rows, clock=time.monotonic):
        self.rows, self.clock, self.start = rows, clock, clock()
        self.times = [row[0] for row in rows]

    def read(self):
        i = min(bisect.bisect(self.times, self.clock() - self.start), len(self.rows) - 1)
        return self.rows[i][1:]
```

Generate traces with a known truth, so a test checks the analysis and not only that it ran: a pendulum of a known length, a 440 Hz tone, 30 steps. Keep what a program records in the same format, so real recordings replay too.

## Recording

- Write to SQLite in batches from a thread, not a row per sample on the main thread.
- Record the time of each sample: the rate you ask for isn't the rate you get.
- Sensors stop when the app is in the background: expect gaps, and show them rather than drawing a line across.

## Analysing

- Resample to an even rate before an FFT.
- Remove the mean first, or the largest peak is at zero.
- See `accelerate-maths` for the FFT.

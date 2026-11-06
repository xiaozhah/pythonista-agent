# Tutorial: a film pycoder builds by itself

Open `run.py` and tap Run, pick a model, and look over the short form. pycoder then builds **Event Horizon** from a written
brief, in the chat where you can watch it: a 140-second film about a spinning black hole, drawn live by Metal, with an organ
score, that a finger can take over.

It stops when it has written `REPORT.md`: what it built, how it checked it, the bugs it found by running it, and what it faked
or couldn't do. It also leaves `demo.mp4`, the film itself. Each model builds in a folder of its own, `~/demos/event-horizon-haiku`
or `~/demos/event-horizon-opus`, so the two can be compared. Your settings aren't changed, nothing is pushed anywhere, and
commits use a made-up identity.

## What it's given

Almost nothing. [`1-event-horizon.md`](1-event-horizon.md) describes the film in words, formulas and numbers, with no code. It writes the
Metal kernels, the light paths in curved spacetime, the camera, the window and the touch handling itself. Only the music is given,
in [`event-horizon/`](event-horizon), so that it comes out the same: the score and the code that plays it on a synthesized organ.
[`rules.md`](rules.md) goes in front of the brief.

The music is not in this repository. The person who runs the project supplies `music.mid`, a 140-second MIDI file of a piece
they have the right to use. Without it the film runs with no sound.

## What pycoder can do with a screen

`look_at_screen` sees what is on screen, the Metal layer included. `use_screen` lists the controls and can tap, drag, type and press
keys. It calls what a finger would reach, one finger at a time, so it can't pinch, hold a press, or reach system dialogs and
other apps: the film is checked by faking those, and the report lists what still needs a person.

Code runs in the same process as pycoder, so if the film crashes the app, pycoder goes with it. `PROGRESS.md` is how it carries on: run
`run.py` again and choose Carry on.

## Adding a project

A file named `2-name.md` here is a new project: its title on the first line, a line naming its skills, and a "## Permissions"
section with a line `- name: why` for each thing it wants. A folder `name/` beside it is copied into the build first.

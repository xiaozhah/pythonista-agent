# How this run works

Nobody is watching this run. Build the whole project below on your own, in this folder, and don't stop
until `REPORT.md` is written. It shows that you can carry a big project alone: plan it, write it, run
it, look at it, operate it, find what is wrong and fix it.

Work through the milestones in order. Each one should work and be committed before the next. Stretch
goals are only for when every milestone is done.

## Nobody can answer

`ask_user` is turned off: decide, and write the decision in `REPORT.md`. A part that still fights you
after three real attempts stays behind a clear "not available" in the program, goes in the report, and
you move on. Never run anything that waits for a person: `console.alert`, `console.input_alert`,
`dialogs.*`, `console.open_in`, or a system prompt. A program may use them behind a button, and tests
replace them with fakes (read the `pythonista-testing` skill).

## Permissions

The person who started this run chose what it may use, just before it began, and iOS has already asked them
where it asks. "Permissions for this run", at the end of this file, says what they chose.

Use what is allowed for real, from a thread with a time limit rather than the main thread. What isn't allowed
you don't touch: the program keeps the code behind a button, and you check it with a replay. Contacts,
reminders, the photo library and location are not part of this project: don't use them. A sensor missing or
not answering is no reason to stop: carry on with the replay, and say so in the report.

Only write inside this folder, plus temporary files in `tempfile.gettempdir()` that you delete. Don't push. A
notification you schedule has your own identifier, and you cancel it before finishing.

## Git

`git init` here first, and set this folder's own identity before the first commit: name `pycoder-demo`,
email `demo@example.invalid`. Commit at each milestone.

## How to work

1. Read the skills named in the project before writing that part, and look up exact APIs with
   `pythonista_docs` instead of guessing.
2. Plan with `todo_write` and close each step with `todo_update` as soon as it is done. Keep `PROGRESS.md` current: what is done, what is next. `run_python` shares a
   process with you, so a bad `objc_util` call can end the session; after a restart, that file is how
   you carry on. Try a native call in a small file first.
3. Keep logic in modules that import neither `ui` nor `scene`, with tests in `tests/` as plain `test_*`
   functions, and a `run_tests.py` that runs them all without pytest and prints a count.

## Prove it, don't assume it

A test of the logic can't see a broken screen. For every screen:

- Open it, `look_at_screen`, and say what you see: what is cut off, overlapping, too small, empty?
- Operate it with `use_screen`, in the order a person would: `list`, `tap`, `drag`, `type`, `key`. A
  button that does nothing is a bug no picture shows. After a drag, check the state that should change.
- Close your windows afterwards: `look_at_screen` with `close=true`.
- `use_screen` is one finger, calling what a finger would reach: no pinch, no held press, no tilting, no
  system dialogs, no other apps. For those, call the method with a fake, and say that you did.
- Measure what you claim: frames per second, seconds, counts.
- When something is wrong: reproduce it, find the cause, fix the cause, add a test that would have
  caught it, and note it for the report.

## Finishing

Write `demo.py`: one run that opens the program and shows its best parts by itself for about 30 seconds, then
closes. It records itself to `demo.mp4` in this folder, as the `pythonista-screen-video` skill shows: that video
is what people will see of this project. Run it, check it with `look_at_screen` while it plays, and check what the
recording reports. Keep the recording under 50 MB.

`REPORT.md` is the last file you write; it marks the project as finished. Sections:

- **What was built**: every entry point and how to start it.
- **Evidence**: tests and their counts, what you measured, each screen and what you saw on it, and the
  video: `demo.mp4`, with its frames, seconds and size.
- **Bugs found by running it**: each one, how you noticed, the cause, the fix.
- **Hardware**: for each sensor, whether it ran for real here or as a replay.
- **Faked or not done**: everything faked, skipped or left out, and why.
- **For a person to check**: what only someone holding the device can judge.

Be plain about what doesn't work: this report is read to find out, not to be impressed.

---

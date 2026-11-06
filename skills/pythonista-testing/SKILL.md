---
name: pythonista-testing
description: "Use when checking a Pythonista program beyond looking at it: faking the keyboard, appex, clipboard, dialogs, sensors or the network, driving a live view or scene, testing a timer, theme or rotation."
---

Say in your report what was faked, and what only a person on a device can check.

To drive a window or a scene, see `testing-a-live-screen`.

## One process
Your code, earlier runs and pycoder itself share one Python process. Each run_python has a new `__main__`, but imported modules stay.
- A fake put on a shared module (`console.alert`, `clipboard.set`, `ui.get_ui_style`, `sys.modules['keyboard']`) stays for later runs and for pycoder. Keep the real one and put it back in `finally`.
- If a module behaves oddly (`appex` says it's in an extension, `console.alert` does nothing), suspect a fake left by an earlier test before blaming the program or the system.

## Loading the program with fakes
- Load it under another name, so its `__main__` part doesn't run: `importlib.util.spec_from_file_location('under_test', path)`, then `module_from_spec` and `spec.loader.exec_module(mod)`.
- Set fakes on that module after `exec_module`: its own `import keyboard` runs during exec, and replaces one set before. Afterwards `mod.keyboard = fake` reaches views already made, since they read the global when called.
- A default argument holds the real thing from import time (`def f(open_url=urllib.request.urlopen)`): patching the module doesn't reach it. Pass the fake in, or set it in `f.__defaults__`.
- State kept in `builtins` across re-runs: classes are defined again on each exec, so `isinstance(old, NewClass)` is False. Test by name or by what it has.
- Real data stays out of tests: fake the clipboard, contacts, photos, keychain and network. Point save files at a temp folder, or delete them, and look at the folder listing afterwards.

## Reaching what is running
- A later run_python has no reference to a window: keep one in `builtins` under a private name, or find it with `gc.get_objects()` by `type(o).__name__`. `isinstance` fails when the file was loaded under another name.
- Importing a test helper again runs it again and resets its state: read state through the live object.
- A timed step: set the field (`game.elapsed = 59.5`), then read the result. A sensor: replace `motion.get_gravity` for the test. Say that you did.
- A game that has ended stops updating: check that it is alive before reading its animation.

## A local web server
`http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)` in a daemon thread, with the port it reports; `shutdown()` in `finally`. Cover a short page, another charset, a 404, and a refused connection.

## Tests that lie
- `assert x or True` always passes: check the real state.
- A view that was never laid out fails for the test's own reasons: call `layout()` first, and check a failure again before calling it a bug.

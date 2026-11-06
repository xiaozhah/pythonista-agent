# pycoder

An agentic coding assistant that runs inside Pythonista 3.4 (Python 3.10) on iOS, calling the
Claude API over raw HTTP. This file is read by Claude Code and by pycoder itself.

## Layout

The repository lives in Pythonista's local Documents ("This iPad" / "This iPhone" / "On My Mac",
`/local`) as `pycoder/`, a git clone on each device; git is how code moves between devices, not
iCloud. On an iPhone the clone may instead be kept by a git app (Working Copy) and added to
Pythonista as an external folder: `config.home_for` then makes Pythonista's own Documents the home, and
the repository is `/pycoder` in the shell. That Documents folder is the user's home (`~`, `config.HOME_DIR`), where their own projects go and where
`.pycoder/` keeps settings, sessions and memory (per device); the repository is
`config.INSTALL_DIR`. Inside the repository:

```
install.py            run once: teaches Pythonista's console the commands below
pycoder/
  frontends/          the screens: chat (opened by `pycoder`), console (the commands typed in it, and for the bridge),
                      and the controls they share (widgets.py)
  app/                the application: controller (one session), commands/ (by topic), prompt commands, @mentions, reports
  shell/              the built-in shell (one command table for `!` and the console), a session of it at the console
  agent/              one model turn: the tool-use loop, permissions, system prompt, compaction
  tools/              what the model can call (files, python, git, device, docs, memory, plan, …)
  api/                the streaming Claude API client over raw HTTP
  state/              what persists: workspace, sessions, file checkpoints, subagents' worktrees, memory,
                      skills, settings
  host/               what Pythonista/iOS provides: environment, keychain, packages, images, git,
                      the main thread, background time, crash reports, native array maths
                      (accelerate), C via JavaScriptCore (cwasm), recording a window to video
  config types cancel events launch updater   constants, the frontend interface, start-up, updates
skills/ commands/     what comes with pycoder and how it is extended (kept in git); a skill the
                      user asks for (save_skill) stays on the device, in ~/.pycoder/skills
tutorial/             a big demo pycoder builds alone: a prompt, what it's given, and run.py to start it
dev/                  development only: the bridge that lets a Mac drive Pythonista, a test runner
stubs/                type stubs for the Pythonista-only modules, so mypy runs on a Mac
tests/                mirrors pycoder/; a scripted fake API and a recording frontend
```

Each package's `__init__.py` says what belongs in it; put new code where its responsibility is,
and keep dependencies pointing down that list (frontends at the top, host at the bottom). `launch`
and `updater` use `host`, and `tools/subagent.py` uses `agent`, since a subagent is an agent.

## Rules

- The code must run on Python 3.10 in Pythonista: no subprocesses, no compiled packages, and
  `open()` defaults to ASCII there, so always pass `encoding='utf-8'`. The two limits are the OS's: the
  sandbox denies fork/exec, and code signing denies running unsigned native code. The
  `process-capabilities` skill says what to use instead (threads, Accelerate, Metal, WebAssembly in
  JavaScriptCore, a worker pool of JavaScriptCore VMs for parallel work).
- The core never prints or reads input; it reports through `Frontend` methods.
- Keep requests append-only: the system prompt and tools are fixed per session, history is only
  appended to or truncated at the end (thinking blocks are checked against what preceded them).
- New tools go in `tools/` with a `TOOLS` list, registered in `tools/registry.py`. Shell commands go in the table in `shell/commands.py` (both `!`
  and the console use it); slash commands go in the topic module under `app/commands/`.
  A tool that writes, runs code or reads private data is `readonly=False`, so the permission mode
  decides whether to ask; Pythonista-only modules are imported inside the tool function and get a
  stub in `stubs/`.
- A new setting is one `SettingSpec` plus a field on `Settings`, both in `state/settings.py`.
- The system prompt (`agent/prompt.py`) holds only rules that apply to every task. Know-how about
  one topic (a kind of question, a device feature, an API) goes in a skill,
  `skills/<name>/SKILL.md`, whose description starts with "Use when …": Claude sees that line and
  reads the skill only when a task matches. The description is a YAML value: put it in double quotes if
  it holds `: ` (GitHub shows an error over the file otherwise; a skill pycoder saves is quoted for you,
  and a test checks the bundled ones). Skills are changed by hand or when the user asks; a single
  fact the model finds out is a memory (`remember`), for this project or, if it holds in any, global.
  A skill says how to do something, not how it went: no timings, no results from one device. Keep it to
  60 lines and 4000 characters, and split one that grows (a test checks).
  When a tool gives wrong results, fix the tool rather
  than explaining around it in a prompt.
- `frontends/console/hooks.py` stays in the app for as long as it runs, so what can change goes in
  `lines.py`, which is imported afresh. Changing `hooks.py` takes a restart of Pythonista. Keep
  `pycoder.frontends.console.hooks.install` stable: pythonista_startup.py calls it.
- Paths saved to disk that point into pycoder's home are saved relative to it (see
  `state/session.py`), so they still resolve when the app's folder moves.

## Checks

Run before committing (pre-commit runs them too; the dev environment is `~/.venvs/pycoder`):

    ruff check . && ruff format --check . && mypy && pytest

## Editing from a Mac

On the Mac the repository is `~/Library/Group Containers/group.pythonista/Pythonista3/Documents/pycoder`.
Pythonista saves its editor buffers back to disk, so files open there are written through the
bridge (`python3 dev/client.py --device mac write <path> <local file>`), not directly.
The bridge must be running in Pythonista: type `bridge` in the console, which stays usable
(`--device iphone` reaches the phone); `bridge restart` after changing it. After each start of a bridge,
`client.py --device NAME pair` gets its token (tap Allow there; a Tailscale address is remembered in
`.bridge/trusted` and isn't asked about again), and `client.py --device NAME pull` updates that device's
clone from GitHub (it needs a GitHub token on that device; on an iPhone whose clone a git app keeps,
pull in the git app instead). Run the client from the repository folder; paths it takes are relative to the
repository. `python3 dev/client.py run <file.py>` runs a script there and prints its output.

Also run the tests inside Pythonista, where the iOS modules are real (about twenty seconds):

    python3 dev/client.py run dev/run_tests.py

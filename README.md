# pycoder

**A Claude Code–style coding agent for Pythonista on iPhone, iPad and Mac.**

pycoder runs **inside Pythonista on iPhone and iPad** (and Pythonista on Apple-silicon Macs), with no
computer needed. Describe what you want; Claude reads and edits files in the workspace, runs
Python right there, uses git, installs pure-Python packages, and remembers what it finds out.

The GitHub repository is `pythonista-agent`; `pycoder` is the folder you clone it into and the command you type.

## Run it

1. Clone this repository into Pythonista's local Documents ("This iPad" / "This iPhone" /
   "On My Mac") as a folder named `pycoder` (`Documents/pycoder/`). Each device has its own clone;
   git keeps them in step (updates pull from GitHub by themselves). On an iPhone the clone can instead
   be kept by a git app such as Working Copy and added to Pythonista as an external folder: your home
   is still Pythonista's own Documents, the repository is `/pycoder` in the shell, and new code
   arrives by pulling in the git app.
2. Open `pycoder/install.py` and tap Run, once. From then on Pythonista's console understands the
   shell's commands and `pycoder` whenever the app starts; Python works there as ever.
3. The shell starts in `~`, that local Documents folder: your own space for projects next to
   `pycoder/`. Keep projects in git to have them on other devices. `cd` into a project and type
   `pycoder`; enter an Anthropic API key once (kept in the iOS keychain).

```
~ $ mkdir work && cd work
~/work $ git clone https://github.com/you/project
~/work $ cd project
~/work/project $ pycoder               # the agent, working in this folder (claude works too)
~/work/project $ pycoder -c            # continue the last session here (-r: pick one)
~/work/project $ pycoder "add a jump"  # start with a request
```

`/exit` goes back to the console. Sessions, project memory and `CLAUDE.md` belong to the folder you
start in; global memory holds in every folder. Sessions and memory stay on the device they were made
on.

**The console** has `cd pwd ls tree cat head touch mkdir mv cp rm echo git pip python` (pycoder's
own pure-Python versions: iOS can't run real programs), `clear`, `history`,
`bridge` (development: lets a Mac drive this device, see below) and Tab completion; `help` lists them.
A line that only makes sense as Python stays Python: `ls` lists a folder, `ls = 5` makes
a variable. The shell starts in `~`: your Documents on this device, also called `/local`. `/iCloud` is
Pythonista's iCloud Drive folder, which syncs between devices. Tab completes a command or a path (on
the phone, the ⇥ key above the keyboard), and the console's completion list offers the commands next to
Python's. Ctrl+C on a hardware keyboard stops a command or clears the typed line; the stop button stops a
command too. Files are in Pythonista's own file browser.

**The chat:** the top bar has **✕** (close), **New**, the session's title, the folder (the files pane) and **⋯** (the menu). Type
and tap **↵** (while Claude works, what you send is queued and goes next; with nothing typed it
stops the reply), and **＋** attaches a photo, the clipboard image or a file. A plan shows in a box
above the input. Typing `/` opens the command palette; `!` runs one of the shell's commands (`!git status`, `!pip
install rich`, `!pycoder update`) and adds its output to the conversation; `@path` attaches a file
or folder to the message. **Tab** completes all three on a hardware keyboard, and ⌘+ / ⌘− change
the text size. The status line under the input shows the folder, model, effort, permission mode and
how full the context is; tap any of the last four to change it or see more.

**Updates are automatic:** at most every 30 minutes, a start checks GitHub in the background and
fetches a newer version; it is installed the next time you start pycoder. Your clone is
fast-forwarded, only when clean and on `main`. `pycoder rollback` undoes an update, and `/config`
turns it off. If this clone can't reach GitHub on its own, pull it by hand.

## What it can do

| | |
|---|---|
| Files | list, read, search, write, edit, move, delete — with a diff for every change |
| Code | `run_python` runs code in Pythonista and returns output, traceback and the failing frame's locals; background jobs; `run_c` for single-file C |
| Screens | `look_at_screen` sees what is on screen, and `use_screen` presses, drags and types in the program it built |
| Understanding code | `python_code`: a file's classes and functions, where a name is defined and used, its signature and docstring, and diagnostics: syntax, undefined names, types (ast, jedi, pyflakes, mypy, all pure Python; installed on first use, in a folder of their own, as Pythonista bundles old ones) |
| git | init, config, status, diff, add, commit, log, branch, checkout, pull, push, clone (pure-Python dulwich) |
| Packages | installs pure-Python wheels from PyPI and their dependencies (`/pip install name`) |
| Pythonista's docs | reads the documentation Pythonista ships (ui, scene, photos, … and the standard library) when it needs an API, matching the installed version |
| Planning | a visible todo list (it goes away when all is done; say so to clear it, or `/todos clear`), and subagents, which can run code as the mode allows: for broad research, or to change code in parallel, each in its own copy of the workspace, merged back when done |
| Images | attach screenshots and photos to a message, and recognize text in them |
| Web | web search and fetch |
| Reading the code | the files pane (the folder at the top, `/files`, ⌘E): folders, coloured code with line numbers, and what this session changed as a diff. It only reads, and stays current while the agent works; a file left open in Pythonista's editor could overwrite what the agent writes |
| Sessions | saved automatically; `/resume` continues one |
| Long work | on-demand compaction (`/compact`, automatic when the context gets large), `/context` |
| Undo | `/rewind` goes back to before a request: the files it changed, the conversation, or both |
| Permissions | modes `default`, `acceptEdits`, `plan` (read-only until you approve a plan), `bypass`; allow / ask / deny rules such as `git(status*)` or `edit_file(src/*)` (`/permissions`) |
| Memory | notes it keeps between sessions: for this project, or global for what holds in any (`/memory`); `CLAUDE.md`, or `AGENTS.md` |
| The device | ask you a question, notifications, clipboard, photos and camera, Files import, share sheet, location, motion sensors, dictation, text to speech, Shortcuts, URLs, battery and storage |
| Spending | `/usage` (or `/cost`) shows the tokens and cost this device spent: this session, today, this week |
| Settings | `/config`: chat font size, code font (SF Mono, Menlo, Courier), theme, model, effort, mode, web, memory, auto-update, notifications, cache lifetime, auto-compact; Status and Usage tabs in the chat |
| Self-update | automatic at the next start; `pycoder update` in the console (or `/update`) does it now, `pycoder rollback` undoes it |

## See it build something big by itself

Open `tutorial/run.py` and tap Run, then pick a model. pycoder builds a film about a spinning black hole from a
written brief: it plans it, writes it, runs it, looks at the screen, taps and drags in what it built, fixes what it
finds, and writes a report, with nobody answering anything. See [tutorial/README.md](tutorial/README.md).

## Extending it — by chatting with it

pycoder can grow without touching its core:

- **Skills** (`skills/<name>/SKILL.md`) – how to do a kind of task, written by hand (like
  `pythonista-ui-apps`) or saved by pycoder when asked. Only their names and descriptions are in the
  system prompt; it reads one in full when a task calls for it.
- **Prompt commands** (`commands/<name>.md`, or `.claude/commands/` in the workspace as in Claude
  Code) – `/name args` sends the template with `$ARGUMENTS` filled in.
- **`CLAUDE.md`** in the workspace is added to the system prompt, shared with Claude Code.

New prompt commands work right away; new skills from the next session (`/clear`). A skill says how to
do a kind of task. Single facts it finds out are memories, not skills.

## Commands

`/help` lists them by topic — conversation (`clear resume rename delete compact rewind fork chapters
btw cd image exit`), information (`files session crashes context memory todos skills cost usage status`),
settings (`model effort config mode plan permissions bypass web key`) and installation
(`pip update`) — plus any prompt commands.

## Architecture

`Documents/` is your home (`~`): your projects, the `pycoder/` repository, and `.pycoder/` with
your settings, sessions and memory (data, not code: outside the repository and git). Inside the
repository:

```
install.py            run once: teaches Pythonista's console the commands below
pycoder/
  frontends/          the screens: chat (opened by `pycoder`), console (the commands typed in it, and for the bridge)
  app/                the application: controller (one session), commands/ (by topic), prompt commands, @mentions, reports
  shell/              the built-in shell (one command table for `!` and the console), a session of it at the console
  agent/              one model turn: the tool-use loop, permissions, system prompt, compaction
  tools/              what the model can call (files, python, git, device, docs, memory, plan, …)
  api/                the streaming Claude API client over raw HTTP
  state/              what persists: workspace, sessions, file checkpoints, memory, skills, settings
  host/               what Pythonista/iOS provides: environment, keychain, packages, images, git, the
                      main thread, background time, crash reports, array maths, C via JavaScriptCore
  config types cancel events launch updater   constants, the frontend interface, start-up, updates
skills/ commands/     what comes with pycoder (in git); a skill made on request stays in ~/.pycoder/skills
dev/                  development only: the bridge that lets a Mac drive Pythonista, a test runner
stubs/                type stubs for the Pythonista-only modules, so mypy runs on a Mac
tests/                mirrors pycoder/; a scripted fake API and a recording frontend
```

Dependencies point downwards in that list. The core never prints: it calls `Frontend` methods, so
every screen shares it, and tests drive it with a recording frontend and a scripted fake API.

## Development (on a Mac)

```bash
uv venv --python 3.10 ~/.venvs/pycoder        # Pythonista runs Python 3.10
VIRTUAL_ENV=~/.venvs/pycoder uv pip install ruff mypy pytest pre-commit requests markdown pygments pillow numpy jedi==0.19.2 \
    types-requests types-Markdown types-Pygments "dulwich==0.22.8"
source ~/.venvs/pycoder/bin/activate
pre-commit install
ruff check . && ruff format --check . && mypy && pytest
```

`dev/bridge.py` (`bridge` in the console) with `dev/client.py` (on the Mac) lets a Mac write files and
run code in Pythonista on the same Mac or on an iPhone over the LAN/Tailscale. Its token and device
addresses stay in `.bridge/`, outside git. See `CLAUDE.md`, which also shows how to run the tests
inside Pythonista.

## License

[MIT](LICENSE).

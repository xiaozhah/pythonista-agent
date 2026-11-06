---
name: improving-pycoder
description: Use when the user wants pycoder itself to do something new or differently — a new ability, a new command, a change to how it looks or behaves
---

Pick the lightest way that does the job:

1. **A skill** (save_skill, when the user asks for one): how to do a kind of task, which steps. A single fact about how something behaves is a memory (remember), not a skill.
   Read in later sessions when a task matches its description.
2. **The core** (the repository's `pycoder/` package) when a skill can't do it.

## Changing the core

- Start pycoder in the repository folder (`cd ~/pycoder`, then `pycoder`) so its `CLAUDE.md`, which
  explains the layout and the rules, is in the system prompt. Put new code where CLAUDE.md says.
- Commit with the git tool before changing anything: a broken core can't repair itself from chat.
- Run the tests afterwards: run_python with path `dev/run_tests.py` (in the repository). Add a
  test for what you changed.
- The running pycoder keeps its old code: tell the user to /exit and type `pycoder` in the console
  again to use the change.
- Commit and push with the git tool on the device you're on: each has its own clone.

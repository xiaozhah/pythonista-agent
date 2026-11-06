"""The terminal: a Shell plus what a session at Pythonista's console adds, and the command that
starts the agent.

The commands themselves are the shell's (commands.py). The terminal keeps history, completes with
Tab, and turns `pycoder` (or `claude`) into a request to open the agent with the current folder as
its workspace.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass

from .. import config
from ..events import Frontend
from .commands import COMMANDS, Shell, ShellError, describe_error, split_commands

HISTORY_FILE = os.path.join(config.DATA_DIR, 'terminal_history')
MAX_HISTORY = 500
AGENT_COMMANDS = ('pycoder', 'claude')  # claude: the habit from Claude Code
NOT_AGENT = ('update', 'rollback')  # `pycoder update` is the shell's command
OWN_COMMANDS = ('clear', 'history', 'bridge')
COMMAND_NAMES = frozenset({*AGENT_COMMANDS, *OWN_COMMANDS, *COMMANDS})

HELP = """Commands run in the current folder; anything else is Python.
  pycoder [prompt]       start the agent in this folder (claude works too)
  pycoder -c | -r        continue the last session here | pick a session to resume
  bridge [stop|restart]  let Claude Code on a Mac drive this device (development)
  clear  history
"""


def _starts_agent(words: list[str]) -> bool:
    return bool(words) and words[0] in AGENT_COMMANDS and words[1:2] not in [[w] for w in NOT_AGENT]


@dataclass
class Result:
    output: str = ''
    ok: bool = True
    error: str = ''  # why it failed, shown apart from what the commands before it printed
    # what the screen should do next: '' (nothing), 'clear', 'bridge', or 'agent' (start it with `arg`)
    action: str = ''
    arg: str = ''


class Terminal:
    def __init__(
        self,
        home: str = config.HOME_DIR,
        history_file: str = HISTORY_FILE,
        frontend: Frontend | None = None,
        places: dict[str, str] | None = None,
    ) -> None:
        self.history_file = history_file
        self.shell = Shell(home, home, frontend, places=places)
        self.history = self._load_history()

    @property
    def cwd(self) -> str:
        return self.shell.cwd

    @property
    def home(self) -> str:
        return self.shell.home

    def display_path(self, path: str | None = None) -> str:
        return self.shell.display(path or self.cwd)

    def prompt(self) -> str:
        return f'{self.display_path()} $'

    def run(self, line: str) -> Result:
        line = line.strip()
        if not line:
            return Result()
        self._remember(line)
        words = line.split()
        if _starts_agent(words):
            return Result(action='agent', arg=line[len(words[0]) :].strip())
        if words[0] == 'clear':
            return Result(action='clear')
        if words[0] == 'bridge':
            return Result(action='bridge', arg=line[len(words[0]) :].strip())
        if words[0] == 'history':
            return Result('\n'.join(f'{i + 1:4}  {h}' for i, h in enumerate(self.history[-50:])))
        # `cd project && pycoder`: the shell runs what comes first, then the agent starts there
        agent: list[str] | None = None
        try:
            commands = split_commands(line)
        except ShellError:
            commands = []
        if len(commands) > 1 and _starts_agent(commands[-1][0]):
            agent = commands[-1][0]
            line = ' '.join(f'{shlex.join(w)} {j}' for w, j in commands[:-1]).rstrip(' &;')
        try:
            output = self.shell.run(line)
        except KeyboardInterrupt:
            return Result('', False, '(interrupted)')
        except ShellError as e:
            return Result(e.done, False, e.reason)
        except Exception as e:  # a command must never take the console's line down
            return Result('', False, describe_error(e))
        if words[0] == 'help':
            output = HELP + output
        if agent is not None:
            return Result(output, action='agent', arg=' '.join(agent[1:]))
        return Result(output)

    # ---- completion

    def complete(self, text: str) -> tuple[str, list[str]]:
        """Tab: complete the last word as a command (first word) or a path."""
        head, _, word = text.rpartition(' ')
        if not head and not text.endswith(' '):
            names = sorted(COMMAND_NAMES)
            matches = [n for n in names if n.startswith(word)]
        else:
            matches = self._path_matches(word, dirs_only=head.split()[:1] == ['cd'])
        if not matches:
            return text, []
        prefix = (head + ' ') if head or text.endswith(' ') else ''
        if len(matches) == 1:
            return prefix + matches[0] + ('' if matches[0].endswith('/') else ' '), matches
        common = os.path.commonprefix(matches)  # noqa: RUF071 - a string prefix, not a path
        return prefix + common, matches

    def _path_matches(self, word: str, dirs_only: bool) -> list[str]:
        if word.startswith('/') and '/' not in word[1:]:  # /lo → /local/
            return [name + '/' for name in self.shell.places if name.startswith(word)]
        folder, _, start = word.rpartition('/')
        try:
            full = self.shell.path(folder or '.')
        except Exception:
            return []
        if not os.path.isdir(full):
            return []
        out = []
        for name in sorted(os.listdir(full)):
            if not name.startswith(start) or (name.startswith('.') and not start.startswith('.')):
                continue
            is_dir = os.path.isdir(os.path.join(full, name))
            if dirs_only and not is_dir:
                continue
            out.append((folder + '/' if folder else '') + name + ('/' if is_dir else ''))
        return out

    # ---- remembered between runs

    def _remember(self, line: str) -> None:
        if self.history and self.history[-1] == line:
            return
        self.history = [*self.history, line][-MAX_HISTORY:]
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(self.history) + '\n')
        except OSError:
            pass  # history is a convenience

    def _load_history(self) -> list[str]:
        try:
            with open(self.history_file, encoding='utf-8') as f:
                return [line.rstrip('\n') for line in f if line.strip()][-MAX_HISTORY:]
        except OSError:
            return []


def agent_args(arg: str) -> tuple[str, str]:
    """`pycoder -c | -r [prompt]` → (resume: '' | 'last' | 'pick', the first message)."""
    words = shlex.split(arg)
    if words[:1] in (['-c'], ['--continue']):
        return 'last', ' '.join(words[1:])
    if words[:1] in (['-r'], ['--resume']):
        return 'pick', ' '.join(words[1:])
    return '', ' '.join(words)

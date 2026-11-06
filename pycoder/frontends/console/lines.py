"""What is typed in Pythonista's console. A line that is one of the shell's commands runs in the shell;
anything else stays Python, so `ls` lists a folder and `ls = 5` makes a variable. hooks.py hands the
lines over."""

from __future__ import annotations

import ast
import builtins
import importlib.util
import os
import sys
import types
from typing import Any

from ... import config
from ...events import Frontend
from ...host import env
from ...shell.terminal import COMMAND_NAMES, Result, Terminal
from ...tools.python_runner import console_stream
from .output import out

# what lasts between lines: each line gets a Terminal from whatever code is loaded by then
state = env.process_wide('console', types.SimpleNamespace(cwd='', previous='', running=None))


class ShellFrontend(Frontend):
    """What shell commands report while they run (pip and git progress), and their questions."""

    def run_output(self, text: str) -> None:
        out(text, 'dim')

    def notice(self, text: str, level: str = 'info') -> None:
        out(text, 'red' if level == 'error' else 'yellow' if level == 'warn' else 'dim')

    def ask_text(self, title: str, message: str = '', secret: bool = False) -> str | None:
        import console

        try:
            return console.password_alert(title, message) if secret else console.input_alert(title, message)
        except KeyboardInterrupt:  # Cancel
            return None


def say(text: str, color: str | None = None) -> None:
    """From the main thread, where anything else printed would go to whatever code is running."""
    out(text, color, stream=console_stream())


def is_command(line: str) -> bool:
    """Whether the line is for the shell. A line that makes sense as Python only is Python, and a name
    defined in the console means what it was defined as."""
    words = line.split()
    name = words[0].rstrip(';') if words else ''
    if name not in COMMAND_NAMES:
        return False
    try:
        tree = ast.parse(line)
    except SyntaxError:
        return True  # git status, cd ..
    if not all(isinstance(statement, ast.Expr) for statement in tree.body):
        return False  # ls = 5
    return name not in vars(sys.modules['__main__']) and (name not in vars(builtins) or name == 'help')


def _terminal() -> Terminal:
    terminal = Terminal(frontend=ShellFrontend())
    if os.path.isdir(state.cwd):
        terminal.shell.cwd = state.cwd
    if os.path.isdir(state.previous):
        terminal.shell.previous = state.previous
    return terminal


def run(line: str) -> None:
    """Run a command, and show where that leaves the shell."""
    terminal = _terminal()
    state.running = terminal
    try:
        result = terminal.run(line)
    finally:
        state.running = None
    state.cwd, state.previous = terminal.cwd, terminal.shell.previous
    os.chdir(terminal.cwd)  # Python in the console, and scripts it starts, are where the shell is
    show(result, terminal)


def show(result: Result, terminal: Terminal) -> None:
    if result.output:
        out(result.output)
    if result.error:
        out(result.error, 'red')
    if result.action == 'clear':
        import console

        console.clear()
    elif result.action == 'bridge':
        bridge(result.arg)
    elif result.action == 'agent':
        open_agent(terminal.cwd, result.arg)
        return
    out(terminal.prompt(), 'dim')


def complete(line: str) -> tuple[str, list[str]] | None:
    """Tab: the line completed and what it could have been, or None if the shell has nothing for it."""
    text, options = _terminal().complete(line)
    return (text, options) if options else None


def suggest(line: str) -> list[str]:
    """The commands to offer among Python's completions for what is being typed: a first word."""
    return sorted(name for name in COMMAND_NAMES if name.startswith(line)) if line and ' ' not in line else []


def interrupt() -> None:
    """Ctrl+C or the stop button while a command runs: many of them look at this, between their steps."""
    terminal = state.running
    if terminal is not None:
        terminal.shell.cancel.cancel()


def bridge(arg: str) -> None:
    """dev/bridge.py runs next to the console. It is development's, so it isn't part of the package."""
    path = os.path.join(config.INSTALL_DIR, 'dev', 'bridge.py')
    spec = importlib.util.spec_from_file_location('pycoder_bridge', path)
    if spec is None or spec.loader is None or not os.path.isfile(path):
        out(f'{path} is not here', 'red')
        return
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if arg == 'stop':
        module.stop()
    elif arg == 'restart':
        module.stop()
        module.start()
    elif arg:
        out('bridge [stop | restart]', 'red')
    else:
        module.start()


def open_agent(root: str, arg: str) -> None:
    """`pycoder [-c | -r] [prompt]`: the chat for this folder, with the code on disk now."""
    from ... import launch

    for note in launch.prepare():  # installs an update downloaded last time, and forgets what is loaded
        out(note, 'yellow')

    from objc_util import on_main_thread

    from ... import launch as fresh
    from ...shell.terminal import agent_args
    from ..chat.view import ChatView

    resume, first = agent_args(arg)
    chat: Any = None

    def closed() -> None:
        session = chat.controller.session
        chat.close()
        if session.messages:
            say(f'Session "{session.title or "untitled"}" saved; pycoder -c continues it', 'dim')
        say(_terminal().prompt(), 'dim')

    def present() -> None:
        nonlocal chat
        try:
            chat = ChatView(root=root, on_exit=closed)
        except Exception as e:  # on the main thread, nothing but this would say so
            say(f'pycoder could not start: {type(e).__name__}: {e}', 'red')
            return
        chat.present('fullscreen', hide_title_bar=True)
        chat.refresh()
        chat.start(first, resume)
        fresh.check_in_background(lambda message: say(message, 'yellow'))

    on_main_thread(present)()

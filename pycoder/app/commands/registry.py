"""The table of slash commands (with those prompt files add) and running one."""

from __future__ import annotations

from collections.abc import Callable

from .. import prompt_commands
from ..controller import Controller
from . import info, options, session, system
from .base import Command


def _help(c: Controller, arg: str) -> None:
    lines = []
    for title, commands in [*GROUPS, ('Added by prompt files', extras(c))]:
        if commands:
            lines.append(title + ':')
            lines += ['  /%-22s %s' % ((cmd.name + ' ' + cmd.args).strip(), cmd.help) for cmd in commands]
    lines.append('Tab completes commands and their arguments. Stop interrupts a running turn.')
    c.frontend.notice('\n'.join(lines))


GROUPS = [
    ('Conversation', [Command('help', 'show the commands', _help), *session.COMMANDS]),
    ('Information', info.COMMANDS),
    ('Settings', options.COMMANDS),
    ('Installation', system.COMMANDS),
]
BUILTIN = [cmd for _, commands in GROUPS for cmd in commands]


def all_commands(c: Controller) -> list[Command]:
    return BUILTIN + extras(c)


def extras(c: Controller) -> list[Command]:
    """Commands Markdown prompt files add; never one that replaces a built-in."""
    taken = {cmd.name for cmd in BUILTIN}
    extra = []
    for p in c.prompt_commands():
        if p.name not in taken:
            taken.add(p.name)
            extra.append(Command(p.name, p.description, _prompt_runner(p), '[text]'))
    return extra


def _prompt_runner(command: prompt_commands.PromptCommand) -> Callable[[Controller, str], None]:
    def runner(c: Controller, arg: str) -> None:
        c.run_turn(command.render(arg))

    return runner


def run_command(c: Controller, line: str) -> bool:
    """Run '/name args'. Returns False when the user asked to quit."""
    name, _, arg = line[1:].partition(' ')
    command = next((cmd for cmd in all_commands(c) if cmd.name == name.lower()), None)
    if command is None:
        c.frontend.notice(f'Unknown command /{name}; /help lists them', 'error')
        return True
    try:
        return command.run(c, arg.strip()) is not False
    except Exception as e:  # a command failed; keep the session alive
        c.frontend.notice(f'/{name} failed: {type(e).__name__}: {e}', 'error')
        return True

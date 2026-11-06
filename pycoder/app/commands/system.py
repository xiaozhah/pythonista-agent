"""Commands that change the installation: pip install, self-update."""

from __future__ import annotations

from ...host import packages
from ..controller import Controller
from .base import Command


def _pip(c: Controller, arg: str) -> None:
    words = arg.split()
    if len(words) < 2 or words[0] != 'install':
        c.frontend.notice('Usage: /pip install <package>[==version]', 'error')
        return
    for name in words[1:]:
        try:
            done = packages.install(name, log=lambda line: c.frontend.notice(line))
        except packages.PackageError as e:
            c.frontend.notice(str(e), 'error')
            continue
        c.frontend.notice('Installed {}'.format(', '.join(done)) if done else f'{name} is already installed')


def _update(c: Controller, arg: str) -> None:
    from ... import updater

    c.frontend.notice('Checking GitHub for a newer pycoder…' if arg != 'rollback' else 'Rolling back…')
    try:
        c.frontend.notice(
            updater.command(
                arg, lambda: c.frontend.ask_text('GitHub token', 'For a private repository', True)
            )
        )
    except updater.UpdateError as e:
        c.frontend.notice(str(e), 'error')


COMMANDS = [
    Command('pip', 'install a pure-Python package', _pip, 'install <name>', lambda c: ['install']),
    Command(
        'update',
        "update pycoder's own code from GitHub",
        _update,
        '[rollback]',
        lambda c: ['rollback'],
    ),
]

"""Tab completion and the command palette: what to offer for the text typed so far."""

from __future__ import annotations

from ...shell.commands import hints as shell_hints
from .. import mentions
from ..controller import Controller
from .registry import all_commands


def complete(c: Controller, text: str) -> tuple[str, list[str]]:
    """Tab completion: (new text, the candidates). The text grows to the longest common prefix."""
    typed = mentions.partial(text)
    if typed is not None:
        paths = mentions.candidates(c.workspace, typed)
        if not paths:
            return text, []
        stem = text[: len(text) - len(typed)]
        if len(paths) == 1:
            return stem + paths[0] + ('' if paths[0].endswith('/') else ' '), paths
        common = _common_prefix(paths)
        return (stem + common if len(common) > len(typed) else text), paths
    if text.startswith('!'):  # the shell's commands and their common forms
        forms = sorted({cmd for cmd, _ in shell_hints() if cmd.startswith(text[1:])})
        if len(forms) == 1:
            return '!' + forms[0], forms
        return ('!' + _common_prefix(forms) if forms else text), forms
    if not text.startswith('/'):
        return text, []
    name, space, arg = text[1:].partition(' ')
    if not space:
        names = sorted(cmd.name for cmd in all_commands(c) if cmd.name.startswith(name.lower()))
        if len(names) == 1:
            return f'/{names[0]} ', names
        return ('/' + _common_prefix(names) if names else text), names
    command = next((cmd for cmd in all_commands(c) if cmd.name == name.lower()), None)
    if command is None:
        return text, []
    options = [o for o in command.complete(c) if o.startswith(arg)]
    if len(options) == 1:
        return f'/{name} {options[0]}', options
    return (f'/{name} {_common_prefix(options)}' if options else text), options


def _common_prefix(words: list[str]) -> str:
    prefix = words[0] if words else ''
    for word in words[1:]:
        while not word.startswith(prefix):
            prefix = prefix[:-1]
    return prefix


def suggestions(c: Controller, text: str, limit: int = 8) -> list[tuple[str, str, str]]:
    """What the command palette offers for the text typed so far: (text to insert, title, help)."""
    if text.startswith('!'):
        return [
            ('!' + cmd, '!' + cmd.strip(), help_) for cmd, help_ in shell_hints() if cmd.startswith(text[1:])
        ][:limit]
    typed = mentions.partial(text) if not text.startswith('/') else None
    if typed is not None:
        stem = text[: len(text) - len(typed)]
        return [
            (stem + p + ('' if p.endswith('/') else ' '), '@' + p, 'folder' if p.endswith('/') else 'file')
            for p in mentions.candidates(c.workspace, typed, limit)
        ]
    if not text.startswith('/'):
        return []
    name, space, arg = text[1:].partition(' ')
    if not space:
        return [
            (f'/{cmd.name} ', f'/{cmd.name} {cmd.args}'.strip(), cmd.help)
            for cmd in all_commands(c)
            if cmd.name.startswith(name.lower())
        ][:limit]
    command = next((cmd for cmd in all_commands(c) if cmd.name == name.lower()), None)
    if command is None:
        return []
    return [
        (f'/{name} {option}', option, command.help)
        for option in command.complete(c)
        if option.startswith(arg)
    ][:limit]

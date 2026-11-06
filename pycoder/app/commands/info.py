"""Commands that show state: cost and usage, status, context, todos, skills, memory."""

from __future__ import annotations

import os

from ...state import memory
from ...tools.todos import format_todos
from .. import reports
from ..controller import Controller
from .base import Command


def _usage(c: Controller, arg: str) -> None:
    c.frontend.notice(reports.table(reports.usage(c)))


def _status(c: Controller, arg: str) -> None:
    c.frontend.notice(reports.table(reports.status(c)))


def _crashes(c: Controller, arg: str) -> None:
    """What the last crashes left: Python's stacks, and what iOS itself reports."""
    from ...host import diagnostics
    from ...launch import LAST_CRASH_FILE, LAST_RUN_FILE, crash_note

    try:
        diagnostics.collect()  # iOS delivers them a little after the start
    except Exception as e:
        c.frontend.notice(f"iOS's crash reports are not available: {e}", 'warn')
    lines = []
    if os.path.exists(LAST_CRASH_FILE):
        lines.append(crash_note(LAST_CRASH_FILE))
    lines += [f'iOS: {line}' for line in diagnostics.all_lines()]
    if os.path.exists(LAST_RUN_FILE):
        lines.append(f'Memory over the last seconds of the previous run: {LAST_RUN_FILE}')
    if lines:
        lines.append(f'The reports are in {diagnostics.DIRECTORY}')
    c.frontend.notice('\n'.join(lines) or 'No crash has been recorded')


def _session(c: Controller, arg: str) -> None:
    c.frontend.show_session()


def _files(c: Controller, arg: str) -> None:
    c.frontend.show_files()


def _context(c: Controller, arg: str) -> None:
    usage = reports.context_usage(c)
    c.frontend.show_context(usage, reports.context_text(usage))


def context_report(c: Controller) -> str:
    return reports.context_text(reports.context_usage(c))


def _todos(c: Controller, arg: str) -> None:
    if arg.strip() == 'clear':
        c.clear_todos()
        c.save()
        c.frontend.notice('Todo list cleared')
    else:
        c.frontend.notice(
            format_todos(c.session.todos) if c.session.todos else 'No todo list in this session'
        )


def _skills(c: Controller, arg: str) -> None:
    skills = c.skills.all()
    c.frontend.notice(
        '\n'.join(f'{s.name} — {s.description}' for s in skills)
        if skills
        else 'No skills yet; pycoder makes one when you ask'
    )


def _memory(c: Controller, arg: str) -> None:
    """/memory: the notes; /memory add <text> (this project), global <text> (every project),
    show <name>, forget <name>."""
    notes = c.memory_store()
    everywhere = memory.global_store(notes.directory)
    verb, _, rest = arg.partition(' ')
    rest = rest.strip()
    if verb in ('add', 'global') and rest:
        name = memory.slug(rest)
        (everywhere if verb == 'global' else notes).save(name, rest[:100], 'user', rest)
        c.frontend.notice(f'Remembered as {name} (used from the next session)')
    elif verb == 'show' and rest:
        note = notes.get(rest) or everywhere.get(rest)
        c.frontend.notice(f'{note.description} ({note.type})\n\n{note.body}' if note else f'No memory {rest}')
    elif verb == 'forget' and rest:
        gone = notes.remove(rest) or everywhere.remove(rest)
        c.frontend.notice(f'Forgot {rest}' if gone else f'No memory {rest}', 'info')
    elif not arg:
        state = '' if c.settings.memory else ' — auto memory is off (/config memory on)'
        c.frontend.notice(
            f'Memory for this project{state}:\n{notes.index() or "(none yet)"}\n'
            + c.display_path(notes.directory)
            + f'\n\nMemory for every project:\n{everywhere.index() or "(none yet)"}\n'
            + c.display_path(everywhere.directory)
        )
    else:
        c.frontend.notice(
            'Usage: /memory [add <text> | global <text> | show <name> | forget <name>]', 'error'
        )


COMMANDS = [
    Command('files', 'look through the code and what this session changed in it', _files),
    Command('session', 'context, background tasks and the files this session made', _session),
    Command('crashes', 'what the last crashes left: Python stacks and reports from iOS', _crashes),
    Command('context', 'show how full the context is', _context),
    Command(
        'memory',
        'notes pycoder keeps between sessions',
        _memory,
        '[add|global|show|forget ...]',
        lambda c: (
            ['add ', 'global ', 'show ', 'forget '] + [f'show {m.name}' for m in c.memory_store().all()]
        ),
    ),
    Command('todos', 'show the todo list, or clear it', _todos, '[clear]', lambda c: ['clear']),
    Command('skills', 'list saved skills', _skills),
    Command('usage', 'tokens and cost: this session, today, this week', _usage),
    Command('cost', 'same as /usage', _usage),
    Command('status', 'version, model, workspace, mode and more', _status),
]

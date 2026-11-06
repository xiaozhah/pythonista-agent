"""remember / recall / forget: the model's notes between sessions (see state/memory.py)."""

from __future__ import annotations

from ..state import memory
from .base import Tool, ToolContext, ToolError, prop


def store(ctx: ToolContext) -> memory.MemoryStore:
    if not ctx.session.memory_dir:
        raise ToolError('Memory is off (/config memory on, then a new session)')
    return memory.MemoryStore(ctx.session.memory_dir)


def stores(ctx: ToolContext) -> list[memory.MemoryStore]:
    """Where a note may be: this project first."""
    notes = store(ctx)
    return [notes, memory.global_store(notes.directory)]


def remember(
    ctx: ToolContext, name: str, description: str, type: str, body: str, scope: str = 'project'
) -> str:
    if scope == 'global' and type == 'project':
        raise ToolError('A note about a project belongs in that project: leave out scope')
    notes = stores(ctx)[scope == 'global']
    existed = notes.get(name) is not None
    try:
        notes.save(name, description, type, body)
    except memory.NoteError as e:
        raise ToolError(str(e)) from e
    where = ' for every project' if scope == 'global' else ''
    ctx.frontend.notice(f'{"Updated" if existed else "Remembered"}{where}: {description}')
    return f'{"Updated" if existed else "Saved"} memory {name}'


def recall(ctx: ToolContext, name: str) -> str:
    for notes in stores(ctx):
        note = notes.get(name)
        if note is not None:
            return f'{note.description} ({note.type})\n\n{note.body}'
    raise ToolError(f'No memory named {name}; the index lists them')


def forget(ctx: ToolContext, name: str) -> str:
    if not any(notes.remove(name) for notes in stores(ctx)):
        raise ToolError(f'No memory named {name}')
    ctx.frontend.notice(f'Forgot: {name}')
    return f'Removed memory {name}'


TOOLS = [
    Tool(
        'remember',
        'Save or update a note for future sessions (see Memory in the system prompt). Saving under '
        'an existing name replaces that note: recall it first and keep what still holds.',
        {
            'name': prop('string', 'Short id: lowercase letters, digits and hyphens'),
            'description': prop('string', 'One line, shown in the index of every future session'),
            'type': prop('string', 'What kind of note', enum=list(memory.TYPES)),
            'body': prop(
                'string', 'The note; for feedback and project notes, add Why: and How to apply: lines'
            ),
            'scope': prop(
                'string',
                'project (the default): holds only here; global: holds in any project',
                enum=['project', 'global'],
            ),
        },
        remember,
        required=['name', 'description', 'type', 'body'],
        readonly=False,  # every future session reads the notes, so the mode decides whether to ask
    ),
    Tool(
        'recall',
        'Read one of your notes from the memory index.',
        {'name': prop('string', 'The note name from the index')},
        recall,
        required=['name'],
    ),
    Tool(
        'forget',
        'Delete a note that turned out wrong or no longer matters.',
        {'name': prop('string', 'The note name from the index')},
        forget,
        required=['name'],
        readonly=False,
    ),
]

"""The task list the user follows: the model plans it, then changes it one step at a time.

A step keeps its number while it is on the list, so dropping one can't make a later call close the
wrong step. The list lives here, not in the conversation: a summary can't lose it.
"""

from __future__ import annotations

from typing import Any

from ..types import Todo
from .base import Tool, ToolContext, ToolError, prop

STATUSES = ('pending', 'in_progress', 'completed')
MARKS = {'pending': '☐', 'in_progress': '▶', 'completed': '☑'}


def todo_write(ctx: ToolContext, todos: list[Any]) -> str:
    plan: list[Todo] = []
    for number, item in enumerate(todos, 1):
        if not isinstance(item, dict) or not isinstance(item.get('content'), str):
            raise ToolError('Each todo needs a "content" string and a "status"')
        status = item.get('status', 'pending')
        if status not in STATUSES:
            raise ToolError('status must be one of {}'.format(', '.join(STATUSES)))
        plan.append({'id': number, 'content': item['content'], 'status': status})
    if sum(t['status'] == 'in_progress' for t in plan) > 1:
        raise ToolError('Only one todo can be in_progress at a time')
    return _show(ctx, plan)


def todo_update(ctx: ToolContext, step: int, status: str = '', content: str = '') -> str:
    todos = [dict(t) for t in ctx.session.todos]
    target = _find(todos, step)
    was_under_way = target['status'] == 'in_progress'
    if status and status not in (*STATUSES, 'removed'):
        raise ToolError('status must be one of {}, removed'.format(', '.join(STATUSES)))
    if status == 'removed':
        todos.remove(target)
    else:
        if status == 'in_progress':
            for t in todos:
                if t['status'] == 'in_progress':
                    t['status'] = 'pending'
        target['status'] = status or target['status']
        target['content'] = content or target['content']
    if was_under_way and status in ('completed', 'removed'):  # any other status is the model's own say
        next_step = next((t for t in todos if t['status'] == 'pending'), None)
        if next_step:
            next_step['status'] = 'in_progress'
    return _show(ctx, todos)


def todo_add(ctx: ToolContext, content: str, after: int = 0) -> str:
    todos = [dict(t) for t in ctx.session.todos]
    place = todos.index(_find(todos, after)) + 1 if after else len(todos)
    number = max((t['id'] for t in todos), default=0) + 1
    todos.insert(place, {'id': number, 'content': content, 'status': 'pending'})
    return _show(ctx, todos)


def _find(todos: list[Todo], step: int) -> Todo:
    for t in todos:
        if t['id'] == step:
            return t
    raise ToolError(f'No step {step}. The list:\n{format_todos(todos)}')


def _show(ctx: ToolContext, todos: list[Todo]) -> str:
    """Put the list in place; with nothing left it is over."""
    done = all(t['status'] == 'completed' for t in todos)
    ctx.session.todos = [] if done else todos
    ctx.frontend.todos_updated(ctx.session.todos)
    return 'Todo list cleared' if done else 'Todo list updated:\n' + format_todos(todos)


def format_todos(todos: list[Todo]) -> str:
    return '\n'.join(f'{t["id"]}. {MARKS[t["status"]]} {t["content"]}' for t in todos) or '(empty)'


def summary_note(todos: list[Todo]) -> str:
    """The list as it stands, for a conversation that was just summarized; '' without one."""
    if not todos:
        return ''
    return f'<system-reminder>The task list now:\n{format_todos(todos)}</system-reminder>'


TOOLS = [
    Tool(
        'todo_write',
        'Write the task list shown to the user, or start it over when the whole plan changes. Use it '
        'for work with three or more steps, then keep it true with todo_update and todo_add. An empty '
        'list clears it, for when the work is dropped. Skip it for quick, single-step requests.',
        {
            'todos': prop(
                'array',
                'The full list, in order',
                items={
                    'type': 'object',
                    'properties': {
                        'content': {'type': 'string'},
                        'status': {'type': 'string', 'enum': list(STATUSES)},
                    },
                    'required': ['content', 'status'],
                },
            )
        },
        todo_write,
        required=['todos'],
    ),
    Tool(
        'todo_update',
        'Change one step of the task list. Call it the moment a step is finished and checked, with '
        'status completed: the next step then starts by itself, and closing the last one closes the '
        'list. Also to start another step, reword one, or drop one no longer needed (status removed).',
        {
            'step': prop('integer', 'The number of the step, as the list shows it'),
            'status': prop('string', 'Its new status', enum=[*STATUSES, 'removed']),
            'content': prop('string', 'Its new wording'),
        },
        todo_update,
        required=['step'],
    ),
    Tool(
        'todo_add',
        'Add a step to the task list, when the work turns out to need one the plan does not have.',
        {
            'content': prop('string', 'What the step is'),
            'after': prop('integer', 'The number of the step it comes after; leave it out for the end'),
        },
        todo_add,
        required=['content'],
    ),
]

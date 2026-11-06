"""read_skill / save_skill: the model reads the skills, and changes one when the user asks."""

from __future__ import annotations

from .. import config
from ..state.skills import SkillLibrary
from .base import Tool, ToolContext, ToolError, prop


def library() -> SkillLibrary:
    return SkillLibrary(config.SKILLS_DIR, config.LEARNED_SKILLS_DIR)


def read_skill(ctx: ToolContext, name: str) -> str:
    skill = library().get(name)
    if skill is None:
        names = ', '.join(s.name for s in library().all()) or 'none yet'
        raise ToolError(f'No skill named {name} (saved skills: {names})')
    return skill.body


def save_skill(ctx: ToolContext, name: str, description: str, body: str) -> str:
    try:
        path = library().save(name, description, body)
    except ValueError as e:
        raise ToolError(str(e)) from e
    ctx.frontend.file_written(
        ctx.workspace.rel(path) if path.startswith(ctx.workspace.root) else path, None, body
    )
    return f'Saved skill {name}; future sessions will see it in their skill list'


TOOLS = [
    Tool(
        'read_skill',
        'Read a skill: how to do a kind of task. Read it when the task needs '
        'the know-how it holds; skip it when the tool descriptions already cover the task.',
        {'name': prop('string', 'Skill name from the list in the system prompt')},
        read_skill,
        required=['name'],
    ),
    Tool(
        'save_skill',
        'Only when the user asks you in this conversation to make or change a skill; what you learn '
        'by yourself goes in memory, with remember. A skill says how to do a kind of task: the '
        'steps, the commands or code, and the pitfalls, verified to work; no timings or results from one '
        'device, and at most 60 lines: split a bigger one. A single fact is a memory. '
        'Only know-how that will help in other tasks, named after the technique (scene-collisions), '
        'never after this program (scene-breakout-game), without its file names or design: its one '
        'line goes in every future system prompt. Prefer adding to a skill on the topic: saving under '
        'an existing name replaces it, so read it first and keep what still holds.',
        {
            'name': prop('string', 'Short id: lowercase letters, digits and hyphens'),
            'description': prop(
                'string',
                'One line under 250 characters starting "Use when …" that says which tasks need it; '
                'shown in every future system prompt, so later sessions know when to read it',
            ),
            'body': prop('string', 'The procedure in Markdown'),
        },
        save_skill,
        required=['name', 'description', 'body'],
        readonly=False,
    ),
]

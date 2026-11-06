"""exit_plan_mode: present a plan for approval before anything is changed."""

from __future__ import annotations

from .base import Tool, ToolContext, ToolError, prop


def exit_plan_mode(ctx: ToolContext, plan: str) -> str:
    agent = ctx.agent
    if agent is None or agent.get_mode() != 'plan':
        raise ToolError('Plan mode is not on; just go ahead')
    agent.on_attention('The plan is ready for your review')
    choice, note = ctx.frontend.approve_plan(plan)
    if choice in ('acceptEdits', 'default'):
        agent.set_mode(choice)
        extra = ' File edits will run without asking.' if choice == 'acceptEdits' else ''
        return 'The user approved the plan. Carry it out now.' + extra
    return 'The user wants to keep planning.' + (f' Their note: {note}' if note else ' Ask what to change.')


TOOLS = [
    Tool(
        'exit_plan_mode',
        'In plan mode, present your plan (Markdown: the steps and the files you will change) for the user to '
        'approve. Only after approval may you change anything. Not needed outside plan mode.',
        {'plan': prop('string', 'The plan, in Markdown')},
        exit_plan_mode,
        required=['plan'],
    ),
]

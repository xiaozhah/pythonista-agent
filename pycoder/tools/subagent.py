"""task: hand a self-contained job to a subagent with its own conversation.

By default it only reads files. With writes it changes a copy of the workspace of its own
(state/worktree.py), merged back when it is done, so that several can change code at once. Either way
it can run code, as the user's mode decides.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from dataclasses import replace

from .. import config
from ..agent.permissions import RUN_TOOLS, Policy, ReadOnlyPolicy, WorktreePolicy, controls
from ..events import Frontend
from ..host import env
from ..state.checkpoints import Checkpoints
from ..state.workspace import Workspace
from ..state.worktree import Worktree, WorktreeError
from ..types import Block, Todo
from . import c_runner, python_runner
from .base import FilePreview, Tool, ToolContext, ToolError, prop
from .describe import describe_call

# Research needs care more than depth: a cheaper model at medium effort (the main agent checks the report)
SUBAGENT_MODEL = 'claude-sonnet-5-5'
SUBAGENT_EFFORT = 'medium'

SUBAGENT_PROMPT = """\
You are a subagent of pycoder, a coding agent running in {environment} with Python {python}. The \
main agent gave you one self-contained task. Your tools: {tools}. You can't change files with them; \
run code to find things out or check them, not to change anything. {code} iOS cannot run subprocesses, \
so there is no shell.

Workspace: {root}. Relative paths are relative to it; you can also read anywhere in the user's home \
(~) and in /local.
{docs}
Reply with a concise, complete report: the facts found, each with the file:line it comes from, and \
what you could not verify. The main agent sees only your final reply."""


WRITING_PROMPT = """\
You are a subagent of pycoder, a coding agent running in {environment} with Python {python}. The \
main agent gave you one self-contained change to make. Your tools: {tools}. Run the code to check \
your change. {code} iOS cannot run subprocesses, so there is no shell.

Workspace: {root}, a copy of the project that is yours alone. Any path the task gives inside the \
project means the same file in this copy, so use it here and don't report the difference. Your changes \
are merged into the project when you finish; other subagents may be changing it at the same time, so \
change only what your task is about, and make small edits rather than rewriting files, which merge \
cleanly.
{docs}
Reply with a concise report: what you changed, file by file, and anything you could not do. The main \
agent sees only your final reply."""

CODE_NOTE = (
    'The user may be asked first, and a denial is an answer: go on without it. Subagents run code one at '
    'a time, in one process, in your workspace.'
)


def subagent_prompt(root: str, tool_names: list[str], template: str = SUBAGENT_PROMPT) -> str:
    docs = (
        '\nCheck the names of Pythonista APIs (ui, scene, photos, objc_util, ...) in pythonista_docs '
        'rather than trusting memory.\n'
        if 'pythonista_docs' in tool_names
        else ''
    )
    return template.format(
        environment=env.describe(),
        python=env.python_version(),
        tools=', '.join(tool_names),
        code=CODE_NOTE,
        root=root,
        docs=docs,
    )


class SubagentFrontend(Frontend):
    """Shows a subagent's work as one-line progress under its task card; everything else stays hidden."""

    def __init__(self, parent: Frontend, key: str) -> None:
        self.parent = parent
        self.key = key

    def tool_input_done(self, index: int, block: Block) -> None:
        self.parent.subagent_progress(
            '{}({})'.format(block['name'], describe_call(block['name'], block['input'])), self.key
        )

    def confirm(
        self, name: str, inp: Block, preview: FilePreview | None = None, rule: str = ''
    ) -> tuple[str, str | None]:
        with _asking:
            return self.parent.confirm(name, inp, preview, rule)

    def notice(self, text: str, level: str = 'info') -> None:
        if level != 'info':
            self.parent.subagent_progress(text, self.key)

    def todos_updated(self, todos: Sequence[Todo]) -> None: ...


_merging = threading.Lock()  # subagents finish at the same time, and merge one after another
_asking = threading.Lock()  # one question on screen at a time
_running = threading.Lock()  # a run's working folder and sys.path belong to the whole process


def code_tools() -> list[Tool]:
    """run_python and run_c as a subagent has them: one run at a time, and none left behind when the
    subagent ends (its copy of the workspace is gone by then)."""

    def one_at_a_time(tool: Tool) -> Tool:
        def run(ctx: ToolContext, **inp: object) -> str | list[Block]:
            while not _running.acquire(timeout=0.2):
                ctx.cancel.check()
            try:
                scan = ctx.checkpoints.scan()  # here rather than in the agent: one run at a time sees it
                try:
                    return tool.run(ctx, **inp)
                finally:
                    ctx.checkpoints.record(scan)
            finally:
                _running.release()

        properties = {name: spec for name, spec in tool.properties.items() if name != 'background'}
        description = python_runner.RUN_FOREGROUND if tool.name == 'run_python' else tool.description
        return replace(tool, description=description, properties=properties, run=run, writes_anywhere=False)

    return [one_at_a_time(t) for t in python_runner.TOOLS + c_runner.TOOLS if t.name in RUN_TOOLS]


def _run(
    ctx: ToolContext,
    tools: list[Tool],
    template: str,
    workspace: Workspace,
    checkpoints: Checkpoints,
    policy: Policy,
    prompt: str,
    max_steps: int,
) -> str:
    """The subagent's report, or the failure as an exception."""
    parent = ctx.agent
    assert parent is not None
    from ..agent.loop import Agent, AgentSettings

    names = [t.name for t in tools] + (['web_search', 'web_fetch'] if parent.settings.web else [])
    settings = AgentSettings(
        # never dearer than the main agent's model
        model=min(SUBAGENT_MODEL, parent.settings.model, key=lambda m: config.price_for(m)[0]),
        effort=SUBAGENT_EFFORT,
        system=subagent_prompt(workspace.root, names, template),
        web=parent.settings.web,
        max_steps=max_steps,
        cache_ttl='5m',  # it runs without pauses, so the cheaper short cache always holds
    )
    key = ctx.call_id
    sub = Agent(
        parent.client,
        tools,
        settings,
        SubagentFrontend(ctx.frontend, key),
        ctx.cancel,
        workspace,
        ctx.session,
        checkpoints,
        policy,
        on_usage=parent.on_usage,
        on_attention=parent.on_attention,
    )
    result = sub.run_turn([], [{'type': 'text', 'text': prompt}])
    if result.status == 'interrupted':
        raise KeyboardInterrupt
    if result.status == 'exhausted':
        raise ToolError(
            f'The subagent ran out of steps ({max_steps}) before finishing; its last words: '
            + (result.text or '(none)')
        )
    if result.status != 'done':
        raise ToolError('The subagent failed: %s' % (result.text or result.status))
    return result.text or '(the subagent returned no text)'


def _in_a_worktree(ctx: ToolContext, prompt: str) -> str:
    """Change a copy of the workspace, then merge it back. Nothing reaches the workspace if it fails."""
    from .registry import writing_subagent_tools

    assert ctx.agent is not None
    policy = ctx.agent.policy
    tree = Worktree(ctx.workspace.root)
    keep = False
    try:
        try:
            work = tree.create(leave_out=policy.denies)
        except WorktreeError as e:
            raise ToolError(str(e)) from e
        workspace = Workspace(work)
        report = _run(
            ctx,
            writing_subagent_tools(),
            WRITING_PROMPT,
            workspace,
            Checkpoints(ctx.session, workspace),  # no turn: rewinding is for the merge, below
            WorktreePolicy(policy),
            prompt,
            config.WRITING_SUBAGENT_MAX_TURNS,
        )

        def allowed(rel: str) -> bool:
            full = os.path.join(ctx.workspace.root, rel)
            bypass = policy.get_mode() == 'bypass'
            return not policy.denies(rel) and (bypass or not controls(full))

        with _merging:
            merged = tree.merge(lambda full, removing: ctx.checkpoints.before_write(full, removing), allowed)
        lines = [report, '']
        lines.append('Merged into the workspace: ' + (', '.join(merged.applied) or 'nothing'))
        if merged.conflicts or merged.refused:
            keep = True
            if merged.conflicts:
                lines.append(
                    'Not merged, changed here too in the same places: ' + ', '.join(merged.conflicts)
                )
            if merged.refused:
                lines.append('Not merged, a rule protects them: ' + ', '.join(merged.refused))
            lines.append(f"The subagent's versions are in {ctx.workspace.rel(tree.work)}")
        return '\n'.join(lines)
    finally:
        if not keep:
            tree.remove()


def task(ctx: ToolContext, description: str, prompt: str, writes: bool = False) -> str:
    if ctx.agent is None:
        raise ToolError('task is not available here')
    from .registry import subagent_tools

    key = ctx.call_id
    ctx.frontend.subagent_start(description, key)
    try:
        if writes:
            report = _in_a_worktree(ctx, prompt)
        else:
            report = _run(
                ctx,
                subagent_tools(),
                SUBAGENT_PROMPT,
                ctx.workspace,
                ctx.checkpoints,
                ReadOnlyPolicy(ctx.agent.policy),
                prompt,
                config.SUBAGENT_MAX_TURNS,
            )
    except ToolError as e:
        ctx.frontend.subagent_done(str(e), key)
        raise
    ctx.frontend.subagent_done(report, key)
    return report


TOOLS = [
    Tool(
        'task',
        'Start a subagent for a self-contained job: broad searches, reading across many files, '
        'or research. It has its own context, so only its final report comes back, keeping this '
        'conversation small. Give it a complete brief; it cannot ask you questions. It can run code, '
        'as the mode allows, so it can compute and check things, not only read. '
        'Several task calls in one reply run at the same time. With writes it can also change files, '
        'in its own copy of the workspace, merged back when it finishes (conflicts come back to you): '
        'use it for separate changes that can go on in parallel, each to its own files.',
        {
            'description': prop('string', 'A 3-6 word label shown to the user'),
            'prompt': prop('string', 'The full task: what to find or answer, where to look, what to report'),
            'writes': prop(
                'boolean', 'Let it change files, in a copy of the workspace (default: it changes none)'
            ),
        },
        task,
        required=['description', 'prompt'],
        readonly=False,
        safe_input=lambda inp: not inp.get('writes'),
    ),
]

"""What a tool is, what it gets to work with, and input validation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..cancel import CancelToken
from ..events import Frontend
from ..state.checkpoints import Checkpoints
from ..state.session import Session
from ..state.workspace import ToolError, Workspace
from ..types import JSON, Block

if TYPE_CHECKING:
    from ..agent.loop import Agent

__all__ = ['FilePreview', 'Tool', 'ToolContext', 'ToolError', 'prop', 'validate_input']

FilePreview = tuple[
    str, 'str | None', str
]  # (workspace-relative path, current content or None if new, new content)


@dataclass
class ToolContext:
    workspace: Workspace
    frontend: Frontend
    session: Session
    checkpoints: Checkpoints
    cancel: CancelToken
    agent: Agent | None = None  # the agent running this tool; the task tool starts subagents from it
    call_id: str = ''  # the tool_use id of the call being run

    def denied(self, full: str) -> bool:
        """Whether a deny rule covers this file, for tools that walk a folder: the permission check
        only sees the folder they were given."""
        return self.agent is not None and self.agent.policy.denies(self.workspace.rel(full))


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, JSON]
    run: Callable[..., str | list[Block]]  # run(ctx, **input) -> result text, or blocks (images)
    required: list[str] = field(default_factory=list)
    readonly: bool = True  # False: asks the user first unless bypass is on
    safe_input: Callable[[JSON], bool] | None = None  # for a write tool: inputs that only read (no question)
    preview: Callable[..., FilePreview] | None = (
        None  # preview(ctx, **input): the change, shown before asking
    )
    # it may change any file without telling the checkpoints (running code, git): the workspace is
    # compared before and after it runs, so /rewind can undo that too
    writes_anywhere: bool = False

    def needs_confirmation(self, inp: JSON) -> bool:
        return not self.readonly and not (self.safe_input is not None and self.safe_input(inp))

    def schema(self) -> JSON:
        return {
            'name': self.name,
            'description': self.description,
            'input_schema': {'type': 'object', 'properties': self.properties, 'required': self.required},
            # stream large inputs (whole files) as they are generated; see validate_input
            'eager_input_streaming': True,
        }


def prop(type_: str, description: str, **extra: Any) -> JSON:
    return {'type': type_, 'description': description, **extra}


_PY_TYPES: dict[str, type | tuple[type, ...]] = {
    'string': str,
    'integer': int,
    'boolean': bool,
    'array': list,
    'object': dict,
    'number': (int, float),
}


def validate_input(tool: Tool, data: Any) -> str | None:
    """Eagerly streamed input isn't validated by the API, so check it before running. None if fine.

    Only what this check understands is checked (a schema may use anyOf or keywords it doesn't
    know); the rest is left to the tool.
    """
    if not isinstance(data, dict):
        return 'Input must be an object'
    for key in tool.required:
        if key not in data:
            return f'Missing required parameter {key}'
    for key, value in data.items():
        spec = tool.properties.get(key)
        if spec is None:
            return f'Unknown parameter {key}'
        if not _is_type(value, spec.get('type')):
            want = spec['type']
            return f'Parameter {key} must be of type {want}'
        if isinstance(spec.get('enum'), list) and value not in spec['enum']:
            return 'Parameter {} must be one of {}'.format(key, ', '.join(map(str, spec['enum'])))
    return None


def _is_type(value: Any, type_: Any) -> bool:
    """Whether value is of the JSON Schema type; True for a type this check doesn't know."""
    want = _PY_TYPES.get(type_) if isinstance(type_, str) else None
    if want is None:
        return True
    return isinstance(value, want) and not (type_ in ('integer', 'number') and isinstance(value, bool))

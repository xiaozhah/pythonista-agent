"""Which tools the main agent and subagents get."""

from __future__ import annotations

from ..host import env
from ..host.cwasm import jsc
from . import (
    c_runner,
    code,
    docs,
    file_ops,
    files,
    git,
    install,
    ios,
    jobs,
    memory,
    plan,
    python_runner,
    screen,
    skills,
    subagent,
    todos,
    vision,
)
from .base import Tool


def main_tools(with_memory: bool = True) -> list[Tool]:
    """Everything."""
    return (
        files.TOOLS
        + code.TOOLS
        + file_ops.TOOLS
        + python_runner.TOOLS
        + jobs.TOOLS
        + (c_runner.TOOLS if jsc.available() else [])
        + todos.TOOLS
        + plan.TOOLS
        + subagent.TOOLS
        + skills.TOOLS
        + (memory.TOOLS if with_memory else [])
        + ios.COMMON
        + (ios.PYTHONISTA + screen.TOOLS if env.IN_PYTHONISTA else [])
        + (vision.TOOLS if env.IN_PYTHONISTA else [])
        + (docs.TOOLS if env.docs_archive() else [])
        + install.TOOLS
        + git.TOOLS
    )


def writing_subagent_tools() -> list[Tool]:
    """To read and change files, in its own copy of the workspace, and to run code."""
    return subagent_tools() + [t for t in files.TOOLS + file_ops.TOOLS if not t.readonly]


def subagent_tools() -> list[Tool]:
    """Tools that read, and running code as the user's mode decides: it researches, changing no file."""
    tools = files.TOOLS + code.TOOLS + skills.TOOLS + (docs.TOOLS if env.docs_archive() else [])
    return [t for t in tools if t.readonly] + subagent.code_tools()

"""Slash commands: the table (registry), the commands by topic, and the palette and Tab completion."""

from .info import context_report
from .palette import complete, suggestions
from .registry import all_commands, run_command

__all__ = ['all_commands', 'complete', 'context_report', 'run_command', 'suggestions']

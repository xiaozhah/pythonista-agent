"""Type aliases for the JSON structures exchanged with the Claude API."""

from __future__ import annotations

from typing import Any

JSON = dict[str, Any]
Block = dict[str, Any]  # one content block: text, thinking, tool_use, tool_result, image, compaction, ...
Message = dict[str, Any]  # {'role': ..., 'content': str | list[Block]}
Usage = dict[str, Any]
Todo = dict[str, Any]  # {'id': 1, 'content': ..., 'status': 'pending' | 'in_progress' | 'completed'}

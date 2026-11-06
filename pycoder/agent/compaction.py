"""Keeping long conversations inside the context window with on-demand compaction.

The API summarizes the whole conversation into one signed `compaction` block; that block then
replaces every earlier message and must be sent back exactly as returned.
"""

from __future__ import annotations

from ..types import Block, Message, Usage

INSTRUCTIONS = """\
Summarize this coding session so the work can continue from the summary alone. Keep: the user's \
goals and preferences, decisions made and why, every file created or changed (with paths) and its \
current state, commands or code that worked, errors still open, the current todo list, and the \
user's latest request and what remains to do for it. Be specific; drop chit-chat. Do not call tools; \
respond with the summary text only."""


def context_tokens(usage: Usage) -> int:
    """Size of the last request plus its reply: roughly the next request's size."""
    return sum(
        int(usage.get(k) or 0)
        for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')
    )


def needs_compaction(usage: Usage, threshold: int) -> bool:
    return threshold > 0 and context_tokens(usage) >= threshold


def can_compact(messages: list[Message]) -> bool:
    """Not with nothing to summarize, nor while a tool call is still waiting for its result."""
    if not messages:
        return False
    last = messages[-1]
    if last['role'] == 'assistant' and isinstance(last['content'], list):
        return not any(b.get('type') == 'tool_use' for b in last['content'])
    return True


def apply(block: Block) -> list[Message]:
    """The new conversation: just the compaction block."""
    return [{'role': 'assistant', 'content': [block]}]


def total_usage(usage: Usage) -> Usage:
    """A compaction response reports its cost in usage.iterations, not the top-level counts."""
    total: Usage = {}
    for item in usage.get('iterations') or [usage]:
        for key in (
            'input_tokens',
            'output_tokens',
            'cache_read_input_tokens',
            'cache_creation_input_tokens',
        ):
            total[key] = int(total.get(key, 0)) + int(item.get(key) or 0)
        hour = int((item.get('cache_creation') or {}).get('ephemeral_1h_input_tokens') or 0)
        if hour:  # priced differently, so it must not vanish in the sum
            made = total.setdefault('cache_creation', {'ephemeral_1h_input_tokens': 0})
            made['ephemeral_1h_input_tokens'] += hour
    return total

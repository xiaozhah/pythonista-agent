"""Assemble a streamed response into content blocks, reporting progress to the frontend."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from ..cancel import CancelToken
from ..events import Frontend
from ..types import Block, Usage


class StreamInterrupted(KeyboardInterrupt):
    """The user stopped the response; `text` is what had arrived by then."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


class StreamError(Exception):
    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass
class AssistantMessage:
    content: list[Block] = field(default_factory=list)
    stop_reason: str | None = None
    stop_details: dict[str, Any] | None = None
    usage: Usage = field(default_factory=dict)
    model: str | None = None
    invalid_json: dict[str, str] = field(default_factory=dict)  # tool_use id -> raw input that didn't parse

    @property
    def tool_uses(self) -> list[Block]:
        return [b for b in self.content if b['type'] == 'tool_use']

    @property
    def text(self) -> str:
        return '\n\n'.join(b['text'] for b in self.content if b['type'] == 'text' and b.get('text'))


def consume_stream(
    events: Iterable[dict[str, Any]], frontend: Frontend, cancel: CancelToken
) -> AssistantMessage:
    msg = AssistantMessage()
    blocks: dict[int, Block] = {}
    partial_json: dict[int, str] = {}
    frontend.stream_start()
    try:
        for ev in _until_stopped(events, cancel):
            cancel.check()
            kind = ev.get('type')
            if kind == 'message_start':
                msg.model = ev['message'].get('model')
                msg.usage.update(ev['message'].get('usage') or {})
            elif kind == 'content_block_start':
                _block_start(ev['index'], dict(ev['content_block']), blocks, partial_json, frontend)
            elif kind == 'content_block_delta':
                _block_delta(ev['index'], ev['delta'], blocks, partial_json, frontend)
            elif kind == 'content_block_stop':
                _block_stop(ev['index'], blocks, partial_json, msg, frontend)
            elif kind == 'message_delta':
                msg.stop_reason = ev['delta'].get('stop_reason')
                msg.stop_details = ev['delta'].get('stop_details')
                msg.usage.update(ev.get('usage') or {})
            elif kind == 'error':
                err = ev.get('error', {})
                raise StreamError(
                    '{}: {}'.format(err.get('type'), err.get('message')),
                    retryable=err.get('type') in ('overloaded_error', 'api_error'),
                )
    except KeyboardInterrupt:
        parts = [blocks[i].get('text', '') for i in sorted(blocks) if blocks[i].get('type') == 'text']
        raise StreamInterrupted('\n\n'.join(p for p in parts if p)) from None
    finally:
        frontend.stream_end()
    if msg.stop_reason is None:
        raise StreamError('The response ended early (no stop reason)', retryable=True)
    msg.content = [blocks[i] for i in sorted(blocks)]
    return msg


def _until_stopped(events: Iterable[dict[str, Any]], cancel: CancelToken) -> Iterator[dict[str, Any]]:
    """The events; a Stop closes the connection, and the error that makes is the Stop."""
    try:
        yield from events
    except Exception:
        if cancel.cancelled:
            cancel.check()  # raises Cancelled
        raise


def _block_start(
    i: int, block: Block, blocks: dict[int, Block], partial_json: dict[int, str], frontend: Frontend
) -> None:
    blocks[i] = block
    kind = block['type']
    if kind in ('tool_use', 'server_tool_use'):
        partial_json[i] = ''
        frontend.tool_start(i, block)
    elif kind == 'thinking':
        frontend.thinking_start()
    elif kind == 'fallback':
        frontend.notice('(switched to a fallback model to continue)', 'warn')
    elif kind.endswith('_tool_result'):
        content = block.get('content')
        frontend.server_result(
            kind.replace('_tool_result', ''), len(content) if isinstance(content, list) else 1
        )


def _block_delta(
    i: int, delta: dict[str, Any], blocks: dict[int, Block], partial_json: dict[int, str], frontend: Frontend
) -> None:
    block = blocks[i]
    kind = delta.get('type')
    if kind == 'text_delta':
        block['text'] = block.get('text', '') + delta['text']
        frontend.text_delta(i, delta['text'])
    elif kind == 'thinking_delta':
        block['thinking'] = block.get('thinking', '') + delta['thinking']
        frontend.thinking_delta(delta['thinking'])
    elif kind == 'signature_delta':
        block['signature'] = delta['signature']
    elif kind == 'input_json_delta':
        chunk = delta.get('partial_json', '')
        partial_json[i] += chunk
        frontend.tool_input(i, chunk)
    elif kind == 'citations_delta':
        block.setdefault('citations', []).append(delta['citation'])


def _block_stop(
    i: int, blocks: dict[int, Block], partial_json: dict[int, str], msg: AssistantMessage, frontend: Frontend
) -> None:
    block = blocks[i]
    if block['type'] == 'text':
        frontend.text_done(i)
    if i in partial_json:
        raw = partial_json.pop(i)
        try:
            # some blocks arrive whole in content_block_start, with no input deltas
            block['input'] = json.loads(raw) if raw.strip() else block.get('input') or {}
        except ValueError:
            block['input'] = {}
            msg.invalid_json[block['id']] = raw
        frontend.tool_input_done(i, block)


def echo_content(content: list[Block]) -> list[Block]:
    """Content to send back after a mid-output fallback: drop thinking, tool calls and the results of
    server-side calls from before the switch (a result without its call is invalid)."""
    last = max((i for i, b in enumerate(content) if b['type'] == 'fallback'), default=-1)
    if last < 0:
        return content
    dropped = ('thinking', 'redacted_thinking', 'tool_use', 'server_tool_use')
    return [
        b
        for i, b in enumerate(content)
        if i >= last or not (b['type'] in dropped or b['type'].endswith('_tool_result'))
    ]

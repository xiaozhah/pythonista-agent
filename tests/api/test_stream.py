"""SSE parsing and assembling streamed responses into content blocks."""

from __future__ import annotations

import json
from typing import Any

import pytest

from pycoder.api.sse import iter_sse
from pycoder.api.stream import consume_stream, echo_content
from pycoder.cancel import CancelToken
from tests.conftest import RecordingFrontend, tool_reply

END: dict[str, Any] = {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {}}


def test_iter_sse_joins_data_lines_and_skips_other_fields() -> None:
    lines = ['event: ping', 'data: {"a":', 'data: 1}', '', 'data: {"b": 2}', '']
    assert list(iter_sse(lines)) == [{'a': 1}, {'b': 2}]


def test_tool_input_streams_and_parses() -> None:
    fe = RecordingFrontend()
    msg = consume_stream(tool_reply('write_file', {'path': 'a.py', 'content': 'x = 1\n'}), fe, CancelToken())
    assert msg.stop_reason == 'tool_use'
    assert msg.tool_uses[0]['input'] == {'path': 'a.py', 'content': 'x = 1\n'}
    assert len(fe.named('tool_input')) > 1  # arrived in several chunks
    assert fe.named('tool_input_done')


def test_invalid_tool_json_is_recorded_not_raised() -> None:
    events: list[dict[str, Any]] = [
        {
            'type': 'content_block_start',
            'index': 0,
            'content_block': {'type': 'tool_use', 'id': 't', 'name': 'x'},
        },
        {
            'type': 'content_block_delta',
            'index': 0,
            'delta': {'type': 'input_json_delta', 'partial_json': '{"a": '},
        },
        {'type': 'content_block_stop', 'index': 0},
        END,
    ]
    msg = consume_stream(events, RecordingFrontend(), CancelToken())
    assert msg.invalid_json == {'t': '{"a": '}


def test_block_that_arrives_whole_keeps_its_input() -> None:
    block = {'type': 'server_tool_use', 'id': 'm', 'name': 'lookup', 'input': {'q': 'x'}}
    events: list[dict[str, Any]] = [
        {'type': 'content_block_start', 'index': 0, 'content_block': block},
        {'type': 'content_block_stop', 'index': 0},
        END,
    ]
    msg = consume_stream(events, RecordingFrontend(), CancelToken())
    assert msg.content[0]['input'] == {'q': 'x'}


def test_thinking_and_signature_are_kept_for_echoing() -> None:
    events: list[dict[str, Any]] = [
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'hm'}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': 'sig'}},
        {'type': 'content_block_stop', 'index': 0},
        END,
    ]
    fe = RecordingFrontend()
    msg = consume_stream(events, fe, CancelToken())
    assert msg.content == [{'type': 'thinking', 'thinking': 'hm', 'signature': 'sig'}]
    assert [name for name, _ in fe.calls if name.startswith('thinking')] == [
        'thinking_start',
        'thinking_delta',
    ]


def test_echo_drops_thinking_and_tool_calls_before_a_fallback() -> None:
    content: list[dict[str, Any]] = [
        {'type': 'thinking'},
        {'type': 'text', 'text': 'a'},
        {'type': 'tool_use', 'id': 'x'},
        {'type': 'fallback'},
        {'type': 'thinking'},
        {'type': 'text', 'text': 'b'},
    ]
    assert [b['type'] for b in echo_content(content)] == ['text', 'fallback', 'thinking', 'text']


def test_cancel_stops_the_stream() -> None:
    cancel = CancelToken()
    cancel.cancel()
    try:
        consume_stream(tool_reply('x', {}), RecordingFrontend(), cancel)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError('expected an interruption')
    assert json.dumps({}) == '{}'


def test_a_stream_that_ends_early_is_an_error() -> None:
    from pycoder.api.stream import StreamError

    events: list[dict[str, Any]] = [
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}}
    ]
    with pytest.raises(StreamError, match='ended early'):
        consume_stream(events, RecordingFrontend(), CancelToken())


def test_echo_drops_server_tool_results_before_a_fallback() -> None:
    content: list[dict[str, Any]] = [
        {'type': 'server_tool_use', 'id': 's1', 'name': 'web_search', 'input': {}},
        {'type': 'web_search_tool_result', 'tool_use_id': 's1', 'content': []},
        {'type': 'fallback'},
        {'type': 'server_tool_use', 'id': 's2', 'name': 'web_search', 'input': {}},
        {'type': 'web_search_tool_result', 'tool_use_id': 's2', 'content': []},
    ]
    kept = echo_content(content)
    assert [b['type'] for b in kept] == ['fallback', 'server_tool_use', 'web_search_tool_result']


def test_requests_transport_reuses_one_session(monkeypatch: Any) -> None:
    import requests

    from pycoder.api.client import RequestsTransport

    made: list[Any] = []

    class FakeSession:
        def close(self) -> None:
            pass

        def __init__(self) -> None:
            made.append(self)
            self.posts = 0

        def post(self, *args: Any, **kwargs: Any) -> Any:
            self.posts += 1
            return object()

    monkeypatch.setattr(requests, 'Session', FakeSession)
    transport = RequestsTransport()
    transport.post('u', {}, {}, True)
    transport.post('u', {}, {}, False)
    assert len(made) == 1
    assert made[0].posts == 2


def test_a_line_separator_in_a_reply_does_not_split_its_line() -> None:
    from pycoder.api.sse import iter_sse

    line = '\n'.join(['data: {"text": "a b"}', '', '']).encode('utf-8')
    assert list(iter_sse(line.splitlines())) == [{'text': 'a b'}]


def test_a_reply_cut_in_the_middle_of_a_line_is_tried_again() -> None:
    from pycoder.api.client import ApiClient
    from tests.conftest import FakeResponse, FakeTransport, text_reply

    class Cut(FakeResponse):
        def iter_lines(self, chunk_size: Any = None, decode_unicode: bool = False) -> Any:
            yield b'data: {"type": "content_block_start", "ind'

    api = FakeTransport([Cut([]), text_reply('whole')])
    client = ApiClient('k', api, sleep=lambda s: None)
    msg = client.stream_turn({'model': 'm'}, RecordingFrontend(), CancelToken())
    assert msg.text == 'whole'

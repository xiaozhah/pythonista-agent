"""The turn loop: what stays in the conversation when a request fails part-way."""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import FakeResponse, FakeTransport, RecordingFrontend, text_reply, tool_reply

BAD = FakeResponse(status=400, body={'error': {'message': 'bad request'}})


def test_a_failed_request_after_tools_ran_keeps_their_record(make_controller: Any, workspace: str) -> None:
    import os

    api = FakeTransport([tool_reply('write_file', {'path': 'new.txt', 'content': 'hi'}), BAD])
    c = make_controller(api)
    c.settings.mode = 'bypass'
    result = c.run_turn('make new.txt')
    assert result.status == 'error'
    assert not result.rolled_back
    assert os.path.exists(os.path.join(workspace, 'new.txt'))
    kinds = [
        b.get('type')
        for m in c.session.messages
        for b in (m['content'] if isinstance(m['content'], list) else [])
    ]
    assert 'tool_use' in kinds
    assert 'tool_result' in kinds
    assert 'failed after the tool calls' in str(c.session.messages[-1]['content'])
    assert [t.text for t in c.session.turns] == ['make new.txt']  # /rewind can still undo it


def test_a_failed_request_before_any_tool_is_rolled_back(make_controller: Any) -> None:
    api = FakeTransport([BAD])
    c = make_controller(api)
    result = c.run_turn('hello')
    assert result.rolled_back
    assert c.session.messages == []
    assert c.session.turns == []


# ---- every tool_use gets a tool_result


def _tool_results(message: Any) -> list[Any]:
    return [b for b in message['content'] if b.get('type') == 'tool_result']


def test_a_failure_around_a_tool_is_an_error_result_and_the_turn_goes_on(
    make_controller: Any, monkeypatch: Any
) -> None:
    from pycoder.tools.base import Tool

    def preview(ctx: Any, **inp: Any) -> Any:
        raise OSError('disk gone')

    api = FakeTransport([tool_reply('a_tool', {'x': 'v'}), text_reply('ok')])
    # a tool with an anyOf parameter and a preview that fails
    tool = Tool(
        'a_tool',
        'm',
        {'x': {'type': 'string'}, 'y': {'anyOf': [{'type': 'string'}]}},
        lambda ctx, **inp: 'ran',
        readonly=False,
        preview=preview,
    )
    monkeypatch.setattr('pycoder.app.controller.main_tools', lambda **_: [tool])
    c = make_controller(api)
    result = c.run_turn('go')
    assert result.status == 'done'
    sent = _tool_results(api.requests[1]['messages'][-1])
    assert sent[0]['is_error']
    assert 'OSError: disk gone' in sent[0]['content']


def test_an_error_outside_any_tool_still_leaves_valid_history(make_controller: Any) -> None:
    import pytest

    class Broken(RecordingFrontend):
        def tool_run(self, block: Any) -> None:
            raise RuntimeError('frontend bug')

    api = FakeTransport([tool_reply('read_file', {'path': 'hello.py'})])
    c = make_controller(api, Broken())
    with pytest.raises(RuntimeError):
        c.run_turn('go')
    results = _tool_results(c.session.messages[-1])
    assert results
    assert results[0]['tool_use_id'] == 'tool1'
    assert results[0]['is_error']


def test_validate_input_checks_what_it_understands() -> None:
    from pycoder.tools.base import Tool, validate_input

    tool = Tool(
        't',
        '',
        {
            'n': {'type': 'integer'},
            'm': {'type': 'string'},
            'e': {'type': 'integer', 'enum': [1, 2]},
        },
        lambda ctx: '',
    )
    assert validate_input(tool, {'m': 'x', 'n': 3, 'e': 2}) is None
    assert validate_input(tool, {'m': 5}) == 'Parameter m must be of type string'
    assert validate_input(tool, {'n': True}) == 'Parameter n must be of type integer'
    assert validate_input(tool, {'e': 3}) == 'Parameter e must be one of 1, 2'


def test_tool_results_are_normalised_and_cut() -> None:
    from pycoder import config
    from pycoder.agent.loop import tool_result

    assert tool_result('a', None)['content'] == '(no output)'
    assert tool_result('a', '')['content'] == '(no output)'
    assert tool_result('a', 3)['content'] == '3'
    assert tool_result('a', {'k': 'v'})['content'] == '{"k": "v"}'
    assert tool_result('a', ['x', 'y'])['content'] == '["x", "y"]'
    big = 'x' * (config.MAX_TOOL_OUTPUT + 10)
    image = {'type': 'image', 'source': {}}
    blocks = tool_result('a', [{'type': 'text', 'text': big}, image, {'type': 'text', 'text': ''}])['content']
    assert len(blocks) == 2
    assert blocks[1] == image
    assert 'truncated' in blocks[0]['text']
    assert len(blocks[0]['text']) < len(big) + 100


# ---- server-side tools and the permission policy


def _tool_names(body: Any) -> list[str]:
    return [t.get('name') for t in body['tools']]


def test_server_tools_follow_deny_rules(make_controller: Any) -> None:
    api = FakeTransport([text_reply('a'), text_reply('b')])
    c = make_controller(api)
    c.run_turn('hi')
    assert {'web_search', 'web_fetch'} <= set(_tool_names(api.requests[0]))
    c.settings.deny = ['web_fetch']
    c.run_turn('again')
    names = _tool_names(api.requests[1])
    assert 'web_search' in names
    assert 'web_fetch' not in names


def test_web_tool_versions_depend_on_the_model(make_controller: Any) -> None:
    api = FakeTransport([text_reply('a')])
    c = make_controller(api)
    c.settings.model = 'claude-haiku-5-5'
    c.run_turn('hi')
    types = {t['name']: t['type'] for t in api.requests[0]['tools'] if 'type' in t}
    assert types == {'web_search': 'web_search_20250305', 'web_fetch': 'web_fetch_20250910'}


# ---- compaction inside a long turn


def test_a_turn_that_grows_too_large_is_compacted_between_steps(make_controller: Any) -> None:
    block = {'type': 'compaction', 'content': 's', 'signature': 'x'}
    compacted = FakeResponse(body={'content': [block], 'stop_reason': 'compaction', 'usage': {}})
    api = FakeTransport(
        [tool_reply('read_file', {'path': 'hello.py'}), compacted, text_reply('done'), compacted]
    )
    c = make_controller(api)
    c.settings.compact_at = 50  # the fake reports 100 input tokens
    result = c.run_turn('go')
    assert result.status == 'done'
    after = api.requests[2]['messages']  # the request after the mid-turn compaction
    assert after[0] == {'role': 'assistant', 'content': [block]}
    assert after[1]['role'] == 'user'
    assert 'summarized' in after[1]['content'][0]['text']
    assert c.session.compactions == 2  # once mid-turn, once after it


def test_a_summary_is_followed_by_the_task_list(make_controller: Any) -> None:
    block = {'type': 'compaction', 'content': 's', 'signature': 'x'}
    compacted = FakeResponse(body={'content': [block], 'stop_reason': 'compaction', 'usage': {}})
    c = make_controller(FakeTransport([text_reply('hi'), compacted, compacted]))
    c.run_turn('go')
    c.session.todos = [{'id': 7, 'content': 'keep me', 'status': 'in_progress'}]
    assert c.compact()
    assert '7. ▶ keep me' in str(c.session.messages[-1])
    c.session.todos = []
    assert c.compact()
    assert len(c.session.messages) == 1  # nothing to add without a list


def test_a_list_saved_before_steps_had_numbers_gets_them() -> None:
    from pycoder.state.session import Session

    saved = Session(id='x', root='r', model='m', system='s', web=False)
    saved.todos = [{'content': 'a', 'status': 'pending'}]
    assert Session.from_json(saved.to_json()).todos == [{'id': 1, 'content': 'a', 'status': 'pending'}]


# ---- resuming on another device


def test_resuming_on_another_device_adds_a_note(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('hi')]))
    c.run_turn('hello')
    from pycoder.host import env

    here = env.describe()
    c.session.system = c.session.system.replace(here, 'some other device')
    c.save()
    c.resume(c.session.id)
    note = c.session.messages[-1]['content'][-1]['text']
    assert f'continues in {here}' in note
    assert c.workspace.root in note
    c.save()
    c.resume(c.session.id)  # said already: not again
    assert sum('continues in' in str(m['content']) for m in c.session.messages) == 1
    c2 = make_controller()
    c2.resume(c.session.id)
    assert c2.session.messages == c.session.messages


def test_a_stop_during_a_paused_reply_leaves_history_the_api_accepts(make_controller: Any) -> None:
    from pycoder.cancel import Cancelled

    block = {'type': 'server_tool_use', 'id': 's', 'name': 'web_search', 'input': {}}
    paused: list[dict[str, Any]] = [
        {'type': 'content_block_start', 'index': 0, 'content_block': block},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'message_delta', 'delta': {'stop_reason': 'pause_turn'}, 'usage': {'output_tokens': 1}},
    ]

    class StoppedSecondTime(FakeTransport):
        def post(self, url: str, headers: Any, body: Any, stream: bool) -> Any:
            if self.requests:
                raise Cancelled()
            return super().post(url, headers, body, stream)

    c = make_controller(StoppedSecondTime([paused]))
    c.run_turn('look')
    assert 'server_tool_use' not in str(c.session.messages)


def test_a_stop_reaches_every_subagent_until_the_next_request() -> None:
    from pycoder.cancel import Cancelled, CancelToken

    token = CancelToken()
    token.cancel()
    for _ in range(2):  # two threads each see it: seeing it doesn't clear it
        with pytest.raises(Cancelled):
            token.check()
    token.reset()
    token.check()


def test_a_closed_token_stays_stopped() -> None:
    from pycoder.cancel import CancelToken

    token = CancelToken()
    token.close()
    token.reset()
    assert token.cancelled

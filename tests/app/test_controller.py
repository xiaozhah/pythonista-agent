"""Whole turns through the controller against a scripted fake API."""

from __future__ import annotations

import json
import os
import sys
import types
from typing import Any

from pycoder.app import reports
from pycoder.app.commands import complete, context_report, run_command
from tests.conftest import FakeResponse, FakeTransport, RecordingFrontend, text_reply, tool_reply


def read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def test_turn_runs_a_tool_and_sends_its_result(make_controller: Any) -> None:
    api = FakeTransport(
        [tool_reply('write_file', {'path': 'new.py', 'content': 'x = 1\n'}), text_reply('Done')]
    )
    c = make_controller(api)
    result = c.run_turn('make new.py')
    assert result.status == 'done'
    assert result.text == 'Done'
    assert read(os.path.join(c.workspace.root, 'new.py')) == 'x = 1\n'
    tool_result = api.requests[1]['messages'][-1]['content'][0]
    assert tool_result == {'type': 'tool_result', 'tool_use_id': 'tool1', 'content': 'Created new.py'}
    assert [m['role'] for m in c.session.messages] == ['user', 'assistant', 'user', 'assistant']


def test_request_shape(make_controller: Any) -> None:
    api = FakeTransport([text_reply('hi')])
    c = make_controller(api)
    c.run_turn('hello')
    body, headers = api.requests[0], api.headers[0]
    assert body['thinking']['block_binding'] == {'prefix_mismatch_behavior': 'drop_block'}
    assert body['fallbacks'] == 'default'
    assert all(t.get('eager_input_streaming') for t in body['tools'] if 'input_schema' in t)
    assert 'compact-2026-09-04' in headers['anthropic-beta']


def test_denied_tool_tells_the_model_why(make_controller: Any) -> None:
    api = FakeTransport([tool_reply('write_file', {'path': 'n.py', 'content': ''}), text_reply('ok')])
    c = make_controller(api, RecordingFrontend(answer='no'))
    c.run_turn('write it')
    result = api.requests[1]['messages'][-1]['content'][0]
    assert result['is_error']
    assert 'use a different file' in result['content']
    assert not os.path.exists(os.path.join(c.workspace.root, 'n.py'))


def test_always_records_a_narrow_rule(make_controller: Any) -> None:
    api = FakeTransport([tool_reply('write_file', {'path': 'n.py', 'content': ''}), text_reply('ok')])
    c = make_controller(api, RecordingFrontend(answer='always'))
    c.run_turn('write it')
    assert c.settings.allow == ['write_file(n.py)']
    assert c.settings.mode == 'default'


def test_api_error_rolls_the_turn_back(make_controller: Any) -> None:
    api = FakeTransport([FakeResponse(status=400, body={'error': {'message': 'bad request'}})])
    c = make_controller(api)
    result = c.run_turn('hello')
    assert result.status == 'error'
    assert c.session.messages == []
    assert c.session.turns == []


def test_retryable_error_is_retried(make_controller: Any) -> None:
    api = FakeTransport(
        [FakeResponse(status=529, body={'error': {'message': 'overloaded'}}), text_reply('ok')]
    )
    c = make_controller(api)
    c.client.sleep = lambda seconds: None
    assert c.run_turn('hello').status == 'done'


def test_session_is_saved_and_resumed(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('first answer')]))
    c.run_turn('first question')
    saved = c.session.id
    c.new_session()
    assert c.session.messages == []
    c.resume(saved)
    assert c.session.title == 'first question'
    assert c.session.messages[-1]['content'][0]['text'] == 'first answer'
    assert c.frontend.named('session_loaded')


def test_rewind_restores_files_and_conversation(make_controller: Any) -> None:
    api = FakeTransport(
        [
            tool_reply('edit_file', {'path': 'hello.py', 'old_str': 'hello', 'new_str': 'bye'}),
            text_reply('edited'),
            tool_reply('write_file', {'path': 'extra.py', 'content': 'x'}, tool_id='t2'),
            text_reply('added'),
        ]
    )
    c = make_controller(api)
    c.run_turn('edit hello')
    c.run_turn('add extra')
    hello = os.path.join(c.workspace.root, 'hello.py')
    assert 'bye' in read(hello)
    assert os.path.exists(os.path.join(c.workspace.root, 'extra.py'))
    restored = c.rewind(1)
    assert sorted(restored) == ['extra.py', 'hello.py']
    assert read(hello) == 'print("hello")\n'
    assert not os.path.exists(os.path.join(c.workspace.root, 'extra.py'))
    assert c.session.messages == []
    assert c.session.turns == []


def test_compaction_replaces_history_with_the_block(make_controller: Any) -> None:
    block = {'type': 'compaction', 'content': 'summary of work', 'signature': 'sig'}
    api = FakeTransport(
        [
            text_reply('one'),
            FakeResponse(
                body={
                    'content': [block],
                    'stop_reason': 'compaction',
                    'usage': {
                        'iterations': [{'type': 'compaction', 'input_tokens': 50, 'output_tokens': 20}]
                    },
                }
            ),
            text_reply('two'),
        ]
    )
    c = make_controller(api)
    c.run_turn('first')
    assert c.compact()
    assert c.session.messages == [{'role': 'assistant', 'content': [block]}]
    assert api.requests[1]['compaction']['type'] == 'summarize'
    c.run_turn('second')
    assert api.requests[2]['messages'][0]['content'][0] == block  # sent back exactly, first
    assert c.rewindable_turns()[0].text == 'second'


def test_automatic_compaction_after_a_large_turn(make_controller: Any) -> None:
    api = FakeTransport(
        [
            text_reply('big'),
            FakeResponse(
                body={
                    'content': [{'type': 'compaction', 'content': 's', 'signature': 'x'}],
                    'stop_reason': 'compaction',
                    'usage': {},
                }
            ),
        ]
    )
    c = make_controller(api)
    c.settings.compact_at = 50  # the fake reports 100 input tokens
    c.run_turn('go')
    assert c.session.compactions == 1


def test_prompt_commands_send_their_template(make_controller: Any, tmp_path: Any) -> None:
    (tmp_path / 'commands').mkdir()
    (tmp_path / 'commands' / 'review.md').write_text(
        '---\ndescription: Review code\n---\nReview $ARGUMENTS now.', encoding='utf-8'
    )
    api = FakeTransport([text_reply('reviewed')])
    c = make_controller(api)
    run_command(c, '/review app.py')
    assert api.requests[0]['messages'][0]['content'][-1]['text'] == 'Review app.py now.'


def test_skills_are_listed_in_new_sessions(make_controller: Any) -> None:
    c = make_controller()
    c.skills.save('install-wheels', 'Use when installing pure-Python wheels', '1. download\n2. unzip')
    c.new_session()
    assert 'install-wheels: Use when installing pure-Python wheels' in c.session.system
    assert c.skills.get('install-wheels').body == '1. download\n2. unzip'


def test_commands_and_tab_completion(make_controller: Any) -> None:
    c = make_controller()
    run_command(c, '/model haiku')
    assert c.settings.model == 'claude-haiku-5-5'
    run_command(c, '/bypass')
    assert c.settings.mode == 'bypass'
    assert complete(c, '/mo') == ('/mode', ['mode', 'model'])
    assert complete(c, '/mode') == ('/mode', ['mode', 'model'])
    assert complete(c, '/model') == ('/model ', ['model'])
    assert complete(c, '!tr') == ('!tree ', ['tree '])
    assert complete(c, '!git pu')[0] == '!git pu'  # pull and push
    assert complete(c, '/model s')[0] == '/model sonnet'
    assert complete(c, '/c')[1] == [
        'cd',
        'chapters',
        'clear',
        'compact',
        'config',
        'context',
        'cost',
        'crashes',
    ]
    assert complete(c, '/mode a')[0] == '/mode acceptEdits'
    assert run_command(c, '/exit') is False


def test_context_report(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('ok')]))
    c.run_turn('hi')
    report = context_report(c)
    assert '105/1.0M tokens' in report
    assert 'System prompt:' in report
    assert 'Tools:' in report
    assert 'Autocompact buffer:' in report


def test_images_go_before_the_text(make_controller: Any) -> None:
    api = FakeTransport([text_reply('a cat')])
    c = make_controller(api)
    c.pending_images.append(
        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'AA=='}}
    )
    c.run_turn('what is this?')
    content = api.requests[0]['messages'][0]['content']
    assert [b['type'] for b in content] == ['image', 'text']
    assert c.pending_images == []


def test_command_palette_suggestions(make_controller: Any) -> None:
    from pycoder.app.commands import suggestions

    c = make_controller()
    names = [title for _, title, _ in suggestions(c, '/co')]
    assert names == ['/compact', '/context', '/cost', '/config [name] [value]']  # grouped by topic
    assert suggestions(c, '/model ')[0][0] == '/model opus'
    assert suggestions(c, '!git p')[0][0] == '!git pull'
    assert suggestions(c, 'hello') == []


def test_settings_are_saved_validated_and_reloaded(make_controller: Any, tmp_path: Any) -> None:
    c = make_controller()
    run_command(c, '/config font_size 20')
    run_command(c, '/config theme dark')
    run_command(c, '/model sonnet')
    run_command(c, '/config font_size 99')  # out of range: rejected
    assert c.settings.font_size == 20
    assert any('between 12 and 26' in n for n in c.frontend.notices())
    with open(tmp_path / 'settings.json', encoding='utf-8') as f:
        saved = json.load(f)
    assert saved['font_size'] == 20
    assert saved['theme'] == 'dark'
    assert saved['model'] == 'claude-sonnet-5-5'
    again = make_controller()
    assert again.settings.font_size == 20
    assert again.settings.model == 'claude-sonnet-5-5'
    from pycoder.app.commands import suggestions

    assert suggestions(c, '/config theme d')[0][0] == '/config theme dark'


def test_config_form_values_are_applied(make_controller: Any) -> None:
    c = make_controller()
    c.frontend.edit_settings = lambda specs, current, tabs=None: {
        **current,
        'effort': 'max',
        'mode': 'acceptEdits',
    }
    run_command(c, '/config')
    assert c.settings.effort == 'max'
    assert c.settings.mode == 'acceptEdits'


def test_changes_are_previewed_before_asking(make_controller: Any) -> None:
    api = FakeTransport(
        [
            tool_reply('edit_file', {'path': 'hello.py', 'old_str': 'hello', 'new_str': 'bye'}),
            text_reply('ok'),
            tool_reply('edit_file', {'path': 'hello.py', 'old_str': 'missing', 'new_str': 'x'}, 't2'),
            text_reply('ok'),
        ]
    )
    c = make_controller(api)
    c.run_turn('edit')
    preview = c.frontend.named('confirm')[0][2]
    assert preview == ('hello.py', 'print("hello")\n', 'print("bye")\n')
    c.run_turn('bad edit')
    assert len(c.frontend.named('confirm')) == 1  # an edit that can't apply is reported, not asked about
    assert 'old_str not found' in api.requests[3]['messages'][-1]['content'][0]['content']


def test_rewind_after_a_shell_command_removes_only_the_request(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('one'), text_reply('two')]))
    c.run_turn('first')
    c.run_shell('echo hi')
    c.run_turn('second')
    c.rewind(2)
    last = c.session.messages[-1]
    assert last['role'] == 'user'
    assert [b['text'][:16] for b in last['content']] == ['<shell-command>e']  # the shell note stays


def test_a_dropped_connection_is_retried(make_controller: Any) -> None:
    class Dropping(FakeResponse):
        def iter_lines(self, chunk_size: Any = None, decode_unicode: bool = False) -> Any:
            yield 'data: {"type": "message_start", "message": {"model": "m", "usage": {}}}'
            yield ''
            raise ConnectionResetError('connection reset by peer')

    api = FakeTransport([Dropping(), text_reply('recovered')])
    c = make_controller(api)
    c.client.sleep = lambda seconds: None
    assert c.run_turn('hello').text == 'recovered'


def test_shell_errors_never_escape(make_controller: Any) -> None:
    c = make_controller()
    assert 'FileNotFoundError' in c.run_shell('cat missing.txt')
    assert 'not supported' in c.run_shell('git add -u')
    assert 'not supported' in c.run_shell('pip install -r req.txt')


def test_rm_removes_a_link_not_its_target(make_controller: Any) -> None:
    c = make_controller()
    root = c.workspace.root
    os.makedirs(os.path.join(root, 'data'))
    with open(os.path.join(root, 'data', 'keep.txt'), 'w', encoding='utf-8') as f:
        f.write('keep')
    os.symlink(os.path.join(root, 'data'), os.path.join(root, 'link'))
    c.run_shell('rm -r link')
    assert not os.path.lexists(os.path.join(root, 'link'))
    assert os.path.exists(os.path.join(root, 'data', 'keep.txt'))


def test_rewind_restores_binary_files_exactly(make_controller: Any) -> None:
    c = make_controller(
        FakeTransport(
            [tool_reply('write_file', {'path': 'blob.bin', 'content': 'text now'}), text_reply('ok')]
        )
    )
    blob = os.path.join(c.workspace.root, 'blob.bin')
    with open(blob, 'wb') as f:
        f.write(b'\xff\xfe binary \x00')
    c.settings.mode = 'bypass'
    c.run_turn('overwrite it')
    c.rewind(1)
    with open(blob, 'rb') as f:
        assert f.read() == b'\xff\xfe binary \x00'


def test_a_stopped_reply_is_kept_and_not_picked_up_again(make_controller: Any) -> None:
    """Stop keeps what was shown and tells Claude the request was abandoned."""

    class StopsWhileStreaming(RecordingFrontend):
        def text_delta(self, index: int, text: str) -> None:
            c.cancel.cancel()  # the user presses Stop as the text comes in

    api = FakeTransport([text_reply('A long article that the user stops'), text_reply('ok')])
    c = make_controller(api, StopsWhileStreaming())
    assert c.run_turn('write an article').status == 'interrupted'
    assert c.session.messages[1] == {
        'role': 'assistant',
        'content': [{'type': 'text', 'text': 'A long article that the user stops'}],
    }
    c.frontend = RecordingFrontend()
    c.run_turn('something else')
    last_user = api.requests[1]['messages'][-1]['content']
    assert 'stopped the response above' in last_user[0]['text']
    assert last_user[-1]['text'] == 'something else'


def test_effort_and_mode_without_an_argument_offer_a_list(make_controller: Any) -> None:
    c = make_controller()
    c.frontend.choice = 4
    run_command(c, '/effort')
    assert c.settings.effort == 'max'
    assert c.frontend.named('choose')[-1][0] == 'How hard should the model think?'
    c.frontend.choice = 2
    run_command(c, '/mode')
    assert c.settings.mode == 'plan'
    c.frontend.choice = None  # cancelled
    run_command(c, '/mode')
    assert c.settings.mode == 'plan'


def test_web_and_bypass_take_on_or_off(make_controller: Any) -> None:
    c = make_controller()
    seen = []
    for line in ('/web off', '/web off', '/web', '/bypass on', '/bypass on', '/bypass off'):
        run_command(c, line)
        seen.append((c.settings.web, c.settings.mode))
    assert seen == [
        (False, 'default'),
        (False, 'default'),
        (True, 'default'),
        (True, 'bypass'),
        (True, 'bypass'),
        (True, 'default'),
    ]
    run_command(c, '/web maybe')
    assert c.frontend.notices()[-1] == 'Say on or off'


def test_only_changed_settings_are_saved(make_controller: Any, tmp_path: Any) -> None:
    c = make_controller()
    run_command(c, '/config theme dark')
    with open(tmp_path / 'settings.json', encoding='utf-8') as f:
        saved = json.load(f)
    assert saved == {'allow': [], 'ask': [], 'deny': [], 'theme': 'dark'}


def test_the_system_prompt_is_the_same_all_day(make_controller: Any) -> None:
    c = make_controller()
    date = c.session.system.split("Today's date: ")[1].split(' (')[0]
    assert ':' not in date  # no time of day
    assert 'nothing outside it is accessible' not in c.session.system


def test_subagents_run_on_a_cheaper_model(make_controller: Any) -> None:
    api = FakeTransport(
        [
            tool_reply('task', {'description': 'look', 'prompt': 'find x'}),
            text_reply('found'),
            text_reply('ok'),
        ]
    )
    c = make_controller(api)
    c.run_turn('go')
    sub = api.requests[1]
    assert sub['model'] == 'claude-sonnet-5-5'
    assert sub['output_config'] == {'effort': 'medium'}
    assert 'file:line' in sub['system']


def test_btw_answers_from_the_conversation_and_leaves_it_as_it_was(make_controller: Any) -> None:
    api = FakeTransport([text_reply('I read main.py')])
    c = make_controller(api)
    c.run_turn('look at main.py')
    before = json.dumps(c.session.messages)
    answer = {'content': [{'type': 'text', 'text': 'It has 3 functions.'}], 'usage': {'output_tokens': 9}}
    api.add(FakeResponse(body=answer))
    run_command(c, '/btw how many functions?')
    assert json.dumps(c.session.messages) == before  # not kept in the conversation
    side = api.requests[1]
    turn = api.requests[0]
    assert side['system'] == turn['system']
    assert side['tools'] == turn['tools']  # the same prefix, so it is read from the prompt cache
    assert side['messages'][: len(turn['messages'])] == turn['messages']
    assert side['messages'][-1]['content'][-1]['text'].endswith('how many functions?')
    assert c.frontend.named('side_answer') == [('how many functions?', 'It has 3 functions.')]


def test_btw_mid_turn_leaves_out_tool_calls_still_running() -> None:
    from pycoder.agent.loop import settled

    messages: list[dict[str, Any]] = [
        {'role': 'user', 'content': 'go'},
        {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 't1', 'name': 'x', 'input': {}}]},
    ]
    copy = settled(messages)
    assert copy == messages[:1]
    copy[-1]['content'] = 'changed'
    assert messages[0]['content'] == 'go'


def test_btw_follow_ups_see_the_earlier_side_questions(make_controller: Any) -> None:
    api = FakeTransport([text_reply('done')])
    c = make_controller(api)
    c.run_turn('build it')
    for answer in ('Two files.', 'main.py and util.py.'):
        api.add(FakeResponse(body={'content': [{'type': 'text', 'text': answer}]}))
    assert c.side_question('how many files?') == 'Two files.'
    assert c.side_question('which?') == 'main.py and util.py.'
    second = api.requests[2]['messages']
    assert [m['role'] for m in second[-3:]] == ['user', 'assistant', 'user']
    assert second[-2]['content'][0]['text'] == 'Two files.'
    assert second[-1]['content'][-1]['text'] == 'which?'
    c.new_session()
    assert c.side_chat == []  # a side chat belongs to its session


def test_subagents_of_one_reply_run_at_the_same_time(make_controller: Any) -> None:
    import threading

    first = tool_reply('task', {'description': 'a', 'prompt': 'look at a'}, 'tool1')[:-1]
    second = [
        dict(e, index=1) for e in tool_reply('task', {'description': 'b', 'prompt': 'look at b'}, 'tool2')
    ]
    api = FakeTransport([first + second, text_reply('report'), text_reply('report'), text_reply('both done')])
    both_asking = threading.Barrier(2, timeout=5)  # broken unless the two subagents ask at once
    post = api.post

    def concurrent_post(url: str, headers: dict[str, str], body: dict[str, Any], stream: bool) -> Any:
        if body['messages'][0]['content'][0].get('text') in ('look at a', 'look at b'):
            both_asking.wait()
        return post(url, headers, body, stream)

    api.post = concurrent_post  # type: ignore[method-assign]
    c = make_controller(api)
    assert c.run_turn('look at both').text == 'both done'
    results = api.requests[-1]['messages'][-1]['content']
    assert [r['tool_use_id'] for r in results] == ['tool1', 'tool2']  # in the calls' order
    assert all(r['content'] == 'report' and not r.get('is_error') for r in results)


def test_a_turn_is_saved_after_each_step(make_controller: Any) -> None:
    api = FakeTransport([tool_reply('write_file', {'path': 'n.py', 'content': 'x'}), text_reply('Done')])
    c = make_controller(api)
    saved = []
    store_save = c.store.save

    def save(session: Any) -> None:
        saved.append(len(session.messages))
        store_save(session)

    c.store.save = save
    c.run_turn('write it')
    assert saved[0] == 3  # the request, the tool call and its result, before the reply is even asked for


def test_a_picked_file_is_copied_in_and_mentioned(
    make_controller: Any, monkeypatch: Any, tmp_path: Any
) -> None:
    picked = tmp_path / 'my notes.txt'
    picked.write_text('from the files app')
    monkeypatch.setitem(
        sys.modules, 'dialogs', types.SimpleNamespace(pick_document=lambda types: str(picked))
    )
    c = make_controller(FakeTransport([]))
    assert c.import_for_mention() == '@"my notes.txt"'
    assert c.import_for_mention() == '@"my notes 2.txt"'  # nothing is overwritten
    with open(os.path.join(c.workspace.root, 'my notes.txt'), encoding='utf-8') as f:
        assert f.read() == 'from the files app'


def test_no_file_picked_mentions_nothing(make_controller: Any, monkeypatch: Any) -> None:
    monkeypatch.setitem(sys.modules, 'dialogs', types.SimpleNamespace(pick_document=lambda types: None))
    assert make_controller(FakeTransport([])).import_for_mention() == ''


def test_status_shows_what_this_device_spent_with_the_api(make_controller: Any) -> None:
    c = make_controller(FakeTransport([]))
    c.session.cost = 1.5
    c.session.usage.update(input=100, output=50, cache_read=300, cache_write=100)
    rows = dict(reports.status(c))
    assert rows['Spent this month'].startswith('$1.50')
    assert rows['Prompt caching'].startswith('60% hit rate')
    assert rows['Tokens'].startswith('550')
    c.store.save(c.session)
    c.store._index = None
    saved = c.store.list()[0]
    assert saved.model == c.session.model
    assert saved.usage['cache_read'] == 300

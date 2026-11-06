"""@file mentions, rewind modes, renaming and deleting sessions, and the saved history view."""

from __future__ import annotations

import os
from typing import Any

import pytest

from pycoder.app import mentions
from pycoder.app.commands import complete, run_command, suggestions
from pycoder.state.workspace import Workspace
from tests.conftest import FakeTransport, text_reply, tool_reply


def read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def test_mentions_are_found_and_attached(workspace: str) -> None:
    os.makedirs(os.path.join(workspace, 'pkg'))
    with open(os.path.join(workspace, 'pkg', 'mod.py'), 'w', encoding='utf-8') as f:
        f.write('x = 1\n')
    text = 'compare @hello.py with @pkg/mod.py, see @pkg and mail me@example.com about @missing.py'
    assert mentions.find(text) == ['hello.py', 'pkg/mod.py', 'pkg', 'missing.py']
    blocks, names = mentions.attach(Workspace(workspace), text)
    assert names == ['hello.py', 'pkg/mod.py', 'pkg']
    assert blocks[0]['text'] == '<file path="hello.py">\nprint("hello")\n\n</file>'
    assert blocks[2]['text'] == '<folder path="pkg">\nmod.py\n</folder>'
    assert all(mentions.is_context(b) for b in blocks)
    assert mentions.attach(Workspace(workspace), 'read @../outside.txt') == ([], [])


def test_mention_completion(make_controller: Any) -> None:
    c = make_controller()
    os.makedirs(os.path.join(c.workspace.root, 'pkg'))
    with open(os.path.join(c.workspace.root, 'pkg', 'helpers.py'), 'w', encoding='utf-8') as f:
        f.write('')
    assert mentions.partial('look at @pk') == 'pk'
    assert mentions.partial('mail a@b') is None
    assert complete(c, 'look at @pk')[0] == 'look at @pkg/'
    assert complete(c, 'look at @pkg/h') == ('look at @pkg/helpers.py ', ['pkg/helpers.py'])
    found = [title for _, title, _ in suggestions(c, 'fix @hel')]
    assert found == ['@hello.py', '@pkg/helpers.py']


def test_a_mentioned_file_goes_with_the_request(make_controller: Any) -> None:
    api = FakeTransport([text_reply('ok')])
    c = make_controller(api)
    c.run_turn('explain @hello.py')
    sent = api.requests[0]['messages'][0]['content']
    assert sent[0]['text'] == 'explain @hello.py'
    assert sent[1]['text'].startswith('<file path="hello.py">')
    assert c.frontend.named('request') == [('explain @hello.py', [], ['hello.py'], 1)]


def two_edits(make_controller: Any) -> Any:
    api = FakeTransport(
        [
            tool_reply('edit_file', {'path': 'hello.py', 'old_str': 'hello', 'new_str': 'bye'}),
            text_reply('edited'),
            text_reply('second'),
        ]
    )
    c = make_controller(api)
    c.run_turn('edit hello')
    c.run_turn('just talk')
    return c


def test_rewind_code_only_keeps_the_conversation(make_controller: Any) -> None:
    c = two_edits(make_controller)
    hello = os.path.join(c.workspace.root, 'hello.py')
    messages = len(c.session.messages)
    assert c.rewind(1, files=True, conversation=False) == ['hello.py']
    assert read(hello) == 'print("hello")\n'
    assert len(c.session.turns) == 2
    assert len(c.session.messages) == messages + 1
    assert 'put these files back' in c.session.messages[-1]['content'][0]['text']


def test_rewind_conversation_only_keeps_the_files(make_controller: Any) -> None:
    c = two_edits(make_controller)
    run_command(c, '/rewind 1 conversation')
    assert c.session.turns == []
    assert 'bye' in read(os.path.join(c.workspace.root, 'hello.py'))


def test_rewind_asks_what_to_restore(make_controller: Any) -> None:
    c = two_edits(make_controller)
    c.frontend.choice = 2  # 'Code only'
    run_command(c, '/rewind 1')
    assert c.frontend.named('choose')[-1][0] == 'Restore what?'
    assert len(c.session.turns) == 2
    assert read(os.path.join(c.workspace.root, 'hello.py')) == 'print("hello")\n'


def test_rename_and_delete(make_controller: Any) -> None:
    c = two_edits(make_controller)
    run_command(c, '/rename My session')
    assert c.store.list()[0].title == 'My session'
    old = c.session.id
    run_command(c, f'/delete {old}')  # choice 0 = Delete
    assert c.store.list() == []
    assert c.session.id != old
    assert c.session.messages == []


def test_history_hides_attached_files_and_shows_times(make_controller: Any) -> None:
    from pycoder.frontends.chat.frontend import history_html

    messages = [
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': 'see @a.py'},
                {'type': 'text', 'text': '<file path="a.py">\nsecret body\n</file>'},
            ],
        },
        {'role': 'assistant', 'content': [{'type': 'text', 'text': 'ok'}]},
    ]
    html = history_html('t', messages, {0: 1_700_000_000.0})
    assert 'see @a.py' in html
    assert 'secret body' not in html
    assert 'class="time"' in html


def test_turn_numbers_are_not_reused_after_a_conversation_rewind(make_controller: Any) -> None:
    api = FakeTransport(
        [
            tool_reply('edit_file', {'path': 'hello.py', 'old_str': 'hello', 'new_str': 'bye'}),
            text_reply('one'),
            tool_reply('edit_file', {'path': 'hello.py', 'old_str': 'bye', 'new_str': 'ciao'}, 't2'),
            text_reply('two'),
        ]
    )
    c = make_controller(api)
    hello = os.path.join(c.workspace.root, 'hello.py')
    c.run_turn('bye')
    c.rewind(1, files=False)  # keep "bye"
    c.run_turn('ciao')
    assert c.session.turns[0].number == 2
    c.rewind(2, conversation=False)
    assert 'bye' in read(hello)  # back to before the new request, not to the original


def test_huge_and_binary_mentions_are_cut(workspace: str) -> None:
    with open(os.path.join(workspace, 'big.log'), 'w', encoding='utf-8') as f:
        f.write('x' * (mentions.MAX_CHARS * 5))
    with open(os.path.join(workspace, 'blob.bin'), 'wb') as f:
        f.write(b'\0\1\2' * 100)
    blocks, _ = mentions.attach(Workspace(workspace), '@big.log @blob.bin')
    assert len(blocks[0]['text']) < mentions.MAX_CHARS + 200
    assert 'binary file, 300 bytes' in blocks[1]['text']


def test_model_html_is_shown_as_text() -> None:
    from pycoder.frontends.chat.render import md_to_html

    html = md_to_html(
        'hi <img src=x onerror="answers[1]=2"> [x](javascript:alert(1))\n\n<script>x()</script>'
    )
    assert '<img' not in html
    assert '<script' not in html
    assert 'javascript:' not in html
    assert '&lt;img' in html


def test_a_session_resumes_on_another_device(make_controller: Any, monkeypatch: Any, tmp_path: Any) -> None:
    """The same iCloud folder has a different absolute path on the Mac and on the iPhone."""
    from pycoder import config
    from pycoder.state.session import SessionStore

    mac_home = tmp_path / 'mac' / 'Documents'
    (mac_home / 'game').mkdir(parents=True)
    monkeypatch.setattr(config, 'HOME_DIR', str(mac_home))
    c = make_controller(FakeTransport([text_reply('hi')]))
    c.new_session(str(mac_home / 'game'))
    c.run_turn('hello')
    saved = os.path.join(c.store.directory, c.session.id + '.json')
    with open(saved, encoding='utf-8') as f:
        assert '"root": "~/game"' in f.read()
    phone_home = tmp_path / 'phone' / 'Documents'
    (phone_home / 'game').mkdir(parents=True)
    monkeypatch.setattr(config, 'HOME_DIR', str(phone_home))
    store = SessionStore(c.store.directory)
    assert store.list()[0].root == str(phone_home / 'game')
    assert store.load(c.session.id).root == str(phone_home / 'game')


def test_history_shows_shell_commands_as_cards() -> None:
    from pycoder.frontends.chat.frontend import history_html
    from pycoder.shell.commands import conversation_note

    messages = [
        {
            'role': 'user',
            'content': [
                {'type': 'text', 'text': conversation_note('ls', 'hello.py  (0 B)')},
                {'type': 'text', 'text': 'is @hello.py empty?'},
                {'type': 'text', 'text': '<file path="hello.py">\n\n</file>'},
            ],
        },
    ]
    html = history_html('t', messages)
    assert '<div class="cmd">$ ls</div><pre>hello.py  (0 B)</pre>' in html
    assert '&lt;shell-command&gt;' not in html
    assert 'shell-command' not in html
    assert '</svg> hello.py</span>' in html  # the @file chip, with its paperclip icon


def test_resume_and_delete_name_an_unknown_session(make_controller: Any) -> None:
    c = make_controller()
    run_command(c, '/resume nosuchid')
    run_command(c, '/delete nosuchid')
    assert c.frontend.notices()[-2:] == ['No session nosuchid', 'No session nosuchid']
    assert not c.frontend.named('choose')


def test_delete_offers_this_folders_sessions(make_controller: Any, tmp_path: Any) -> None:
    c = two_edits(make_controller)
    c.save()
    other = tmp_path / 'other'
    other.mkdir()
    c.new_session(str(other))
    c.frontend.choice = None
    run_command(c, '/delete')
    assert 'No saved sessions in this folder' in c.frontend.notices()[-1]
    run_command(c, '/delete all')
    title, labels, _ = c.frontend.named('choose')[-1]
    assert title == 'Delete which session?'
    assert len(labels) == 1  # the first folder's session


def test_mention_completion_walks_the_workspace_once_while_typing(
    make_controller: Any, monkeypatch: Any
) -> None:
    c = make_controller()
    from pycoder.tools import files

    walks = []

    def walk(root: str) -> Any:
        walks.append(root)
        return files.walk(root)

    monkeypatch.setattr('pycoder.app.mentions.walk', walk)
    for typed in ('h', 'he', 'hel'):
        assert 'hello.py' in mentions.candidates(c.workspace, typed)
    assert len(walks) == 1


def test_fork_goes_on_in_a_new_session_and_leaves_this_one(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('one'), text_reply('two')]))
    c.submit('first')
    c.submit('second')
    original = c.session.id
    c.fork(1)
    assert c.session.id != original
    assert [t.number for t in c.session.turns] == [1]
    assert [m['role'] for m in c.session.messages] == ['user', 'assistant']
    kept = c.store.load(original)
    assert [t.number for t in kept.turns] == [1, 2]


def test_a_fork_from_the_last_request_keeps_its_reply(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('one')]))
    c.submit('first')
    c.fork(1)
    assert c.session.reply_text(1) == 'one'


def test_forking_from_a_request_that_is_not_there_says_so(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('one')]))
    c.submit('first')
    with pytest.raises(ValueError, match='cannot be forked'):
        c.fork(9)


def test_a_chapter_is_titled_by_its_reply_saved_and_unpinned(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('# The plan\nmore')]))
    c.submit('first')
    assert c.toggle_chapter(1) == 'The plan'
    assert c.store.load(c.session.id).chapters == {'1': 'The plan'}
    assert c.toggle_chapter(1) == ''
    assert c.session.chapters == {}


def test_rewinding_past_a_chapter_drops_it(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('one'), text_reply('two')]))
    c.submit('first')
    c.submit('second')
    c.toggle_chapter(1)
    c.toggle_chapter(2)
    c.rewind(2, files=False)
    assert list(c.session.chapters) == ['1']


def test_a_lone_surrogate_in_a_message_does_not_stop_saving(tmp_path: Any) -> None:
    from pycoder.agent.loop import tool_result
    from pycoder.state.session import Session, SessionStore

    assert tool_result('t', 'bad \ud83d')['content'] == 'bad ?'
    store = SessionStore(str(tmp_path))
    session = Session.new(str(tmp_path), 'm', 's', False)
    session.messages = [{'role': 'user', 'content': 'bad \ud83d'}]
    store.save(session)
    assert store.load(session.id).messages[0]['content'] == 'bad \ud83d'


def test_todos_clear_empties_the_list(make_controller: Any) -> None:
    from pycoder.app.commands.registry import run_command

    c = make_controller(FakeTransport())
    c.session.todos = [{'content': 'left over', 'status': 'in_progress'}]
    run_command(c, '/todos clear')
    assert c.session.todos == []


def test_rewinding_the_conversation_takes_its_plan_along(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('ok')]))
    c.run_turn('make a plan')
    c.session.todos = [{'content': 'step', 'status': 'pending'}]
    c.rewind(c.rewindable_turns()[-1].number)
    assert c.session.todos == []

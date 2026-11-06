"""`!` commands in the built-in shell."""

from __future__ import annotations

import os
from typing import Any

import pytest

from tests.conftest import FakeTransport, text_reply


def test_basic_commands_and_conversation_note(make_controller: Any) -> None:
    api = FakeTransport([text_reply('I saw the output')])
    c = make_controller(api)
    assert c.run_shell('pwd') == c.workspace.root
    assert c.run_shell('echo hi there') == 'hi there'
    assert 'hello.py' in c.run_shell('ls')
    assert '4' in c.run_shell('python -c "print(2 + 2)"')
    c.run_shell('mkdir -p build/out')
    assert os.path.isdir(os.path.join(c.workspace.root, 'build', 'out'))
    assert c.run_shell('rm -r build') == 'removed build'
    shown = c.frontend.named('shell_output')
    assert shown[0] == ('pwd', c.workspace.root, True)
    c.run_turn('what did you see?')
    first = api.requests[0]['messages'][0]['content']
    assert first[0]['text'].startswith('<shell-command>pwd</shell-command>')
    assert first[-1]['text'] == 'what did you see?'


def test_unknown_command_and_errors_are_reported(make_controller: Any) -> None:
    c = make_controller()
    assert 'command not found' in c.run_shell('npm install')
    assert 'no such file' in c.run_shell('rm missing.txt')
    assert 'no such folder' in c.run_shell('cd nowhere')
    assert [ok for _, _, ok in c.frontend.named('shell_output')] == [False, False, False]


def test_submit_routes_bang_lines_to_the_shell(make_controller: Any) -> None:
    c = make_controller()
    assert c.submit('!echo routed') is True
    assert c.frontend.named('shell_output')[-1][1] == 'routed'


def test_git_through_the_shell(make_controller: Any) -> None:
    pytest.importorskip('dulwich')
    c = make_controller()
    assert 'Initialized' in c.run_shell('git init repo')
    with open(os.path.join(c.workspace.root, 'repo', 'a.txt'), 'w', encoding='utf-8') as f:
        f.write('x\n')
    assert 'user.name = Me' in c.run_shell('git -C repo config user.name Me')
    c.run_shell('git -C repo config user.email me@example.com')
    out = c.run_shell('git -C repo commit -am "first commit"')
    assert 'Staged 1 change(s)' in out
    assert 'Committed' in out
    assert 'first commit' in c.run_shell('git -C repo log -n 5')
    assert 'first commit' in c.run_shell('git -C repo log --oneline -1')
    assert 'working tree clean' in c.run_shell('git -C repo status')


def test_the_chat_and_the_terminal_share_one_command_set(make_controller: Any) -> None:
    c = make_controller()
    os.makedirs(os.path.join(c.workspace.root, 'pkg'))
    c.run_shell('touch pkg/a.py')
    assert '└── a.py' in c.run_shell('tree pkg')
    c.run_shell('cp pkg/a.py b.py')
    assert os.path.exists(os.path.join(c.workspace.root, 'b.py'))
    assert 'Workspace:' in c.run_shell('cd pkg')  # in the chat, cd starts a session there
    assert c.workspace.root.endswith('pkg')


def test_and_and_semicolons_chain_commands(make_controller: Any) -> None:
    c = make_controller()
    c.run_shell('mkdir work && cd work')
    assert c.workspace.root.endswith('work')  # cd ran after mkdir, and no folders named && or cd
    assert not os.path.exists(os.path.join(os.path.dirname(c.workspace.root), '&&'))
    out = c.run_shell('cat missing.txt && echo never')
    assert 'never' not in out
    assert c.run_shell('cat missing.txt ; echo still').endswith('still')
    assert "isn't supported" in c.run_shell('ls | head')
    assert c.run_shell('echo "a && b"') == 'a && b'  # quoted operators are text

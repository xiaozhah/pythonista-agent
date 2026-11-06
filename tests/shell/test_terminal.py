"""The shell at the console: a current folder inside pycoder's home, commands, completion, and claude."""

from __future__ import annotations

import os
from typing import Any

import pytest

from pycoder.app.commands import run_command
from pycoder.shell.terminal import Terminal, agent_args
from tests.conftest import FakeTransport, text_reply


@pytest.fixture
def home(tmp_path: Any) -> str:
    root = tmp_path / 'home'
    (root / 'projects' / 'game' / 'sprites').mkdir(parents=True)
    (root / 'projects' / 'game' / 'main.py').write_text('print(1)\nprint(2)\nprint(3)\n', encoding='utf-8')
    (root / 'notes').mkdir()
    return str(root)


def term(home: str, tmp_path: Any) -> Terminal:
    return Terminal(home, str(tmp_path / 'history'))


def test_cd_moves_inside_home_only(home: str, tmp_path: Any) -> None:
    t = term(home, tmp_path)
    assert t.prompt() == '~ $'
    t.run('cd projects/game')
    assert t.prompt() == '~/projects/game $'
    assert t.run('pwd').output == os.path.join(os.path.realpath(home), 'projects', 'game')
    t.run('cd ../../notes')
    assert t.display_path() == '~/notes'
    t.run('cd -')
    assert t.display_path() == '~/projects/game'
    t.run('cd ~')
    assert t.display_path() == '~'
    result = t.run('cd ..')
    assert not result.ok
    assert 'outside' in result.error
    assert not t.run('cd nowhere').ok


def test_a_new_terminal_starts_at_home_and_keeps_the_history(home: str, tmp_path: Any) -> None:
    t = term(home, tmp_path)
    t.run('cd projects')
    t.run('ls')
    again = term(home, tmp_path)
    assert again.display_path() == '~'
    assert again.history == ['cd projects', 'ls']


def test_file_commands_work_in_the_current_folder(home: str, tmp_path: Any) -> None:
    t = term(home, tmp_path)
    t.run('cd projects/game')
    assert 'main.py' in t.run('ls').output
    assert t.run('head -n 2 main.py').output == 'print(1)\nprint(2)'
    t.run('touch new.txt')
    t.run('cp main.py copy.py')
    t.run('mv copy.py ~/notes')
    assert os.path.exists(os.path.join(home, 'notes', 'copy.py'))
    assert t.run('cat ~/notes/copy.py').output.startswith('print(1)')
    tree = t.run('tree').output
    assert '├── main.py' in tree
    assert '└── sprites/' in tree
    assert not t.run('rm sprites').ok  # a folder needs -r
    missing = t.run('frobnicate')
    assert not missing.ok
    assert missing.error.startswith('frobnicate: command not found')


def test_claude_starts_the_agent_here(home: str, tmp_path: Any) -> None:
    t = term(home, tmp_path)
    t.run('cd notes')
    result = t.run('pycoder -c "fix the build"')
    assert result.action == 'agent'
    assert agent_args(result.arg) == ('last', 'fix the build')
    assert t.run('claude').action == 'agent'
    assert t.run('pycoder update').action == ''  # the shell's update command, not the agent
    assert t.run('clear').action == 'clear'


def test_tab_completion(home: str, tmp_path: Any) -> None:
    t = term(home, tmp_path)
    assert t.complete('pyc') == ('pycoder ', ['pycoder'])
    assert t.complete('cd pro') == ('cd projects/', ['projects/'])
    assert t.complete('cat projects/game/m') == ('cat projects/game/main.py ', ['projects/game/main.py'])
    assert t.complete('cd projects/game/') == ('cd projects/game/sprites/', ['projects/game/sprites/'])


def test_resume_lists_this_folders_sessions(make_controller: Any, tmp_path: Any) -> None:
    api = FakeTransport([text_reply('a'), text_reply('b')])
    c = make_controller(api)
    c.run_turn('in the root')
    root_session = c.session.id
    sub = os.path.join(c.workspace.root, 'sub')
    os.makedirs(sub)
    c.change_dir('sub')
    c.run_turn('in sub')
    sub_session = c.session.id
    c.new_session()
    c.frontend.choice = 0
    run_command(c, '/resume')
    labels = c.frontend.named('choose')[-1][1]
    assert len(labels) == 1  # only sub's session
    assert c.session.id == sub_session
    c.new_session(os.path.dirname(sub))
    run_command(c, '/resume last')
    assert c.session.id == root_session


def test_local_storage_next_to_the_home(home: str, tmp_path: Any) -> None:
    """A place besides the home: /local, the device's storage, or /iCloud, its iCloud Drive folder."""
    local = tmp_path / 'local'
    local.mkdir()
    t = Terminal(home, str(tmp_path / 'history'), places={'/local': str(local)})
    t.run('cd /local')
    assert t.prompt() == '/local $'
    t.run('mkdir scratch')
    t.run('cd scratch')
    assert t.display_path() == '/local/scratch'
    t.run('cp ~/projects/game/main.py .')
    assert (local / 'scratch' / 'main.py').exists()
    t.run('cp main.py ~/notes/')
    assert os.path.exists(os.path.join(home, 'notes', 'main.py'))
    assert t.complete('cd /lo') == ('cd /local/', ['/local/'])
    assert not t.run('rm -r /local').ok
    again = Terminal(home, str(tmp_path / 'history'), places={'/local': str(local)})
    assert again.prompt() == '~ $'  # a new terminal starts at home, wherever the last one was
    t.run('cd ~')
    assert t.prompt() == '~ $'
    assert not t.run('cd /elsewhere').ok


def test_a_chain_ending_in_pycoder_runs_first_then_opens_the_agent(home: str, tmp_path: Any) -> None:
    t = term(home, tmp_path)
    result = t.run('cd projects/game && ls && pycoder fix the bug')
    assert result.action == 'agent'
    assert result.arg == 'fix the bug'
    assert 'main.py' in result.output
    assert t.cwd.endswith(os.path.join('projects', 'game'))
    failed = t.run('cd nowhere && pycoder')
    assert failed.action == ''
    assert failed.error


def test_a_failing_chain_keeps_what_worked_apart_from_the_error(home: str, tmp_path: Any) -> None:
    t = term(home, tmp_path)
    result = t.run('pwd && frobnicate')
    assert result.output == t.cwd
    assert result.error.startswith('frobnicate: command not found')


def test_icloud_is_a_place_when_it_is_there(monkeypatch: Any, tmp_path: Any) -> None:
    from pycoder.host import env
    from pycoder.shell import commands

    cloud = tmp_path / 'cloud'
    monkeypatch.setattr(env, 'icloud_documents', lambda: str(cloud))
    assert commands.default_places()[commands.ICLOUD] == str(cloud)
    monkeypatch.setattr(env, 'icloud_documents', lambda: None)
    assert commands.ICLOUD not in commands.default_places()

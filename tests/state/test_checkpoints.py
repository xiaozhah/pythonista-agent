"""Checkpoints of files changed by running code or git, which don't say what they change."""

from __future__ import annotations

import os
from typing import Any

from pycoder.state import checkpoints
from tests.conftest import FakeTransport, text_reply, tool_reply

CODE = """
import os, shutil
open('hello.py', 'w', encoding='utf-8').write('changed')
os.makedirs('new/deep', exist_ok=True)
open('new/deep/made.txt', 'w', encoding='utf-8').write('made')
shutil.rmtree('pkg')
"""


def test_rewind_undoes_what_run_python_changed(make_controller: Any, workspace: str) -> None:
    os.makedirs(os.path.join(workspace, 'pkg'))
    with open(os.path.join(workspace, 'pkg', 'mod.py'), 'w', encoding='utf-8') as f:
        f.write('x = 1\n')
    api = FakeTransport([tool_reply('run_python', {'code': CODE}), text_reply('done')])
    c = make_controller(api)
    c.settings.mode = 'bypass'
    c.run_turn('change things')
    assert not os.path.exists(os.path.join(workspace, 'pkg'))
    restored = c.rewind(1)
    assert restored == ['hello.py', os.path.join('new', 'deep', 'made.txt'), os.path.join('pkg', 'mod.py')]
    with open(os.path.join(workspace, 'hello.py'), encoding='utf-8') as f:
        assert f.read() == 'print("hello")\n'
    with open(os.path.join(workspace, 'pkg', 'mod.py'), encoding='utf-8') as f:  # its folder came back
        assert f.read() == 'x = 1\n'
    assert not os.path.exists(os.path.join(workspace, 'new', 'deep', 'made.txt'))


def test_a_file_too_big_to_keep_is_reported_on_rewind(
    make_controller: Any, workspace: str, monkeypatch: Any
) -> None:
    monkeypatch.setattr(checkpoints, 'KEEP_FILE', 5)
    code = "open('hello.py', 'w', encoding='utf-8').write('changed')"
    api = FakeTransport([tool_reply('run_python', {'code': code}), text_reply('done')])
    c = make_controller(api)
    c.settings.mode = 'bypass'
    c.run_turn('change it')
    assert c.checkpoints.changed_since(1) == ['hello.py']
    assert c.rewind(1) == []
    assert any('too big' in n and 'hello.py' in n for n in c.frontend.notices())


def test_read_only_git_and_runs_outside_a_turn_are_not_scanned(make_controller: Any) -> None:
    c = make_controller()
    assert c.checkpoints.scan() is None  # no turn running
    from pycoder.tools import git

    assert not git.TOOLS[0].needs_confirmation({'command': 'status'})


def test_modified_since_lists_files_newest_first(tmp_path: Any) -> None:
    import os

    from pycoder.state.checkpoints import Checkpoints
    from pycoder.state.session import Session
    from pycoder.state.workspace import Workspace

    root = str(tmp_path)
    for name, when in (('old.txt', 1000), ('new.txt', 3000), ('newer.txt', 4000)):
        path = os.path.join(root, name)
        open(path, 'w', encoding='utf-8').close()
        os.utime(path, (when, when))
    session = Session.new(root, 'm', 's', web=False)
    found = Checkpoints(session, Workspace(root)).modified_since(2000)
    assert [rel for rel, _, _ in found] == ['newer.txt', 'new.txt']


def _setup(tmp_path: Any, monkeypatch: Any) -> tuple[Any, Any, Any]:
    from pycoder import config
    from pycoder.state.checkpoints import Checkpoints
    from pycoder.state.session import Session
    from pycoder.state.workspace import Workspace

    monkeypatch.setattr(config, 'SET_ASIDE_DIR', str(tmp_path / 'aside'))
    root = tmp_path / 'work'
    root.mkdir()
    session = Session.new(str(root), 'm', 's', False)
    checkpoints = Checkpoints(session, Workspace(str(root)))
    checkpoints.turn = 1
    return root, session, checkpoints


def test_appending_to_a_moved_file_does_not_change_what_is_kept(tmp_path: Any, monkeypatch: Any) -> None:
    root, _, checkpoints = _setup(tmp_path, monkeypatch)
    (root / 'm').write_text('original', encoding='utf-8')
    checkpoints.before_write(str(root / 'm'), removing=True)
    checkpoints.before_write(str(root / 'n'))
    os.replace(root / 'm', root / 'n')
    with open(root / 'n', 'a', encoding='utf-8') as f:
        f.write(' APPENDED')
    checkpoints.restore(1)
    assert (root / 'm').read_text(encoding='utf-8') == 'original'
    assert not (root / 'n').exists()


def test_a_file_that_became_a_folder_comes_back_as_a_file(tmp_path: Any, monkeypatch: Any) -> None:
    root, _, checkpoints = _setup(tmp_path, monkeypatch)
    (root / 'u').write_text('was a file', encoding='utf-8')
    checkpoints.before_write(str(root / 'u'), removing=True)
    os.remove(root / 'u')
    (root / 'u').mkdir()
    checkpoints.before_write(str(root / 'u' / 'b'))
    (root / 'u' / 'b').write_text('new', encoding='utf-8')
    assert checkpoints.restore(1) == ['u', 'u/b']
    assert (root / 'u').read_text(encoding='utf-8') == 'was a file'
    assert checkpoints.stuck == []


def test_a_folder_in_the_way_is_reported_and_the_rest_comes_back(tmp_path: Any, monkeypatch: Any) -> None:
    root, _, checkpoints = _setup(tmp_path, monkeypatch)
    checkpoints.before_write(str(root / 'new'))
    (root / 'other').write_text('old', encoding='utf-8')
    checkpoints.before_write(str(root / 'other'))
    (root / 'other').write_text('changed', encoding='utf-8')
    (root / 'new').mkdir()
    (root / 'new' / 'unknown').write_text('not ours', encoding='utf-8')
    assert checkpoints.restore(1) == ['other']
    assert checkpoints.stuck == ['new']
    assert (root / 'other').read_text(encoding='utf-8') == 'old'


def test_a_fork_counts_nothing_twice_and_keeps_its_own_copies(tmp_path: Any, monkeypatch: Any) -> None:
    from pycoder.state.checkpoints import Checkpoints, own_set_aside
    from pycoder.state.session import SessionStore, Turn
    from pycoder.state.workspace import Workspace

    root, session, checkpoints = _setup(tmp_path, monkeypatch)
    session.cost, session.usage['input'] = 5.0, 100
    session.messages = [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'yo'}]
    session.turns = [Turn(1, 'hi', 0, 0.0)]
    (root / 'big').write_text('original', encoding='utf-8')
    checkpoints.before_write(str(root / 'big'), removing=True)
    os.remove(root / 'big')
    fork = session.forked_after(1)
    own_set_aside(fork)
    assert (fork.cost, fork.usage['input']) == (0.0, 0)
    SessionStore(str(tmp_path / 'sessions')).delete(session.id)  # takes the parent's folder with it
    assert Checkpoints(fork, Workspace(str(root))).restore(1) == ['big']
    assert (root / 'big').read_text(encoding='utf-8') == 'original'

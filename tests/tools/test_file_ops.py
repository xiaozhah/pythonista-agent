"""move_file / delete_file: they change only the workspace, and /rewind undoes them."""

from __future__ import annotations

import json
import os

import pytest

from pycoder import config
from pycoder.cancel import CancelToken
from pycoder.host import env
from pycoder.state import checkpoints
from pycoder.state.checkpoints import Checkpoints
from pycoder.state.session import Session
from pycoder.state.workspace import Workspace
from pycoder.tools import file_ops
from pycoder.tools.base import ToolContext, ToolError
from tests.conftest import RecordingFrontend


@pytest.fixture(autouse=True)
def set_aside_here(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, 'SET_ASIDE_DIR', str(tmp_path_factory.mktemp('set-aside')))


@pytest.fixture
def ctx(workspace: str) -> ToolContext:
    ws = Workspace(workspace)
    session = Session.new(workspace, 'claude-opus-5-5', 'system', web=False)
    checkpoints = Checkpoints(session, ws)
    checkpoints.turn = 1  # as during a turn: changes are remembered for /rewind
    return ToolContext(ws, RecordingFrontend(), session, checkpoints, CancelToken())


def write(root: str, rel: str, text: str) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def test_move_and_rewind(ctx: ToolContext) -> None:
    root = ctx.workspace.root
    write(root, 'src/a.py', 'a')
    assert file_ops.move_file(ctx, 'src/a.py', 'lib/b.py') == 'Moved src/a.py to lib/b.py'
    assert file_ops.move_file(ctx, 'lib', 'pkg') == 'Moved lib to pkg'
    assert os.path.isfile(os.path.join(root, 'pkg/b.py'))
    ctx.checkpoints.restore(1)
    assert os.path.isfile(os.path.join(root, 'src/a.py'))
    assert not os.path.exists(os.path.join(root, 'pkg/b.py'))


def test_move_refuses_to_overwrite_or_leave_the_workspace(ctx: ToolContext) -> None:
    write(ctx.workspace.root, 'b.py', 'b')
    with pytest.raises(ToolError, match='already exists'):
        file_ops.move_file(ctx, 'hello.py', 'b.py')
    with pytest.raises(ToolError, match='outside'):
        file_ops.move_file(ctx, 'hello.py', '../hello.py')
    with pytest.raises(ToolError, match='Not found'):
        file_ops.move_file(ctx, 'nope.py', 'x.py')


def test_delete_and_rewind(ctx: ToolContext) -> None:
    root = ctx.workspace.root
    write(root, 'build/x.txt', 'x')
    write(root, 'build/sub/y.txt', 'y')
    assert file_ops.delete_file(ctx, 'hello.py') == 'Deleted hello.py'
    assert file_ops.delete_file(ctx, 'build') == 'Deleted the folder build (2 files)'
    assert not os.path.exists(os.path.join(root, 'build'))
    with pytest.raises(ToolError, match='workspace folder itself'):
        file_ops.delete_file(ctx, '.')
    ctx.checkpoints.restore(1)
    with open(os.path.join(root, 'build/sub/y.txt'), encoding='utf-8') as f:
        assert f.read() == 'y'
    assert os.path.isfile(os.path.join(root, 'hello.py'))


def test_size_is_no_limit_and_nothing_goes_in_the_session(ctx: ToolContext) -> None:
    root = ctx.workspace.root
    big = os.path.join(root, 'big.bin')
    with open(big, 'wb') as f:
        f.truncate(50_000_000)
    for i in range(300):
        write(root, f'many/{i}.txt', str(i))

    file_ops.delete_file(ctx, 'big.bin')
    file_ops.delete_file(ctx, 'many')
    assert not os.path.exists(big)
    assert len(json.dumps(ctx.session.checkpoints)) < 50_000

    ctx.checkpoints.restore(1)
    assert os.path.getsize(big) == 50_000_000
    with open(os.path.join(root, 'many/299.txt'), encoding='utf-8') as f:
        assert f.read() == '299'


def test_moving_a_big_file_and_back(ctx: ToolContext) -> None:
    root = ctx.workspace.root
    with open(os.path.join(root, 'big.bin'), 'wb') as f:
        f.truncate(20_000_000)
    file_ops.move_file(ctx, 'big.bin', 'sub/renamed.bin')
    ctx.checkpoints.restore(1)
    assert os.path.getsize(os.path.join(root, 'big.bin')) == 20_000_000
    assert not os.path.exists(os.path.join(root, 'sub/renamed.bin'))


def test_a_big_file_replaced_comes_back(ctx: ToolContext) -> None:
    big = os.path.join(ctx.workspace.root, 'big.bin')
    with open(big, 'wb') as f:
        f.truncate(2_000_000)
    ctx.checkpoints.before_write(big)
    env.write_text(big, 'small now')
    assert len(json.dumps(ctx.session.checkpoints)) < 1000
    ctx.checkpoints.restore(1)
    assert os.path.getsize(big) == 2_000_000


def test_what_was_set_aside_long_ago_is_given_back_and_said_to_be_lost(ctx: ToolContext) -> None:
    file_ops.delete_file(ctx, 'hello.py')
    checkpoints.forget_old_set_aside(days=-1)
    assert ctx.checkpoints.not_restorable(1) == ['hello.py']
    assert ctx.checkpoints.restore(1) == []

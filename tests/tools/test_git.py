"""The git tool through dulwich."""

from __future__ import annotations

import os

import pytest

from pycoder.cancel import CancelToken
from pycoder.host import auth, vcs
from pycoder.state.checkpoints import Checkpoints
from pycoder.state.session import Session
from pycoder.state.workspace import Workspace
from pycoder.tools import git
from pycoder.tools.base import ToolContext, ToolError
from tests.conftest import RecordingFrontend


@pytest.fixture
def ctx(workspace: str) -> ToolContext:
    ws = Workspace(workspace)
    session = Session.new(workspace, 'claude-opus-5-5', 'system', web=False)
    return ToolContext(ws, RecordingFrontend(), session, Checkpoints(session, ws), CancelToken())


def test_git_init_add_commit_status_log_diff(ctx: ToolContext) -> None:
    pytest.importorskip('dulwich')
    vcs.disable_shell_hooks()
    assert 'Initialized' in git.git(ctx, 'init', path='repo')
    root = os.path.join(ctx.workspace.root, 'repo')
    hooks = os.path.join(root, '.git', 'hooks')
    os.makedirs(hooks, exist_ok=True)
    with open(os.path.join(hooks, 'pre-commit'), 'w', encoding='utf-8') as f:
        f.write('#!/bin/sh\nexit 1\n')  # would block the commit if hooks ran (they can't on iOS)
    os.chmod(os.path.join(hooks, 'pre-commit'), 0o755)
    with open(os.path.join(root, 'a.txt'), 'w', encoding='utf-8') as f:
        f.write('one\n')
    assert 'untracked: a.txt' in git.git(ctx, 'status', path='repo')
    git.git(ctx, 'add', path='repo')
    with open(os.path.join(root, '.git', 'config'), encoding='utf-8') as f:
        has_global = 'user' in f.read() or os.path.exists(os.path.expanduser('~/.gitconfig'))
    if not has_global:
        with pytest.raises(ToolError, match='No commit identity'):
            git.git(ctx, 'commit', path='repo', message='first')
    with open(os.path.join(root, '.git', 'config'), 'a', encoding='utf-8') as f:
        f.write('[user]\n\tname = Test\n\temail = test@example.com\n')
    assert git.git(ctx, 'commit', path='repo', message='first').startswith('Committed ')
    with open(os.path.join(root, 'a.txt'), 'w', encoding='utf-8') as f:
        f.write('two\n')
    assert '-one' in git.git(ctx, 'diff', path='repo')
    assert '+two' in git.git(ctx, 'diff', path='repo')
    assert 'first' in git.git(ctx, 'log', path='repo')
    os.remove(os.path.join(root, 'a.txt'))
    assert git.git(ctx, 'add', path='repo') == 'Staged 1 change(s)'
    git.git(ctx, 'commit', path='repo', message='remove a')
    assert 'working tree clean' in git.git(ctx, 'status', path='repo')


def test_git_reads_need_no_confirmation() -> None:
    tool = git.TOOLS[0]
    assert not tool.needs_confirmation({'command': 'status'})
    assert tool.needs_confirmation({'command': 'commit', 'message': 'x'})


class HTTPUnauthorized(Exception):
    """Named like dulwich's: GitHub turned the request away."""


def test_github_asks_for_a_token_only_when_turned_away(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored: list[str] = []
    monkeypatch.setattr(auth, '_keychain_get', lambda account: stored[0] if stored else None)
    monkeypatch.setattr(auth, '_keychain_set', lambda account, value: stored.append(value))
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    frontend = ctx.frontend
    assert isinstance(frontend, RecordingFrontend)
    sent: list[dict[str, str]] = []

    git._authorized(ctx, 'https://github.com/public/repo', sent.append)
    assert sent == [{}]
    assert frontend.named('ask_text') == []

    def private(creds: dict[str, str]) -> None:
        sent.append(creds)
        if not creds:
            raise HTTPUnauthorized()

    git._authorized(ctx, 'https://github.com/me/private', private)
    assert sent[-1] == {'username': 'x-access-token', 'password': 'secret-token'}
    assert len(frontend.named('ask_text')) == 1

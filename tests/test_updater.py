"""Self-update from a git remote, and rolling it back."""

from __future__ import annotations

import io
import json
import os
from typing import Any

import pytest

from pycoder import updater


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


V1 = {
    'pycoder/__init__.py': 'v1\n',
    'pycoder/gone.py': 'old module\n',
    'pycoder/edited.py': 'v1\n',
    'install.py': 'installer\n',
    'skills/shared/SKILL.md': 'upstream skill\n',
}
V2 = {
    'pycoder/__init__.py': 'v2\n',
    'pycoder/added.py': 'new\n',
    'pycoder/edited.py': 'v2\n',
    'install.py': 'installer\n',
    'skills/shared/SKILL.md': 'changed upstream\n',
    'skills/more/SKILL.md': 'more\n',
}


@pytest.fixture
def git_pair(tmp_path: Any) -> tuple[str, str, Any]:
    porcelain = pytest.importorskip('dulwich.porcelain')
    from pycoder.host.vcs import disable_shell_hooks

    disable_shell_hooks()  # on iOS dulwich would otherwise fail every commit
    upstream = str(tmp_path / 'upstream')
    porcelain.init(upstream)
    write(f'{upstream}/pycoder/__init__.py', 'v1\n')
    write(f'{upstream}/pycoder/old.py', 'old\n')
    write(f'{upstream}/skills/s/SKILL.md', 'skill\n')
    porcelain.add(
        upstream,
        paths=[
            f'{upstream}/pycoder/__init__.py',
            f'{upstream}/pycoder/old.py',
            f'{upstream}/skills/s/SKILL.md',
        ],
    )
    porcelain.commit(upstream, message=b'v1')
    local = str(tmp_path / 'local')
    porcelain.clone(upstream, local, errstream=io.BytesIO())
    write(f'{upstream}/pycoder/__init__.py', 'v2\n')
    write(f'{upstream}/pycoder/new.py', 'new\n')
    os.remove(f'{upstream}/pycoder/old.py')
    porcelain.add(upstream, paths=[f'{upstream}/pycoder/__init__.py', f'{upstream}/pycoder/new.py'])
    porcelain.remove(upstream, paths=[f'{upstream}/pycoder/old.py'], cached=True)
    porcelain.commit(upstream, message=b'v2')
    return upstream, local, porcelain


def git_updater(local: str) -> updater.Updater:
    return updater.Updater(home=local, branch='master', state_file=f'{local}/.pycoder/v.json')


def test_git_update_and_rollback(git_pair: tuple[str, str, Any]) -> None:
    _, local, porcelain = git_pair
    u = git_updater(local)
    before = porcelain.open_repo(local).head()
    result = u.update()
    assert result.changed == ['pycoder/__init__.py', 'pycoder/new.py', 'pycoder/old.py']
    assert read(f'{local}/pycoder/__init__.py') == 'v2\n'
    assert not os.path.exists(f'{local}/pycoder/old.py')  # deleted upstream: gone here too

    assert 'Rolled back' in u.rollback()
    repo = porcelain.open_repo(local)
    assert repo.head() == before  # the branch really moved back
    assert read(f'{local}/pycoder/__init__.py') == 'v1\n'
    assert read(f'{local}/pycoder/old.py') == 'old\n'
    assert not os.path.exists(f'{local}/pycoder/new.py')
    status = porcelain.status(repo)
    assert not status.unstaged
    assert not any(status.staged.values())


def test_git_update_refuses_uncommitted_changes_anywhere(git_pair: tuple[str, str, Any]) -> None:
    _, local, _ = git_pair
    write(f'{local}/skills/s/SKILL.md', 'edited skill\n')
    with pytest.raises(updater.UpdateError, match='Uncommitted changes'):
        git_updater(local).update()
    assert read(f'{local}/skills/s/SKILL.md') == 'edited skill\n'


def test_git_update_refuses_another_branch(git_pair: tuple[str, str, Any]) -> None:
    _, local, porcelain = git_pair
    repo = porcelain.open_repo(local)
    porcelain.branch_create(repo, 'dev')
    porcelain.checkout_branch(repo, 'dev')
    with pytest.raises(updater.UpdateError, match='On branch dev'):
        git_updater(local).update()


def test_git_update_is_fetched_then_fast_forwarded(git_pair: tuple[str, str, Any]) -> None:
    _, local, porcelain = git_pair
    u = updater.Updater(
        home=local, branch='master', state_file=f'{local}/.pycoder/v.json', stage_dir=f'{local}/.pycoder/st'
    )
    before = porcelain.open_repo(local).head()
    message = u.check_and_stage()
    assert message is not None
    assert 'next time' in message
    assert porcelain.open_repo(local).head() == before  # only fetched
    result = u.apply_staged()
    assert result is not None
    assert result.changed == ['pycoder/__init__.py', 'pycoder/new.py', 'pycoder/old.py']
    assert read(f'{local}/pycoder/__init__.py') == 'v2\n'
    assert not os.path.exists(f'{local}/pycoder/old.py')
    assert u.check_and_stage() is None


def test_a_staged_commit_that_was_not_fetched_is_refused(git_pair: tuple[str, str, Any]) -> None:
    _, local, porcelain = git_pair
    u = updater.Updater(
        home=local, branch='master', state_file=f'{local}/.pycoder/v.json', stage_dir=f'{local}/.pycoder/st'
    )
    assert u.check_and_stage() is not None
    before = porcelain.open_repo(local).head()
    u._save_staged({'sha': 'f' * 40, 'base': before.decode()})
    with pytest.raises(updater.UpdateError, match='not what was fetched'):
        u.apply_staged()
    assert porcelain.open_repo(local).head() == before


def test_checks_are_throttled(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from pycoder import launch

    monkeypatch.setattr(launch, 'CHECK_FILE', str(tmp_path / 'check.json'))
    assert launch._due(60)
    assert not launch._due(60)
    assert launch._due(0)


def test_a_checkout_ahead_of_github_has_nothing_to_get(git_pair: tuple[str, str, Any]) -> None:
    _, local, porcelain = git_pair
    u = updater.Updater(
        home=local, branch='master', state_file=f'{local}/.pycoder/v.json', stage_dir=f'{local}/.pycoder/st'
    )
    u.update()  # now level with upstream
    write(f'{local}/pycoder/mine.py', 'x\n')
    porcelain.add(local, paths=[f'{local}/pycoder/mine.py'])
    porcelain.commit(local, message=b'local work')
    assert u.check_and_stage() is None


def test_home_is_the_folder_holding_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    from pycoder import config

    monkeypatch.setattr(config, '_usable', lambda folder: True)
    assert config.home_for('/x/Documents/pycoder') == '/x/Documents'
    assert config.home_for('/x/Documents') == '/x/Documents'  # an install at the top of Documents
    assert config.SKILLS_DIR.startswith(config.INSTALL_DIR)
    assert os.path.join(config.HOME_DIR, '.pycoder') == config.DATA_DIR


def test_git_updates_report_what_they_added() -> None:
    git = updater._git_result('a', 'b', {'skills/clock/SKILL.md', 'pycoder/x.py'}, set(), set())
    assert git.added == ['skills/clock/SKILL.md']


def test_a_crash_is_reported_at_the_next_start(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import faulthandler
    import signal
    import sys

    from pycoder import launch
    from pycoder.host import diagnostics

    crash, last = tmp_path / 'crash.log', tmp_path / 'last.log'
    crash.write_text(
        'Fatal Python error: Segmentation fault\n\nThread 0x1 (most recent call first):\n'
        '  File "other.py", line 1 in x\n\nCurrent thread 0x2 (most recent call first):\n'
        '  File "game.py", line 12 in update\n  File "game.py", line 3 in main\n',
        encoding='utf-8',
    )
    monkeypatch.delitem(sys.__dict__, '_pycoder_crash_log', raising=False)
    monkeypatch.setattr(launch, '_heartbeat', lambda: None)
    monkeypatch.setattr(diagnostics, 'collect', lambda: [])
    notes = launch.watch_for_crashes(str(crash), str(last))
    try:
        assert 'at File "game.py", line 12 in update' in notes[0]
        assert last.exists()
        assert crash.read_text(encoding='utf-8') == ''  # ready for the next one
        assert launch.watch_for_crashes(str(crash), str(last)) == []  # a re-run in the same process
    finally:
        faulthandler.disable()
        faulthandler.unregister(signal.SIGTRAP)
        sys.__dict__.pop('_pycoder_crash_log').close()


def test_home_is_the_folder_holding_the_repository_when_it_can_be_used(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pycoder import config

    repo = tmp_path / 'home' / 'pycoder'
    repo.mkdir(parents=True)
    assert config.home_for(str(repo)) == str(tmp_path / 'home')
    assert config.home_for(str(tmp_path / 'Documents')) == str(tmp_path / 'Documents')  # the old layout
    monkeypatch.setattr(config, '_usable', lambda folder: False)  # a clone kept by a git app, on iOS
    documents = tmp_path / 'app' / 'Documents'
    documents.mkdir(parents=True)
    monkeypatch.setenv('HOME', str(tmp_path / 'app'))
    assert config.home_for(str(repo)) == str(documents.resolve())


def test_running_out_of_memory_is_noticed_at_the_next_start(tmp_path: Any) -> None:
    from pycoder import launch

    seen, last = tmp_path / 'last_seen.json', tmp_path / 'last_run.json'

    def note(samples: list[list[float]]) -> list[str]:
        seen.write_text(json.dumps(samples), encoding='utf-8')
        return launch.memory_note(str(seen), str(last))

    assert 'with 90 MB of memory left' in note([[1000, 90_000_000]])[0]
    assert not seen.exists()  # said once
    assert last.exists()  # and kept, for /crashes
    # plenty left at the end, but falling fast enough to be gone a moment later
    fast = note([[1000, 1_500_000_000], [1004, 700_000_000]])
    assert 'falling 200 MB a second' in fast[0]
    assert note([[1000, 3_000_000_000], [1004, 2_999_000_000]]) == []  # closed some other way
    assert launch.memory_note(str(tmp_path / 'none.json'), str(last)) == []
    seen.write_text('{"time": 1000, "memory_left": 9}', encoding='utf-8')  # an older version's
    assert launch.memory_note(str(seen), str(last)) == []

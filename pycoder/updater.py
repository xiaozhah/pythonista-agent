"""Self-update: bring pycoder's own git clone up to date from GitHub.

A fast-forward pull of the update branch, refused while anything tracked has uncommitted changes or
another branch is checked out. rollback() undoes the last update.

Automatic updates (as in Claude Code): opening pycoder calls check_and_stage() in the background, which
fetches a newer version without touching any file; it calls apply_staged() at the next
start, before pycoder's modules are imported, since Pythonista keeps imported modules and swapping
them under a running app breaks it. What was staged is checked against what was fetched before it is
installed.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import config
from .host import env, vcs

USER_CONTENT = ('skills/', 'commands/')  # what an update's notes name when it brings new ones


class UpdateError(Exception):
    pass


@dataclass
class UpdateResult:
    old: str
    new: str
    changed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)  # new skills or commands

    @property
    def up_to_date(self) -> bool:
        return self.old == self.new

    def summary(self) -> str:
        if self.up_to_date:
            return f'pycoder is up to date ({self.new[:7]})'
        lines = [
            f'Updated pycoder {self.old[:7] or "?"} → {self.new[:7]}, {len(self.changed)} file(s) changed'
        ]
        lines += ['  ' + p for p in self.changed[:15]]
        if len(self.changed) > 15:
            lines.append(f'  … {len(self.changed) - 15} more')
        if self.added:
            lines.append('New skills or commands: ' + ', '.join(self.added))
        lines.append('Restart pycoder to use the new version; /update rollback undoes it.')
        return '\n'.join(lines)


class Updater:
    def __init__(
        self,
        home: str = config.INSTALL_DIR,
        branch: str = config.UPDATE_BRANCH,
        token: Callable[[], str | None] = lambda: None,
        state_file: str = config.UPDATE_STATE,
        stage_dir: str = config.STAGE_DIR,
    ) -> None:
        self.home = home
        self.branch = branch
        self._token_source = token
        self._token: str | None = None
        self._token_asked = False
        self.state_file = state_file
        self.stage_dir = stage_dir

    def token(self) -> str | None:
        """Asked at most once per update."""
        if not self._token_asked:
            self._token_asked = True
            self._token = self._token_source()
        return self._token

    # ---- entry points

    def update(self) -> UpdateResult:
        repo = self._git_repo()
        if repo is None:
            raise UpdateError(f'{self.home} is not a git clone that can be used here; pull it by hand')
        return self._git_pull(repo)

    def rollback(self) -> str:
        state = self._state()
        if not state.get('previous'):
            raise UpdateError('No update to roll back')
        return self._git_rollback(state)

    # ---- automatic updates

    def check_and_stage(self) -> str | None:
        """Fetch a newer version for the next start. Returns what to tell the user, or None when there
        is nothing to say (up to date, or no clone that can be used here)."""
        repo = self._git_repo()
        if repo is None:
            return None
        head = repo.head().decode()
        remote = self._git_fetch(repo)
        if remote is None or remote == head:
            return None
        from dulwich.graph import can_fast_forward

        if can_fast_forward(repo, remote.encode(), head.encode()):  # type: ignore[no-untyped-call]
            return None  # this checkout is ahead (unpushed commits): nothing to get
        if not can_fast_forward(repo, head.encode(), remote.encode()):  # type: ignore[no-untyped-call]
            return f'pycoder: {self.branch} on GitHub has diverged from this checkout; merge it with git'
        self._save_staged({'sha': remote, 'base': head})
        return f'pycoder {remote[:7]} is ready; it takes effect the next time you open pycoder'

    def apply_staged(self) -> UpdateResult | None:
        """Install what check_and_stage() prepared, if anything (UpdateError if it can't be)."""
        staged = self._staged()
        if not staged:
            return None
        try:
            repo = self._git_repo()
            if repo is None:
                return None
            if self._fetched(repo) != staged['sha']:
                raise UpdateError(f'{staged["sha"][:7]} is not what was fetched for {self.branch}')
            return self._git_fast_forward(repo, staged['sha'])
        finally:
            self._clear_staged()  # whatever happens, try a staged update only once

    def _staged(self) -> dict[str, Any]:
        try:
            with open(os.path.join(self.stage_dir, 'staged.json'), encoding='utf-8') as f:
                data: dict[str, Any] = json.load(f)
                return data
        except (OSError, ValueError):
            return {}

    def _save_staged(self, staged: dict[str, Any]) -> None:
        os.makedirs(self.stage_dir, exist_ok=True)
        with open(os.path.join(self.stage_dir, 'staged.json'), 'w', encoding='utf-8') as f:
            json.dump(staged, f)

    def _clear_staged(self) -> None:
        shutil.rmtree(self.stage_dir, ignore_errors=True)

    # ---- git

    def _git_fetch(self, repo: Any) -> str | None:
        """Fetch origin; the branch's commit there, or None if it can't be read."""
        from dulwich import porcelain

        credentials = vcs.credentials(self.token() if vcs.is_github(vcs.remote_url(repo)) else None)
        try:
            porcelain.fetch(  # type: ignore[no-untyped-call]
                repo, 'origin', outstream=io.StringIO(), errstream=io.BytesIO(), **credentials
            )
        except Exception as e:
            raise UpdateError(f'git fetch failed: {type(e).__name__}: {e}') from e
        return self._fetched(repo)

    def _fetched(self, repo: Any) -> str | None:
        """The commit the last fetch recorded for the update branch."""
        try:
            return str(repo.refs[b'refs/remotes/origin/' + self.branch.encode()].decode())
        except KeyError:
            return None

    def _git_fast_forward(self, repo: Any, sha: str) -> UpdateResult:
        """Move the branch to an already fetched commit, as pull would, without the network."""
        from dulwich import porcelain
        from dulwich.graph import can_fast_forward

        self._check_clean(repo)
        old = repo.head().decode()
        if old == sha:
            return UpdateResult(old, sha)
        if not can_fast_forward(repo, old.encode(), sha.encode()):  # type: ignore[no-untyped-call]
            raise UpdateError('The checkout moved since the update was fetched; run pycoder update')
        added, removed, modified = vcs.tree_diff(repo, old, sha)
        ref = b'refs/heads/' + porcelain.active_branch(repo)  # type: ignore[no-untyped-call]
        repo.refs[ref] = sha.encode()
        porcelain.reset(repo, 'hard', sha.encode())
        for rel in removed:
            full = os.path.join(self.home, rel)
            if os.path.isfile(full):
                env.remove_file(full)
        self._save_state({'previous': old, 'current': sha, 'time': time.time()})
        return _git_result(old, sha, added, removed, modified)

    def _check_clean(self, repo: Any) -> None:
        from dulwich import porcelain

        branch = porcelain.active_branch(repo).decode()  # type: ignore[no-untyped-call]
        if branch != self.branch:
            raise UpdateError(f'On branch {branch}; switch to {self.branch} to update pycoder')
        dirty = vcs.dirty_files(repo)
        if dirty:
            raise UpdateError(
                'Uncommitted changes would be overwritten; commit or discard them first: '
                + ', '.join(dirty[:5])
            )

    def _git_repo(self) -> Any:
        """The dulwich repository for pycoder's folder, or None if git can't be used here."""
        if not os.path.exists(os.path.join(self.home, '.git')):
            return None
        return vcs.open_repo(self.home)

    def _git_pull(self, repo: Any) -> UpdateResult:
        from dulwich import porcelain

        self._check_clean(repo)
        old = repo.head().decode()
        credentials = vcs.credentials(self.token() if vcs.is_github(vcs.remote_url(repo)) else None)
        try:
            porcelain.pull(
                repo,
                'origin',
                refspecs=[self.branch.encode()],
                errstream=io.BytesIO(),
                outstream=io.BytesIO(),
                **credentials,
            )
        except Exception as e:
            raise UpdateError(f'git pull failed: {type(e).__name__}: {e}') from e
        new = repo.head().decode()
        if new == old:
            return UpdateResult(old, new)
        added, removed, modified = vcs.tree_diff(repo, old, new)
        for rel in removed:  # deleted upstream: a stale module would still be importable
            full = os.path.join(self.home, rel)
            if os.path.isfile(full):
                env.remove_file(full)
        self._save_state({'previous': old, 'current': new, 'time': time.time()})
        return _git_result(old, new, added, removed, modified)

    def _git_rollback(self, state: dict[str, Any]) -> str:
        repo = self._git_repo()
        if repo is None:
            raise UpdateError('The git repository is not available here')
        current, previous = state['current'], state['previous']
        if repo.head().decode() != current:
            raise UpdateError('The repository moved on since the update; roll back with git instead')
        from dulwich import porcelain

        added, _, _ = vcs.tree_diff(repo, previous, current)
        for rel in added:  # files the update brought in
            full = os.path.join(self.home, rel)
            if os.path.isfile(full):
                env.remove_file(full)
        ref = b'refs/heads/' + porcelain.active_branch(repo)  # type: ignore[no-untyped-call]
        repo.refs[ref] = previous.encode()  # move the branch back, then the index and files
        porcelain.reset(repo, 'hard', previous.encode())
        self._save_state({})
        return f'Rolled back to {previous[:7]}'

    # ---- helpers

    def _state(self) -> dict[str, Any]:
        try:
            with open(self.state_file, encoding='utf-8') as f:
                data: dict[str, Any] = json.load(f)
                return data
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f)


def command(arg: str, ask_token: Callable[[], str | None]) -> str:
    """`pycoder update` and `pycoder rollback`, from the shell or /update.

    ask_token asks the user for a GitHub token, used only if the repository needs one.
    """
    from .host import auth

    def token() -> str | None:
        try:
            return auth.get_github_token(ask_token)
        except auth.MissingSecret:
            return None  # a public repository needs none

    u = Updater(token=token)
    if arg == 'rollback':
        return u.rollback() + '; restart pycoder to use it'
    result = u.update()
    return result.summary() + ('' if result.up_to_date else '\nRestart pycoder to use it.')


def _git_result(old: str, new: str, added: set[str], removed: set[str], modified: set[str]) -> UpdateResult:
    changed = sorted(added | removed | modified)
    return UpdateResult(old, new, changed, sorted(p for p in added if p.startswith(USER_CONTENT)))

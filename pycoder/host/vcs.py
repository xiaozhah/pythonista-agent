"""git helpers shared by the git tool and the updater, over dulwich (pure-Python git).

dulwich is pinned to 0.22.8: newer releases need urllib3 2.x, which would clash with the requests
version Pythonista ships.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from . import env

DULWICH = 'dulwich==0.22.8'


def disable_shell_hooks() -> None:
    """Make dulwich skip git hooks when processes can't be started (iOS).

    dulwich runs every hook with subprocess.call and relies on OSError for a missing hook file,
    but on iOS subprocess raises RuntimeError, so without this every commit fails, hook or not.
    """
    if not env.IN_PYTHONISTA:
        return
    from dulwich import hooks

    hooks.ShellHook.execute = lambda self, *args: None  # type: ignore[method-assign]


def open_repo(path: str) -> Any:
    """The repository at path, or None when there is none that works here: a .git that points at
    another device's data (a Mac's checkout seen through iCloud) opens as an empty repository."""
    try:
        from dulwich import porcelain
        from dulwich.repo import Repo

        disable_shell_hooks()
        repo = Repo(path)
        porcelain.active_branch(repo)  # type: ignore[no-untyped-call]
        repo.head()
    except Exception:
        return None
    repo.hooks.clear()  # hooks are shell scripts; iOS can't run them
    return repo


def is_github(url: str) -> bool:
    """Checked on the parsed host, not a string prefix: a GitHub token goes only to github.com."""
    return (urlparse(url).hostname or '').lower() == 'github.com'


def remote_url(repo: Any, remote: str = 'origin') -> str:
    if '://' in remote:
        return remote
    try:
        return str(repo.get_config().get((b'remote', remote.encode()), b'url').decode())
    except KeyError:
        return ''


def credentials(token: str | None) -> dict[str, str]:
    """Keyword arguments for dulwich's clone, fetch, pull and push."""
    return {'username': 'x-access-token', 'password': token} if token else {}


def dirty_files(repo: Any) -> list[str]:
    """Tracked files with uncommitted changes, staged or not."""
    from dulwich import porcelain

    status = porcelain.status(repo)  # type: ignore[no-untyped-call]
    return [p.decode() for p in status.unstaged] + [
        p.decode() for kind in ('add', 'modify', 'delete') for p in status.staged.get(kind, [])
    ]


def tree_diff(repo: Any, old: str, new: str) -> tuple[set[str], set[str], set[str]]:
    """(added, removed, modified) paths between two commits."""
    added, removed, modified = set(), set(), set()
    for change in repo.object_store.tree_changes(repo[old.encode()].tree, repo[new.encode()].tree):
        old_path, new_path = change[0]
        if old_path is None:
            added.add(new_path.decode())
        elif new_path is None:
            removed.add(old_path.decode())
        else:
            modified.add(new_path.decode())
    return added, removed, modified

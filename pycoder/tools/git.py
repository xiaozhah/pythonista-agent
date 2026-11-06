"""git: version control through dulwich, a pure-Python git implementation (as StaSh uses).

dulwich is installed on first use (see vcs.py for the pin and the helpers shared with updates).
"""

from __future__ import annotations

import difflib
import io
import os
from collections.abc import Callable
from typing import Any

from ..host import auth, packages, vcs
from ..host.vcs import DULWICH, disable_shell_hooks, is_github, remote_url
from .base import Tool, ToolContext, ToolError, prop

COMMANDS = (
    'status',
    'diff',
    'add',
    'commit',
    'log',
    'branch',
    'checkout',
    'pull',
    'push',
    'clone',
    'init',
    'config',
)
IDENTITY = ('user.name', 'user.email')
READ_ONLY_COMMANDS = ('status', 'diff', 'log')


def _porcelain(ctx: ToolContext) -> Any:
    try:
        from dulwich import porcelain
    except ImportError:
        ctx.frontend.run_output(f'installing {DULWICH} (first use of git)')
        try:
            packages.install(DULWICH, log=lambda line: ctx.frontend.run_output(line))
        except packages.PackageError as e:
            raise ToolError(f'Could not install dulwich: {e}') from e
        from dulwich import porcelain
    disable_shell_hooks()
    return porcelain


def git(
    ctx: ToolContext,
    command: str,
    path: str = '.',
    paths: list[str] | None = None,
    message: str = '',
    url: str = '',
    branch: str = '',
    remote: str = 'origin',
    count: int = 10,
    key: str = '',
    value: str = '',
    everywhere: bool = False,
) -> str:
    porcelain = _porcelain(ctx)
    repo_dir = ctx.workspace.resolve(path)
    try:
        if command == 'config':
            return _set_identity(repo_dir, key, value, everywhere)
        if command == 'init':
            porcelain.init(repo_dir)
            return f'Initialized an empty repository in {ctx.workspace.rel(repo_dir)}'
        if command == 'clone':
            if not url:
                raise ToolError('clone needs url')
            _authorized(
                ctx, url, lambda creds: porcelain.clone(url, repo_dir, errstream=io.BytesIO(), **creds)
            )
            return f'Cloned {url} into {ctx.workspace.rel(repo_dir)}'
        with porcelain.open_repo_closing(repo_dir) as repo:
            # git hooks are shell scripts and iOS can't start processes, so they never run here
            repo.hooks.clear()
            if command == 'status':
                return _status(porcelain, repo)
            if command == 'diff':
                return _diff(porcelain, repo, repo_dir)
            if command == 'add':
                return _add(porcelain, repo, repo_dir, paths)
            if command == 'commit':
                if not message:
                    raise ToolError('commit needs message')
                try:  # the repository's own config, then the user's (~/.gitconfig)
                    repo.get_config_stack().get((b'user',), b'name')
                except KeyError:
                    raise ToolError(
                        'No commit identity: ask the user for their name and email, then set them with '
                        'command config, key user.name / user.email (everywhere: true for all repositories)'
                    ) from None
                sha = porcelain.commit(repo, message=message.encode('utf-8'))
                return f'Committed {sha.decode()[:7]}'
            if command == 'log':
                return _log(repo, count)
            if command == 'branch':
                if branch:
                    porcelain.branch_create(repo, branch)
                    return f'Created branch {branch}'
                current = porcelain.active_branch(repo).decode()
                return '\n'.join(
                    ('* ' if b.decode() == current else '  ') + b.decode()
                    for b in porcelain.branch_list(repo)
                )
            if command == 'checkout':
                if not branch:
                    raise ToolError('checkout needs branch')
                porcelain.checkout_branch(repo, branch)
                return f'Switched to {branch}'
            if command in ('pull', 'push'):
                out, err = io.BytesIO(), io.BytesIO()
                refspec = branch or porcelain.active_branch(repo).decode()
                run = porcelain.pull if command == 'pull' else porcelain.push
                _authorized(
                    ctx,
                    remote_url(repo, remote),
                    lambda creds: run(
                        repo, remote, refspecs=[refspec.encode()], outstream=out, errstream=err, **creds
                    ),
                )
                detail = (out.getvalue() + err.getvalue()).decode('utf-8', 'replace').strip()
                return '{} {} {} done{}'.format(command, remote, refspec, '\n' + detail if detail else '')
    except ToolError:
        raise
    except Exception as e:
        raise ToolError(f'git {command} failed: {type(e).__name__}: {e}') from e
    raise ToolError('Unknown git command {}; use one of {}'.format(command, ', '.join(COMMANDS)))


def _set_identity(repo_dir: str, key: str, value: str, everywhere: bool) -> str:
    """git config user.name / user.email, for this repository or (everywhere) the user's ~/.gitconfig."""
    if key not in IDENTITY or not value:
        raise ToolError(f'config sets {" or ".join(IDENTITY)}: give key and value')
    from dulwich.config import ConfigFile

    path = os.path.expanduser('~/.gitconfig') if everywhere else os.path.join(repo_dir, '.git', 'config')
    if not everywhere and not os.path.isdir(os.path.dirname(path)):
        raise ToolError(f'Not a git repository: {repo_dir}')
    config = ConfigFile.from_path(path) if os.path.exists(path) else ConfigFile()
    section, _, name = key.partition('.')
    config.set((section.encode(),), name.encode(), value.encode())
    config.write_to_path(path)
    return f'{key} = {value} ({"every repository" if everywhere else "this repository"})'


def _authorized(ctx: ToolContext, url: str, run: Callable[[dict[str, str]], Any]) -> None:
    """Run a network command against url. A GitHub token already in the keychain goes along; the user
    is asked for one only when GitHub turns the request away, so public repositories never ask. The
    token goes only to github.com itself (checked on the parsed host, not a string prefix)."""
    if not is_github(url):
        run({})
        return
    credentials = _credentials(ctx, ask=False)
    try:
        run(credentials)
        return
    except Exception as e:
        if credentials or type(e).__name__ != 'HTTPUnauthorized':
            raise
        refused = e
    credentials = _credentials(ctx, ask=True)
    if not credentials:
        raise refused
    run(credentials)


def _credentials(ctx: ToolContext, ask: bool) -> dict[str, str]:
    def ask_text() -> str | None:
        return ctx.frontend.ask_text(
            'GitHub token',
            'GitHub needs a personal access token for this repository; kept in the iOS keychain',
            True,
        )

    try:
        token = auth.get_github_token(ask_text if ask else lambda: None)
    except auth.MissingSecret:
        return {}
    return vcs.credentials(token)


def _add(porcelain: Any, repo: Any, repo_dir: str, paths: list[str] | None) -> str:
    """Stage the given files, or every change. Paths are passed absolute: dulwich would otherwise
    resolve them against the process's working directory, which in Pythonista isn't the repository."""
    if paths:
        porcelain.add(repo, paths=[os.path.join(repo_dir, p) for p in paths])
        return 'Staged ' + ', '.join(paths)
    st = porcelain.status(repo)
    changed = [_text(p) for p in st.unstaged] + [_text(p) for p in st.untracked]
    present = [p for p in changed if os.path.exists(os.path.join(repo_dir, p))]
    gone = [p for p in changed if p not in present]
    if present:
        porcelain.add(repo, paths=[os.path.join(repo_dir, p) for p in present])
    if gone:
        porcelain.remove(repo, paths=[os.path.join(repo_dir, p) for p in gone], cached=True)
    return 'Staged %d change(s)' % len(changed) if changed else 'Nothing to stage'


def _text(path: bytes | str) -> str:
    return path.decode() if isinstance(path, bytes) else path


def _status(porcelain: Any, repo: Any) -> str:
    st = porcelain.status(repo)
    lines = [f'On branch {porcelain.active_branch(repo).decode()}']
    for label, key in (('new', 'add'), ('modified', 'modify'), ('deleted', 'delete')):
        lines += [f'  staged {label}: {p.decode()}' for p in st.staged.get(key, [])]
    lines += [f'  not staged: {p.decode()}' for p in st.unstaged]
    lines += ['  untracked: %s' % (p.decode() if isinstance(p, bytes) else p) for p in st.untracked]
    return '\n'.join(lines) if len(lines) > 1 else lines[0] + '\nnothing to commit, working tree clean'


def _diff(porcelain: Any, repo: Any, repo_dir: str) -> str:
    """Working tree against HEAD, as a unified diff."""
    from dulwich.object_store import tree_lookup_path

    st = porcelain.status(repo)
    changed = sorted(
        {p.decode() for p in st.unstaged}
        | {p.decode() for k in ('add', 'modify', 'delete') for p in st.staged.get(k, [])}
    )
    try:
        tree = repo[repo.head()].tree
    except KeyError:
        tree = None
    chunks: list[str] = []
    for rel in changed:
        old = ''
        if tree is not None:
            try:
                _, sha = tree_lookup_path(repo.get_object, tree, rel.encode())  # type: ignore[no-untyped-call]
                old = repo[sha].data.decode('utf-8', 'replace')
            except KeyError:
                pass
        full = os.path.join(repo_dir, rel)
        new = ''
        if os.path.isfile(full):
            with open(full, encoding='utf-8', errors='replace') as f:
                new = f.read()
        chunks += difflib.unified_diff(
            old.splitlines(), new.splitlines(), 'a/' + rel, 'b/' + rel, lineterm=''
        )
    return '\n'.join(chunks) or 'No changes'


def _log(repo: Any, count: int) -> str:
    lines = []
    for entry in repo.get_walker(max_entries=count):
        c = entry.commit
        lines.append(
            '{} {}  {}'.format(
                c.id.decode()[:7],
                c.author.decode('utf-8', 'replace').split(' <')[0],
                c.message.decode('utf-8', 'replace').splitlines()[0] if c.message else '',
            )
        )
    return '\n'.join(lines) or 'No commits yet'


TOOLS = [
    Tool(
        'git',
        'Run a git command on a repository in the workspace (pure-Python git via dulwich; installed on first '
        'use). Commands: {}. GitHub asks for a token only for private repositories and pushes; it is '
        'kept in the iOS keychain. Show the user what you will commit before committing.'.format(
            ', '.join(COMMANDS)
        ),
        {
            'command': prop('string', 'The git command', enum=list(COMMANDS)),
            'path': prop(
                'string', 'Repository folder relative to the workspace (default "."); for clone, the target'
            ),
            'paths': prop('array', 'Files to stage for add (default: all changes)', items={'type': 'string'}),
            'message': prop('string', 'Commit message'),
            'url': prop('string', 'Remote URL for clone, ending in .git'),
            'branch': prop('string', 'Branch for branch (create), checkout, pull and push'),
            'remote': prop('string', 'Remote name for pull/push, default "origin"'),
            'count': prop('integer', 'Number of log entries, default 10'),
            'key': prop('string', 'For config: user.name or user.email'),
            'value': prop('string', 'For config: the name or email address'),
            'everywhere': prop('boolean', 'For config: set it for every repository (~/.gitconfig)'),
        },
        git,
        required=['command'],
        readonly=False,
        writes_anywhere=True,  # checkout, pull and clone change the working tree
        safe_input=lambda inp: (
            inp.get('command') in READ_ONLY_COMMANDS
            or (inp.get('command') == 'branch' and not inp.get('branch'))
        ),
    ),
]

"""The built-in shell: one set of commands for `!` lines in the chat and for the console.

iOS can't start processes, so every command is pycoder's own pure-Python code (dulwich git, the
package installer, run_python, file operations). A Shell has a current folder and a home it never
leaves; paths are relative to the current folder, and ~ is the home.
"""

from __future__ import annotations

import itertools
import os
import shlex
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from .. import config, updater
from ..cancel import CancelToken
from ..events import Frontend
from ..host import env, packages
from ..state.checkpoints import Checkpoints
from ..state.session import Session
from ..state.workspace import ToolError, Workspace
from ..tools import files, git, python_runner
from ..tools.base import ToolContext

MAX_NOTE = 8000  # characters of output kept in the conversation for a `!` command


class ShellError(Exception):
    """A command failed. done is what the commands before it in the line printed."""

    def __init__(self, message: str, done: str = '') -> None:
        super().__init__('\n'.join(filter(None, [done, message])))
        self.reason = message
        self.done = done


def split_commands(line: str) -> list[tuple[list[str], str]]:
    """The commands of a line and what follows each: '&&', ';' or '' for the last."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars='&;|')
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as e:
        raise ShellError(f'Cannot parse the command: {e}') from e
    commands: list[tuple[list[str], str]] = []
    words: list[str] = []
    for token in tokens:
        if token in ('&&', ';'):
            commands.append((words, token))
            words = []
        elif token in ('|', '||', '&', '|&', ';;'):
            raise ShellError(f"'{token}' isn't supported here (no pipes or background jobs); use && or ;")
        else:
            words.append(token)
    commands.append((words, ''))
    return [(w, j) for w, j in commands if w]


def describe_error(e: BaseException) -> str:
    """How a failed command reads: the shell's own errors as they are, others with their type."""
    if isinstance(e, (ShellError, ToolError, updater.UpdateError)):
        return str(e)
    return f'{type(e).__name__}: {e}'


ICLOUD = '/iCloud'  # the shell's name for Pythonista's iCloud Drive folder, synced between devices
LOCAL = '/local'  # the shell's name for the device's own storage (Pythonista's "This iPad")


def default_places() -> dict[str, str]:
    """Folders besides the home that the shell can reach, by the name typed for them."""
    local, icloud = env.local_documents(), env.icloud_documents()
    places = {LOCAL: local} if local else {}
    if icloud:
        places[ICLOUD] = icloud
    # a clone a git app keeps for Pythonista isn't in the home: still reachable, to work on pycoder
    if os.path.commonpath([config.HOME_DIR, config.INSTALL_DIR]) != config.HOME_DIR:
        places['/pycoder'] = config.INSTALL_DIR
    return places


class Shell:
    def __init__(
        self,
        cwd: str,
        home: str = config.HOME_DIR,
        frontend: Frontend | None = None,
        cancel: CancelToken | None = None,
        on_cd: Callable[[str], str] | None = None,
        places: dict[str, str] | None = None,
    ) -> None:
        self.home = os.path.realpath(home)
        # ~ is the home; /local is this device's storage
        named = default_places() if places is None else places
        self.places = {name: os.path.realpath(path) for name, path in named.items() if path}
        self.cwd = os.path.realpath(cwd)
        self.previous = self.cwd
        self.frontend = frontend or Frontend()
        self.cancel = cancel or CancelToken()
        # the chat hands a cd over to the controller, which starts a session in the new folder
        self.on_cd = on_cd

    @property
    def workspace(self) -> Workspace:
        return Workspace(self.cwd, (self.home, *self.places.values()), home=self.home)

    def path(self, path: str) -> str:
        """Absolute path for one relative to the current folder, or under ~, /local or /iCloud."""
        if path == '~' or path.startswith('~/'):
            path = self.home + path[1:]
        for name, folder in self.places.items():
            if path == name or path.startswith(name + '/'):
                path = folder + path[len(name) :]
        return self.workspace.resolve(path)

    def display(self, path: str) -> str:
        """How a folder is shown: ~/… in the home, /local/… or /iCloud/… there, else as it is."""
        for name, folder in [('~', self.home), *self.places.items()]:
            if os.path.commonpath([folder, path]) == folder:
                rel = os.path.relpath(path, folder)
                return name if rel == '.' else f'{name}/{rel}'
        return path

    def contains(self, path: str) -> bool:
        """Whether a folder is somewhere the shell may go."""
        full = os.path.realpath(path)
        return any(os.path.commonpath([f, full]) == f for f in (self.home, *self.places.values()))

    def context(self) -> ToolContext:
        """What the tools behind git, python and ls need: a scratch session in the current folder."""
        workspace = self.workspace
        session = Session.new(self.cwd, config.DEFAULT_MODEL, '', False)
        return ToolContext(workspace, self.frontend, session, Checkpoints(session, workspace), self.cancel)

    def run(self, line: str) -> str:
        """Run a command line, where `a && b` runs b only if a worked and `a; b` runs both;
        ShellError (or ToolError, UpdateError) when it fails."""
        outputs: list[str] = []
        for words, joiner in split_commands(line):
            try:
                output = self._run_one(words)
            except Exception as e:
                if joiner != ';':
                    raise ShellError(describe_error(e), '\n'.join(outputs)) from e
                output = describe_error(e)
            if output:
                outputs.append(output)
        return '\n'.join(outputs)

    def _run_one(self, words: list[str]) -> str:
        if not words:
            return ''
        command = COMMANDS.get(words[0])
        if command is None:
            raise ShellError(
                f'{words[0]}: command not found (help lists the commands; iOS has no real shell)'
            )
        self.cancel.reset()
        try:
            return command.run(self, words[1:])
        except ToolError as e:
            raise ShellError(str(e)) from e

    def cd(self, target: str) -> str:
        full = self.path(self.previous if target == '-' else target or '~')
        if not os.path.isdir(full):
            raise ShellError(f'cd: no such folder: {target}')
        if self.on_cd is not None:
            return self.on_cd(full)
        self.previous, self.cwd = self.cwd, full
        return ''


@dataclass(frozen=True)
class Command:
    usage: str
    run: Callable[[Shell, list[str]], str]
    # what the command palette offers for it: (text to insert, what it does); default: the usage
    hints: tuple[tuple[str, str], ...] = ()


# ---- files


def _ls(sh: Shell, args: list[str]) -> str:
    return files.list_files(sh.context(), next((a for a in args if not a.startswith('-')), '.'))


def _cat(sh: Shell, args: list[str]) -> str:
    return '\n'.join(sh.workspace.read_text(sh.path(a)) for a in args)


def _head(sh: Shell, args: list[str]) -> str:
    count = int(args[args.index('-n') + 1]) if '-n' in args else 20
    paths = [a for i, a in enumerate(args) if not a.startswith('-') and (i == 0 or args[i - 1] != '-n')]
    out = []
    for p in paths:
        with open(sh.path(p), encoding='utf-8', errors='replace') as f:
            out.append(''.join(itertools.islice(f, count)).rstrip('\n'))
    return '\n'.join(out)


def _tree(sh: Shell, args: list[str], limit: int = 300) -> str:
    top = sh.path(next((a for a in args if not a.startswith('-')), '.'))
    lines = ['.' if top == sh.cwd else os.path.relpath(top, sh.cwd)]
    count = 0

    def walk(folder: str, prefix: str) -> None:
        nonlocal count
        names = sorted(n for n in os.listdir(folder) if not Workspace.is_hidden(n))
        for i, name in enumerate(names):
            count += 1
            if count > limit:
                return
            last = i == len(names) - 1
            full = os.path.join(folder, name)
            is_dir = os.path.isdir(full) and not os.path.islink(full)
            lines.append(prefix + ('└── ' if last else '├── ') + name + ('/' if is_dir else ''))
            if is_dir:
                walk(full, prefix + ('    ' if last else '│   '))

    walk(top, '')
    if count > limit:
        lines.append(f'… (stopped after {limit} entries)')
    return '\n'.join(lines)


def _touch(sh: Shell, args: list[str]) -> str:
    for a in args:
        full = sh.path(a)
        if os.path.exists(full):
            os.utime(full)
        else:
            open(full, 'a', encoding='utf-8').close()
    return ''


def _mkdir(sh: Shell, args: list[str]) -> str:
    for a in (a for a in args if not a.startswith('-')):
        os.makedirs(sh.path(a), exist_ok=True)
    return ''


def _move_or_copy(name: str) -> Callable[[Shell, list[str]], str]:
    def run(sh: Shell, args: list[str]) -> str:
        paths = [a for a in args if not a.startswith('-')]
        if len(paths) < 2:
            raise ShellError(f'usage: {name} <source>… <target>')
        target = sh.path(paths[-1])
        sources = [sh.path(p) for p in paths[:-1]]
        if len(sources) > 1 and not os.path.isdir(target):
            raise ShellError(f'{name}: {paths[-1]} is not a folder')
        for src in sources:
            if src in (sh.home, sh.cwd, *sh.places.values()):
                raise ShellError(f'{name}: refusing to move or copy the current folder, the home or /local')
            dest = os.path.join(target, os.path.basename(src)) if os.path.isdir(target) else target
            if name == 'mv':
                shutil.move(src, dest)
            elif os.path.isdir(src):
                if '-r' not in args:
                    raise ShellError(f'cp: {os.path.basename(src)} is a folder (use cp -r)')
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
        return ''

    return run


def _rm(sh: Shell, args: list[str]) -> str:
    recursive = any(a in ('-r', '-rf', '-fr', '-R') for a in args)
    removed = []
    for a in (a for a in args if not a.startswith('-')):
        link = os.path.join(sh.cwd, a)
        if os.path.islink(link):  # path() follows links; remove the link, not its target
            os.remove(link)
            removed.append(a)
            continue
        full = sh.path(a)
        if full in (sh.cwd, sh.home, *sh.places.values()):
            raise ShellError('refusing to remove the current folder, the home or /local')
        if os.path.isdir(full):
            if not recursive:
                raise ShellError(f'{a} is a folder (use rm -r)')
            shutil.rmtree(full)
        elif os.path.exists(full):
            env.remove_file(full)
        else:
            raise ShellError(f'{a}: no such file')
        removed.append(a)
    return 'removed ' + ', '.join(removed) if removed else ''


# ---- git, pip, python, pycoder


def _git(sh: Shell, args: list[str]) -> str:
    ctx = sh.context()
    path = '.'
    if args[:1] == ['-C'] and len(args) > 1:
        path, args = args[1], args[2:]
    if not args:
        raise ShellError('usage: git <command> …')
    command, rest = args[0], args[1:]
    if command == 'clone':
        if not rest:
            raise ShellError('usage: git clone <url> [dir]')
        url = rest[0]
        target = rest[1] if len(rest) > 1 else url.rstrip('/').removesuffix('.git').rsplit('/', 1)[-1]
        return git.git(ctx, 'clone', path=os.path.join(path, target), url=url)
    if command == 'init':
        return git.git(ctx, 'init', path=os.path.join(path, rest[0]) if rest else path)
    if command in ('status', 'diff'):
        return git.git(ctx, command, path=path)
    if command == 'log':
        short = [a[1:] for a in rest if a[:1] == '-' and a[1:].isdigit()]  # git log -3
        count = int(short[0]) if short else int(rest[rest.index('-n') + 1]) if '-n' in rest else 10
        return git.git(ctx, 'log', path=path, count=count)
    if command == 'add':
        flags = [p for p in rest if p.startswith('-') and p not in ('-A', '--all')]
        if flags:
            raise ShellError(f'git add: {" ".join(flags)} not supported; give paths, "." or -A')
        targets = [p for p in rest if p not in ('.', '-A', '--all')]
        return git.git(ctx, 'add', path=path, paths=targets or None)
    if command == 'commit':
        if '-m' not in rest and '-am' not in rest:
            raise ShellError('usage: git commit [-a] -m <message>')
        flag = '-m' if '-m' in rest else '-am'
        message = rest[rest.index(flag) + 1]
        out = ''
        if flag == '-am' or '-a' in rest:
            out = git.git(ctx, 'add', path=path) + '\n'
        return out + git.git(ctx, 'commit', path=path, message=message)
    if command == 'config':
        everywhere = '--global' in rest
        rest = [a for a in rest if a != '--global']
        if len(rest) != 2:
            raise ShellError('usage: git config [--global] user.name|user.email <value>')
        return git.git(ctx, 'config', path=path, key=rest[0], value=rest[1], everywhere=everywhere)
    if command == 'branch':
        return git.git(ctx, 'branch', path=path, branch=rest[0] if rest else '')
    if command == 'checkout':
        if '-b' in rest:
            name = rest[rest.index('-b') + 1]
            created = git.git(ctx, 'branch', path=path, branch=name)
            return created + '\n' + git.git(ctx, 'checkout', path=path, branch=name)
        if not rest:
            raise ShellError('usage: git checkout [-b] <branch>')
        return git.git(ctx, 'checkout', path=path, branch=rest[0])
    if command in ('pull', 'push'):
        remote = rest[0] if rest else 'origin'
        branch = rest[1] if len(rest) > 1 else ''
        return git.git(ctx, command, path=path, remote=remote, branch=branch)
    raise ShellError(f'git {command}: not supported here; try {", ".join(git.COMMANDS)}')


def _pip(sh: Shell, args: list[str]) -> str:
    if args[:1] != ['install'] or len(args) < 2:
        raise ShellError('usage: pip install <name>[==version] …')
    if any(a.startswith('-') for a in args[1:]):
        raise ShellError('pip install: options such as -r are not supported; list package names')
    lines: list[str] = []
    for name in args[1:]:
        try:
            done = packages.install(name, log=lines.append)
        except packages.PackageError as e:
            lines.append(f'{name}: {e}')
            continue
        lines.append('Installed ' + ', '.join(done) if done else f'{name} is already installed')
    return '\n'.join(lines)


def _python(sh: Shell, args: list[str]) -> str:
    if args[:1] == ['-c']:
        if len(args) < 2:
            raise ShellError('usage: python -c <code>')
        return python_runner.run_code(sh.workspace, code=args[1], cancel=sh.cancel)
    if not args:
        raise ShellError('usage: python <file.py> [args] | python -c <code>')
    return python_runner.run_code(sh.workspace, path=args[0], args=args[1:], timeout=600, cancel=sh.cancel)


def _pycoder(sh: Shell, args: list[str]) -> str:
    if args[:1] not in (['update'], ['rollback']):
        raise ShellError('usage: pycoder update | pycoder rollback')
    arg = 'rollback' if args[0] == 'rollback' else ''
    return updater.command(
        arg, lambda: sh.frontend.ask_text('GitHub token', 'Needed for a private repository', True)
    )


def _help(sh: Shell, args: list[str]) -> str:
    return HELP


COMMANDS: dict[str, Command] = {
    'cd': Command('cd [dir | .. | - | ~ | /local]', lambda sh, args: sh.cd(args[0] if args else '~')),
    'pwd': Command('pwd', lambda sh, args: sh.cwd),
    'ls': Command('ls [dir]', _ls),
    'tree': Command('tree [dir]', _tree),
    'cat': Command('cat <file>…', _cat),
    'head': Command('head [-n N] <file>…', _head),
    'touch': Command('touch <file>…', _touch),
    'mkdir': Command('mkdir [-p] <dir>…', _mkdir),
    'mv': Command('mv <source>… <target>', _move_or_copy('mv')),
    'cp': Command('cp [-r] <source>… <target>', _move_or_copy('cp')),
    'rm': Command('rm [-r] <path>…', _rm),
    'echo': Command('echo <text>', lambda sh, args: ' '.join(args)),
    'git': Command(
        'git clone <url> [dir] | init | status | diff | add | commit [-a] -m <msg> | log [-n N] | branch'
        ' | config [--global] user.name|user.email <value>'
        ' | checkout [-b] | pull | push   (-C <dir> picks the repository)',
        _git,
        (
            ('git status', 'show changed files'),
            ('git diff', 'show uncommitted changes'),
            ('git commit -am ""', 'stage everything and commit'),
            ('git pull', 'pull from origin'),
            ('git push', 'push to origin'),
            ('git clone ', 'clone a repository'),
        ),
    ),
    'pip': Command(
        'pip install <name>[==version]…   (pure-Python packages)',
        _pip,
        (('pip install ', 'install a pure-Python package'),),
    ),
    'python': Command(
        'python <file.py> [args] | python -c <code>', _python, (('python ', 'run a .py file'),)
    ),
    'pycoder': Command(
        'pycoder update | pycoder rollback',
        _pycoder,
        (
            ('pycoder update', "update pycoder's own code from GitHub"),
            ('pycoder rollback', 'undo the last update'),
        ),
    ),
    'help': Command('help', _help),
}
ALIASES = {'pip3': 'pip', 'python3': 'python'}
COMMANDS.update({alias: COMMANDS[name] for alias, name in ALIASES.items()})
HELP = "Commands (pycoder's own; iOS has no real shell):\n" + '\n'.join(
    f'  {c.usage}' for name, c in COMMANDS.items() if name not in ALIASES and name != 'help'
)


def hints() -> list[tuple[str, str]]:
    """Every command's palette entries: its hints, or its name and usage."""
    out: list[tuple[str, str]] = []
    for name, command in COMMANDS.items():
        if name not in ALIASES:
            out += list(command.hints) or [(name + ' ', command.usage)]
    return out


def conversation_note(line: str, output: str) -> str:
    """How a `!` command and its output are recorded for Claude."""
    if len(output) > MAX_NOTE:
        output = output[:MAX_NOTE] + f'\n… [{len(output) - MAX_NOTE} more characters]'
    return f'<shell-command>{line}</shell-command>\n<shell-output>\n{output}\n</shell-output>'

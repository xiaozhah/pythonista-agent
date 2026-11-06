"""Permission modes and rules: whether a tool call runs, is asked about, or is refused.

Modelled on Claude Code:
- modes: default (ask before writes and runs), acceptEdits (file edits run without asking),
  plan (read-only until the user approves a plan), bypass (nothing is asked).
- rules: `tool` or `tool(pattern)`, where the pattern is a glob matched against what the call
  acts on (a path as the workspace resolves it, a git command and its remote, a package name, a
  URL). Deny rules win over ask rules, which win over allow rules; deny and ask rules apply in
  every mode, also to calls that only read, and ignore letter case. A deny rule for a file keeps
  every tool away from it, not only the one it names.
- pycoder's own control files (settings, staged updates, its code, git internals) are
  never changed without asking, whatever the rules, except in bypass.
"""

from __future__ import annotations

import fnmatch
import os
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .. import config
from ..host import vcs
from ..state.settings import Settings
from ..state.settings import save as save_settings
from ..state.workspace import ToolError, Workspace
from ..tools.base import Tool

MODES = ('default', 'acceptEdits', 'plan', 'bypass')
MODE_LABELS = {
    'default': '● ask first',
    'acceptEdits': '⏵⏵ accept edits',
    'plan': '❚\u200a❚ plan mode',  # not ⏸: iOS draws that as a blue emoji
    'bypass': '⏵⏵ bypass',
}
MODE_HELP = {
    'default': 'ask before changing files or running code',
    'acceptEdits': 'edit files without asking; ask before running code',
    'plan': 'read and plan only; nothing changes until you approve the plan',
    'bypass': 'never ask (deny rules still apply)',
}
RUN_TOOLS = ('run_python', 'run_c')  # a subagent may run code, as the user's mode decides
EDIT_TOOLS = ('write_file', 'edit_file', 'move_file', 'delete_file', 'task')  # task: one that writes
PLAN_MODE = 'plan mode: nothing runs until the plan is approved'
_RULE = re.compile(r'^\s*([\w*?-]+)\s*(?:\((.*)\))?\s*$')


@dataclass(frozen=True)
class Decision:
    action: str  # 'allow', 'ask', 'deny' or 'plan'
    reason: str = ''


class Policy(Protocol):
    """What the agent asks about permissions: SettingsPolicy for the main agent, ReadOnlyPolicy for
    subagents."""

    def decide(self, tool: Tool, inp: dict[str, Any]) -> Decision: ...
    def denies(self, path: str) -> bool: ...
    def always_allow(self, rule: str) -> None: ...
    def get_mode(self) -> str: ...
    def set_mode(self, mode: str) -> None: ...


class ReadOnlyPolicy:
    """For subagents: reading runs and changing files is refused. Running code is the user's to decide,
    as in the main conversation, and the parent's rules still apply."""

    def __init__(self, parent: Policy | None = None) -> None:
        self.parent = parent

    def decide(self, tool: Tool, inp: dict[str, Any]) -> Decision:
        decision = self.parent.decide(tool, inp) if self.parent else Decision('allow')
        if decision.action == 'deny':
            return decision
        if tool.needs_confirmation(inp) and (self.parent is None or tool.name not in RUN_TOOLS):
            return Decision('deny', 'this subagent only reads')
        return Decision('deny', PLAN_MODE) if decision.action == 'plan' else decision

    def denies(self, path: str) -> bool:
        return self.parent.denies(path) if self.parent else False

    def always_allow(self, rule: str) -> None:
        if self.parent:
            self.parent.always_allow(rule)

    def get_mode(self) -> str:
        return 'default'

    def set_mode(self, mode: str) -> None: ...


class WorktreePolicy:
    """For a subagent changing its own copy of the workspace: changing files asks nothing, as that only
    reaches the workspace once the task the user allowed is merged back. Code can reach anything, so
    running it is the user's to decide, as in the main conversation. The parent's deny rules hold."""

    def __init__(self, parent: Policy) -> None:
        self.parent = parent

    def decide(self, tool: Tool, inp: dict[str, Any]) -> Decision:
        decision = self.parent.decide(tool, inp)
        if tool.name in RUN_TOOLS:
            return Decision('deny', PLAN_MODE) if decision.action == 'plan' else decision
        return decision if decision.action == 'deny' else Decision('allow')

    def denies(self, path: str) -> bool:
        return self.parent.denies(path)

    def always_allow(self, rule: str) -> None:
        self.parent.always_allow(rule)

    def get_mode(self) -> str:
        return 'default'

    def set_mode(self, mode: str) -> None: ...


class SettingsPolicy:
    """The main agent's Policy: the user's mode and rules from the settings, saved as they change."""

    def __init__(
        self,
        settings: Settings,
        settings_file: str,
        root: Callable[[], str | Workspace],
        set_mode: Callable[[str], object],
        notice: Callable[[str], None],
    ) -> None:
        self.settings = settings
        self.settings_file = settings_file
        self.root = root  # the workspace changes with cd, so it is asked for each time
        self._set_mode = set_mode  # through the controller, so the frontend shows the new mode
        self.notice = notice

    def decide(self, tool: Tool, inp: dict[str, Any]) -> Decision:
        s = self.settings
        return decide(tool, inp, s.mode, s.allow, s.ask, s.deny, self.root())

    def denies(self, path: str) -> bool:
        return path_denied(path, self.settings.deny)

    def always_allow(self, rule: str) -> None:
        if rule not in self.settings.allow:
            self.settings.allow.append(rule)
            save_settings(self.settings_file, self.settings)
        self.notice(f'Always allowed from now on: {rule}  (/permissions to review)')

    def get_mode(self) -> str:
        return self.settings.mode

    def set_mode(self, mode: str) -> None:
        self._set_mode(mode)

    def edit_rules(self, kind: str, rule: str, remove: bool = False) -> None:
        """Add or remove an allow / ask / deny rule (ValueError if it isn't a rule)."""
        if kind not in ('allow', 'ask', 'deny'):
            raise ValueError('Rules are allow, ask or deny')
        parse_rule(rule)
        rules = getattr(self.settings, kind)
        if remove:
            if rule not in rules:
                raise ValueError(f'No {kind} rule {rule}')
            rules.remove(rule)
        elif rule not in rules:
            rules.append(rule)
        save_settings(self.settings_file, self.settings)


CONTROL_NAMES = ('.git', '.pycoder', '.bridge')  # folders that steer git or pycoder, wherever they are


@dataclass(frozen=True)
class Call:
    """What a call acts on, worked out once per decision: `target` is what rule patterns match,
    `path` the workspace's reading of its path ('' without one), `full` that path resolved."""

    name: str
    target: str
    path: str = ''
    full: str = ''


def workspace_of(root: str | Workspace) -> Workspace:
    """The workspace that will run the call, so rules see a path exactly as the tool resolves it.
    From a bare root: one that reads everywhere, with pycoder's home as `~` when the root is inside
    it, as the controller builds it."""
    if isinstance(root, Workspace):
        return root
    home = os.path.realpath(config.HOME_DIR)
    inside = os.path.commonpath([home, os.path.realpath(root)]) == home
    return Workspace(root, readable=(os.sep,), home=home if inside else root)


def call_of(name: str, inp: dict[str, Any], root: str | Workspace = '') -> Call:
    """Without a root (a description for the user), paths are only normalized."""
    path, full = '', ''
    if inp.get('path') and root:
        ws = workspace_of(root)
        try:
            full = ws.resolve_readable(str(inp['path']))
            path = ws.rel(full)
        except ToolError:  # out of reach: the tool refuses it; rules still see the path as given
            path = os.path.normpath(str(inp['path']))
    elif inp.get('path'):
        path = os.path.normpath(str(inp['path']))
    special = _TARGETS.get(name)
    return Call(name, special(inp, root) if special else path, path, full)


def target(name: str, inp: dict[str, Any], root: str | Workspace = '') -> str:
    """What a call acts on, for matching rule patterns: a path as the workspace resolves it
    (relative inside it, ~/… elsewhere in the home), so ./a, x/../a, ~/p/a and /abs/a all read
    the same; inline code has no path, so its target is '', which no path can be."""
    return call_of(name, inp, root).target


def _git_target(inp: dict[str, Any], root: str | Workspace) -> str:
    """For pull and push, where the commits go or come from: the remote's URL and the branch, so a
    rule for one remote can't cover another (or a raw URL the model passes as remote)."""
    command = str(inp.get('command', ''))
    if command in ('pull', 'push'):
        return ' '.join([command, *_remote(inp, root)])
    return ' '.join(str(p) for p in (command, inp.get('branch') or inp.get('url') or '') if p)


def _remote(inp: dict[str, Any], root: str | Workspace) -> list[str]:
    """[url, branch] for pull/push, as far as they can be read (no repository: a raw URL only)."""
    remote = str(inp.get('remote') or 'origin')
    repo = None
    if root:
        try:
            repo = vcs.open_repo(workspace_of(root).resolve_readable(str(inp.get('path') or '.')))
        except ToolError:
            pass
    try:
        url = remote if '://' in remote else vcs.remote_url(repo, remote) if repo is not None else ''
        branch = str(inp.get('branch') or '') or (_active_branch(repo) if repo is not None else '')
    finally:
        if repo is not None:
            repo.close()
    return [url, branch] if url and branch else [url] if url else []


def _active_branch(repo: Any) -> str:
    from dulwich import porcelain

    return str(porcelain.active_branch(repo).decode())  # type: ignore[no-untyped-call]


def _field(key: str) -> Callable[[dict[str, Any], str | Workspace], str]:
    return lambda inp, root: str(inp.get(key, ''))


def _url(inp: dict[str, Any], root: str | Workspace) -> str:
    u = urllib.parse.urlsplit(str(inp.get('url', '')))
    return f'{u.scheme}://{u.netloc}{u.path or "/"}'


def _photos(inp: dict[str, Any], root: str | Workspace) -> str:
    return ' '.join(p for p in (str(inp.get('action', '')), call_of('', inp, root).path) if p)


# tools whose target is not their path; for every other tool it is the path
_TARGETS: dict[str, Callable[[dict[str, Any], str | Workspace], str]] = {
    'git': _git_target,
    'install_package': _field('name'),
    'save_skill': _field('name'),
    'read_skill': _field('name'),
    'remember': _field('name'),
    'recall': _field('name'),
    'forget': _field('name'),
    'task': _field('description'),
    'run_shortcut': _field('name'),
    'open_url': _url,
    'photos': _photos,
}
URL_TOOLS = ('open_url',)


def controls(full: str) -> bool:
    """Whether a path is one of the files that decide what pycoder runs and allows: its settings
    and staged updates (.pycoder/), its own code (the install folder), the bridge's, and
    git's internals. Compared ignoring case, as the Mac's file system does."""
    if not full:
        return False
    folded = os.path.normpath(full).lower()
    if any(part in CONTROL_NAMES for part in folded.split(os.sep)):
        return True
    install = os.path.realpath(config.INSTALL_DIR).lower()
    return os.path.commonpath([install, folded]) == install


def outside(call: Call, ws: Workspace | None) -> bool:
    """Whether the call's path leaves the project."""
    return ws is not None and bool(call.full) and os.path.commonpath([ws.root, call.full]) != ws.root


def parse_rule(rule: str) -> tuple[str, str | None]:
    m = _RULE.match(rule)
    if not m:
        raise ValueError(
            f'Not a rule: {rule!r}; write tool or tool(pattern), e.g. git(status) or edit_file(src/*)'
        )
    return m.group(1), m.group(2)


def matches(rule: str, call: Call, strict: bool = False, any_tool: bool = False) -> bool:
    """Whether a rule covers a call. `strict` is for deny and ask rules, which must not be dodged
    by letter case (the Mac's file system ignores it). `any_tool` is for deny rules: a rule for a
    file keeps every tool that takes a path away from it (search, share, recognize_text, photos …
    reach its contents as well as the tool the rule names)."""
    try:
        tool, pattern = parse_rule(rule)
    except ValueError:
        return False  # a broken rule in settings.json matches nothing (/permissions shows it)
    if pattern is None:
        return fnmatch.fnmatchcase(call.name, tool)
    glob = pattern.strip()

    def fits(text: str) -> bool:
        return fnmatch.fnmatchcase(text.lower(), glob.lower()) if strict else fnmatch.fnmatchcase(text, glob)

    if any_tool and call.path and tool not in _TARGETS and fits(call.path):
        return True
    return fnmatch.fnmatchcase(call.name, tool) and fits(call.target)


def path_denied(path: str, deny: list[str]) -> bool:
    """Whether a deny rule keeps tools away from this path, for those that walk a folder."""
    call = Call('', path, path)
    return any(matches(rule, call, strict=True, any_tool=True) for rule in deny)


def _denied_inside(call: Call, ws: Workspace | None, deny: list[str]) -> str:
    """A file under the folder a move or delete takes with it that a deny rule covers ('' if none)."""
    if ws is None or call.name not in EDIT_TOOLS or not os.path.isdir(call.full):
        return ''
    for folder, _, names in os.walk(call.full):
        for name in names:
            path = ws.rel(os.path.join(folder, name))
            if path_denied(path, deny):
                return path
    return ''


# how far each decision goes: a call that acts on two paths gets the stricter
_STRICTNESS = {'allow': 0, 'ask': 1, 'plan': 2, 'deny': 3}


def decide(
    tool: Tool,
    inp: dict[str, Any],
    mode: str,
    allow: list[str],
    ask: list[str],
    deny: list[str],
    root: str | Workspace = '',
) -> Decision:
    decision = _decide_path(tool, inp, mode, allow, ask, deny, root)
    if tool.name != 'move_file' or not inp.get('to'):
        return decision
    other = _decide_path(tool, {**inp, 'path': inp['to']}, mode, allow, ask, deny, root)
    return max(decision, other, key=lambda d: _STRICTNESS[d.action])


def _decide_path(
    tool: Tool,
    inp: dict[str, Any],
    mode: str,
    allow: list[str],
    ask: list[str],
    deny: list[str],
    root: str | Workspace = '',
) -> Decision:
    ws = workspace_of(root) if root else None
    call = call_of(tool.name, inp, ws or '')
    for rule in deny:
        if matches(rule, call, strict=True, any_tool=True):
            return Decision('deny', f'denied by the rule {rule}')
    inside = _denied_inside(call, ws, deny)
    if inside:
        return Decision('deny', f'a deny rule covers {inside}, in that folder')
    writes = tool.needs_confirmation(inp)
    if writes and mode == 'plan':
        return Decision('plan', 'plan mode is on')
    for rule in ask:
        if matches(rule, call, strict=True):
            return Decision('ask', f'the rule {rule} asks first')
    # changing what governs pycoder (its settings, its code) outlasts this session, so neither a
    # rule nor accept-edits covers it; bypass does, as run_python could change it unasked anyway
    if writes and mode != 'bypass' and controls(call.full):
        return Decision('ask', f'{call.path} steers pycoder or git')
    # the project is the boundary: reading in it is free, reading beyond it (other projects, secrets) asks
    if not writes and not outside(call, ws):
        return Decision('allow')
    for rule in allow:
        if matches(rule, call):
            return Decision('allow', f'allowed by the rule {rule}')
    if mode == 'bypass' or (mode == 'acceptEdits' and tool.name in EDIT_TOOLS):
        return Decision('allow')
    return Decision('ask')


def rule_for(name: str, inp: dict[str, Any], root: str | Workspace = '') -> str:
    """The narrow rule that "always allow" records for this call; '' when none would be narrow
    (inline code: allowing one snippet would allow them all) or none would count (pycoder's own
    control files always ask)."""
    call = call_of(name, inp, root)
    if controls(call.full) or name == 'move_file':  # a move has two paths: no rule covers both
        return ''
    if name == 'git':
        command = str(inp.get('command', ''))
        if command in ('pull', 'push'):  # any branch of this remote; one that can't be read gets none
            parts = call.target.split(' ')
            return f'git({escape(" ".join(parts[:2]))} *)' if len(parts) == 3 else ''
        return f'git({escape(command)}*)'
    if name == 'run_python':
        return f'run_python({escape(call.target)})' if call.target else ''
    if name in URL_TOOLS:
        u = urllib.parse.urlsplit(str(inp.get('url', '')))
        return f'{name}({escape(f"{u.scheme}://{u.netloc}")}/*)'
    return f'{name}({escape(call.target)})' if call.target else name


def escape(text: str) -> str:
    """Make glob characters in a name match only themselves."""
    return re.sub(r'([*?\[])', r'[\1]', text)


PLAN_REMINDER = (
    '<system-reminder>Plan mode is on. Research with read-only tools and do not change anything. '
    'When you have a plan, call exit_plan_mode with it; the user approves it before any change is made.'
    '</system-reminder>'
)

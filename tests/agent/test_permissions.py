"""Permission modes, allow / ask / deny rules and plan mode."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from pycoder import config
from pycoder.agent import permissions
from pycoder.state.workspace import Workspace
from pycoder.tools import files, git, python_runner
from tests.conftest import FakeTransport, RecordingFrontend, text_reply, tool_reply

WRITE = files.TOOLS[3]
READ = files.TOOLS[1]
RUN = python_runner.TOOLS[0]
GIT = git.TOOLS[0]


def decide(
    tool: Any, inp: dict[str, Any], mode: str = 'default', allow: Any = (), ask: Any = (), deny: Any = ()
) -> str:
    return permissions.decide(tool, inp, mode, list(allow), list(ask), list(deny)).action


def test_modes() -> None:
    write = {'path': 'a.py', 'content': ''}
    assert decide(READ, {'path': 'a.py'}) == 'allow'
    assert decide(WRITE, write) == 'ask'
    assert decide(WRITE, write, 'acceptEdits') == 'allow'
    assert decide(RUN, {'code': 'x'}, 'acceptEdits') == 'ask'
    assert decide(WRITE, write, 'bypass') == 'allow'
    assert decide(WRITE, write, 'plan') == 'plan'
    assert decide(READ, {'path': 'a.py'}, 'plan') == 'allow'


def test_rules_and_precedence() -> None:
    commit = {'command': 'commit', 'message': 'x'}
    assert decide(GIT, commit, allow=['git(commit*)']) == 'allow'
    assert decide(GIT, {'command': 'push'}, allow=['git(commit*)']) == 'ask'
    assert decide(GIT, commit, allow=['git(commit*)'], ask=['git']) == 'ask'  # ask beats allow
    assert decide(GIT, commit, 'bypass', deny=['git(commit*)']) == 'deny'  # deny applies in every mode
    assert decide(READ, {'path': '.env'}, deny=['read_file(.env)']) == 'deny'
    assert (
        decide(WRITE, {'path': 'src/a.py', 'content': ''}, allow=['edit_file(*)', 'write_file(src/*)'])
        == 'allow'
    )
    with pytest.raises(ValueError, match='Not a rule'):
        permissions.parse_rule('git(status')


def test_rule_for_is_narrow() -> None:
    assert permissions.rule_for('git', {'command': 'status'}) == 'git(status*)'
    assert permissions.rule_for('run_python', {'code': 'print(1)'}) == ''  # no 'always' for inline code
    assert permissions.rule_for('run_python', {'path': '*.py'}) == 'run_python([*].py)'
    assert (
        permissions.rule_for('open_url', {'url': 'https://example.com/a?b'})
        == 'open_url(https://example.com/*)'
    )
    assert permissions.rule_for('run_shortcut', {'name': 'Make GIF'}) == 'run_shortcut(Make GIF)'
    assert permissions.rule_for('edit_file', {'path': 'a.py'}) == 'edit_file(a.py)'


def test_plan_mode_blocks_changes_until_the_plan_is_approved(make_controller: Any) -> None:
    api = FakeTransport(
        [
            tool_reply('write_file', {'path': 'early.py', 'content': 'x'}),
            tool_reply('exit_plan_mode', {'plan': '1. write plan.py'}, 't2'),
            tool_reply('write_file', {'path': 'plan.py', 'content': 'x'}, 't3'),
            text_reply('done'),
        ]
    )
    c = make_controller(api, RecordingFrontend(answer='no', plan_answer='acceptEdits'))
    c.policy.set_mode('plan')
    c.run_turn('add plan.py')
    root = c.workspace.root
    assert not os.path.exists(os.path.join(root, 'early.py'))
    assert 'Plan mode is on' in api.requests[1]['messages'][-1]['content'][0]['content']
    assert 'approved the plan' in api.requests[2]['messages'][-1]['content'][0]['content']
    assert os.path.exists(os.path.join(root, 'plan.py'))  # ran without asking: edits were auto-accepted
    assert c.settings.mode == 'acceptEdits'
    assert c.frontend.named('confirm') == []
    first_user = api.requests[0]['messages'][0]['content']
    assert first_user[-1]['text'].startswith('<system-reminder>Plan mode is on')


def test_keep_planning_returns_the_note(make_controller: Any) -> None:
    api = FakeTransport([tool_reply('exit_plan_mode', {'plan': 'p'}), text_reply('ok')])
    c = make_controller(api, RecordingFrontend(plan_answer='keep'))
    c.policy.set_mode('plan')
    c.run_turn('plan it')
    assert c.settings.mode == 'plan'
    assert 'keep planning' in api.requests[1]['messages'][-1]['content'][0]['content']


def test_permissions_command_and_saved_rules(make_controller: Any, tmp_path: Any) -> None:
    c = make_controller()
    from pycoder.app.commands import run_command

    run_command(c, '/permissions deny run_python()')
    run_command(c, '/permissions allow git(status*)')
    run_command(c, '/permissions remove allow git(status*)')
    with open(tmp_path / 'settings.json', encoding='utf-8') as f:
        saved = json.load(f)
    assert saved['deny'] == ['run_python()']
    assert saved['allow'] == []


def test_paths_are_normalized_before_matching(workspace: str) -> None:
    deny = ['edit_file(secrets/*)']
    edit = next(t for t in files.TOOLS if t.name == 'edit_file')
    for path in ('secrets/k.txt', './secrets/k.txt', 'sub/../secrets/k.txt', f'{workspace}/secrets/k.txt'):
        inp = {'path': path, 'old_str': 'a', 'new_str': 'b'}
        assert permissions.decide(edit, inp, 'bypass', [], [], deny, workspace).action == 'deny', path
    escape = {'path': 'src/../pycoder/agent.py', 'content': ''}
    assert (
        permissions.decide(WRITE, escape, 'default', ['write_file(src/*)'], [], [], workspace).action == 'ask'
    )


def test_url_rules_cover_one_site() -> None:
    from pycoder.tools import ios

    tool = next(t for t in ios.PYTHONISTA if t.name == 'open_url')
    allow = [permissions.rule_for('open_url', {'url': 'https://example.com/x'})]
    assert decide(tool, {'url': 'https://example.com/other'}, allow=allow) == 'allow'
    assert decide(tool, {'url': 'https://example.com.evil.io/'}, allow=allow) == 'ask'
    assert decide(tool, {'url': 'pythonista3://x.py?action=run'}, allow=allow) == 'ask'


def test_ask_rules_also_cover_reads() -> None:
    assert decide(GIT, {'command': 'status'}, ask=['git(status*)']) == 'ask'


def test_a_broken_rule_matches_nothing() -> None:
    assert decide(WRITE, {'path': 'a.py', 'content': ''}, 'bypass', deny=['edit_file(src/*']) == 'allow'


def test_subagents_obey_deny_rules(make_controller: Any) -> None:
    api = FakeTransport(
        [
            tool_reply('task', {'description': 'look', 'prompt': 'read hello.py'}),
            tool_reply('read_file', {'path': 'hello.py'}, 's1'),
            text_reply('could not'),
            text_reply('done'),
        ]
    )
    c = make_controller(api)
    c.policy.edit_rules('deny', 'read_file(hello.py)')
    c.run_turn('summarize')
    sub_result = api.requests[2]['messages'][-1]['content'][0]
    assert 'denied by the rule' in sub_result['content']


def test_reading_beyond_the_project_asks_unless_bypass_or_allowed(tmp_path: Any) -> None:
    from pycoder.tools import files

    read = next(t for t in files.TOOLS if t.name == 'read_file')
    root = str(tmp_path / 'project')
    os.makedirs(root)
    assert permissions.decide(read, {'path': 'a.py'}, 'default', [], [], [], root).action == 'allow'
    assert permissions.decide(read, {'path': '../other/.env'}, 'default', [], [], [], root).action == 'ask'
    assert permissions.decide(read, {'path': '../other/.env'}, 'plan', [], [], [], root).action == 'ask'
    assert permissions.decide(read, {'path': '../other/.env'}, 'bypass', [], [], [], root).action == 'allow'
    rule = permissions.rule_for('read_file', {'path': '../other/.env'}, root)
    assert (
        permissions.decide(read, {'path': '../other/.env'}, 'default', [rule], [], [], root).action == 'allow'
    )


EDIT = next(t for t in files.TOOLS if t.name == 'edit_file')
SEARCH = next(t for t in files.TOOLS if t.name == 'search')


def test_rule_targets_are_read_as_the_workspace_resolves_paths(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / 'home'
    root = home / 'proj'
    (root / 'secrets').mkdir(parents=True)
    monkeypatch.setattr(config, 'HOME_DIR', str(home))
    deny = ['edit_file(secrets/*)']
    for where in (str(root), Workspace(str(root), home=str(home))):
        for path in (
            'secrets/k.txt',
            './secrets/k.txt',
            'secrets/../secrets/k.txt',
            f'{root}/secrets/k.txt',
            '~/proj/secrets/k.txt',  # ~ is pycoder's home, as the file tools read it
            'SECRETS/K.txt',  # the Mac's file system ignores case, so the rule does too
        ):
            inp = {'path': path, 'old_str': 'a', 'new_str': 'b'}
            assert permissions.decide(EDIT, inp, 'bypass', [], [], deny, where).action == 'deny', path
    assert permissions.target('read_file', {'path': '~/other/a.py'}, str(root)) == '~/other/a.py'
    # allow rules stay exact: a different spelling asks rather than being let through
    allow = ['write_file(src/*)']
    assert (
        permissions.decide(
            WRITE, {'path': 'SRC/a.py', 'content': ''}, 'default', allow, [], [], str(root)
        ).action
        == 'ask'
    )


def test_a_deny_rule_for_a_file_covers_every_tool_that_takes_a_path(workspace: str) -> None:
    deny = ['read_file(.env)']
    for tool, inp in (
        (SEARCH, {'pattern': 'KEY', 'path': '.env'}),
        (RUN, {'path': '.env'}),
        (WRITE, {'path': './.env', 'content': ''}),
    ):
        assert permissions.decide(tool, inp, 'bypass', [], [], deny, workspace).action == 'deny', tool.name
    assert (
        permissions.decide(SEARCH, {'pattern': 'x', 'path': 'src'}, 'bypass', [], [], deny, workspace).action
        == 'allow'
    )
    # rules whose target isn't a path keep to their own tool
    assert (
        permissions.decide(
            GIT, {'command': 'status', 'path': 'push'}, 'bypass', [], [], ['git(push*)'], workspace
        ).action
        == 'allow'
    )


def test_changes_to_control_files_always_ask(workspace: str) -> None:
    allow = ['write_file(*)', 'edit_file(*)']
    paths = ['.git/config', 'sub/.GIT/hooks/pre-commit', '.pycoder/settings.json', '.bridge/token']
    paths.append(os.path.join(config.INSTALL_DIR, 'commands', 'new.md'))
    for path in paths:
        inp = {'path': path, 'content': ''}
        for mode in ('default', 'acceptEdits'):
            assert permissions.decide(WRITE, inp, mode, allow, [], [], workspace).action == 'ask', (
                path,
                mode,
            )
        assert permissions.decide(WRITE, inp, 'bypass', [], [], [], workspace).action == 'allow'
        assert permissions.decide(WRITE, inp, 'bypass', [], [], ['write_file(*)'], workspace).action == 'deny'
        assert permissions.rule_for('write_file', inp, workspace) == ''  # "always" would not count
    assert (
        permissions.decide(
            WRITE, {'path': 'a.py', 'content': ''}, 'acceptEdits', [], [], [], workspace
        ).action
        == 'allow'
    )
    assert (
        permissions.decide(READ, {'path': '.git/config'}, 'default', [], [], [], workspace).action == 'allow'
    )


def test_a_script_named_code_does_not_stand_for_inline_code(workspace: str) -> None:
    script = {'path': 'code'}
    allow = [permissions.rule_for('run_python', script, workspace)]
    assert allow == ['run_python(code)']
    assert permissions.decide(RUN, script, 'default', allow, [], [], workspace).action == 'allow'
    assert permissions.decide(RUN, {'code': 'import os'}, 'default', allow, [], [], workspace).action == 'ask'
    assert permissions.target('run_python', {'code': 'x'}, workspace) == ''
    assert (
        permissions.decide(RUN, {'code': 'x'}, 'bypass', [], [], ['run_python()'], workspace).action == 'deny'
    )
    assert permissions.decide(RUN, script, 'bypass', [], [], ['run_python()'], workspace).action == 'allow'


def test_git_rules_for_pull_and_push_name_the_remote(workspace: str) -> None:
    porcelain = pytest.importorskip('dulwich.porcelain')

    from pycoder.host.vcs import disable_shell_hooks

    disable_shell_hooks()  # as the git tool does: on iOS a hook would try to start a process
    repo = porcelain.init(workspace)
    config_ = repo.get_config()
    config_.set((b'remote', b'origin'), b'url', b'https://github.com/me/app.git')
    config_.write_to_path()
    porcelain.commit(repo, message=b'first', author=b'a <a@b>', committer=b'a <a@b>')
    branch = porcelain.active_branch(repo).decode()
    push = {'command': 'push'}
    rule = permissions.rule_for('git', push, workspace)
    assert rule == 'git(push https://github.com/me/app.git *)'
    assert permissions.target('git', push, workspace) == f'push https://github.com/me/app.git {branch}'
    assert (
        permissions.decide(
            GIT, {'command': 'push', 'branch': 'x'}, 'default', [rule], [], [], workspace
        ).action
        == 'allow'
    )
    evil = {'command': 'push', 'remote': 'https://evil.example/app.git'}
    assert permissions.decide(GIT, evil, 'default', [rule], [], [], workspace).action == 'ask'
    config_.set((b'remote', b'origin'), b'url', b'https://evil.example/app.git')
    config_.write_to_path()
    assert permissions.decide(GIT, push, 'default', [rule], [], [], workspace).action == 'ask'


def test_mode_labels_use_symbols_that_ios_keeps_as_text() -> None:
    # iOS turns these into coloured emoji, which clash with the labels around them on a phone
    emoji = '⏸⏯⏹⏺▶⏩⏪☑✔'
    assert not [label for label in permissions.MODE_LABELS.values() if set(label) & set(emoji)]


def _tools() -> dict[str, Any]:
    from pycoder.tools import file_ops, files

    return {t.name: t for t in file_ops.TOOLS + files.TOOLS}


def test_a_move_is_judged_by_where_it_goes_too(workspace: str) -> None:
    move = _tools()['move_file']
    into_git = {'path': 'hello.py', 'to': '.git/hooks/pre-commit'}
    assert permissions.decide(move, into_git, 'acceptEdits', [], [], [], workspace).action == 'ask'
    denied = {'path': 'hello.py', 'to': 'secret/x'}
    assert (
        permissions.decide(move, denied, 'bypass', [], [], ['write_file(secret/*)'], workspace).action
        == 'deny'
    )
    away = {'path': 'src/a', 'to': '.pycoder/x'}
    assert permissions.decide(move, away, 'default', ['move_file(src/*)'], [], [], workspace).action == 'ask'
    fine = {'path': 'src/a', 'to': 'src/b'}
    assert (
        permissions.decide(move, fine, 'default', ['move_file(src/*)'], [], [], workspace).action == 'allow'
    )
    assert permissions.rule_for('move_file', fine, workspace) == ''


def test_a_folder_with_a_denied_file_cannot_be_moved_or_deleted(workspace: str) -> None:
    os.makedirs(os.path.join(workspace, 'box', 'secret'))
    with open(os.path.join(workspace, 'box', 'secret', 'key'), 'w', encoding='utf-8') as f:
        f.write('x')
    tools = _tools()
    deny = ['read_file(box/secret/*)']
    assert (
        permissions.decide(tools['delete_file'], {'path': 'box'}, 'bypass', [], [], deny, workspace).action
        == 'deny'
    )
    move = {'path': 'box', 'to': 'other'}
    assert permissions.decide(tools['move_file'], move, 'bypass', [], [], deny, workspace).action == 'deny'
    assert (
        permissions.decide(
            tools['delete_file'], {'path': 'hello.py'}, 'bypass', [], [], deny, workspace
        ).action
        == 'allow'
    )


def test_search_and_list_leave_out_what_a_deny_rule_covers(make_controller: Any) -> None:
    from tests.conftest import FakeTransport, text_reply, tool_reply

    root = make_controller(FakeTransport([])).workspace.root
    os.makedirs(os.path.join(root, 'secret'))
    with open(os.path.join(root, 'secret', 'key'), 'w', encoding='utf-8') as f:
        f.write('hunter2\n')
    api = FakeTransport(
        [
            tool_reply('search', {'pattern': 'hunter'}),
            tool_reply('list_files', {'recursive': True}, 't2'),
            text_reply('done'),
        ]
    )
    c = make_controller(api)
    c.settings.deny = ['read_file(secret/*)']
    c.run_turn('look')
    assert 'hunter2' not in str(api.requests[1]['messages'][-1])
    assert 'secret/key' not in str(api.requests[2]['messages'][-1])


def test_a_web_tool_that_must_ask_is_not_offered(make_controller: Any) -> None:
    from tests.conftest import FakeTransport, text_reply

    api = FakeTransport([text_reply('ok')])
    c = make_controller(api)
    c.settings.ask = ['web_fetch']
    c.run_turn('hi')
    names = [t.get('name') for t in api.requests[0]['tools']]
    assert 'web_fetch' not in names
    assert 'web_search' in names

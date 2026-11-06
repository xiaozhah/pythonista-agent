"""task with writes: subagents change their own copies, in parallel, and are merged back."""

from __future__ import annotations

import json
import os
from typing import Any

from pycoder.agent import permissions
from pycoder.tools import subagent
from tests.conftest import FakeResponse, FakeTransport, text_reply, tool_reply


class ByPrompt(FakeTransport):
    """Answers each subagent from a script of its own, whatever order the threads ask in."""

    def __init__(self, main: list[Any], scripts: dict[str, list[Any]]) -> None:
        super().__init__(main)
        self.scripts = scripts

    def post(self, url: str, headers: Any, body: Any, stream: bool) -> Any:
        first = body['messages'][0]['content']
        text = first if isinstance(first, str) else str(first)
        for word, script in self.scripts.items():
            if word in text:
                self.requests.append(json.loads(json.dumps(body)))
                return FakeResponse(script.pop(0))
        return super().post(url, headers, body, stream)


def _two_tasks(*tasks: tuple[str, str, bool]) -> list[Any]:
    events: list[Any] = []
    for i, (name, prompt, writes) in enumerate(tasks):
        raw = json.dumps({'description': name, 'prompt': prompt, 'writes': writes})
        events += [
            {
                'type': 'content_block_start',
                'index': i,
                'content_block': {'type': 'tool_use', 'id': f't{i}', 'name': 'task', 'input': {}},
            },
            {
                'type': 'content_block_delta',
                'index': i,
                'delta': {'type': 'input_json_delta', 'partial_json': raw},
            },
            {'type': 'content_block_stop', 'index': i},
        ]
    events.append(
        {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}, 'usage': {'output_tokens': 1}}
    )
    return events


def _edit(path: str, old: str, new: str, tid: str) -> list[Any]:
    return tool_reply('edit_file', {'path': path, 'old_str': old, 'new_str': new}, tid)


def test_two_subagents_change_one_file_at_once_and_both_are_merged(make_controller: Any) -> None:
    probe = make_controller(FakeTransport([]))
    root = probe.workspace.root
    with open(os.path.join(root, 'shared.py'), 'w', encoding='utf-8') as f:
        f.write('first = 1\nmiddle = 2\nlast = 3\n')
    api = ByPrompt(
        [
            _two_tasks(('Top', 'ALPHA change the top', True), ('End', 'BETA change the end', True)),
            text_reply('done'),
        ],
        {
            'ALPHA': [_edit('shared.py', 'first = 1', 'first = 10', 'a1'), text_reply('changed the top')],
            'BETA': [_edit('shared.py', 'last = 3', 'last = 30', 'b1'), text_reply('changed the end')],
        },
    )
    c = make_controller(api)
    c.settings.mode = 'acceptEdits'
    result = c.run_turn('change both')
    assert result.status == 'done'
    with open(os.path.join(root, 'shared.py'), encoding='utf-8') as f:
        assert f.read() == 'first = 10\nmiddle = 2\nlast = 30\n'
    sent = str(api.requests[-1]['messages'][-1])
    assert 'Merged into the workspace: shared.py' in sent
    assert 'changed the top' in sent
    c.rewind(c.session.turns[-1].number, conversation=False)  # /rewind undoes what they did
    with open(os.path.join(root, 'shared.py'), encoding='utf-8') as f:
        assert f.read() == 'first = 1\nmiddle = 2\nlast = 3\n'


def test_a_conflict_comes_back_and_the_other_change_is_kept(make_controller: Any) -> None:
    probe = make_controller(FakeTransport([]))
    root = probe.workspace.root
    with open(os.path.join(root, 'shared.py'), 'w', encoding='utf-8') as f:
        f.write('value = 1\n')
    api = ByPrompt(
        [_two_tasks(('A', 'ALPHA', True), ('B', 'BETA', True)), text_reply('done')],
        {
            'ALPHA': [_edit('shared.py', 'value = 1', 'value = 2', 'a1'), text_reply('two')],
            'BETA': [_edit('shared.py', 'value = 1', 'value = 3', 'b1'), text_reply('three')],
        },
    )
    c = make_controller(api)
    c.settings.mode = 'bypass'
    c.run_turn('change it')
    sent = str(api.requests[-1]['messages'][-1])
    assert 'Not merged, changed here too in the same places: shared.py' in sent
    assert "The subagent's versions are in" in sent
    with open(os.path.join(root, 'shared.py'), encoding='utf-8') as f:
        assert f.read() in ('value = 2\n', 'value = 3\n')


def test_a_writing_task_asks_first_and_plan_mode_refuses_it(make_controller: Any) -> None:
    tool = next(t for t in subagent.TOOLS if t.name == 'task')
    read = {'description': 'd', 'prompt': 'p'}
    write = {**read, 'writes': True}
    root = make_controller(FakeTransport([])).workspace.root
    assert permissions.decide(tool, read, 'default', [], [], [], root).action == 'allow'
    assert permissions.decide(tool, write, 'default', [], [], [], root).action == 'ask'
    assert permissions.decide(tool, write, 'plan', [], [], [], root).action == 'plan'
    assert permissions.decide(tool, write, 'acceptEdits', [], [], [], root).action == 'allow'


def test_a_writing_subagent_cannot_reach_past_a_deny_rule(make_controller: Any) -> None:
    from pycoder.tools.registry import writing_subagent_tools

    names = {t.name for t in writing_subagent_tools()}
    assert {'write_file', 'edit_file', 'move_file', 'delete_file', 'read_file', 'python_code'} <= names
    assert {'run_python', 'run_c'} <= names
    assert not {'git', 'task', 'save_skill', 'remember'} & names

    root = make_controller(FakeTransport([])).workspace.root
    with open(os.path.join(root, 'secret.py'), 'w', encoding='utf-8') as f:
        f.write('key\n')
    api = ByPrompt(
        [_two_tasks(('A', 'ALPHA', True)), text_reply('done')],
        {
            'ALPHA': [
                tool_reply('write_file', {'path': 'secret.py', 'content': 'overwritten'}, 'a1'),
                text_reply('tried'),
            ]
        },
    )
    c = make_controller(api)
    c.settings.mode = 'bypass'
    c.settings.deny = ['read_file(secret.py)']
    c.run_turn('go')
    with open(os.path.join(root, 'secret.py'), encoding='utf-8') as f:
        assert f.read() == 'key\n'


def _results(api: FakeTransport) -> str:
    return json.dumps([request['messages'] for request in api.requests], ensure_ascii=False)


def test_a_subagent_runs_code(make_controller: Any) -> None:
    api = ByPrompt(
        [_two_tasks(('A', 'ALPHA', False)), text_reply('done')],
        {'ALPHA': [tool_reply('run_python', {'code': 'print(6 * 7)'}, 'a1'), text_reply('it is 42')]},
    )
    c = make_controller(api)
    c.settings.mode = 'bypass'
    c.run_turn('compute')
    assert '42' in _results(api)
    assert 'Not allowed' not in _results(api)


def test_code_a_writing_subagent_runs_is_in_its_own_copy(make_controller: Any) -> None:
    api = ByPrompt(
        [_two_tasks(('A', 'ALPHA', True)), text_reply('done')],
        {
            'ALPHA': [
                tool_reply('write_file', {'path': 'made.py', 'content': 'print("from the copy")'}, 'a1'),
                tool_reply('run_python', {'path': 'made.py'}, 'a2'),
                text_reply('it works'),
            ]
        },
    )
    c = make_controller(api)
    c.settings.mode = 'bypass'
    c.run_turn('change and check')
    assert 'from the copy' in _results(api)
    assert os.path.exists(os.path.join(c.workspace.root, 'made.py'))


def test_subagents_run_code_one_at_a_time(make_controller: Any, tmp_path: Any) -> None:
    log = str(tmp_path / 'log')
    code = f'import time\nopen({log!r}, "a").write("in ")\ntime.sleep(0.2)\nopen({log!r}, "a").write("out ")'
    api = ByPrompt(
        [_two_tasks(('A', 'ALPHA', False), ('B', 'BETA', False)), text_reply('done')],
        {
            'ALPHA': [tool_reply('run_python', {'code': code}, 'a1'), text_reply('one')],
            'BETA': [tool_reply('run_python', {'code': code}, 'b1'), text_reply('two')],
        },
    )
    c = make_controller(api)
    c.settings.mode = 'bypass'
    c.run_turn('both')
    with open(log, encoding='utf-8') as f:
        assert f.read() == 'in out in out '


def test_a_subagents_code_is_the_users_to_decide(make_controller: Any) -> None:
    from pycoder.tools.registry import subagent_tools, writing_subagent_tools

    class Parent:
        def __init__(self, action: str) -> None:
            self.action = action

        def decide(self, tool: Any, inp: Any) -> permissions.Decision:
            return permissions.Decision(self.action)

    run = next(t for t in subagent_tools() if t.name == 'run_python')
    write = next(t for t in writing_subagent_tools() if t.name == 'write_file')
    for policy in (permissions.ReadOnlyPolicy, permissions.WorktreePolicy):
        assert policy(Parent('ask')).decide(run, {}).action == 'ask'  # type: ignore[arg-type]
        assert policy(Parent('allow')).decide(run, {}).action == 'allow'  # type: ignore[arg-type]
        assert policy(Parent('deny')).decide(run, {}).action == 'deny'  # type: ignore[arg-type]
        assert policy(Parent('plan')).decide(run, {}).action == 'deny'  # type: ignore[arg-type]
    assert permissions.ReadOnlyPolicy(Parent('allow')).decide(write, {}).action == 'deny'  # type: ignore[arg-type]
    assert permissions.WorktreePolicy(Parent('ask')).decide(write, {}).action == 'allow'  # type: ignore[arg-type]
    assert 'background' not in run.properties


def test_a_question_from_a_subagent_reaches_the_user(make_controller: Any) -> None:
    from pycoder.events import Frontend

    asked: list[str] = []

    class Answers(Frontend):
        def confirm(self, name: str, inp: Any, preview: Any = None, rule: str = '') -> tuple[str, str | None]:
            asked.append(name)
            return 'no', 'not now'

    api = ByPrompt(
        [_two_tasks(('A', 'ALPHA', False)), text_reply('done')],
        {'ALPHA': [tool_reply('run_python', {'code': 'print(1)'}, 'a1'), text_reply('denied')]},
    )
    c = make_controller(api, frontend=Answers())
    c.settings.mode = 'default'
    c.run_turn('compute')
    assert asked == ['run_python']
    assert 'not now' in _results(api)

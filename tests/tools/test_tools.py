"""File tools, run_python and the todo list, called the way the agent calls them."""

from __future__ import annotations

import os
import pathlib
import sys
import time
from typing import Any

import pytest

from pycoder.cancel import CancelToken
from pycoder.state.checkpoints import Checkpoints
from pycoder.state.session import Session
from pycoder.state.workspace import Workspace
from pycoder.tools import files, python_runner, todos
from pycoder.tools.base import ToolContext, ToolError, validate_input
from tests.conftest import RecordingFrontend


@pytest.fixture
def ctx(workspace: str) -> ToolContext:
    ws = Workspace(workspace)
    session = Session.new(workspace, 'claude-opus-5-5', 'system', web=False)
    return ToolContext(ws, RecordingFrontend(), session, Checkpoints(session, ws), CancelToken())


def test_paths_cannot_leave_the_workspace(ctx: ToolContext) -> None:
    with pytest.raises(ToolError):
        files.read_file(ctx, '../outside.txt')


def test_write_then_edit_reports_diff_and_content(ctx: ToolContext) -> None:
    assert files.write_file(ctx, 'pkg/a.py', 'x = 1\ny = 2\n') == 'Created pkg/a.py'
    assert files.edit_file(ctx, 'pkg/a.py', 'y = 2', 'y = 3').startswith('Edited pkg/a.py')
    with open(os.path.join(ctx.workspace.root, 'pkg/a.py'), encoding='utf-8') as f:
        assert f.read() == 'x = 1\ny = 3\n'
    written = ctx.frontend.named('file_written')  # type: ignore[attr-defined]
    assert written[0][1] is None
    assert written[1][1] == 'x = 1\ny = 2\n'


def test_edit_refuses_ambiguous_text(ctx: ToolContext) -> None:
    files.write_file(ctx, 'b.py', 'a\na\n')
    with pytest.raises(ToolError, match='appears 2 times'):
        files.edit_file(ctx, 'b.py', 'a', 'b')
    assert files.edit_file(ctx, 'b.py', 'a', 'b', replace_all=True).endswith('(2 replacement(s))')


def test_read_list_and_search(ctx: ToolContext) -> None:
    assert '1\tprint("hello")' in files.read_file(ctx, 'hello.py')
    assert 'hello.py' in files.list_files(ctx)
    assert files.search(ctx, r'print\(', glob='*.py') == 'hello.py:1: print("hello")'


def test_search_leaves_out_installed_and_huge_files(ctx: ToolContext) -> None:
    root = ctx.workspace.root
    for rel, text in [
        ('node_modules/lib/x.js', 'needle'),
        ('site-packages/pkg/x.py', 'needle'),
        ('src/a.py', 'needle'),
        ('big.log', 'needle\n' + 'x' * files.MAX_SEARCH_FILE),
    ]:
        os.makedirs(os.path.dirname(os.path.join(root, rel)) or root, exist_ok=True)
        with open(os.path.join(root, rel), 'w', encoding='utf-8') as f:
            f.write(text)
    assert files.search(ctx, 'needle') == (
        'src/a.py:1: needle\n(1 file(s) over 1 MB not searched; name one as the path to search it)'
    )
    assert files.search(ctx, 'needle', path='big.log') == 'big.log:1: needle'
    assert files.search(ctx, 'needle', path='node_modules') == 'node_modules/lib/x.js:1: needle'
    assert 'node_modules' not in files.list_files(ctx, recursive=True)


def test_run_python_reports_output_traceback_and_locals(ctx: ToolContext) -> None:
    out = python_runner.run_python(ctx, code='total = 41\nprint(total + 1)\nitems = []\nitems[3]')
    assert '42' in out
    assert 'IndexError' in out
    assert 'items = []' in out
    assert 'total = 41' in out


def test_run_python_times_out(ctx: ToolContext) -> None:
    out = python_runner.run_code(ctx.workspace, code='import time\nwhile True: time.sleep(0.05)', timeout=1)
    assert '[timed out after 1s' in out


def test_a_timeout_stops_code_that_swallows_it(ctx: ToolContext) -> None:
    code = """
import time
for _ in range(3):  # TimeoutError is an OSError: realpath's own `except OSError` did this
    try:
        while True:
            time.sleep(0.02)
    except OSError:
        pass
print("ended")
"""
    out = python_runner.run_code(ctx.workspace, code=code, timeout=1)
    assert 'ended' in out
    assert 'stuck' not in out


def test_a_run_looks_up_where_each_module_is_only_once(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    python_runner._forget_user_modules(ctx.workspace.root)  # all of them are known now
    real = os.path.realpath
    asked: list[str] = []

    def realpath(path: str) -> str:
        asked.append(path)
        return real(path)

    monkeypatch.setattr(os.path, 'realpath', realpath)
    python_runner._forget_user_modules(ctx.workspace.root)
    modules = {getattr(m, '__file__', None) for m in sys.modules.values()}
    assert not modules.intersection(asked)


def test_the_machine_sleeping_is_not_a_timeout(ctx: ToolContext, monkeypatch: pytest.MonkeyPatch) -> None:
    real = time.time
    start = real()
    monkeypatch.setattr(time, 'time', lambda: real() + (1000 if real() - start > 0.1 else 0))
    out = python_runner.run_code(ctx.workspace, 'import time\ntime.sleep(0.4)\nprint("finished")')
    assert 'finished' in out


def test_run_python_runs_a_file_with_args(ctx: ToolContext) -> None:
    files.write_file(ctx, 'args.py', 'import sys\nprint(sys.argv[1:])\n')
    assert "['a', 'b']" in python_runner.run_code(ctx.workspace, path='args.py', args=['a', 'b'])


def _plan(ctx: ToolContext) -> None:
    todos.todo_write(
        ctx,
        [
            {'content': 'a', 'status': 'in_progress'},
            {'content': 'b', 'status': 'pending'},
            {'content': 'c', 'status': 'pending'},
        ],
    )


def _statuses(ctx: ToolContext) -> list[str]:
    return [t['status'] for t in ctx.session.todos]


def test_closing_a_step_starts_the_next_and_the_last_closes_the_list(ctx: ToolContext) -> None:
    shown: list[list[dict[str, str]]] = []
    ctx.frontend.todos_updated = lambda todos: shown.append(list(todos))  # type: ignore[method-assign]
    _plan(ctx)
    assert '2. ▶ b' in todos.todo_update(ctx, 1, 'completed')
    assert _statuses(ctx) == ['completed', 'in_progress', 'pending']
    assert shown[-1] == ctx.session.todos
    todos.todo_update(ctx, 2, 'completed')
    assert todos.todo_update(ctx, 3, 'completed') == 'Todo list cleared'
    assert ctx.session.todos == []
    assert shown[-1] == []


def test_a_step_can_be_started_reworded_or_dropped(ctx: ToolContext) -> None:
    _plan(ctx)
    todos.todo_update(ctx, 3, 'in_progress')
    assert _statuses(ctx) == ['pending', 'pending', 'in_progress']
    todos.todo_update(ctx, 2, content='b, but better')
    assert ctx.session.todos[1] == {'id': 2, 'content': 'b, but better', 'status': 'pending'}
    todos.todo_update(ctx, 3, 'removed')
    assert [t['content'] for t in ctx.session.todos] == ['a', 'b, but better']
    assert _statuses(ctx) == ['in_progress', 'pending']


def test_a_step_keeps_its_number_when_another_goes(ctx: ToolContext) -> None:
    _plan(ctx)
    todos.todo_update(ctx, 2, 'removed')
    assert '3. ☐ c' in todos.todo_update(ctx, 3, content='c')
    todos.todo_update(ctx, 3, 'completed')
    assert ctx.session.todos[1] == {'id': 3, 'content': 'c', 'status': 'completed'}


def test_a_step_can_be_added_anywhere(ctx: ToolContext) -> None:
    _plan(ctx)
    todos.todo_add(ctx, 'end')
    todos.todo_add(ctx, 'between', after=1)
    assert [(t['id'], t['content']) for t in ctx.session.todos] == [
        (1, 'a'),
        (5, 'between'),
        (2, 'b'),
        (3, 'c'),
        (4, 'end'),
    ]
    with pytest.raises(ToolError, match='No step 9'):
        todos.todo_add(ctx, 'x', after=9)


def test_a_wrong_step_or_status_is_refused(ctx: ToolContext) -> None:
    _plan(ctx)
    with pytest.raises(ToolError, match='No step 4'):
        todos.todo_update(ctx, 4, 'completed')
    with pytest.raises(ToolError, match='status must be'):
        todos.todo_update(ctx, 1, 'finished')
    assert _statuses(ctx) == ['in_progress', 'pending', 'pending']


def test_only_closing_the_step_under_way_starts_the_next(ctx: ToolContext) -> None:
    todos.todo_write(ctx, [{'content': 'a', 'status': 'pending'}, {'content': 'b', 'status': 'pending'}])
    assert _statuses(ctx) == ['pending', 'pending']  # planned, not begun
    _plan(ctx)
    todos.todo_update(ctx, 1, 'completed')
    assert _statuses(ctx) == ['completed', 'in_progress', 'pending']
    todos.todo_update(ctx, 2, 'pending')  # stopping before it: that stays so
    assert _statuses(ctx) == ['completed', 'pending', 'pending']
    todos.todo_add(ctx, 'd')
    assert _statuses(ctx) == ['completed', 'pending', 'pending', 'pending']


def test_the_strip_shows_only_what_is_left_with_the_current_step_first() -> None:
    from pycoder.frontends.chat.render import strip_steps

    steps = [
        {'id': 1, 'content': 'a', 'status': 'completed'},
        {'id': 2, 'content': 'b', 'status': 'pending'},
        {'id': 3, 'content': 'c', 'status': 'in_progress'},
        {'id': 4, 'content': 'd', 'status': 'pending'},
    ]
    assert strip_steps(steps, 2) == [('in_progress', '1/4 · c'), ('pending', 'b')]
    assert strip_steps(steps[:1], 6) == []


def test_todo_write_validates_and_stores(ctx: ToolContext) -> None:
    todos.todo_write(
        ctx, [{'content': 'plan', 'status': 'completed'}, {'content': 'build', 'status': 'in_progress'}]
    )
    assert ctx.session.todos[1] == {'id': 2, 'content': 'build', 'status': 'in_progress'}
    with pytest.raises(ToolError):
        todos.todo_write(
            ctx, [{'content': 'a', 'status': 'in_progress'}, {'content': 'b', 'status': 'in_progress'}]
        )


def test_a_finished_or_empty_todo_list_goes_away(ctx: ToolContext) -> None:
    shown: list[list[Any]] = []
    ctx.frontend.todos_updated = lambda todos: shown.append(list(todos))  # type: ignore[method-assign]
    todos.todo_write(ctx, [{'content': 'a', 'status': 'completed'}, {'content': 'b', 'status': 'pending'}])
    assert len(ctx.session.todos) == 2
    assert todos.todo_write(ctx, [{'content': 'a', 'status': 'completed'}]) == 'Todo list cleared'
    assert ctx.session.todos == []
    assert shown[-1] == []
    todos.todo_write(ctx, [{'content': 'b', 'status': 'pending'}])
    assert todos.todo_write(ctx, []) == 'Todo list cleared'
    assert ctx.session.todos == []


def test_validate_input_checks_types_and_enums() -> None:
    tool = todos.TOOLS[0]
    assert validate_input(tool, {'todos': []}) is None
    assert validate_input(tool, {'todos': 'no'}) == 'Parameter todos must be of type array'
    assert validate_input(tool, {}) == 'Missing required parameter todos'


def test_failing_locals_skip_modules_and_library_frames(ctx: ToolContext) -> None:
    out = python_runner.run_code(ctx.workspace, code='import json\nvalue = "x"\njson.loads(value)')
    assert "value = 'x'" in out
    assert 'json = <module' not in out
    assert 'JSONDecodeError' in out


def test_files_elsewhere_in_the_home_can_be_read_but_not_changed(tmp_path: pathlib.Path) -> None:
    home = tmp_path / 'home'
    (home / 'project').mkdir(parents=True)
    (home / 'other').mkdir()
    (home / 'other' / 'notes.txt').write_text('hi', encoding='utf-8')
    ws = Workspace(str(home / 'project'), readable=[str(home)], home=str(home))
    full = ws.resolve_readable('~/other/notes.txt')
    assert ws.rel(full) == '~/other/notes.txt'
    with pytest.raises(ToolError):
        ws.resolve('~/other/notes.txt')
    with pytest.raises(ToolError):
        ws.resolve_readable(str(tmp_path))


def test_run_python_keeps_the_start_and_end_of_huge_output(tmp_path: pathlib.Path) -> None:
    out = python_runner.run_code(Workspace(str(tmp_path)), code='for i in range(300_000): print("line", i)')
    assert out.startswith('line 0\nline 1\n')
    assert 'line 299999' in out
    assert 'characters of output left out' in out
    assert len(out) < 45_000


def test_run_python_stops_code_before_memory_runs_out(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = iter([10**9, 10**9, 10**6] + [10**6] * 100)
    monkeypatch.setattr(python_runner, 'available_memory', lambda: next(left))
    out = python_runner.run_code(Workspace(str(tmp_path)), code='while True: pass', timeout=30)
    assert 'MemoryError' in out
    assert 'memory was almost used up' in out


@pytest.mark.parametrize(
    ('data', 'note'),
    [
        ('café au lait\nnaïve\n'.encode('cp1252'), 'Windows-1252'),
        ('价格：十元\n备注\n'.encode('gb18030'), 'GBK/GB18030'),
        ('\ufeffhello\nworld\n'.encode('utf-16'), 'UTF-16 with a byte-order mark'),
        (b'line one\r\nline two\r\n', 'Windows (CRLF) line endings'),
        (b'\xef\xbb\xbfwith bom\n', 'UTF-8 with a byte-order mark'),
    ],
)
def test_files_keep_their_encoding_and_line_endings(ctx: ToolContext, data: bytes, note: str) -> None:
    path = os.path.join(ctx.workspace.root, 'f.txt')
    with open(path, 'wb') as f:
        f.write(data)
    shown = files.read_file(ctx, 'f.txt')
    assert note in shown
    text, fmt = ctx.workspace.read(path)
    first = text.splitlines()[0]
    files.edit_file(ctx, 'f.txt', first, first + '!')  # the model writes plain \n text
    with open(path, 'rb') as f:
        assert f.read() == fmt.encode(text.replace(first, first + '!', 1))
    assert ctx.workspace.read(path)[1] == fmt


def test_reading_and_writing_back_never_changes_a_byte() -> None:
    from pycoder.state import textfile

    samples = [bytes(range(1, 256)) * 3, '混合 text é\r\nmixed\nends'.encode('gb18030'), b'\xff\xfe\x00']
    for data in samples:
        try:
            text, fmt = textfile.decode(data)
        except textfile.BinaryFile:
            continue
        assert fmt.encode(text) == data


def test_a_big_file_reads_in_parts_with_an_outline(ctx: ToolContext) -> None:
    path = os.path.join(ctx.workspace.root, 'big.py')
    body = ''.join(f'def f{i}():\n    return "{"x" * 60}"\n\n' for i in range(3000))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(body + 'x = "' + 'y' * 5000 + '"\n')
    first = files.read_file(ctx, 'big.py')
    assert isinstance(first, str)
    assert first.startswith('Outline (line: name)')
    assert '1: def f0' in first
    assert len(first) < 40_000
    offset = int(first.rsplit('offset=', 1)[1].split(';')[0])
    second = files.read_file(ctx, 'big.py', offset=offset)
    assert isinstance(second, str)
    assert second.lstrip().startswith(str(offset))
    assert 'Outline' not in second
    last = files.read_file(ctx, 'big.py', offset=9001)
    assert 'line cut: 5006 characters' in last


def test_a_stuck_run_ending_late_leaves_a_newer_runs_settings_alone() -> None:
    import sys
    import threading

    from pycoder.tools.python_runner import _ProcessState

    state = _ProcessState()
    before = (list(sys.argv), os.getcwd(), list(sys.path))
    a_took, b_took, a_done = threading.Event(), threading.Event(), threading.Event()

    def stuck_run() -> None:  # a run that hangs past its timeout, then ends during a newer run
        state.take()
        sys.path.insert(0, 'from-a')
        a_took.set()
        b_took.wait(5)
        state.give_back()
        a_done.set()

    thread = threading.Thread(target=stuck_run)
    thread.start()
    a_took.wait(5)

    seen: list[str] = []

    def newer_run() -> None:
        state.take()
        sys.path.insert(0, 'from-b')
        b_took.set()
        a_done.wait(5)
        seen.append(sys.path[0])
        state.give_back()

    b = threading.Thread(target=newer_run)
    b.start()
    b.join(5)
    thread.join(5)
    assert seen == ['from-b']  # the old run's late end didn't undo the newer run's settings
    assert (list(sys.argv), os.getcwd(), list(sys.path)) == before  # as before the first of them


def test_search_shows_context_and_the_enclosing_function(ctx: ToolContext) -> None:
    path = os.path.join(ctx.workspace.root, 'm.py')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('class A:\n    def run(self):\n        x = 1\n        return X\n')
    out = files.search(ctx, 'return x', path='m.py', context=1, ignore_case=True)
    assert 'm.py:4: return X  (in A.run)' in out.replace('        ', '')
    assert 'm.py:3- ' in out
    with pytest.raises(ToolError, match='one line at a time'):
        files.search(ctx, 'a\\nb')


def test_run_python_tests_the_workspace_copy_not_an_installed_one(tmp_path: pathlib.Path) -> None:
    import json as installed  # stands for a package Pythonista ships under the same name

    root = tmp_path / 'proj'
    (root / 'src' / 'json').mkdir(parents=True)
    (root / 'src' / 'json' / '__init__.py').write_text('WHERE = "workspace"\n', encoding='utf-8')
    out = python_runner.run_code(Workspace(str(root)), code='import json; print(json.WHERE)')
    assert out.startswith('workspace')
    import json  # after the run, the installed one again, for pycoder

    assert json is installed
    assert json.decoder.JSONDecodeError is installed.JSONDecodeError


def test_run_python_forgets_modules_an_earlier_run_imported_from_another_folder(
    tmp_path: pathlib.Path,
) -> None:
    for name in ('one', 'two'):
        (tmp_path / name / 'tests').mkdir(parents=True)
        (tmp_path / name / 'tests' / 'helper_mod.py').write_text(f'WHERE = {name!r}\n', encoding='utf-8')
    code = 'import sys; sys.path.insert(0, "tests"); import helper_mod; print(helper_mod.WHERE)'
    try:
        assert python_runner.run_code(Workspace(str(tmp_path / 'one')), code=code).startswith('one')
        assert python_runner.run_code(Workspace(str(tmp_path / 'two')), code=code).startswith('two')
    finally:
        import sys

        sys.modules.pop('helper_mod', None)


def test_run_python_runs_a_test_file_with_unittest_main(tmp_path: pathlib.Path) -> None:
    import sys

    (tmp_path / 'test_add.py').write_text(
        'import unittest\n\nclass T(unittest.TestCase):\n'
        '    def test_add(self):\n        self.assertEqual(1 + 1, 2)\n\n'
        "if __name__ == '__main__':\n    unittest.main()\n",
        encoding='utf-8',
    )
    before = sys.modules.get('__main__')
    out = python_runner.run_code(Workspace(str(tmp_path)), path='test_add.py')
    assert 'Ran 1 test' in out
    assert 'OK' in out
    assert sys.modules.get('__main__') is before


def test_run_python_never_forgets_a_compiled_module(tmp_path: pathlib.Path) -> None:
    import sys
    import types

    compiled = types.ModuleType('fake_ext')
    compiled.__file__ = str(tmp_path / 'elsewhere' / 'fake_ext.cpython-310-darwin.so')  # off sys.path
    sys.modules['fake_ext'] = compiled
    try:
        python_runner.run_code(Workspace(str(tmp_path)), code='pass')
        assert sys.modules.get('fake_ext') is compiled  # importing it again would crash the process
    finally:
        sys.modules.pop('fake_ext', None)


def test_read_file_shows_an_image_to_the_model(ctx: ToolContext) -> None:
    from PIL import Image

    Image.new('RGB', (40, 20), 'red').save(os.path.join(ctx.workspace.root, 'chart.png'))
    shown = files.read_file(ctx, 'chart.png')
    assert isinstance(shown, list)
    text, image = shown
    assert text['text'].startswith('chart.png (')
    assert image['type'] == 'image'

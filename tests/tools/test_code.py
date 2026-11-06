"""python_code: what Python code means, from ast and jedi."""

from __future__ import annotations

import os
from typing import Any

import pytest

from pycoder.cancel import CancelToken
from pycoder.state.checkpoints import Checkpoints
from pycoder.state.session import Session
from pycoder.state.workspace import Workspace
from pycoder.tools import code
from pycoder.tools.base import ToolContext, ToolError
from tests.conftest import RecordingFrontend

LIB = '''"""A library."""


class Greeter:
    """Says hello."""

    def greet(self, who: str = 'you') -> str:
        """Greet someone."""
        return f'hello {who}'


def helper(n):
    return n + 1
'''
MAIN = """from lib import Greeter, helper

g = Greeter()
print(g.greet('x'), helper(1))
"""


@pytest.fixture
def ctx(tmp_path: Any) -> ToolContext:
    (tmp_path / 'lib.py').write_text(LIB, encoding='utf-8')
    (tmp_path / 'main.py').write_text(MAIN, encoding='utf-8')
    ws = Workspace(str(tmp_path))
    session = Session.new(str(tmp_path), 'claude-opus-5-5', 'system', web=False)
    return ToolContext(ws, RecordingFrontend(), session, Checkpoints(session, ws), CancelToken())


def test_symbols_are_nested_with_their_parameters(ctx: ToolContext) -> None:
    out = code.python_code(ctx, 'symbols', 'lib.py')
    assert out.splitlines() == [
        '4: class Greeter',
        "  7: def greet(self, who: str='you')",
        '12: def helper(n)',
    ]


def test_definition_follows_the_import(ctx: ToolContext) -> None:
    out = code.python_code(ctx, 'definition', 'main.py', 4, 'greet')
    assert out.startswith('lib.py:7: def greet')


def test_references_cross_files(ctx: ToolContext) -> None:
    out = code.python_code(ctx, 'references', 'lib.py', 12, 'helper')
    assert 'lib.py:12:' in out
    assert 'main.py:1:' in out
    assert 'main.py:4:' in out


def test_hover_gives_signature_and_docstring(ctx: ToolContext) -> None:
    out = code.python_code(ctx, 'hover', 'main.py', 4, 'greet')
    assert "greet(who: str='you') -> str" in out
    assert 'Greet someone.' in out


def test_find_looks_through_the_project(ctx: ToolContext) -> None:
    assert code.python_code(ctx, 'find', name='helper').startswith('lib.py:12:')
    assert 'No definition' in code.python_code(ctx, 'find', name='nothing_called_this')


def test_a_name_must_be_on_the_line_it_is_said_to_be_on(ctx: ToolContext) -> None:
    with pytest.raises(ToolError, match='not on line 1'):
        code.python_code(ctx, 'definition', 'main.py', 1, 'greet')
    with pytest.raises(ToolError, match='outside the file'):
        code.python_code(ctx, 'hover', 'main.py', 99, 'greet')
    with pytest.raises(ToolError, match='needs'):
        code.python_code(ctx, 'references')


def test_syntax_errors_say_where(ctx: ToolContext, tmp_path: Any) -> None:
    (tmp_path / 'bad.py').write_text('def (\n', encoding='utf-8')
    with pytest.raises(ToolError, match='Line 1'):
        code.python_code(ctx, 'symbols', 'bad.py')


def test_results_leave_out_what_a_deny_rule_covers(ctx: ToolContext, monkeypatch: Any) -> None:
    monkeypatch.setattr(ToolContext, 'denied', lambda self, full: os.path.basename(full) == 'lib.py')
    assert 'lib.py' not in code.python_code(ctx, 'references', 'main.py', 4, 'helper')


def test_whatever_jedi_was_imported_stays_as_it_was(ctx: ToolContext, monkeypatch: Any) -> None:
    import sys
    import types

    theirs = types.ModuleType('jedi')
    monkeypatch.setitem(sys.modules, 'jedi', theirs)
    assert code.python_code(ctx, 'find', name='helper').startswith('lib.py:12:')  # ours did this
    assert sys.modules['jedi'] is theirs
    assert code.TOOLS_DIR not in sys.path


def test_check_finds_undefined_names_and_syntax_errors(ctx: ToolContext, tmp_path: Any) -> None:
    (tmp_path / 'wrong.py').write_text('import os\n\n\ndef f():\n    return missing\n', encoding='utf-8')
    (tmp_path / 'bad.py').write_text('def (\n', encoding='utf-8')
    out = code.python_code(ctx, 'check')
    assert "wrong.py:1:1: 'os' imported but unused" in out
    assert "wrong.py:5:12: undefined name 'missing'" in out
    assert 'bad.py:1:' in out
    assert 'main.py' not in out
    assert code.python_code(ctx, 'check', 'lib.py') == 'No problems found in 1 file'


def test_types_finds_what_mypy_finds_and_leaves_the_process_as_it_was(
    ctx: ToolContext, tmp_path: Any
) -> None:
    import gc

    (tmp_path / 'typed.py').write_text(
        'from lib import Greeter\n\nn: int = Greeter().greet()\nm: int = "x"\n', encoding='utf-8'
    )
    before = gc.get_threshold()
    out = code.python_code(ctx, 'types', 'typed.py')
    assert 'typed.py:3: error: Incompatible types in assignment' in out
    assert 'typed.py:4: error:' in out
    assert '[assignment]' in out
    assert gc.get_threshold() == before
    assert 'MYPYPATH' not in os.environ
    assert code.python_code(ctx, 'types', 'lib.py').startswith('No problems found')
    (tmp_path / 'plain.py').write_text(
        'from lib import helper\n\n\ndef f():\n    x: int = "s"\n', encoding='utf-8'
    )
    assert 'plain.py:5: error:' in code.python_code(ctx, 'types', 'plain.py')  # not annotated, still checked
    (tmp_path / 'web.py').write_text('import requests\n\nrequests.get("x")\n', encoding='utf-8')
    assert code.python_code(ctx, 'types', 'web.py').startswith('No problems found')  # no stubs: fine

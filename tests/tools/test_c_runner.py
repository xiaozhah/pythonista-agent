"""The run_c tool: output, exit codes, errors and the time limit."""

from __future__ import annotations

import os

import pytest

from pycoder.cancel import CancelToken
from pycoder.host.cwasm import jsc
from pycoder.state.checkpoints import Checkpoints
from pycoder.state.session import Session
from pycoder.state.workspace import Workspace
from pycoder.tools import c_runner
from pycoder.tools.base import ToolContext, ToolError
from tests.conftest import RecordingFrontend

if not jsc.available():
    pytest.skip('no JavaScriptCore here', allow_module_level=True)
pytest.importorskip('ppci')


@pytest.fixture
def ctx(workspace: str) -> ToolContext:
    ws = Workspace(workspace)
    session = Session.new(workspace, 'claude-opus-5-5', 'system', web=False)
    return ToolContext(ws, RecordingFrontend(), session, Checkpoints(session, ws), CancelToken())


HELLO = '#include <stdio.h>\nint main(void) { printf("hello %d\\n", 6 * 7); return 2; }\n'


def test_runs_code_and_reports_output_and_exit_code(ctx: ToolContext) -> None:
    text = c_runner.run_c(ctx, code=HELLO)
    assert text.startswith('hello 42\n[exit 2]\n[compiled in ')
    frontend = ctx.frontend
    assert isinstance(frontend, RecordingFrontend)
    assert frontend.named('run_output')[-1] == (text,)  # no install: ppci is already there


def test_runs_a_workspace_file_and_names_it_in_errors(ctx: ToolContext) -> None:
    with open(os.path.join(ctx.workspace.root, 'prog.c'), 'w', encoding='utf-8') as f:
        f.write('int main(void) { return 0 }\n')
    with pytest.raises(ToolError, match=r'prog\.c:1:'):
        c_runner.run_c(ctx, path='prog.c')


def test_reports_missing_library_functions(ctx: ToolContext) -> None:
    with pytest.raises(ToolError, match='strtok') as e:
        c_runner.run_c(ctx, code='char *strtok(char *s, const char *d);\nint main(void) { strtok(0, 0); }\n')
    assert 'stdio.h (printf' in str(e.value)


def test_stops_at_the_time_limit_keeping_the_output(ctx: ToolContext) -> None:
    source = '#include <stdio.h>\nint main(void) { puts("spinning"); volatile int x = 0; while (1) x++; }\n'
    text = c_runner.run_c(ctx, code=source, timeout=1)
    assert text.startswith('spinning\n[stopped: it ran longer than the time limit of 1s]')


def test_traps_are_reported(ctx: ToolContext) -> None:
    text = c_runner.run_c(ctx, code='int main(void) { int *p = (int *)-8; return *p; }')
    assert 'Out of bounds memory access' in text


def test_input_is_checked(ctx: ToolContext) -> None:
    with pytest.raises(ToolError, match='exactly one'):
        c_runner.run_c(ctx)
    with pytest.raises(ToolError, match='timeout'):
        c_runner.run_c(ctx, code=HELLO, timeout=0)
    assert c_runner.TOOLS[0].needs_confirmation({'code': HELLO})

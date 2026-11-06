"""Background jobs: run_python(background=true), job_output, and telling the agent when one ends."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

import pytest

from pycoder.cancel import CancelToken
from pycoder.state.checkpoints import Checkpoints
from pycoder.state.session import Session
from pycoder.state.workspace import Workspace
from pycoder.tools import jobs, python_runner
from pycoder.tools.base import ToolContext, ToolError
from tests.conftest import FakeTransport, RecordingFrontend, text_reply, tool_reply


@pytest.fixture
def ctx(workspace: str) -> ToolContext:
    ws = Workspace(workspace)
    session = Session.new(workspace, 'claude-opus-5-5', 'system', web=False)
    return ToolContext(ws, RecordingFrontend(), session, Checkpoints(session, ws), CancelToken())


@pytest.fixture(autouse=True)
def no_jobs_left() -> Iterator[None]:
    yield
    for job in jobs.running():
        job.run.interrupt('stopped')
    jobs.JOBS.clear()  # they are the process's: in Pythonista, the app the tests run in


def job_number(started: str) -> int:
    found = re.search(r'job (\d+)', started)
    assert found
    return int(found.group(1))


def test_a_job_runs_on_while_other_code_runs_and_keeps_its_own_output(ctx: ToolContext) -> None:
    code = 'import time\nprint("job started")\ntime.sleep(0.6)\nprint("job done")'
    number = job_number(python_runner.run_python(ctx, code=code, background=True))
    foreground = python_runner.run_python(ctx, code='print("foreground")')
    assert foreground.startswith('foreground')
    assert 'job' not in foreground  # the job's prints went to the job
    assert 'running' in jobs.job_output(ctx, number)
    out = jobs.job_output(ctx, number, wait=10)
    assert 'finished' in out
    assert 'job started\njob done' in out
    assert jobs.ended_notes() == []  # it has seen how the job ended


def test_a_job_can_be_stopped(ctx: ToolContext) -> None:
    number = job_number(python_runner.run_python(ctx, code='while True: pass', background=True))
    out = jobs.job_output(ctx, number, stop=True)
    assert 'stopped' in out
    with pytest.raises(ToolError, match='No background job 999'):
        jobs.job_output(ctx, 999)


def test_the_agent_is_told_in_its_next_request_when_a_job_ends(make_controller: Any, tmp_path: Any) -> None:
    go_on = tmp_path / 'go_on'
    code = f'import os, time\nwhile not os.path.exists({str(go_on)!r}): time.sleep(0.01)\nprint(6 * 7)'
    api = FakeTransport(
        [
            tool_reply('run_python', {'code': code, 'background': True}),
            text_reply('started it'),
        ]
    )
    c = make_controller(api)
    c.run_turn('train in the background')  # it can't end before this turn's last request
    go_on.touch()
    deadline = time.time() + 5
    while any(job.run.alive() for job in jobs.JOBS.values()) and time.time() < deadline:
        time.sleep(0.05)
    api.add(text_reply('it printed 42'))
    c.run_turn('how is it going?')
    note = api.requests[-1]['messages'][-1]['content'][-1]['text']
    assert 'finished' in note
    assert 'job_output(job=' in note


def test_a_job_outlives_a_reload_of_pycoder(ctx: ToolContext) -> None:
    import importlib

    code = 'import time\ntime.sleep(0.3)\nprint("still here")'
    number = job_number(python_runner.run_python(ctx, code=code, background=True))
    fresh = importlib.reload(jobs)  # as opening pycoder again (or the dev bridge) loads it again
    assert 'still here' in fresh.job_output(ctx, number, wait=10)


def test_a_job_keeps_its_folder_after_a_foreground_run_ends(ctx: ToolContext) -> None:
    import os

    code = 'import time\ntime.sleep(0.5)\nopen("made_by_job.txt", "w").close()'
    before = os.getcwd()
    number = job_number(python_runner.run_python(ctx, code=code, background=True))
    python_runner.run_python(ctx, code='print("quick")')  # ends while the job goes on
    jobs.job_output(ctx, number, wait=10)
    assert os.path.exists(os.path.join(ctx.workspace.root, 'made_by_job.txt'))
    assert os.getcwd() == before  # and all is as it was once they have both ended


def test_pythonistas_sys_exit_is_an_exit_not_a_traceback(ctx: ToolContext) -> None:
    out = python_runner.run_python(ctx, code='raise KeyboardInterrupt("Exit: False")')
    assert '[exit False]' in out
    assert 'Traceback' not in out

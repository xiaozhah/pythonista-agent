"""What one run must not leave to the next, and whose output is whose."""

from __future__ import annotations

import sys
import threading
import warnings
from typing import Any

from pycoder.tools import python_runner


def _ran(workspace: Any, code: str) -> str:
    from pycoder.state.workspace import Workspace

    run = python_runner.Run(Workspace(workspace), code, None, None)
    run.start()
    run.wait(10)
    return run.report()


def test_warning_filters_come_back_after_a_run(workspace: str) -> None:
    before = list(warnings.filters)
    _ran(workspace, "import warnings; warnings.simplefilter('error')")
    assert warnings.filters == before


def test_a_thread_already_there_does_not_print_into_the_run(workspace: str) -> None:
    go, done = threading.Event(), threading.Event()

    def outsider() -> None:
        go.wait(5)
        print('from outside')
        done.set()

    threading.Thread(target=outsider, daemon=True).start()
    sys.__dict__['_test_run_events'] = (go, done)
    code = 'import sys\ngo, done = sys.__dict__["_test_run_events"]\nprint("mine")\ngo.set()\ndone.wait(5)\n'
    report = _ran(workspace, code)
    assert done.is_set()
    assert 'mine' in report
    assert 'from outside' not in report


def test_a_thread_the_code_starts_prints_into_the_run(workspace: str) -> None:
    code = (
        'import threading\nt = threading.Thread(target=lambda: print("from a thread"))\nt.start()\nt.join()\n'
    )
    assert 'from a thread' in _ran(workspace, code)

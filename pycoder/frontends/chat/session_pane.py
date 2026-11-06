"""The session pane: how full the context is, what runs in the background (a job's output, Stop),
and the files this session made or changed (tap to preview). It stays current while it is open."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

import console

from ...app import reports
from ...tools import jobs
from . import icons, render
from .frontend import AppFrontend
from .pane import LivePane

OUTPUT_SHOWN = 4000  # characters of a job's output, its end
ENDED_SHOWN = 5  # finished jobs listed


class SessionPanel(LivePane):
    def __init__(
        self, controller: Any, frontend: AppFrontend, on_close: Callable[[], None], dark: bool
    ) -> None:
        super().__init__('Session', '', on_close, dark)
        self.controller = controller
        self.frontend = frontend
        self.outputs: list[str] = []  # full paths, in the order shown
        self.style()

    def act(self, action: str) -> None:
        kind, _, what = action.partition(':')
        if kind == 'stop' and int(what) in jobs.JOBS:
            jobs.JOBS[int(what)].run.interrupt('stopped')
            self.redraw()
        elif kind == 'clear-tasks':
            self.controller.clear_todos()
            self.redraw()
        elif kind == 'open' and int(what) < len(self.outputs):
            full = self.outputs[int(what)]
            threading.Thread(target=console.quicklook, args=(full,), daemon=True).start()

    def page_html(self) -> str:
        c = self.controller
        now = time.time()
        subagents = [(r.description, r.step, now - r.started) for r in list(self.frontend.running.values())]
        shown = []
        ended = 0
        for job in reversed(list(jobs.JOBS.values())):
            if not job.run.alive():
                ended += 1
                if ended > ENDED_SHOWN or job.run.started < c.session.created:
                    continue  # the running ones, and the latest few of this session
            status = (
                render.elapsed(now - job.run.started) if job.run.alive() else job.status().rsplit(': ', 1)[1]
            )
            shown.append((job.number, job.label, status, job.run.alive(), job.run.report()[-OUTPUT_SHOWN:]))
        files = c.checkpoints.modified_since(c.session.created)
        self.outputs = [full for _, full, _ in files]
        outputs = [(os.path.basename(rel), os.path.dirname(rel), stat[1]) for rel, _, stat in files]
        usage = reports.context_usage(c)
        return render.session_html(usage, subagents, shown, outputs, icons.icon('file'), self.frontend.todos)

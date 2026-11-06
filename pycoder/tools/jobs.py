"""Code run in the background (run_python with background=true): it goes on while the agent works;
job_output reads what it printed, waits for it or stops it, and when it ends the agent is told in
its next request, and the user on screen (or by a notification when away)."""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass

from ..events import Frontend
from ..host import background, env
from .base import Tool, ToolContext, ToolError, prop
from .describe import shorten
from .python_runner import Run


@dataclass
class Job:
    number: int
    label: str
    run: Run
    told: bool = False  # the agent has been told that it ended

    def status(self) -> str:
        if self.run.alive():
            return f'job {self.number} ({self.label}): running for {time.time() - self.run.started:.0f}s'
        result = self.run.result
        how = 'stopped' if result.get('stopped') else 'failed' if result.get('tb') else 'finished'
        return f'job {self.number} ({self.label}): {how} after {self.run.ended - self.run.started:.0f}s'


# the jobs of this process: a reload of pycoder's modules (env.process_wide) must not lose them
JOBS: dict[int, Job] = env.process_wide('jobs', {})


def running() -> list[Job]:
    return [job for job in list(JOBS.values()) if job.run.alive()]


_numbers: itertools.count[int] = env.process_wide('job_numbers', itertools.count(1))
_lock: threading.Lock = env.process_wide('jobs_lock', threading.Lock())


def start(run: Run, label: str, frontend: Frontend) -> Job:
    with _lock:
        job = Job(next(_numbers), label, run)
        JOBS[job.number] = job
    background.hold(True, label)  # iOS would suspend it with the app
    run.start()
    threading.Thread(target=_watch, args=(job, frontend), daemon=True).start()
    frontend.jobs_changed()
    return job


def _watch(job: Job, frontend: Frontend) -> None:
    """Keep the memory guard on while it runs (no time limit), then say that it ended."""
    while job.run.alive():
        job.run.wait(3600)
    background.hold(False)
    frontend.jobs_changed()
    frontend.notice(f'Background {job.status()}')
    env.notify_if_away(f'Background {job.status()}')


def ended_notes() -> list[str]:
    """For the agent's next request: the jobs that ended since it was last told."""
    notes = []
    with _lock:
        for job in JOBS.values():
            if not job.told and not job.run.alive():
                job.told = True
                notes.append(
                    f'<system-reminder>Background {job.status()}. Read its output with '
                    f'job_output(job={job.number}).</system-reminder>'
                )
    return notes


def job_output(ctx: ToolContext, job: int, wait: int = 0, stop: bool = False) -> str:
    found = JOBS.get(job)
    if found is None:
        known = ', '.join(str(n) for n in JOBS) or 'none'
        raise ToolError(f'No background job {job} (jobs: {known})')
    if stop:
        found.run.interrupt('stopped')
    elif wait > 0:
        found.run.wait(min(wait, 600), ctx.cancel)
    if not found.run.alive():
        found.told = True  # the agent has seen how it ended
    return f'[{found.status()}]\n{found.run.report()}'


def _label(code: str) -> str:
    """What to call a job run from code: its first line that does something."""
    lines = [line.strip() for line in code.splitlines() if line.strip()]
    doing = [line for line in lines if not line.startswith(('import ', 'from ', '#'))]
    return shorten((doing or lines or ['code'])[0], 40)


def run_in_background(ctx: ToolContext, code: str | None, path: str | None, args: list[str] | None) -> str:
    run = Run(ctx.workspace, code, path, args)
    label = path or _label(code or '')
    job = start(run, label, ctx.frontend)
    return (
        f'Started background job {job.number} ({label}). It runs on while you work; read what it has '
        f'printed with job_output(job={job.number}), and you will be told when it ends.'
    )


TOOLS = [
    Tool(
        'job_output',
        'What a background job (run_python with background=true) has printed so far and whether it is '
        'still running. wait waits up to that many seconds for it to end; stop stops it.',
        {
            'job': prop('integer', 'The job number run_python gave'),
            'wait': prop('integer', 'Seconds to wait for the job to end (at most 600), default 0'),
            'stop': prop('boolean', 'Stop the job'),
        },
        job_output,
        required=['job'],
    ),
]

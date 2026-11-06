"""Run one request through pycoder with nobody watching, and record what the harness did.

For comparing harnesses: give pycoder and Claude Code the same project, model and request, and
compare the records. From the Mac:

    python3 dev/client.py run dev/bench.py <workspace> <model> <request file> <record file>

<workspace> is a folder in pycoder's home (or an absolute path); the request is read from a file
(UTF-8); the record is written as JSON: the reply, every tool call in order, API requests,
tokens, cost and seconds. pycoder runs in bypass mode with settings of its own
(.pycoder-bench/settings.json), so the user's own settings are not touched; the session is saved
with the user's, so /resume in that folder shows the whole conversation.
"""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for name in [n for n in sys.modules if n == 'pycoder' or n.startswith('pycoder.')]:
    del sys.modules[name]  # Pythonista keeps modules between runs
sys.path.insert(0, ROOT)

from pycoder import config  # noqa: E402
from pycoder.app.controller import Controller  # noqa: E402
from pycoder.events import Frontend  # noqa: E402


class Quiet(Frontend):
    """Shows nothing; counts the API responses."""

    def __init__(self) -> None:
        self.responses = 0

    def stream_start(self) -> None:
        self.responses += 1


def main(workspace: str, model: str, request_file: str, record_file: str) -> None:
    home = os.path.dirname(ROOT)
    workspace = os.path.join(home, workspace)
    data = os.path.join(home, '.pycoder-bench')
    with open(os.path.join(home, request_file), encoding='utf-8') as f:  # an absolute path stays as it is
        request = f.read().strip()
    frontend = Quiet()
    c = Controller(
        frontend,
        root=workspace,
        settings_file=os.path.join(data, 'settings.json'),
    )
    c.set_setting('mode', 'bypass')
    c.set_model(config.resolve_model(model) or model)
    c.connect()
    started = time.time()
    result = c.run_turn(request)
    seconds = time.time() - started
    calls = [
        {'name': b['name'], 'input': b.get('input')}
        for m in c.session.messages
        if m['role'] == 'assistant' and isinstance(m['content'], list)
        for b in m['content']
        if b.get('type') in ('tool_use', 'server_tool_use')
    ]
    record = {
        'harness': 'pycoder',
        'model': c.settings.model,
        'status': result.status,
        'reply': result.text,
        'tool_calls': calls,
        'api_requests': frontend.responses,
        'cost_usd': round(c.session.cost, 5),
        'seconds': round(seconds, 1),
        'usage_last': result.usage,
    }
    out = os.path.join(home, record_file)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
    print(f'{result.status}: {len(calls)} tool calls, {frontend.responses} requests, ', end='')
    print(f'${record["cost_usd"]}, {seconds:.0f}s')


if __name__ == '__main__':
    main(*sys.argv[1:5])

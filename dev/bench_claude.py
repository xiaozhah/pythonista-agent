"""The Claude Code side of a harness comparison (see bench.py): one request, run headless with
`claude -p`, recorded in the same JSON shape as bench.py's.

    python3 dev/bench_claude.py <claude executable> <workspace> <model> <effort> <request file> <record file>

Run on the Mac. Only the project's own settings are read (--setting-sources project, no MCP
servers, no session saved), so the user's personal setup doesn't change the result; edits and
commands are allowed without asking, as bench.py runs pycoder in bypass.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any


def main(claude: str, workspace: str, model: str, effort: str, request_file: str, record_file: str) -> None:
    with open(request_file, encoding='utf-8') as f:
        request = f.read().strip()
    command = [
        claude, '-p', request, '--model', model, '--effort', effort,
        '--output-format', 'stream-json', '--verbose',
        '--setting-sources', 'project', '--strict-mcp-config',
        '--permission-mode', 'bypassPermissions', '--no-session-persistence',
    ]  # fmt: skip
    started = time.time()
    done = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=1800)
    seconds = time.time() - started
    events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith('{')]
    calls = [
        {'name': block['name'], 'input': block.get('input')}
        for event in events
        if event.get('type') == 'assistant'
        for block in event['message'].get('content', [])
        if block.get('type') in ('tool_use', 'server_tool_use')
    ]
    final: dict[str, Any] = next((e for e in reversed(events) if e.get('type') == 'result'), {})
    requests = len({e['message'].get('id') for e in events if e.get('type') == 'assistant'})
    record = {
        'harness': 'claude-code',
        'model': model,
        'status': 'error' if final.get('is_error') else 'done',
        'reply': final.get('result', done.stderr[-2000:]),
        'tool_calls': calls,
        'api_requests': requests,
        'cost_usd': round(float(final.get('total_cost_usd') or 0), 5),
        'seconds': round(seconds, 1),
        'usage_last': final.get('usage'),
    }
    with open(record_file, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=1)
    summary = f'{record["status"]}: {len(calls)} tool calls, {requests} requests'
    print(f'{summary}, ${record["cost_usd"]}, {seconds:.0f}s')


if __name__ == '__main__':
    main(*sys.argv[1:7])

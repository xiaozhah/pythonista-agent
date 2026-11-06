"""Server-sent events: lines in, event dicts out."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any


def iter_sse(lines: Iterable[str | bytes | None]) -> Iterator[dict[str, Any]]:
    data: list[str] = []
    for line in lines:
        if line is None:
            continue
        if isinstance(line, bytes):
            line = line.decode('utf-8', 'replace')
        if line == '':
            if data:
                yield json.loads('\n'.join(data))
                data = []
        elif line.startswith('data:'):
            data.append(line[5:].lstrip())
    if data:
        yield json.loads('\n'.join(data))

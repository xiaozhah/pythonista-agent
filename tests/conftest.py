"""Shared test helpers: a scripted fake of the Claude API and a frontend that records events."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator, Sequence
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pycoder import config
from pycoder.app.controller import Controller
from pycoder.events import Frontend

# ---- building fake responses


def text_reply(text: str, stop: str = 'end_turn') -> list[dict[str, Any]]:
    return [
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
        {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}},
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'message_delta', 'delta': {'stop_reason': stop}, 'usage': {'output_tokens': 5}},
    ]


def tool_reply(
    name: str, inp: dict[str, Any], tool_id: str = 'tool1', chunk: int = 7
) -> list[dict[str, Any]]:
    raw = json.dumps(inp)
    events = [
        {
            'type': 'content_block_start',
            'index': 0,
            'content_block': {'type': 'tool_use', 'id': tool_id, 'name': name, 'input': {}},
        },
    ]
    events += [
        {
            'type': 'content_block_delta',
            'index': 0,
            'delta': {'type': 'input_json_delta', 'partial_json': raw[i : i + chunk]},
        }
        for i in range(0, len(raw), chunk)
    ]
    events += [
        {'type': 'content_block_stop', 'index': 0},
        {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}, 'usage': {'output_tokens': 9}},
    ]
    return events


class FakeResponse:
    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        status: int = 200,
        body: dict[str, Any] | None = None,
    ) -> None:
        self.events = events or []
        self.status_code = status
        self.encoding: str | None = None
        self.body = body or {}

    @property
    def text(self) -> str:
        return json.dumps(self.body)

    def json(self) -> Any:
        return self.body

    def iter_lines(self, chunk_size: int | None = None, decode_unicode: bool = False) -> Iterator[str]:
        start = {
            'type': 'message_start',
            'message': {'model': 'claude-opus-5-5', 'usage': {'input_tokens': 100}},
        }
        for event in [start, *self.events]:
            yield 'data: ' + json.dumps(event)
            yield ''

    def close(self) -> None:
        pass


class FakeTransport:
    """Answers each request with the next scripted response and keeps every request body."""

    def __init__(self, responses: Sequence[FakeResponse | list[dict[str, Any]]] = ()) -> None:
        self.responses = [r if isinstance(r, FakeResponse) else FakeResponse(r) for r in responses]
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []

    def add(self, *responses: FakeResponse | list[dict[str, Any]]) -> None:
        self.responses += [r if isinstance(r, FakeResponse) else FakeResponse(r) for r in responses]

    def post(self, url: str, headers: dict[str, str], body: dict[str, Any], stream: bool) -> FakeResponse:
        self.requests.append(json.loads(json.dumps(body)))  # a snapshot, as it would be sent
        self.headers.append(headers)
        if not self.responses:
            raise AssertionError('unexpected request')
        return self.responses.pop(0)


class RecordingFrontend(Frontend):
    """Records every call; answers confirmations with `answer` and choices with `choice`."""

    def __init__(self, answer: str = 'yes', choice: int | None = 0, plan_answer: str = 'acceptEdits') -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.answer = answer
        self.choice = choice
        self.plan_answer = plan_answer

    def __getattribute__(self, name: str) -> Any:
        attr = object.__getattribute__(self, name)
        if callable(attr) and not name.startswith('_') and name in Frontend.__dict__:

            def record(*args: Any) -> Any:
                object.__getattribute__(self, 'calls').append((name, args))
                return attr(*args)

            return record
        return attr

    def confirm(
        self, name: str, inp: dict[str, Any], preview: Any = None, rule: str = ''
    ) -> tuple[str, str | None]:
        return self.answer, 'use a different file' if self.answer == 'no' else None

    def approve_plan(self, plan: str) -> tuple[str, str | None]:
        return self.plan_answer, None

    def choose(self, title: str, options: Sequence[str], current: int | None = None) -> int | None:
        return self.choice

    def ask_text(self, title: str, message: str = '', secret: bool = False) -> str | None:
        return 'secret-token'

    def named(self, name: str) -> list[tuple[Any, ...]]:
        return [args for n, args in self.calls if n == name]

    def notices(self) -> list[str]:
        return [args[0] for args in self.named('notice')]


@pytest.fixture
def workspace(tmp_path: Any) -> str:
    root = tmp_path / 'ws'
    root.mkdir()
    (root / 'hello.py').write_text('print("hello")\n', encoding='utf-8')
    return str(root)


@pytest.fixture(autouse=True)
def worktrees_here(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, 'WORKTREES_DIR', str(tmp_path / 'worktrees'))


@pytest.fixture
def make_controller(tmp_path: Any, workspace: str) -> Any:
    def make(transport: FakeTransport | None = None, frontend: RecordingFrontend | None = None) -> Controller:
        c = Controller(
            frontend or RecordingFrontend(),
            root=workspace,
            transport=transport or FakeTransport(),
            sessions_dir=str(tmp_path / 'sessions'),
            skills_dir=str(tmp_path / 'skills'),
            commands_dir=str(tmp_path / 'commands'),
            settings_file=str(tmp_path / 'settings.json'),
            memory_dir=str(tmp_path / 'memory'),
            home=workspace,
        )
        c.connect('test-key')
        return c

    return make

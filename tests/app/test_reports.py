"""/context, /status, /usage, cache lifetime and costs, transcripts kept before compaction."""

from __future__ import annotations

import json
import os
from typing import Any

from pycoder import config
from pycoder.app import reports
from pycoder.app.commands import run_command
from tests.conftest import FakeTransport, text_reply


def test_cost_of_prices_one_hour_cache_writes_at_twice_input() -> None:
    usage = {
        'input_tokens': 1_000_000,
        'output_tokens': 0,
        'cache_creation_input_tokens': 2_000_000,
        'cache_creation': {'ephemeral_1h_input_tokens': 1_000_000, 'ephemeral_5m_input_tokens': 1_000_000},
    }
    p_in, _, _, p_write = config.price_for('claude-opus-5-5')
    assert config.cost_of(usage, 'claude-opus-5-5') == p_in + p_write + 2 * p_in


def test_cache_ttl_reaches_the_request(make_controller: Any) -> None:
    api = FakeTransport([text_reply('a'), text_reply('b')])
    c = make_controller(api)
    c.set_setting('cache_ttl', '5m')
    c.run_turn('one')
    assert api.requests[0]['cache_control'] == {'type': 'ephemeral'}
    c.set_setting('cache_ttl', '1h')
    c.run_turn('two')
    assert api.requests[1]['cache_control'] == {'type': 'ephemeral', 'ttl': '1h'}


def test_context_grid_fills_the_window(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('ok')]))
    c.run_turn('hi')
    usage = reports.context_usage(c)
    cells = usage.cells()
    assert len(cells) == reports.GRID * reports.GRID
    assert usage.used == usage.measured == 105
    names = [cell.name for cell in cells]
    assert names[0] == 'System prompt'  # every used category shows, however small
    assert names[-1] == reports.BUFFER
    assert names.count(reports.BUFFER) == 80  # 1M window, compacting at 200k
    c.frontend.calls.clear()
    run_command(c, '/context')
    assert c.frontend.named('show_context')


def test_status_and_usage(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('ok')]))
    c.run_turn('hi')
    status = dict(reports.status(c))
    assert status['Permission mode'] == 'default'
    assert status['Workspace'] == c.folder_label()
    usage = dict(reports.usage(c))
    assert usage['This session'].endswith('1 requests')
    assert usage['Today'] == f'${c.session.cost:.2f}'
    run_command(c, '/status')
    assert 'pycoder v' in c.frontend.notices()[-1]


def test_config_form_gets_status_and_usage_tabs(make_controller: Any) -> None:
    c = make_controller()
    seen: dict[str, Any] = {}

    def edit(specs: Any, current: dict[str, Any], tabs: Any = None) -> dict[str, Any]:
        seen.update(tabs or {})
        return current

    c.frontend.edit_settings = edit
    run_command(c, '/config')
    assert sorted(seen) == ['Status', 'Usage']


def test_turn_cost_goes_to_the_footer(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('ok')]))
    c.run_turn('hi')
    _, _, total, turn = c.frontend.named('turn_done')[0]
    assert total == turn == c.session.cost > 0


def test_transcript_is_kept_before_compaction(make_controller: Any) -> None:
    c = make_controller(FakeTransport([text_reply('first')]))
    c.run_turn('first')
    path = c.store.save_transcript(c.session)
    assert path.endswith('.pre-compact-1.json')
    with open(path, encoding='utf-8') as f:
        assert json.load(f)['messages'][0]['content'][0]['text'] == 'first'
    c.save()
    assert [s.id for s in c.store.list()] == [c.session.id]  # transcripts aren't sessions
    c.store.delete(c.session.id)
    assert not os.path.exists(path)

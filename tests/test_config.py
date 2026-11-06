"""Prices."""

from __future__ import annotations

import pytest


def test_prices_follow_the_price_list() -> None:
    from pycoder import config

    haiku, sonnet = 'claude-haiku-5-5', 'claude-sonnet-5-5'
    assert config.price_for(sonnet)[2] == 0.10
    short = {'input_tokens': 100_000, 'output_tokens': 1000}
    assert config.cost_of(short, haiku) == pytest.approx(0.0105)
    long_prompt = {'input_tokens': 1, 'cache_read_input_tokens': 100_000, 'output_tokens': 1000}
    assert config.cost_of(long_prompt, haiku) == pytest.approx((0.0000001 + 0.001 + 0.0005) * 5)
    assert config.cost_of({'server_tool_use': {'web_search_requests': 3}}, sonnet) == pytest.approx(0.03)


def test_compaction_totals_keep_what_one_hour_writes_cost() -> None:
    from pycoder import config
    from pycoder.agent import compaction

    usage = {
        'iterations': [
            {
                'cache_creation_input_tokens': 1_000_000,
                'cache_creation': {'ephemeral_1h_input_tokens': 1_000_000},
            }
        ]
    }
    assert config.cost_of(compaction.total_usage(usage), 'claude-opus-5-5') == pytest.approx(8.0)

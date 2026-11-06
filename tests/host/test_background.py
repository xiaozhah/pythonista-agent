"""The work held on while the phone is locked: one task, from the first holder to the last."""

from __future__ import annotations

import threading
import time
import types

import pytest

from pycoder.host import background, env
from pycoder.tools.describe import doing


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    log: list[str] = []
    state = types.SimpleNamespace(lock=threading.Lock(), holders=0, said='', task=None)
    monkeypatch.setattr(background, '_shared', lambda: state)
    monkeypatch.setattr(background, '_begin', lambda: log.append(f'begin {state.said}'))
    monkeypatch.setattr(background, '_end', lambda: log.append('end'))
    monkeypatch.setattr(background, 'LINGER', 0.05)
    return log


def test_one_task_from_the_first_holder_to_the_last(calls: list[str]) -> None:
    background.hold(True, 'the turn')
    background.hold(True, 'a job')
    background.hold(False)
    assert calls == ['begin the turn']
    background.hold(False)
    time.sleep(0.15)
    assert calls == ['begin the turn', 'end']


def test_a_second_holder_changes_what_the_card_says(calls: list[str]) -> None:
    background.hold(True, 'the turn')
    background.hold(True, 'a job')
    assert background._shared().said == 'a job'


def test_work_that_follows_at_once_goes_on_under_the_same_task(calls: list[str]) -> None:
    background.hold(True, 'a turn')
    background._shared().task = object()  # iOS has started it
    background.hold(False)
    background.hold(True, 'the next message')
    time.sleep(0.15)
    assert calls == ['begin a turn']  # no new one, and that one hasn't ended
    background.hold(False)
    time.sleep(0.15)
    assert calls == ['begin a turn', 'end']


def test_a_late_wake_up_ends_what_it_was_started_for(
    monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    background._end_soon()
    others: list[str] = []
    monkeypatch.setattr(background, '_end', lambda: others.append('end'))
    time.sleep(0.15)
    assert calls == ['end']
    assert others == []


def test_a_failure_does_not_stop_the_work(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    def fails() -> None:
        raise RuntimeError

    monkeypatch.setattr(background, '_begin', fails)
    monkeypatch.setattr(background, '_note', lambda text: None)  # not in the device's real record
    background.hold(True, 'the turn')


def test_the_ring_fills_but_never_finishes() -> None:
    assert background.units(0)[0] == 0
    done, total = background.units(background.HALF_AT)
    assert done / total == 0.5
    done, total = background.units(360000)
    assert done < total
    assert background.units(360003)[0] > done


def test_nothing_happens_where_it_is_not_there(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, 'IN_PYTHONISTA', False)
    assert background.available() is False


def test_the_card_shows_the_step_under_way_or_the_tool() -> None:
    todos = [
        {'content': 'Write the sieve', 'status': 'in_progress'},
        {'content': 'Test', 'status': 'pending'},
    ]
    assert doing('todo_write', {'todos': todos}) == 'Write the sieve'
    assert doing('todo_write', {'todos': []}) == ''
    assert doing('todo_update', {'step': 1, 'status': 'completed'}) == ''
    assert doing('write_file', {'path': 'a.py'}) == 'write file: a.py'


def test_a_plan_with_nothing_under_way_leaves_the_card_as_it_is(calls: list[str]) -> None:
    background.hold(True, 'the turn')
    background.say('')
    assert background._shared().said == 'the turn'


def test_a_failure_is_noted_and_does_not_stop_the_work(monkeypatch: pytest.MonkeyPatch) -> None:
    notes: list[str] = []
    monkeypatch.setattr(background, '_note', notes.append)

    def fails() -> None:
        raise TypeError('cannot convert parameter to block')

    background._safely(fails)
    assert notes == ['TypeError: cannot convert parameter to block']

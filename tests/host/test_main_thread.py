"""Calls onto the main thread wait in a queue, and none is lost."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from pycoder.host import main_thread


@pytest.fixture
def main(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A thread standing in for the main one: each perform runs the next call there."""
    shared = main_thread._shared
    seen: list[str] = []

    def perform() -> None:
        def go() -> None:
            seen.append(threading.current_thread().name)
            main_thread.run_next()

        threading.Thread(target=go, name='main').start()

    monkeypatch.setattr(shared, 'perform', perform)
    monkeypatch.setattr(shared, 'is_main', lambda: False)
    return seen


def test_the_result_comes_back_from_the_main_thread(main: Any) -> None:
    where = main_thread.on_main_thread(lambda x: (x, threading.current_thread().name))
    assert where(5) == (5, 'main')


def test_many_threads_lose_nothing(main: Any) -> None:
    double = main_thread.on_main_thread(lambda x: x * 2)
    results: list[int] = []

    def caller(start: int) -> None:
        results.extend(double(start + i) for i in range(50))

    threads = [threading.Thread(target=caller, args=(n * 100,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == sorted(2 * (n * 100 + i) for n in range(8) for i in range(50))


def test_on_the_main_thread_it_just_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_thread._shared, 'perform', lambda: None)
    monkeypatch.setattr(main_thread._shared, 'is_main', lambda: True)
    assert main_thread.on_main_thread(lambda: 7)() == 7


def test_a_failure_is_printed_and_gives_none(main: Any, capsys: Any) -> None:
    def fails() -> None:
        raise ValueError('boom')

    assert main_thread.on_main_thread(fails)() is None
    assert 'boom' in capsys.readouterr().err


def test_only_callables() -> None:
    with pytest.raises(TypeError):
        main_thread.on_main_thread(3)  # type: ignore[arg-type]


def test_delay_calls_later_on_the_main_thread_and_can_be_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    called = threading.Event()
    on_main: list[object] = []

    def direct(func: Any) -> Any:
        on_main.append(func)
        return func

    monkeypatch.setattr(main_thread, 'on_main_thread', direct)
    main_thread.delay(called.set, 0.01)
    assert called.wait(2)
    assert on_main == [called.set]

    never = threading.Event()
    main_thread.delay(never.set, 0.05)
    main_thread.cancel_delays()
    assert not never.wait(0.15)

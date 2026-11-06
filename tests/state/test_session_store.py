"""Saving sessions: the index /resume lists them from, and what is saved."""

from __future__ import annotations

import json
import os
from typing import Any

from pycoder.state.session import INDEX, Session, SessionStore, Turn


def saved(store: SessionStore, title: str) -> Session:
    s = Session.new('/somewhere', 'm', 'system', False)
    s.title = title
    s.messages = [{'role': 'user', 'content': 'hi'}]
    s.turns = [Turn(1, 'hi', 0, 1.0)]
    store.save(s)
    return s


def test_listing_reads_only_sessions_that_changed(tmp_path: Any) -> None:
    store = SessionStore(str(tmp_path))
    a, b = saved(store, 'a'), saved(store, 'b')
    assert {i.title for i in store.list()} == {'a', 'b'}
    # a file the index knows (same time and size) isn't read again: garbage of the same size passes
    path = store.path(a.id)
    st = os.stat(path)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('x' * st.st_size)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert {i.title for i in SessionStore(str(tmp_path)).list()} == {'a', 'b'}
    # a changed file is read again; one that is gone leaves the index
    b.title = 'b2'
    with open(store.path(b.id), 'w', encoding='utf-8') as f:
        json.dump(b.to_json(), f)
    os.remove(path)
    assert [i.title for i in store.list()] == ['b2']
    with open(tmp_path / INDEX, encoding='utf-8') as f:
        assert list(json.load(f)) == [b.id + '.json']


def test_a_damaged_index_is_rebuilt(tmp_path: Any) -> None:
    store = SessionStore(str(tmp_path))
    saved(store, 'a')
    (tmp_path / INDEX).write_text('{"x.json": [1, 2, {"id": 3}]', encoding='utf-8')
    assert [i.title for i in SessionStore(str(tmp_path)).list()] == ['a']


def test_snapshots_of_summarized_turns_are_not_saved(tmp_path: Any) -> None:
    s = Session.new('/somewhere', 'm', 'system', False)
    s.checkpoints = {'1': {'a.py': 'old'}, '2': {'a.py': 'older'}, '3': {'b.py': None}}
    s.compacted_through = 2
    assert list(s.to_json()['checkpoints']) == ['3']
    assert s.next_turn_number() == 4

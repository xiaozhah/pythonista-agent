"""A subagent's own copy of the workspace, and bringing its changes back."""

from __future__ import annotations

import os
from typing import Any

from pycoder.state.worktree import Worktree, merge3


def test_merge3_takes_both_sides_unless_they_touch_the_same_lines() -> None:
    base = 'a\nb\nc\nd\n'
    assert merge3(base, 'A\nb\nc\nd\n', 'a\nb\nc\nD\n') == 'A\nb\nc\nD\n'
    assert merge3(base, 'A\nb\nc\nd\n', 'A\nb\nc\nd\n') == 'A\nb\nc\nd\n'
    assert merge3(base, 'x\nb\nc\nd\n', 'y\nb\nc\nd\n') is None
    assert merge3(base, 'a\nnew\nb\nc\nd\n', 'a\nb\nc\nd\nend\n') == 'a\nnew\nb\nc\nd\nend\n'


def _tree(tmp_path: Any) -> tuple[Any, Worktree]:
    root = tmp_path / 'project'
    (root / 'pkg').mkdir(parents=True)
    (root / 'pkg' / 'a.py').write_text('one\ntwo\nthree\n', encoding='utf-8')
    (root / 'b.py').write_text('b\n', encoding='utf-8')
    (root / '.git').mkdir()
    (root / '.git' / 'config').write_text('x', encoding='utf-8')
    tree = Worktree(str(root), str(tmp_path / 'tree'))
    tree.create()
    return root, tree


def test_the_copy_leaves_the_workspace_alone_until_it_is_merged(tmp_path: Any) -> None:
    root, tree = _tree(tmp_path)
    assert not os.path.exists(os.path.join(tree.work, '.git'))
    with open(os.path.join(tree.work, 'b.py'), 'w', encoding='utf-8') as f:
        f.write('changed\n')
    os.remove(os.path.join(tree.work, 'pkg', 'a.py'))
    with open(os.path.join(tree.work, 'new.py'), 'w', encoding='utf-8') as f:
        f.write('new\n')
    assert (root / 'b.py').read_text(encoding='utf-8') == 'b\n'
    assert tree.changed() == ['b.py', 'new.py', 'pkg/a.py']
    before: list[tuple[str, bool]] = []
    merged = tree.merge(lambda full, removing: before.append((os.path.basename(full), removing)))
    assert merged.applied == ['b.py', 'new.py', 'pkg/a.py']
    assert (root / 'b.py').read_text(encoding='utf-8') == 'changed\n'
    assert (root / 'new.py').read_text(encoding='utf-8') == 'new\n'
    assert not (root / 'pkg' / 'a.py').exists()
    assert ('a.py', True) in before  # the checkpoints hear of each first, so /rewind undoes it


def test_changes_on_both_sides_merge_or_are_reported(tmp_path: Any) -> None:
    root, tree = _tree(tmp_path)
    (root / 'pkg' / 'a.py').write_text('ONE\ntwo\nthree\n', encoding='utf-8')
    (root / 'b.py').write_text('here\n', encoding='utf-8')
    with open(os.path.join(tree.work, 'pkg', 'a.py'), 'w', encoding='utf-8') as f:
        f.write('one\ntwo\nTHREE\n')
    with open(os.path.join(tree.work, 'b.py'), 'w', encoding='utf-8') as f:
        f.write('there\n')
    merged = tree.merge(lambda full, removing: None)
    assert merged.applied == ['pkg/a.py']
    assert (root / 'pkg' / 'a.py').read_text(encoding='utf-8') == 'ONE\ntwo\nTHREE\n'
    assert merged.conflicts == ['b.py']
    assert (root / 'b.py').read_text(encoding='utf-8') == 'here\n'


def test_what_a_rule_protects_stays_out(tmp_path: Any) -> None:
    root, tree = _tree(tmp_path)
    with open(os.path.join(tree.work, 'b.py'), 'w', encoding='utf-8') as f:
        f.write('changed\n')
    merged = tree.merge(lambda full, removing: None, allowed=lambda rel: False)
    assert merged.refused == ['b.py']
    assert (root / 'b.py').read_text(encoding='utf-8') == 'b\n'
    fresh = Worktree(str(root), str(tmp_path / 'tree2'))
    fresh.create(leave_out=lambda rel: rel == 'b.py')
    assert not os.path.exists(os.path.join(fresh.work, 'b.py'))

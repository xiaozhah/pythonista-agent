"""pythonista_docs: pages, sections and search in the documentation Pythonista ships."""

from __future__ import annotations

import zipfile
from typing import Any

import pytest

from pycoder.host import env
from pycoder.tools import docs, registry
from pycoder.tools.base import ToolError

UI = """ui — Native GUI for iOS
=======================

.. module:: ui

Overview
--------

Build user interfaces.

.. class:: View([frame=(0, 0, 100, 100)])

    The base class.

    .. method:: View.present(style='default')

        Present the view on screen.

.. class:: TableView()

    A table view displays a list of items.

    .. attribute:: TableView.data_source

        The table's data source.

Functions
---------

.. function:: in_background(fn)

    Run fn on a background thread.
"""


@pytest.fixture
def archive(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    path = str(tmp_path / 'Documentation.zip')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('py3/_sources/ios/ui.rst.txt', UI)
        z.writestr('py3/_sources/library/json.rst.txt', 'json — JSON encoder and decoder\n')
        z.writestr('py3/ios/ui.html', '<html></html>')
    monkeypatch.setattr(env, 'docs_archive', lambda: path)
    docs._archive.cache_clear()
    return path


def run(**kwargs: str) -> str:
    return docs.pythonista_docs(None, **kwargs)  # type: ignore[arg-type]


def test_lists_and_reads_pages(archive: str) -> None:
    assert 'iOS module pages: ui' in run()
    assert run(page='ui').startswith('ui — Native GUI for iOS')
    assert run(page='json').startswith('json')  # library/json found by its short name
    with pytest.raises(ToolError, match='did you mean ui'):
        run(page='u')


def test_one_section_with_what_is_nested_in_it(archive: str) -> None:
    table = run(page='ui', section_name='TableView')
    assert table.startswith('.. class:: TableView()')
    assert 'TableView.data_source' in table
    assert 'in_background' not in table  # stops at the next heading
    view = run(page='ui', section_name='ui.View')
    assert 'View.present' in view
    assert 'TableView' not in view
    assert 'background thread' in run(page='ui', section_name='in_background')


def test_search(archive: str) -> None:
    assert run(query='background thread') == 'ui:32: Run fn on a background thread.'
    assert 'Nothing found' in run(query='nonsense')


def test_offered_only_where_the_docs_exist(archive: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert 'pythonista_docs' in [t.name for t in registry.main_tools()]
    assert 'pythonista_docs' in [t.name for t in registry.subagent_tools()]
    monkeypatch.setattr(env, 'docs_archive', lambda: None)
    assert 'pythonista_docs' not in [t.name for t in registry.main_tools()]


def test_a_section_without_a_page_is_found_on_any_ios_page(archive: str) -> None:
    assert run(section_name='TableView').startswith('From page ui:\n.. class:: TableView()')
    assert 'View.present' in run(section_name='ui.View')
    with pytest.raises(ToolError, match='search for it with query'):
        run(section_name='Nonsense')


def test_a_missing_section_lists_what_the_page_has(archive: str) -> None:
    with pytest.raises(ToolError, match='classes and functions: View, TableView, in_background'):
        run(page='ui', section_name='Nonsense')


def test_the_description_names_the_module_pages() -> None:
    assert 'objc_util' in docs.TOOLS[0].description


def test_a_titled_section_with_its_subsections(archive: str) -> None:
    overview = run(page='ui', section_name='overview')
    assert overview.startswith('Overview\n--------')
    assert 'Build user interfaces.' in overview
    assert 'Functions' not in overview  # the next heading of the same level ends it
    with pytest.raises(ToolError, match='its sections: ui — Native GUI for iOS, Overview, Functions'):
        run(page='ui', section_name='Nothing Like It')


def test_search_finds_lines_with_the_most_of_the_words(archive: str) -> None:
    out = run(query='present data_source')  # on different lines
    assert out.startswith("(no line has all of 'present data_source'; these have 1 of the words)")
    assert 'View.present' in out
    assert 'TableView.data_source' in out


def test_what_has_no_section_is_found_by_the_lines_that_mention_it(monkeypatch: pytest.MonkeyPatch) -> None:
    text = 'ui\n==\n\n.. class:: View\n\n   Override layout to place subviews.\n'
    assert 'mention' in docs.section(text, 'View.layout')
    assert 'Override layout' in docs.section(text, 'View.layout')

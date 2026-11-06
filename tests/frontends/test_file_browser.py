"""The files pane's pages: folders, code, and what this session changed."""

from __future__ import annotations

import os
import re
import time
from typing import Any

import pytest

from pycoder.frontends.chat import file_browser
from pycoder.frontends.chat.file_browser import FileBrowser
from pycoder.host import env
from tests.conftest import FakeTransport, text_reply, tool_reply


@pytest.fixture
def browser(make_controller: Any) -> FileBrowser:
    return FileBrowser(make_controller(FakeTransport()))


def write(browser: FileBrowser, rel: str, content: str | bytes) -> str:
    full = os.path.join(browser.controller.workspace.root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'wb') as f:
        f.write(content.encode() if isinstance(content, str) else content)
    return full


def tap(browser: FileBrowser, name: str) -> str:
    """Tap the row or crumb called `name` on the page, and return the page that comes up."""
    page = browser.page_html()
    for part in page.split("act('go:")[1:]:
        if f'>{name}<' in part:
            assert browser.act('go:' + part.split("'")[0])
            return browser.page_html()
    raise AssertionError(f'{name} is not on the page: {page}')


def test_a_folder_lists_folders_first_and_leaves_out_what_list_files_does(browser: FileBrowser) -> None:
    write(browser, 'b.py', 'x = 1\n')
    write(browser, 'a/inner.py', 'y = 2\n')
    write(browser, '.hidden', 'secret\n')
    write(browser, '__pycache__/c.pyc', 'z')
    page = browser.page_html()
    assert page.index('>a<') < page.index('>b.py<')
    assert '.hidden' not in page
    assert '__pycache__' not in page


def test_going_into_a_folder_and_back(browser: FileBrowser) -> None:
    write(browser, 'a/inner.py', 'y = 2\n')
    root = os.path.basename(browser.controller.workspace.root)
    assert '>inner.py<' in tap(browser, 'a')
    assert '>a<' in tap(browser, root)


def test_a_file_shows_coloured_code_with_line_numbers(browser: FileBrowser) -> None:
    write(browser, 'b.py', 'def f():\n    return "<x>"\n')
    page = tap(browser, 'b.py')
    assert 'class="codehilite"' in page
    assert 'linenos' in page
    assert '2 lines' in page
    assert '&lt;' in page  # as text, not as markup
    assert 'Changes' not in page  # this session hasn't touched it


def test_a_file_of_an_unknown_kind_is_plain_text(browser: FileBrowser) -> None:
    write(browser, 'notes.zzz', 'hello\n')
    assert 'hello' in tap(browser, 'notes.zzz')


def test_what_is_not_text_offers_the_preview(browser: FileBrowser) -> None:
    full = write(browser, 'p.png', b'\x89PNG\0\0\xff')
    page = tap(browser, 'p.png')
    assert "act('preview')" in page
    assert browser.preview_path() == full


def read_all(browser: FileBrowser, page: str) -> str:
    """Scroll to the end of the page."""
    while browser.left:
        page += browser.more() or ''
    return page


def test_a_big_file_can_be_read_to_its_end_a_block_at_a_time(
    browser: FileBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(file_browser, 'BLOCK', 1000)
    lines = [f'line_{i}_中文' for i in range(2000)]
    write(browser, 'big.txt', '\n'.join(lines) + '\nlast_line\n')
    page = tap(browser, 'big.txt')
    assert 'id="more"' in page  # it isn't all there yet
    assert 'last_line' not in page
    whole = read_all(browser, page)
    assert 'last_line' in whole
    assert all(line in whole for line in lines)
    assert '2001 lines' in browser.page_html()
    assert 'id="more"' not in browser.page_html()
    assert re.search(r'linenos">\s*2001<', whole)  # the numbers go on across blocks


def test_one_long_line_is_not_cut_inside_a_character(
    browser: FileBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(file_browser, 'BLOCK', 1000)
    write(browser, 'wide.txt', '中' * 2000)
    whole = read_all(browser, tap(browser, 'wide.txt'))
    assert whole.count('中') == 2000
    assert '\ufffd' not in whole


def test_a_folder_can_be_read_to_its_end(browser: FileBrowser, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_browser, 'ROWS', 3)
    browser.rows = 3
    for i in range(7):
        write(browser, f'many/f{i}.py', '')
    page = tap(browser, 'many')
    assert 'id="more"' in page
    assert '>f0.py<' in page
    assert '>f6.py<' not in page
    while 'id="more"' in page:
        assert browser.more() is None  # the whole page is drawn again
        page = browser.page_html()
    assert '>f6.py<' in page


def wait_for_comparison(browser: FileBrowser) -> str:
    for _ in range(100):
        page = browser.page_html()
        if 'Comparing' not in page:
            return page
        time.sleep(0.05)
    raise AssertionError('still comparing')


def changed_by_the_agent(make_controller: Any, path: str, before: str, after: str) -> FileBrowser:
    api = FakeTransport([tool_reply('write_file', {'path': path, 'content': after}), text_reply('done')])
    c = make_controller(api)
    c.settings.mode = 'bypass'
    browser = FileBrowser(c)
    write(browser, path, before)
    c.run_turn('change it')
    return browser


def test_all_of_a_long_comparison_can_be_read(make_controller: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_browser, 'DIFF_ROWS', 50)
    before = ''.join(f'old_{i}\n' for i in range(300))
    after = ''.join(f'new_{i}\n' for i in range(300))
    browser = changed_by_the_agent(make_controller, 'a.py', before, after)
    browser.file, browser.showing = 'a.py', 'changes'
    page = wait_for_comparison(browser)
    assert 'id="more"' in page
    whole = read_all(browser, page)
    assert 'old_299' in whole
    assert 'new_299' in whole
    assert 'more lines' not in whole


def test_a_comparison_that_would_use_too_much_memory_says_so(
    make_controller: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = changed_by_the_agent(make_controller, 'a.py', 'before\n', 'after\n')
    monkeypatch.setattr(env, 'available_memory', lambda: 1)
    browser.file, browser.showing = 'a.py', 'changes'
    assert 'enough memory' in wait_for_comparison(browser)


def test_a_new_version_keeps_as_much_of_the_file_as_was_read(
    browser: FileBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(file_browser, 'BLOCK', 100)
    full = write(browser, 'big.txt', ''.join(f'line_{i}\n' for i in range(300)))
    tap(browser, 'big.txt')
    browser.more()
    browser.more()
    assert 'line_30' in browser.page_html()
    with open(full, 'a', encoding='utf-8') as f:
        f.write('added\n')
    assert 'line_30' in browser.page_html()


def test_a_file_that_goes_away_goes_back_to_its_folder(browser: FileBrowser) -> None:
    full = write(browser, 'a/inner.py', 'y = 2\n')
    write(browser, 'a/other.py', 'z = 3\n')
    tap(browser, 'a')
    tap(browser, 'inner.py')
    os.remove(full)
    page = browser.page_html()
    assert '>other.py<' in page
    assert 'linenos' not in page


def test_a_new_page_is_drawn_when_the_file_changes(browser: FileBrowser) -> None:
    full = write(browser, 'b.py', 'first = 1\n')
    assert 'first' in tap(browser, 'b.py')
    with open(full, 'w', encoding='utf-8') as f:
        f.write('second_name = 1\n')
    assert 'second_name' in browser.page_html()


def test_what_the_session_changed_shows_on_top_and_opens_on_its_changes(make_controller: Any) -> None:
    api = FakeTransport(
        [
            tool_reply('write_file', {'path': 'made.py', 'content': 'new = 1\n'}),
            tool_reply('write_file', {'path': 'kept.py', 'content': 'after = 2\n'}),
            text_reply('done'),
        ]
    )
    c = make_controller(api)
    c.settings.mode = 'bypass'
    browser = FileBrowser(c)
    write(browser, 'kept.py', 'before = 1\n')
    c.run_turn('change things')
    page = browser.page_html()
    assert 'Changed in this session' in page
    assert 'class="how new"' in page
    assert 'class="how changed"' in page
    changes = page[: page.index('class="crumbs"')]
    target = re.search(r"act\('(go:\d+)'\)\"><span class=\"icon\">.*?kept\.py", changes, re.S)
    assert target
    browser.act(re.findall(r'go:\d+', target.group(0))[-1])
    page = wait_for_comparison(browser)
    assert 'class="diff"' in page
    assert 'class="del"' in page
    assert 'before = 1' in page
    assert 'after = 2' in page
    browser.act('show:code')
    page = browser.page_html()
    assert 'linenos' in page
    assert 'before' not in page


def test_a_deleted_file_can_still_be_seen_as_a_change(make_controller: Any) -> None:
    c = make_controller(FakeTransport([tool_reply('delete_file', {'path': 'old.py'}), text_reply('done')]))
    c.settings.mode = 'bypass'
    browser = FileBrowser(c)
    write(browser, 'old.py', 'gone = 1\n')
    c.run_turn('delete it')
    page = browser.page_html()
    assert 'class="how deleted"' in page
    browser.act(re.findall(r'go:\d+', page[: page.index('class="crumbs"')])[0])
    page = wait_for_comparison(browser)
    assert 'class="del"' in page
    assert 'gone = 1' in page
    assert 'show:code' not in page

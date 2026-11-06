"""Markdown in the console and HTML for the chat screen."""

from __future__ import annotations

from typing import Any


def test_console_markdown_renders_styles(capsys: Any) -> None:
    from pycoder.frontends.console.markdown import MarkdownStream

    stream = MarkdownStream()
    for chunk in ['## Ti', 'tle\n- **bo', 'ld** `co', 'de`\n```py\nx = 1\n```\ndone']:
        stream.feed(chunk)
    stream.finish()
    plain = capsys.readouterr().out
    for code in ('\033[1m', '\033[35m', '\033[38;5;208m', '\033[36m', '\033[90m', '\033[0m'):
        plain = plain.replace(code, '')
    assert plain == 'Title\n• bold code\nx = 1\ndone'


def test_app_render_helpers() -> None:
    from pycoder.frontends.chat import render
    from pycoder.frontends.chat.frontend import history_html

    assert '<strong>hi</strong>' in render.md_to_html('**hi**')
    assert 'codehilite' in render.md_to_html('```python\nx = 1')  # unclosed fence still renders as code
    assert '<span class="add">+b</span>' in render.diff_html('a\n', 'b\n', 'f.py')
    html = history_html(
        't',
        [
            {'role': 'user', 'content': [{'type': 'text', 'text': 'hello'}]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': '**yo**'}]},
        ],
    )
    assert 'hello' in html
    assert '<strong>yo</strong>' in html


def test_a_saved_reply_with_tool_calls_is_one_row_with_folded_output() -> None:
    from pycoder.frontends.chat.frontend import history_html

    call = {'type': 'tool_use', 'id': 't1', 'name': 'run_python', 'input': {'path': 'a.py'}}
    result = {'type': 'tool_result', 'tool_use_id': 't1', 'content': '42'}
    html = history_html(
        't',
        [
            {'role': 'user', 'content': 'run it'},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Running.'}, call]},
            {'role': 'user', 'content': [result]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': 'It printed 42.'}]},
        ],
    )
    assert html.count('class="row c"') == 1
    assert '<summary>output · 1 line</summary><pre class="out">42</pre>' in html


def test_github_style_markdown_renders() -> None:
    """Claude writes GitHub-style Markdown; Python-Markdown needs blank lines and 4-space nesting."""
    from pycoder.frontends.chat.render import md_to_html

    def html(text: str) -> str:
        return md_to_html(text).replace('\n', '')

    assert html('比如：\n- 看看文件\n- 写脚本') == '<p>比如：</p><ul><li>看看文件</li><li>写脚本</li></ul>'
    assert '<ol><li>one</li><li>two</li></ol>' in html('Steps:\n1. one\n2. two')
    assert (
        html('- a\n  - b\n    - c\n- d')
        == '<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li><li>d</li></ul>'
    )
    assert '<ol><li>one<ul><li>sub</li></ul></li><li>two</li></ol>' in html('1. one\n   - sub\n2. two')
    assert '<table>' in html('Here:\n| a | b |\n|---|---|\n| 1 | 2 |')
    assert html('line one\nline two') == '<p>line one<br />line two</p>'
    assert '<li>' not in html('Run:\n```\n- not a list\n```')
    assert html('- a\n- b\n\nafter') == '<ul><li>a</li><li>b</li></ul><p>after</p>'


def test_console_confirmation_needs_a_typed_yes(monkeypatch: Any) -> None:
    from pycoder.frontends.console import frontend

    answers: list[str] = []
    monkeypatch.setattr(frontend, 'ask', lambda prompt: answers.pop(0) if answers else '')
    console = frontend.ConsoleFrontend()
    for typed, expected in (('', 'no'), ('y', 'yes'), ('a', 'always'), ('x', 'no')):
        answers[:] = [typed]
        assert console.confirm('write_file', {'path': 'a'}, None, 'write_file(a)')[0] == expected, typed
    answers[:] = ['']
    assert console.approve_plan('1. do it')[0] == 'keep'


def test_the_session_pane_shows_context_tasks_and_outputs() -> None:
    from pycoder.app.reports import Category, ContextUsage
    from pycoder.frontends.chat import render

    usage = ContextUsage(
        'claude-haiku-5-5',
        200_000,
        (Category('Messages', 98_000, '#123456', 'x'), Category('Free space', 102_000, '', '.')),
        98_000,
        0,
    )
    html = render.session_html(
        usage,
        [('review <a>', 'read_file(a.py)', 75)],
        [(3, 'train.py', '12s', True, 'epoch <1>')],
        [('chart.png', 'out', 2048)],
        '<svg></svg>',
    )
    assert '<b>49%</b>' in html
    assert 'review &lt;a&gt;' in html
    assert '1m 15s' in html
    assert "act('stop:3')" in html
    assert 'epoch &lt;1&gt;' in html
    assert "act('open:0')" in html
    assert 'out · 2 KB' in html
    idle = render.session_html(usage, [], [(3, 'train.py', 'finished', False, '')], [], '')
    assert 'stop:3' not in idle
    assert 'No files made' in idle


def test_a_thoughts_line_is_its_last_finished_sentence() -> None:
    from pycoder.frontends.chat import render

    assert render.thought_line('') == ''
    assert render.thought_line('Reading the') == 'Reading the'
    assert render.thought_line('**Weighing it**\n\nThe first') == 'Weighing it'
    assert render.thought_line('One. Two! Three') == 'Two!'
    assert render.thought_line('梳理进展。然后计算') == '梳理进展。'
    assert render.thought_line('Done.\n\n') == 'Done.'

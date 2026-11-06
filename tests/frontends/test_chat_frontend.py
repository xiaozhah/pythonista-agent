"""The chat frontend's traffic with the page: streaming, thinking, cards waiting for a tap, resume."""

from __future__ import annotations

import json
import time
from typing import Any

from pycoder.cancel import CancelToken
from pycoder.frontends.chat import frontend as chat
from pycoder.frontends.chat import render


class FakePage:
    def __init__(self, answers: list[str] | None = None) -> None:
        self.calls: list[str] = []
        self.answers = answers or []

    def eval_js(self, code: str) -> str:
        self.calls.append(code)
        if code.startswith('takeAnswer(') and self.answers:
            return self.answers.pop(0)
        return ''

    def named(self, fn: str) -> list[list[Any]]:
        """The arguments of each call of fn (calls joined with ; are split)."""
        out = []
        for code in self.calls:
            for part in _split(code):
                if part.startswith(fn + '('):
                    out.append(json.loads('[' + part[len(fn) + 1 : -1] + ']'))
        return out


def _split(code: str) -> list[str]:
    """Calls joined by AppFrontend.run, split again (arguments are JSON, so ; can be inside them)."""
    parts: list[str] = []
    depth, start, quoted, escaped = 0, 0, False, False
    for i, ch in enumerate(code):
        if quoted:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ';' and depth == 0:
            parts.append(code[start:i])
            start = i + 1
    return [*parts, code[start:]]


def frontend(page: FakePage) -> chat.AppFrontend:
    return chat.AppFrontend(page, CancelToken(), lambda *a: None, lambda *a: None, lambda: None)


REPLY = (
    'Here is the plan:\n- read the file\n- fix it\n\n'
    '```python\ndef f(x):\n\n    return x\n```\n\n'
    'Then **run** it.\n\n1. one\n\n2. two\n\n'
    '| a | b |\n|---|---|\n| 1 | 2 |\n\nDone.\n'
)


def test_settled_cuts_only_between_blocks_that_cant_continue() -> None:
    cut = render.settled(REPLY)
    assert REPLY[cut:] == 'Done.\n'
    # not inside the code block (its blank line), not before a list item or a table row
    ends = [i + 1 for i, ch in enumerate(REPLY) if ch == '\n']
    cuts = sorted({render.settled(REPLY[:end]) for end in ends} - {0})
    assert [REPLY[c:].split('\n')[0] for c in cuts] == ['```python', 'Then **run** it.', 'Done.']
    assert render.settled('para\n\n    indented\n\nnext\n') == len('para\n\n    indented\n\n')
    assert render.settled('para\n\nnext line still com') == 0  # the line after must be whole


def test_streaming_renders_finished_blocks_once_and_ends_with_the_whole_text(monkeypatch: Any) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    page = FakePage()
    fe = frontend(page)
    for i in range(0, len(REPLY), 5):
        clock[0] += 1  # every chunk comes after the update interval
        fe.text_delta(0, REPLY[i : i + 5])
    fe.text_done(0)
    streamed = page.named('streamHtml')
    assert len(streamed) > 10
    done = ''.join(d for _, d, _ in streamed)
    # what was added for good is the start of the reply, each block once
    assert done.count('<li>read the file</li>') == 1
    assert done.count('def') == 1
    assert done.count('<table>') == 1  # once Done. came, nothing could add to it
    # rendered in parts, the reply looks as it does rendered at once
    assert (done + streamed[-1][2]).replace('\n', '') == render.md_to_html(REPLY).replace('\n', '')
    element, html = page.named('setHtml')[-1]
    assert element == streamed[0][0]
    assert html == render.md_to_html(REPLY)


def test_streaming_waits_longer_when_rendering_is_slow(monkeypatch: Any) -> None:
    page = FakePage()
    fe = frontend(page)
    monkeypatch.setattr(render, 'md_to_html', lambda text: text)
    ticks = iter([0.0, 0.2] * 10)  # each render takes 0.2 s
    monkeypatch.setattr(time, 'perf_counter', lambda: next(ticks))
    fe.text_delta(0, 'a')
    assert fe.texts[0].every == 0.2 / chat.RENDER_SHARE


def test_thinking_is_shown_in_batches(monkeypatch: Any) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    page = FakePage()
    fe = frontend(page)
    for _ in range(100):
        clock[0] += 0.01
        fe.thinking_delta('hm ')
    fe.text_delta(0, 'ok')
    shown = page.named('appendText')
    assert ''.join(text for _, text in shown) == 'hm ' * 100
    assert len(shown) <= 10
    assert len(page.calls) <= 15


def test_thinking_is_one_folded_line_that_ends_with_how_long_it_took(monkeypatch: Any) -> None:
    clock = [1000.0]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    page = FakePage()
    fe = frontend(page)
    fe.request('go', turn=1)
    fe.thinking_start()
    row = next(c for c in page.named('add') if c[2] == 'thinking live')
    assert '<details>' in row[3]  # folded: the text is there for whoever opens it
    assert 'data-since="1000000"' in row[3]
    assert not page.named('appendText')
    clock[0] += 1
    fe.thinking_delta('Reading **the** code.\n\nNow the <tests>')
    assert page.named('setHtml')[-1] == [row[1] + 'l', 'Reading the code.']
    clock[0] += 1
    fe.thinking_delta(' next. And')
    assert page.named('setHtml')[-1] == [row[1] + 'l', 'Now the &lt;tests&gt; next.']
    clock[0] += 5
    fe.text_delta(0, 'ok')
    assert page.named('endThinking') == [[row[1], 'Thought for 7s']]
    fe.stream_end()
    assert len(page.named('endThinking')) == 1


def test_thinking_without_a_start_event_still_gets_its_row() -> None:
    page = FakePage()
    fe = frontend(page)
    fe.thinking_delta('hm')
    assert [c for c in page.named('add') if c[2] == 'thinking live']
    assert page.named('appendText')[-1][1] == 'hm'


def test_cards_ask_the_page_less_often_while_waiting(monkeypatch: Any) -> None:
    slept: list[float] = []
    monkeypatch.setattr(time, 'sleep', slept.append)
    page = FakePage([''] * 8 + ['yes'])
    fe = frontend(page)
    assert fe.confirm('write_file', {'path': 'a.py', 'content': ''})[0] == 'yes'
    assert slept[0] == chat.ANSWER_POLL[0]
    assert slept[-1] == chat.ANSWER_POLL[1]
    assert slept == sorted(slept)


def _conversation(requests: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for i in range(requests):
        result = {'type': 'tool_result', 'tool_use_id': f't{i}', 'content': f'out {i}'}
        messages += [
            {'role': 'user', 'content': f'request {i}'},
            {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': f't{i}', 'name': 'x', 'input': {}}]},
            {'role': 'user', 'content': [result]},
            {'role': 'assistant', 'content': [{'type': 'text', 'text': f'reply {i}'}]},
        ]
    return messages


def test_a_resumed_session_shows_its_latest_requests_first() -> None:
    page = FakePage()
    fe = frontend(page)
    messages = _conversation(chat.HISTORY_REQUESTS + 5)
    fe.session_loaded('t', messages)
    (shown,) = page.named('clearChat')[0]
    assert 'Show 5 earlier requests' in shown
    assert 'request 4<' not in shown
    assert 'request 5<' in shown
    assert 'out 5' in shown  # tool output stays with its call
    (earlier,) = page.named('setEarlier')[0]
    assert 'request 0<' in earlier
    assert 'request 4<' in earlier
    assert 'reply 4' in earlier
    assert 'request 5<' not in earlier
    # the two parts together are the whole conversation
    latest = shown.split('</a></span></div>', 1)[1]
    assert earlier + latest == chat.history_html('t', messages).split('</div>', 1)[1]

    page = FakePage()
    frontend(page).session_loaded('t', _conversation(3))
    assert 'earlier' not in page.named('clearChat')[0][0]
    assert not page.named('setEarlier')


def test_requests_and_replies_have_their_buttons_live_and_when_resumed() -> None:
    page = FakePage()
    fe = frontend(page)
    fe.request('hello', turn=3)
    fe.turn_done('m', {}, 0.0)
    live = ' '.join(page.calls)
    for action in ('rewind', 'copy-request', 'copy-reply', 'fork', 'pin'):
        assert f'pycoder://{action}/3' in live

    page = FakePage()
    messages = [{'role': 'user', 'content': 'hello'}, {'role': 'assistant', 'content': 'hi'}]
    frontend(page).session_loaded('t', messages, {0: 1.0}, {0: 3}, {3: 'The plan'})
    shown = ' '.join(page.calls)
    for expected in ('pycoder://rewind/3', 'pycoder://pin/3', 'req-3', 'The plan'):
        assert expected in shown


def test_a_request_that_cannot_be_rewound_has_no_buttons() -> None:
    page = FakePage()
    messages = [{'role': 'user', 'content': 'hello'}, {'role': 'assistant', 'content': 'hi'}]
    frontend(page).session_loaded('t', messages, {0: 1.0})
    assert 'pycoder://' not in ' '.join(page.calls)


def test_tool_calls_in_a_row_fold_into_one_line_that_counts_them() -> None:
    assert chat.tools_label(['run_python', 'run_python']) == 'Ran 2 commands'
    assert chat.tools_label(['read_file', 'write_file', 'read_file']) == 'Read 2 files, edited 1 file'
    assert chat.tools_label(['read_file'], 'a.py') == 'Read a file · a.py'
    assert chat.tools_label(['some_tool']) == 'Used some_tool'


def test_text_ends_a_run_of_tool_calls_live_and_when_resumed() -> None:
    page = FakePage()
    fe = frontend(page)
    block = {'type': 'tool_use', 'id': 'a', 'name': 'run_python', 'input': {}}
    fe.request('go', turn=1)
    fe.tool_start(0, block)
    fe.tool_start(1, dict(block, id='b'))
    assert len(page.named('closeDetails')) == 0
    fe.text_delta(2, 'done')
    assert len(page.named('closeDetails')) == 1
    labels = [c[1] for c in page.named('setHtml') if str(c[0]).endswith('-s')]
    assert labels[-1] == 'Ran 2 commands'

    page = FakePage()
    messages: list[dict[str, Any]] = [
        {'role': 'user', 'content': 'go'},
        {
            'role': 'assistant',
            'content': [
                {'type': 'tool_use', 'id': 'a', 'name': 'run_python', 'input': {}},
                {'type': 'tool_use', 'id': 'b', 'name': 'run_python', 'input': {}},
                {'type': 'text', 'text': 'done'},
            ],
        },
    ]
    frontend(page).session_loaded('t', messages)
    assert 'Ran 2 commands' in ' '.join(page.calls)


def test_a_message_waiting_for_its_turn_can_be_taken_back_or_sent_now() -> None:
    page = FakePage()
    fe = frontend(page)
    number = fe.queued('next')
    shown = ' '.join(page.calls)
    assert f'pycoder://queue-cancel/{number}' in shown
    assert f'pycoder://queue-now/{number}' in shown
    fe.unqueued(number)
    assert [call[0] for call in page.named('remove')] == [f'q{number}', f'qa{number}']

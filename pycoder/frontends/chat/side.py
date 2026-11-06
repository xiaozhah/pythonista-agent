"""The side chat (/btw): questions about the work, answered from the conversation without tools
and without adding to it. A pane of its own beside the chat on a wide screen, over it on a narrow
one, with its own input; follow-ups see the earlier side questions. It may run while a turn does."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable

from .. import keys, theme, widgets
from . import render
from .frontend import AVATAR_CLAUDE, js, user_bubble
from .pane import Pane

INTRO = (
    '<div class="welcome">Ask about the work while it runs. Answers come from the '
    'conversation, without tools, and are not added to it.</div>'
)


class SidePanel(Pane):
    def __init__(
        self, ask: Callable[[str], str], session: Callable[[], str], on_close: Callable[[], None], dark: bool
    ) -> None:
        super().__init__('Side chat', INTRO, on_close, dark)
        self.ask = ask  # question -> answer (the controller's side_question)
        self.session = session  # the id of the conversation the side chat is about
        self.shown_for = session()
        self.lock = threading.Lock()  # one question at a time, in the order they were asked
        self.waiting = 0  # questions not answered yet
        self.input = widgets.InputBox(lambda s: self.submit(), hint='Ask about the work')
        self.input.on_resize = self.layout
        self.field = self.input.field
        self.field.delegate = self
        self.add_subview(self.input)
        keys.intercept(self.field, self.on_field_key)
        self.style()

    def layout(self) -> None:
        w, h = self.width, self.height - self.inset
        bar = 8 + self.input.field_height + 8
        self.layout_head(bar)
        self.input.frame = (widgets.SIDE, h - bar + 8, w - 2 * widgets.SIDE, self.input.field_height)

    def style(self) -> None:
        super().style()
        self.input.style(theme.colors(self.dark))

    def opened(self) -> None:
        self.field.begin_editing()

    # ---- questions and answers

    def textview_did_change(self, textview: object) -> None:
        self.input.changed()

    def textview_should_change(self, textview: object, range: tuple[int, int], replacement: str) -> bool:
        if replacement == '\n' and not keys.newline_held():
            self.submit()
            return False
        return True

    def on_field_key(self, key: str, shift: bool) -> bool:
        if key == 'escape':
            self.on_close()
            return True
        return False

    def submit(self) -> None:
        text = self.field.text.strip()
        self.field.text = ''
        self.input.changed()
        if text:
            self.question(text)

    def question(self, text: str) -> None:
        """Show the question, then its answer when it comes (in a thread)."""
        self.follow_session()
        row = self.new_id('a')
        self.run(
            js('add', 'chat', self.new_id('q'), 'row me', user_bubble(text)),
            js(
                'add',
                'chat',
                row,
                'row c',
                f'<div class="avatar">{AVATAR_CLAUDE}</div><div class="col"></div>',
            ),
            js('toBottom'),
        )
        self.waiting += 1
        self.busy(True)

        def answer() -> None:
            with self.lock:
                try:
                    reply = self.ask(text)
                except Exception as e:
                    reply = f'✗ {type(e).__name__}: {e}'
            self.waiting -= 1
            self.answered(row, reply)

        threading.Thread(target=answer, daemon=True).start()

    def show(self, question: str, answer: str) -> None:
        """An exchange that happened elsewhere (/btw sent as a command)."""
        self.follow_session()
        row = self.new_id('a')
        self.run(
            js('add', 'chat', self.new_id('q'), 'row me', user_bubble(question)),
            js(
                'add',
                'chat',
                row,
                'row c',
                f'<div class="avatar">{AVATAR_CLAUDE}</div><div class="col"></div>',
            ),
        )
        self.answered(row, answer)

    def follow_session(self) -> None:
        """After /clear or /resume the side chat starts over, as the controller's does."""
        if self.session() != self.shown_for:
            self.shown_for = self.session()
            self.run(js('clearChat', INTRO))

    def answered(self, row: str, answer: str) -> None:
        html = (
            f'<div class="avatar">{AVATAR_CLAUDE}</div>'
            f'<div class="col"><div class="bubble text">{render.md_to_html(answer)}</div></div>'
        )
        self.run(js('setHtml', row, html), js('toBottom'))
        self.busy(self.waiting > 0)

    def busy(self, on: bool) -> None:
        self.run(f"document.documentElement.classList.toggle('busy', {json.dumps(on)})")

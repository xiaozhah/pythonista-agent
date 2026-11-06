"""The frontend interface: everything the core reports, and the few questions it asks.

The core never prints. It calls these methods on the active frontend; the console and the app
each implement the ones they display. Every method has a harmless default, so a frontend (or a
test) only overrides what it needs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from .types import Block, Todo, Usage

if TYPE_CHECKING:
    from .app.reports import ContextUsage
    from .state.settings import SettingSpec
    from .tools.base import FilePreview


class Frontend:
    # ---- a request going to Claude
    def request(
        self, text: str, images: Sequence[Block] = (), attached: Sequence[str] = (), turn: int = 0
    ) -> None:
        """Show the user's request (with the image blocks and which @files go with it) before the
        reply; called for every request, typed, queued or started by a command such as /plan."""

    # ---- a response streaming in
    def thinking_start(self) -> None:
        """A thinking block began; its text may take a while to arrive."""

    def thinking_delta(self, text: str) -> None: ...
    def text_delta(self, index: int, text: str) -> None: ...
    def text_done(self, index: int) -> None: ...
    def tool_start(self, index: int, block: Block) -> None:
        """A tool call began; its input is still streaming."""

    def tool_input(self, index: int, chunk: str) -> None:
        """More of that tool call's JSON input arrived."""

    def tool_input_done(self, index: int, block: Block) -> None:
        """The input is complete; block['input'] is the parsed dict."""

    def server_result(self, kind: str, count: int) -> None:
        """web_search / web_fetch results arrived."""

    def stream_start(self) -> None:
        """A response starts streaming (a retry starts another)."""

    def stream_discarded(self) -> None:
        """The response streamed so far failed and is retried: take its partial output away."""

    def stream_end(self) -> None: ...

    # ---- tools running
    def tool_run(self, block: Block) -> None:
        """This tool call is about to run; the result events below belong to it."""

    def tools_run(self, blocks: Sequence[Block]) -> None:
        """These calls are about to run at the same time (subagents); tool_done follows for each."""
        for block in blocks:
            self.tool_run(block)

    def tool_done(self, block: Block, result: str = '') -> None:
        """This tool call has finished, whether it printed anything or not; result is the text the
        model gets back."""

    def confirm(
        self, name: str, inp: Block, preview: FilePreview | None = None, rule: str = ''
    ) -> tuple[str, str | None]:
        """Ask before a write or a run: ('yes' | 'no' | 'always', optional note for Claude).

        preview, for file changes, is (path, current content or None, new content); rule is what
        'always' would allow from now on, e.g. git(status*).
        """
        return 'yes', None

    def approve_plan(self, plan: str) -> tuple[str, str | None]:
        """Show a plan: ('acceptEdits' | 'default' to go ahead in that mode, or 'keep' planning, note)."""
        return 'keep', None

    def file_written(self, path: str, old: str | None, new: str) -> None:
        """old is None for a new file."""

    def run_output(self, text: str) -> None: ...
    def tool_error(self, message: str, level: str = 'error') -> None:
        """level is 'error' or 'denied'."""

    def todos_updated(self, todos: Sequence[Todo]) -> None: ...
    def shell_output(self, command: str, output: str, ok: bool) -> None:
        """A `!` command ran in the built-in shell."""

    def show_files(self) -> None:
        """Open the files pane, where there is one."""

    def show_session(self) -> None:
        """/session: context, background tasks and the files made; a pane where there is room."""
        self.notice('The session pane is in the chat screen; /context and /status show the same here')

    def jobs_changed(self) -> None:
        """A background job started or ended (tools/jobs.py)."""

    # ---- subagents: `key` is the task call's tool_use id (several may run at once)
    def subagent_start(self, description: str, key: str = '') -> None: ...
    def subagent_progress(self, text: str, key: str = '') -> None: ...
    def subagent_done(self, summary: str, key: str = '') -> None: ...

    # ---- the session
    def notice(self, text: str, level: str = 'info') -> None:
        """level is 'info', 'warn' or 'error'."""

    def side_answer(self, question: str, answer: str) -> None:
        """The answer to a /btw question, shown aside: it isn't part of the conversation."""
        self.notice(f'btw: {question}\n\n{answer}')

    def turn_done(self, model: str, usage: Usage, cost: float, turn_cost: float = 0.0) -> None:
        """cost is the session's total so far; turn_cost what this request cost."""

    def compacting(self) -> None: ...
    def compacted(self, summary: str) -> None: ...
    def session_loaded(
        self,
        title: str,
        messages: Sequence[Block],
        times: Mapping[int, float] | None = None,
        turns: Mapping[int, int] | None = None,
        chapters: Mapping[int, str] | None = None,
    ) -> None:
        """A saved session was resumed (or rewound); messages are its conversation so far.

        times maps the index of a message that starts a request to when it was sent, turns to the
        number of that request, if it can be rewound or forked from; chapters maps request numbers
        to the titles of the chapters they start.
        """

    def add_to_input(self, text: str) -> None:
        """Add this to what the user is typing, to send with it."""
        self.notice(f'Put this in your next message: {text}')

    def chapter_changed(self, turn: int, title: str) -> None:
        """That request now starts a chapter with this title ('': no longer)."""

    def show_chapter(self, turn: int) -> None:
        """Bring the chapter that request starts into view."""

    def session_cleared(self) -> None: ...
    def settings_changed(self) -> None:
        """A setting changed (font size, theme, model, …); refresh whatever shows it."""

    def edit_settings(
        self,
        specs: Sequence[SettingSpec],
        current: dict[str, Any],
        tabs: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    ) -> dict[str, Any] | None:
        """Show a settings form, with read-only tabs (Status, Usage) of name/value rows beside it.

        Returns the edited values, or None if this frontend has no form.
        """
        return None

    def show_context(self, usage: ContextUsage, text: str) -> None:
        """/context: the grid of what fills the context window; text is a plain rendering."""
        self.notice(text)

    # ---- questions
    def choose(self, title: str, options: Sequence[str], current: int | None = None) -> int | None:
        """Pick one option; the index, or None if cancelled. current marks the option now in use.
        An option may be "label — what it means"; frontends can show the two parts apart."""
        return None

    def ask_text(self, title: str, message: str = '', secret: bool = False) -> str | None:
        """Free text from the user, or None if cancelled; secret hides what is typed (keys, tokens)."""
        return None

"""Render Markdown into the console while it streams in.

Handles headings, bold, inline code, code blocks, lists, quotes and rules. Characters at the start
of a line are held back until the line's kind is known; everything else prints immediately.
"""

from __future__ import annotations

import re

from .output import write

# style -> (color, bold)
STYLES: dict[str, tuple[str | None, bool]] = {
    'plain': (None, False),
    'bold': (None, True),
    'heading': ('magenta', True),
    'code': ('orange', False),
    'codeblock': ('cyan', False),
    'quote': ('dim', False),
    'marker': ('dim', False),
}
_PREFIX_CHARS = set(' \t#->*+`0123456789.')


class MarkdownStream:
    def __init__(self) -> None:
        self.in_fence = False
        self.segment_style: str | None = None
        self.segment = ''
        self._new_line()

    def feed(self, text: str) -> None:
        for ch in text:
            self._char(ch)
        self._flush_segment()

    def finish(self) -> None:
        if self.at_line_start and self.line_buf:
            self._classify(complete=True)
        self._flush_star()
        self._flush_segment()

    # ---- line state

    def _new_line(self) -> None:
        self.at_line_start = True
        self.line_buf = ''
        self.line_style: str | None = None  # 'heading', 'quote' or 'fence'
        self.bold = False
        self.code = False
        self.pending_star = False

    def _char(self, ch: str) -> None:
        if self.at_line_start:
            if ch == '\n':
                self._classify(complete=True)
                self._end_line()
                return
            self.line_buf += ch
            if ch not in _PREFIX_CHARS or len(self.line_buf) > 12:
                self._classify(complete=False)
            return
        if ch == '\n':
            self._end_line()
        elif self.line_style == 'fence':
            pass  # the ``` line itself, language name included, is not shown
        elif self.in_fence:
            self._emit(ch, 'codeblock')
        else:
            self._inline(ch)

    def _classify(self, complete: bool) -> None:
        buf, self.line_buf = self.line_buf, ''
        self.at_line_start = False
        if buf.lstrip().startswith('```'):
            self.in_fence = not self.in_fence
            self.line_style = 'fence'
            return
        if self.in_fence:
            self._emit(buf, 'codeblock')
            return
        rest = buf
        heading = re.match(r'\s*#{1,6}\s', buf)
        bullet = re.match(r'(\s*)[-*+]\s', buf)
        quote = re.match(r'\s*>\s?', buf)
        if heading:
            self.line_style = 'heading'
            rest = buf[heading.end() :]
        elif complete and re.match(r'\s*(-{3,}|\*{3,}|_{3,})\s*$', buf):
            self._emit('─' * 40, 'marker')
            return
        elif bullet:
            self._emit(bullet.group(1) + '• ', 'marker')
            rest = buf[bullet.end() :]
        elif quote:
            self._emit('│ ', 'marker')
            self.line_style = 'quote'
            rest = buf[quote.end() :]
        for c in rest:
            self._inline(c)

    def _end_line(self) -> None:
        self._flush_star()
        if self.line_style != 'fence':
            self._emit('\n', 'plain')
        self._new_line()

    # ---- inline styles

    def _style(self) -> str:
        if self.code:
            return 'code'
        if self.line_style in ('heading', 'quote'):
            return self.line_style
        return 'bold' if self.bold else 'plain'

    def _inline(self, ch: str) -> None:
        if self.code:
            if ch == '`':
                self.code = False
            else:
                self._emit(ch, 'code')
            return
        if ch == '*':
            if self.pending_star:
                self.pending_star = False
                self.bold = not self.bold
            else:
                self.pending_star = True
            return
        self._flush_star()
        if ch == '`':
            self.code = True
        else:
            self._emit(ch, self._style())

    def _flush_star(self) -> None:
        if self.pending_star:
            self.pending_star = False
            self._emit('*', self._style())

    # ---- output, merged into runs of one style to keep console style switches few

    def _emit(self, text: str, style: str) -> None:
        if style != self.segment_style:
            self._flush_segment()
            self.segment_style = style
        self.segment += text

    def _flush_segment(self) -> None:
        if self.segment and self.segment_style:
            color, bold = STYLES[self.segment_style]
            write(self.segment, color, bold)
        self.segment = ''

"""A pane beside the chat (over it on a phone): a title, a close button and a page of its own, which takes
calls as soon as the pane exists and runs them once it has loaded."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable

import ui
from objc_util import on_main_thread

from .. import keys, theme, widgets
from .frontend import js
from .page import page

HEAD_HEIGHT = widgets.TOP_HEIGHT
TICK = 0.25  # seconds between looks at what was tapped in a pane that stays current
REDRAW_EVERY = 8  # ticks between its redraws (2 seconds)


class Pane(ui.View):
    def __init__(self, title: str, intro: str, on_close: Callable[[], None], dark: bool) -> None:
        self.on_close = on_close
        self.dark = dark
        self.inset = 0.0  # the iPhone's home indicator or the keyboard takes this much at the bottom
        self.intro = intro  # what the page shows at first
        self.seq = 0
        self.ready = False  # the page has loaded; until then calls wait in `queued`
        self.queued: list[str] = []
        self.page_lock = threading.Lock()

        self.divider = ui.View()  # a hairline between the chat and this pane
        self.add_subview(self.divider)
        self.head = widgets.TopBar([], [widgets.glyph_button('close', lambda s: self.on_close(), 'Close')])
        self.head.title_label.text = title
        self.add_subview(self.head)
        self.web = ui.WebView()
        self.web.load_html(page())
        self.add_subview(self.web)
        keys.hide_keyboard_on_drag(self.web)
        threading.Thread(target=self._when_loaded, daemon=True).start()

    def layout_head(self, below: float = 0) -> None:
        """The title, then the page down to `below` points above the bottom."""
        w, h = self.width, int(self.height)
        self.divider.frame = (0, 0, 0.5, h)
        self.head.frame = (0, 0, w, HEAD_HEIGHT)
        self.web.frame = (1, HEAD_HEIGHT, w - 1, h - HEAD_HEIGHT - int(below + self.inset))

    def layout(self) -> None:
        self.layout_head()

    def style(self) -> None:
        t = theme.colors(self.dark)
        self.background_color = t['bg']
        self.divider.background_color = t['line']
        self.head.style(t)

    def opened(self) -> None:
        """It has just come on screen."""

    # ---- the page

    def new_id(self, prefix: str) -> str:
        self.seq += 1
        return f'{prefix}{self.seq}'

    @on_main_thread
    def eval_js(self, code: str) -> str:
        return self.web.eval_js(code)

    def run(self, *calls: str) -> None:
        with self.page_lock:
            if not self.ready:
                self.queued.extend(calls)
                return
        self.eval_js(';'.join(calls))

    def _when_loaded(self) -> None:
        for _ in range(200):
            if self.eval_js('typeof add') == 'function':
                break
            time.sleep(0.05)
        self.queued.insert(0, js('clearChat', self.intro))
        while True:  # not under the lock: the main thread may be waiting for it
            with self.page_lock:
                calls, self.queued = self.queued, []
                self.ready = not calls
            if not calls:
                return
            self.eval_js(';'.join(calls))


class LivePane(Pane):
    """A pane drawn whole from page_html(), which stays current for as long as it is on screen."""

    def __init__(self, title: str, intro: str, on_close: Callable[[], None], dark: bool) -> None:
        super().__init__(title, intro, on_close, dark)
        self.watching = False
        self.drawn = ''

    def page_html(self) -> str:
        raise NotImplementedError

    def act(self, action: str) -> None:
        """Something on the page was tapped."""

    def opened(self) -> None:
        if not self.watching:
            self.watching = True
            threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self) -> None:
        """While it is on screen: what was tapped, every moment, and a redraw every so often."""
        ticks = 0
        try:
            while self.superview is not None:
                if self.ready:
                    for action in filter(None, (self.eval_js('takeActions()') or '').split('\n')):
                        self.act(action)
                    if ticks % REDRAW_EVERY == 0:
                        self.redraw()
                    ticks += 1
                time.sleep(TICK)
        finally:
            self.watching = False

    def redraw(self) -> None:
        html = self.page_html()
        if html != self.drawn:  # as it is, a redraw would only reset a selection or a scroll
            self.drawn = html
            self.run(f'setPane({json.dumps(html)})')

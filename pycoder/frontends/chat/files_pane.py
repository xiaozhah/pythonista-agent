"""The files pane: the workspace's folders and code, and what this session changed in it, to read while
the agent works. It stays current, and changes nothing (see file_browser.py)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Any

import console

from .file_browser import FileBrowser
from .pane import LivePane


class FilesPanel(LivePane):
    def __init__(self, controller: Any, on_close: Callable[[], None], dark: bool) -> None:
        super().__init__('Files', '', on_close, dark)
        self.browser = FileBrowser(controller)
        self.style()

    def page_html(self) -> str:
        return self.browser.page_html()

    def act(self, action: str) -> None:
        if action == 'preview':
            threading.Thread(
                target=console.quicklook, args=(self.browser.preview_path(),), daemon=True
            ).start()
            return
        if action == 'more':
            added = self.browser.more()
            if added is None:
                self.redraw()
            else:
                self.drawn = self.browser.page_html()
                self.run(f'appendPane({json.dumps(added)}, {json.dumps(self.browser.left)})')
            return
        elsewhere = self.browser.act(action)
        self.redraw()
        if elsewhere:
            self.run('window.scrollTo(0, 0)')

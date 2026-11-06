"""What the files pane shows: the workspace's folders, its files with their code, and what this session
changed in them. It only reads, and what it reads goes on the screen, not to the model. A file left open in
Pythonista's editor can overwrite what the agent writes, so looking at code here is safe while it works.

Everything can be seen, whatever its size: a page holds what has been scrolled to, and asks for more as
it gets near the end, so what limits it is how far someone reads."""

from __future__ import annotations

import codecs
import itertools
import os
import threading
from collections.abc import Iterator
from typing import Any

from ...host import env
from ...state.workspace import Workspace
from ...tools.files import skipped_dir
from . import icons, render

BLOCK = 256 * 1024  # bytes of a file read and coloured at a time
ROWS = 1000  # rows of a folder drawn at a time
DIFF_ROWS = 2000  # rows of a comparison drawn at a time
COMPARE_WAIT = 0.3  # seconds to wait for a comparison before showing that it is under way
COMPARE_MEMORY = 10  # a comparison takes about this many times the bytes it compares


class FileBrowser:
    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.folder = ''  # in the workspace; '' is its root
        self.file = ''  # in the workspace; '' when a folder is shown
        self.showing = 'code'  # of a file: 'code' or 'changes'
        self.rows = ROWS  # of the folder, drawn so far
        self.targets: list[tuple[str, str]] = []  # what the rows lead to, in the order drawn
        self.key: Any = None  # the file on screen as it is now: when this changes, it is read again
        self.blocks: list[str] = []  # of the file on screen, drawn so far
        self.source: Iterator[str] = iter(())  # the rest of them
        self.left = False  # there are more
        self.comparing = False
        self.lines = 0  # of the whole file, once it has all been read
        self.lock = threading.Lock()  # guards the above against a comparison that ends

    def _full(self, rel: str) -> str:
        return os.path.join(self.controller.workspace.root, rel)

    def _target(self, kind: str, rel: str) -> int:
        self.targets.append((kind, rel))
        return len(self.targets) - 1

    def act(self, action: str) -> bool:
        """Do what was tapped. Whether another page comes up, so that it starts from its top."""
        kind, _, what = action.partition(':')
        if kind == 'show':
            self.showing = what
            return False
        if kind != 'go' or not what.isdigit() or int(what) >= len(self.targets):
            return False
        where, rel = self.targets[int(what)]
        self.rows = ROWS
        if where == 'folder':
            self.folder, self.file = rel, ''
        else:
            self.folder, self.file = os.path.dirname(rel), rel
            self.showing = 'changes' if where == 'changes' else 'code'
        return True

    def more(self) -> str | None:
        """The page got near its end. What to add to it, or None if it has to be drawn again."""
        if not self.file:
            self.rows += ROWS
            return None
        with self.lock:
            if self.comparing or not self.left:
                return ''
        block = self._next()
        with self.lock:
            self.blocks.append(block)
        return block

    def _next(self) -> str:
        self.left = False  # unless what comes says otherwise
        return next(self.source, '')

    def preview_path(self) -> str:
        """The file on screen, for the system's preview of what isn't text."""
        return self._full(self.file) if self.file else ''

    def page_html(self) -> str:
        changes = dict(self.controller.checkpoints.session_changes())
        self.targets = []
        if self.file and (os.path.isfile(self._full(self.file)) or self.file in changes):
            return self._file_page(changes)
        self.file = ''
        if not os.path.isdir(self._full(self.folder)):
            self.folder = ''  # it has gone, or another session is open now
        return self._folder_page(changes)

    def _crumbs(self, path: str) -> list[tuple[str, int]]:
        """The way from the root to `path`: (name, target), the last one being where it is."""
        root = os.path.basename(self.controller.workspace.root.rstrip(os.sep)) or os.sep
        crumbs = [(root, self._target('folder', ''))]
        parts = path.split(os.sep) if path else []
        for i, name in enumerate(parts):
            crumbs.append((name, self._target('folder', os.sep.join(parts[: i + 1]))))
        return crumbs

    # ---- a folder

    def _folder_page(self, changes: dict[str, str]) -> str:
        crumbs = self._crumbs(self.folder)
        changed = []
        if not self.folder:  # the first thing to want from the top: what the agent just did
            for rel, how in changes.items():
                target = 'changes' if how != 'new' else 'file'
                changed.append((os.path.basename(rel), os.path.dirname(rel), how, self._target(target, rel)))
        folders, files = self._listing()
        shown_files = files[: max(0, self.rows - len(folders))]
        return render.folder_html(
            crumbs,
            changed,
            [(name, self._target('folder', rel)) for name, rel in folders[: self.rows]],
            [
                (name, self._size(rel), changes.get(rel, ''), self._target('file', rel))
                for name, rel in shown_files
            ],
            len(folders) + len(files) > self.rows,
            icons.icon('folder'),
            icons.icon('file'),
        )

    def _size(self, rel: str) -> int:
        try:
            return os.path.getsize(self._full(rel))
        except OSError:
            return 0

    def _listing(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """(name, path) of the folders here and of the files, as list_files sees them."""
        try:
            with os.scandir(self._full(self.folder)) as entries:
                found = sorted(entries, key=lambda entry: entry.name.lower())
        except OSError:
            return [], []
        folders, files = [], []
        for entry in found:
            rel = os.path.join(self.folder, entry.name)
            if entry.is_dir():
                if not skipped_dir(entry.name):
                    folders.append((entry.name, rel))
            elif not Workspace.is_hidden(entry.name):
                files.append((entry.name, rel))
        return folders, files

    # ---- a file

    def _file_page(self, changes: dict[str, str]) -> str:
        rel, how = self.file, changes.get(self.file, '')
        full = self._full(rel)
        exists = os.path.isfile(full)
        showing = self.showing if how and exists else ('changes' if how else 'code')
        size = self._size(rel) if exists else 0
        try:
            stat = os.stat(full).st_mtime_ns
        except OSError:
            stat = 0
        turns = len(self.controller.checkpoints.session.checkpoints)
        key = (rel, showing, how, stat, size, turns)
        if key != self.key:
            self._read_again(key, rel, showing, exists)
        with self.lock:
            body = ''.join(self.blocks)
            comparing, left = self.comparing, self.left
        meta = render.file_size(size)
        if not left and not comparing and showing == 'code' and self.lines:
            meta = f'{self.lines} lines · {meta}'
        return render.file_page_html(
            self._crumbs(os.path.dirname(rel)),
            os.path.basename(rel),
            '' if showing == 'changes' else meta,
            how,
            showing if exists else '',
            render.COMPARING if comparing else body,
            left,
        )

    def _read_again(self, key: Any, rel: str, showing: str, exists: bool) -> None:
        """As far as it was read, if this is the same page with a new version of the file."""
        same = self.key is not None and self.key[:2] == key[:2]
        wanted = max(1, len(self.blocks)) if same else 1
        self.key, self.lines = key, 0
        if showing == 'changes':
            self.blocks, self.comparing, self.left = [], True, False
            source = self._changes(rel, exists)
            worker = threading.Thread(target=self._compare, args=(key, source, wanted), daemon=True)
            worker.start()
            worker.join(COMPARE_WAIT)
            return
        self.source = self._code(rel)
        self.left = True
        self.blocks = []
        while self.left and len(self.blocks) < wanted:
            self.blocks.append(self._next())

    def _compare(self, key: Any, source: Iterator[str], wanted: int) -> None:
        """Comparing what is big takes time, and the pane shouldn't stop answering meanwhile."""
        with self.lock:
            if self.key != key:
                return  # another page is on screen by now
            self.source = source
            self.left = True
        blocks: list[str] = []
        while self.left and len(blocks) < wanted:
            blocks.append(self._next())
        with self.lock:
            if self.key == key:
                self.blocks, self.comparing = blocks, False

    def _code(self, rel: str) -> Iterator[str]:
        """The file by blocks, each cut after a line where it can be. Colours start over with each."""
        full = self._full(rel)
        decoder = codecs.getincrementaldecoder('utf-8')('strict')
        number, tail = 1, ''
        try:
            with open(full, 'rb') as f:
                data = f.read(BLOCK)
                if not data:
                    yield render.EMPTY
                    return
                while data:
                    following = f.read(BLOCK)
                    try:
                        if b'\0' in data and number == 1:
                            raise ValueError
                        text = tail + decoder.decode(data, final=not following)
                    except ValueError:  # UnicodeDecodeError is a ValueError
                        if number > 1:
                            raise
                        yield render.not_text_html()
                        return
                    decoder.errors = 'replace'  # text so far: a bad byte further on is only that
                    tail = ''
                    if following:
                        cut = text.rfind('\n') + 1
                        if cut:
                            text, tail = text[:cut], text[cut:]
                    start, number = number, number + text.count('\n')
                    self.left = bool(following)
                    if not following:
                        self.lines = number - 1 + (0 if text.endswith('\n') else 1)
                    yield render.source_html(text, rel, start)
                    data = following
        except (OSError, ValueError):
            self.left = False
            yield render.UNREADABLE

    def _changes(self, rel: str, exists: bool) -> Iterator[str]:
        """This session's changes to the file, by blocks of rows."""
        checkpoints = self.controller.checkpoints
        room = env.available_memory()
        size = (self._size(rel) if exists else 0) + checkpoints.earlier_size(rel)
        if room is not None and size * COMPARE_MEMORY > room:
            yield render.NO_ROOM_TO_COMPARE
            return
        earlier = checkpoints.earlier_text(rel)
        if earlier is None:
            yield render.NO_EARLIER
            return
        text = ''
        if exists:
            try:
                with open(self._full(rel), encoding='utf-8') as f:
                    text = f.read()
            except (OSError, ValueError):
                yield render.not_text_html()
                return
        rows = render.diff_lines(earlier, text, rel)
        first = list(itertools.islice(rows, DIFF_ROWS))
        if not first:
            yield render.NO_CHANGES
            return
        while first:
            following = list(itertools.islice(rows, DIFF_ROWS))
            self.left = bool(following)
            yield render.diff_rows_html(first)
            first = following

"""A conversation and everything needed to resume it, saved as JSON under .pycoder/sessions/."""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import config
from ..types import Message, Todo, Usage

PRE_COMPACT = '.pre-compact-'  # <id>.pre-compact-<n>.json: the conversation before compaction n
INDEX = 'index.json'  # what list() shows about each session, kept by SessionStore


def portable(path: str) -> str:
    """A folder as saved: relative to pycoder's home when inside it, so a session file still resolves
    wherever that home is, as the app's container path changes between installs."""
    if not path:
        return path
    home = os.path.realpath(config.HOME_DIR)
    full = os.path.realpath(path)
    if os.path.commonpath([home, full]) != home:
        return path
    rel = os.path.relpath(full, home)
    return '~' if rel == '.' else '~/' + rel


def local(saved: str) -> str:
    """The absolute folder on this device for one saved by portable() (absolute paths stay)."""
    if saved == '~' or saved.startswith('~/'):
        return os.path.join(config.HOME_DIR, saved[2:]) if saved != '~' else config.HOME_DIR
    return saved


@dataclass
class Turn:
    """One user request: where it starts in `messages`, for rewinding."""

    number: int
    text: str
    message_index: int
    time: float
    # when the request was appended to an existing user message (after a `!` command or an
    # interruption), how many content blocks that message already had
    block_offset: int = 0


def _new_id() -> str:
    return time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:4]


@dataclass
class Session:
    id: str
    root: str
    model: str
    # Fixed when the session starts: changing system or tools later would invalidate the
    # thinking blocks already in the conversation (the API checks the prefix they were made with).
    system: str
    web: bool
    memory_dir: str = ''  # where this session's auto memory lives; '' when memory is off
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    title: str = ''
    messages: list[Message] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    # turn number -> {workspace-relative path: content before that turn first changed it, None if new}
    checkpoints: dict[str, dict[str, str | None]] = field(default_factory=dict)
    todos: list[Todo] = field(default_factory=list)
    chapters: dict[str, str] = field(default_factory=dict)  # turn number -> the title of its chapter
    usage: dict[str, int] = field(
        default_factory=lambda: {'input': 0, 'output': 0, 'cache_read': 0, 'cache_write': 0}
    )
    cost: float = 0.0
    compactions: int = 0
    compacted_through: int = 0  # turns up to this number were summarized; rewind can't reach them
    last_usage: Usage = field(default_factory=dict)

    @staticmethod
    def new(root: str, model: str, system: str, web: bool, memory_dir: str = '') -> Session:
        return Session(
            id=_new_id(),
            root=root,
            model=model,
            system=system,
            web=web,
            memory_dir=memory_dir,
        )

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data['root'], data['memory_dir'] = portable(self.root), portable(self.memory_dir)
        # the file snapshots of summarized turns can't be rewound to any more
        data['checkpoints'] = {
            n: files for n, files in self.checkpoints.items() if int(n) > self.compacted_through
        }
        return data

    @staticmethod
    def from_json(data: dict[str, Any]) -> Session:
        data = dict(data)
        data['root'] = local(data.get('root', ''))
        data['memory_dir'] = local(data.get('memory_dir', ''))
        data['turns'] = [Turn(**t) for t in data.get('turns', [])]
        for number, todo in enumerate(data.get('todos', []), 1):  # saved before steps had numbers
            todo.setdefault('id', number)
        known = Session.__dataclass_fields__
        return Session(**{k: v for k, v in data.items() if k in known})

    def cut_before(self, turn: Turn) -> None:
        """Drop `turn` and everything after it from the conversation."""
        if turn.block_offset:  # keep what was already in that user message, drop the rest
            del self.messages[turn.message_index + 1 :]
            message = self.messages[turn.message_index]
            if isinstance(message['content'], str):
                message['content'] = [{'type': 'text', 'text': message['content']}]
            del message['content'][turn.block_offset :]
        else:
            del self.messages[turn.message_index :]
        self.turns = [t for t in self.turns if t.number < turn.number]
        self.chapters = {n: title for n, title in self.chapters.items() if int(n) < turn.number}

    def forked_after(self, number: int) -> Session:
        """A new session with this conversation up to the end of request `number`."""
        fork = Session.from_json(json.loads(json.dumps(self.to_json())))
        fork.id, fork.created = _new_id(), time.time()
        fork.title = f'{self.title or self.id} (fork)'
        fork.todos = []
        fork.cost = 0.0  # what was spent stays counted once, in the session that spent it
        fork.usage = dict.fromkeys(fork.usage, 0)
        later = next((t for t in fork.turns if t.number > number), None)
        if later is not None:
            fork.cut_before(later)
        fork.checkpoints = {n: files for n, files in fork.checkpoints.items() if int(n) <= number}
        return fork

    def reply_text(self, number: int) -> str:
        """The text of the last message of the reply to request `number` that has any."""
        turn = next((t for t in self.turns if t.number == number), None)
        if turn is None:
            return ''
        later = next((t.message_index for t in self.turns if t.number > number), len(self.messages))
        for message in reversed(self.messages[turn.message_index + 1 : later + 1]):
            content = message['content']
            if message['role'] != 'assistant':
                continue
            text = (
                content
                if isinstance(content, str)
                else '\n\n'.join(
                    str(b.get('text')) for b in content if b.get('type') == 'text' and b.get('text')
                )
            )
            if text:
                return text
        return ''

    def next_turn_number(self) -> int:
        """Never reused: a rewound turn's file snapshots may still be kept under its number."""
        used = [t.number for t in self.turns] + [int(n) for n in self.checkpoints] + [self.compacted_through]
        return max(used) + 1


@dataclass
class SessionInfo:
    id: str
    title: str
    updated: float
    turns: int
    cost: float = 0.0
    root: str = ''
    model: str = ''
    usage: dict[str, int] = field(default_factory=dict)


def _index_entry(full: str, data: dict[str, Any]) -> list[Any] | None:
    """The index entry of a session file: its mtime and size (to tell when it changed) and what
    /resume shows about it."""
    try:
        st = os.stat(full)
        info = SessionInfo(
            str(data['id']),
            data.get('title') or '(untitled)',
            float(data.get('updated') or 0),
            len(data.get('turns', [])),
            float(data.get('cost') or 0),
            str(data.get('root') or ''),  # as saved (portable); list() makes it local
            str(data.get('model') or ''),
            dict(data.get('usage') or {}),
        )
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return [st.st_mtime_ns, st.st_size, asdict(info)]


class SessionStore:
    """Sessions as <id>.json files, and an index of what /resume lists about each, so listing them
    doesn't read every conversation (each a few MB with its images and file snapshots)."""

    def __init__(self, directory: str) -> None:
        self.directory = directory
        self._index: dict[str, Any] | None = None  # file name -> [mtime_ns, size, SessionInfo fields]

    def path(self, session_id: str) -> str:
        return os.path.join(self.directory, session_id + '.json')

    def save(self, session: Session) -> None:
        session.updated = time.time()
        os.makedirs(self.directory, exist_ok=True)
        tmp = self.path(session.id) + '.tmp'
        data = session.to_json()
        # backslashreplace: a lone surrogate in a message, written as \\ud83d, is still valid JSON
        with open(tmp, 'w', encoding='utf-8', errors='backslashreplace') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, self.path(session.id))
        index = self._load_index()
        entry = _index_entry(self.path(session.id), data)
        if entry is not None:
            index[session.id + '.json'] = entry
            self._save_index(index)

    def load(self, session_id: str) -> Session:
        with open(self.path(session_id), encoding='utf-8') as f:
            return Session.from_json(json.load(f))

    def list(self) -> list[SessionInfo]:
        """Saved sessions, most recently updated first."""
        if not os.path.isdir(self.directory):
            return []
        index = self._load_index()
        fresh: dict[str, Any] = {}
        for name in os.listdir(self.directory):
            if not name.endswith('.json') or PRE_COMPACT in name or name == INDEX:
                continue
            full = os.path.join(self.directory, name)
            known = index.get(name)
            try:
                st = os.stat(full)
                if known is not None and known[:2] == [st.st_mtime_ns, st.st_size]:
                    fresh[name] = known
                    continue
                with open(full, encoding='utf-8') as f:
                    entry = _index_entry(full, json.load(f))
            except (OSError, ValueError):
                continue  # half-synced or damaged; skip it
            if entry is not None:
                fresh[name] = entry
        if fresh != index:
            self._save_index(fresh)
        infos = [SessionInfo(**{**info, 'root': local(info['root'])}) for _, _, info in fresh.values()]
        return sorted(infos, key=lambda i: i.updated, reverse=True)

    def _load_index(self) -> dict[str, Any]:
        if self._index is None:
            try:
                with open(os.path.join(self.directory, INDEX), encoding='utf-8') as f:
                    saved = json.load(f)
                fields = set(SessionInfo.__dataclass_fields__)
                self._index = {
                    name: entry
                    for name, entry in saved.items()
                    if isinstance(entry, list) and len(entry) == 3 and set(entry[2]) == fields
                }
            except (OSError, ValueError, TypeError, AttributeError):
                self._index = {}
        return self._index

    def _save_index(self, index: dict[str, Any]) -> None:
        """Best effort: the index only saves time, list() rebuilds whatever is missing."""
        self._index = index
        path = os.path.join(self.directory, INDEX)
        try:
            with open(path + '.tmp', 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False)
            os.replace(path + '.tmp', path)
        except OSError:
            pass

    def save_transcript(self, session: Session) -> str:
        """Keep the conversation as it was before a compaction replaced it with a summary."""
        path = os.path.join(self.directory, f'{session.id}{PRE_COMPACT}{session.compactions + 1}.json')
        os.makedirs(self.directory, exist_ok=True)
        with open(path, 'w', encoding='utf-8', errors='backslashreplace') as f:
            json.dump(
                {'id': session.id, 'turns': [asdict(t) for t in session.turns], 'messages': session.messages},
                f,
                ensure_ascii=False,
            )
        return path

    def delete(self, session_id: str) -> None:
        """Delete a session, the transcripts kept from before its compactions and its set-aside files."""
        shutil.rmtree(os.path.join(config.SET_ASIDE_DIR, session_id), ignore_errors=True)
        if not os.path.isdir(self.directory):
            return
        for name in os.listdir(self.directory):
            if name == session_id + '.json' or name.startswith(session_id + PRE_COMPACT):
                os.remove(os.path.join(self.directory, name))

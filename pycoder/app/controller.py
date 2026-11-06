"""One running pycoder: the session, its turns, and everything the commands can do to it.

Both frontends drive a Controller. It owns no UI: it reports through the frontend and asks the
frontend when it needs a choice or text from the user.
"""

from __future__ import annotations

import os
import shutil
import threading
import time

from .. import config
from ..agent import compaction, permissions
from ..agent.loop import Agent, AgentSettings, TurnResult, add_user_content, settled
from ..agent.prompt import build_system_prompt
from ..api import ApiClient, ApiError
from ..api.client import Transport
from ..cancel import CancelToken
from ..events import Frontend
from ..host import auth, background, env, images
from ..shell.commands import Shell, conversation_note, describe_error
from ..state import memory, settings
from ..state.checkpoints import Checkpoints, forget_old_set_aside, own_set_aside
from ..state.session import Session, SessionStore, Turn
from ..state.skills import SkillLibrary
from ..state.workspace import Workspace
from ..state.worktree import forget_old_worktrees
from ..tools.describe import shorten
from ..tools.registry import main_tools
from ..tools.todos import summary_note
from ..types import Block, Usage
from . import mentions, prompt_commands

BTW_NOTE = (
    '<system-reminder>A side question from the user, asked while you work. Answer it briefly from '
    'what this conversation already shows, without tools. The answer is shown to the user aside and '
    'is not kept in the conversation.</system-reminder>\n'
)

# what a Chinese input method types for / and ! when it isn't switched to English
_FULL_WIDTH_PREFIXES = {'、': '/', '／': '/', '！': '!'}


def free_name(path: str) -> str:
    """path, or if something is there 'name 2.ext', 'name 3.ext'..."""
    stem, ext = os.path.splitext(path)
    number = 1
    while os.path.exists(path):
        number += 1
        path = f'{stem} {number}{ext}'
    return path


def normalize_input(text: str) -> str:
    """A leading 、 or ／ starts a command and ！ a shell line, as / and ! do."""
    if text[:1] in _FULL_WIDTH_PREFIXES:
        return _FULL_WIDTH_PREFIXES[text[0]] + text[1:]
    return text


LONG_TURN = 20  # seconds; a request that took longer notifies when it ends (if you're away)
MOVED_NOTE = '<system-reminder>This session now continues in '


class Controller:
    def __init__(
        self,
        frontend: Frontend,
        root: str = config.HOME_DIR,
        transport: Transport | None = None,
        sessions_dir: str = config.SESSIONS_DIR,
        skills_dir: str = config.SKILLS_DIR,
        commands_dir: str = config.COMMANDS_DIR,
        settings_file: str = config.SETTINGS_FILE,
        memory_dir: str = config.MEMORY_DIR,
        home: str = config.HOME_DIR,
    ) -> None:
        # the slash commands import this module, so they are bound here rather than at the top; bound
        # now, not at the first command, so both come from the same load of pycoder (opening it again
        # drops and reloads its modules, and a later import would mix two copies)
        from .commands import run_command

        self._run_command = run_command
        self.frontend = frontend
        # where `cd` and `!` commands may go: pycoder's home and /local, or only the workspace when it
        # is elsewhere (as in tests)
        self.home = home if self._shell(root, home).contains(root) else root
        self.settings_file = settings_file
        self.memory_base = memory_dir
        self.settings = settings.load(settings_file)
        self.store = SessionStore(sessions_dir)
        learned = config.LEARNED_SKILLS_DIR if skills_dir == config.SKILLS_DIR else ''
        self.skills = SkillLibrary(skills_dir, learned)
        self.commands_dir = commands_dir
        self._prompt_commands: list[prompt_commands.PromptCommand] = []
        self._prompt_commands_at = 0.0
        self.transport = transport
        self.cancel = CancelToken()
        self.client: ApiClient | None = None
        self.pending_images: list[Block] = []
        self.busy = False
        self.workspace = self._workspace(root)
        # the permission mode and rules the agent consults; the frontend may be swapped later
        self.policy = permissions.SettingsPolicy(
            self.settings,
            settings_file,
            lambda: self.workspace.root,
            lambda mode: self.set_setting('mode', mode),
            lambda text: self.frontend.notice(text),
        )
        forget_old_set_aside()
        forget_old_worktrees()
        self.session = self._fresh_session()
        self.checkpoints = Checkpoints(self.session, self.workspace)
        self.side_chat: list[tuple[str, str]] = []  # this session's /btw questions and answers (not saved)
        self._usage_lock = threading.Lock()

    # ---- setup

    def connect(self, api_key: str | None = None) -> None:
        """Get the API key (asking once if needed) and create the client."""
        key = api_key or auth.get_api_key(
            lambda: self.frontend.ask_text('Anthropic API Key', 'Stored in the iOS keychain', True)
        )
        self.client = ApiClient(key, self.transport)

    def reset_api_key(self) -> None:
        self.connect(
            auth.get_api_key(
                lambda: self.frontend.ask_text('Anthropic API Key', 'Replaces the stored key', True),
                reset=True,
            )
        )
        self.frontend.notice('API key updated')

    def _fresh_session(self) -> Session:
        notes = self.memory_store() if self.settings.memory else None
        system = build_system_prompt(
            self.workspace.root,
            self.skills.prompt_section(),
            notes.prompt_section(memory.global_store(notes.directory)) if notes else '',
        )
        return Session.new(
            self.workspace.root,
            self.settings.model,
            system,
            self.settings.web,
            notes.directory if notes else '',
        )

    def memory_store(self) -> memory.MemoryStore:
        """The auto memory of the current workspace."""
        return memory.MemoryStore(memory.directory(self.workspace.root, self.memory_base))

    def new_session(self, root: str | None = None) -> None:
        """Start over: a new conversation, picking up edited CLAUDE.md and skills."""
        if root:
            self.workspace = self._workspace(root)
        self.session = self._fresh_session()
        self.checkpoints = Checkpoints(self.session, self.workspace)
        self.side_chat = []
        self.pending_images.clear()
        self.frontend.session_cleared()

    def resume(self, session_id: str) -> None:
        session = self.store.load(session_id)
        if not os.path.isdir(session.root):
            self.frontend.notice(f"That session's folder is gone: {session.root}", 'error')
            return
        self.workspace = self._workspace(session.root)
        self.session = session
        self.side_chat = []
        self.settings.model = session.model
        self.checkpoints = Checkpoints(session, self.workspace)
        note = self._moved_note()
        if note:
            add_user_content(session.messages, [{'type': 'text', 'text': note}])
        self._show_session()
        self.frontend.todos_updated(session.todos)

    def _moved_note(self) -> str:
        """The system prompt is frozen with the device and workspace folder the session started in.
        Resumed on another device, or with its folder moved, a note in the conversation says what
        holds now ('' when nothing changed, or the last note already says so)."""
        s = self.session
        device, root = env.describe(), s.root
        if device in s.system and root in s.system:  # whatever the prompt's wording
            return ''
        note = (
            f'{MOVED_NOTE}{device}, with the workspace root at {root}; where the system prompt names '
            'another device or folder, this is what holds now.</system-reminder>'
        )
        earlier = [
            b.get('text', '')
            for m in s.messages
            if m['role'] == 'user' and isinstance(m['content'], list)
            for b in m['content']
            if str(b.get('text', '')).startswith(MOVED_NOTE)
        ]
        return '' if earlier and earlier[-1] == note else note

    # ---- turns

    def agent(self) -> Agent:
        if self.client is None:
            self.connect()
        assert self.client is not None
        settings = AgentSettings(
            self.settings.model,
            self.settings.effort,
            self.session.system,
            self.session.web,
            cache_ttl=self.settings.cache_ttl,
            compact_at=self.settings.compact_at,
        )
        return Agent(
            self.client,
            main_tools(with_memory=bool(self.session.memory_dir)),
            settings,
            self.frontend,
            self.cancel,
            self.workspace,
            self.session,
            self.checkpoints,
            self.policy,
            on_usage=self._add_usage,
            on_attention=self._attention,
            compact=self._compact_mid_turn,
            on_step=self.save,  # iOS can end the app at any moment: a /resume finds all that was done
        )

    def prompt_commands(self) -> list[prompt_commands.PromptCommand]:
        """Markdown commands: pycoder's own, then the workspace's .claude/commands (as in Claude Code).

        Cached for a few seconds: the command palette asks on every keystroke.
        """
        now = time.time()
        if now - self._prompt_commands_at > 3:
            self._prompt_commands = prompt_commands.load(
                [self.commands_dir, os.path.join(self.workspace.root, '.claude', 'commands')]
            )
            self._prompt_commands_at = now
        return self._prompt_commands

    def submit(self, text: str) -> bool:
        """Handle one line from the user. Returns False when the user asked to quit."""
        text = normalize_input(text.strip())
        if not text and not self.pending_images:
            return True
        self.cancel.reset()  # a Stop of the last request doesn't reach this one
        if text.startswith('/'):
            return self._run_command(self, text)
        if text.startswith('!'):
            self.run_shell(text[1:].strip())
            return True
        self.run_turn(text)
        return True

    def side_question(self, question: str) -> str:
        """/btw: answer a question from the conversation so far, without tools, and leave the
        conversation as it is; it may run while a turn does. Earlier side questions of this session
        come along, so follow-ups work. The request repeats the turn's own (same system prompt, tools
        and history), so most of it is read from the prompt cache."""
        agent = self.agent()
        assert self.client is not None
        messages = settled(self.session.messages)
        asked = [*(q for q, _ in self.side_chat), question]
        for n, q in enumerate(asked):
            add_user_content(messages, [{'type': 'text', 'text': (BTW_NOTE if n == 0 else '') + q}])
            if n < len(self.side_chat):
                messages.append(
                    {'role': 'assistant', 'content': [{'type': 'text', 'text': self.side_chat[n][1]}]}
                )
        data = self.client.complete(agent.request_body(messages))
        self._add_usage(data.get('usage') or {}, data.get('model'))
        text = '\n\n'.join(b['text'] for b in data.get('content', []) if b.get('type') == 'text').strip()
        answer = text or '(no answer: it would need tools for that; ask in the conversation instead)'
        self.side_chat.append((question, answer))
        return answer

    def run_shell(self, line: str) -> str:
        """A `!` command: run it in the built-in shell, show it, and add it to the conversation."""
        shell = self._shell(self.workspace.root, self.home)
        shell.frontend, shell.cancel, shell.on_cd = self.frontend, self.cancel, self.change_dir
        try:
            output, ok = shell.run(line), True
        except KeyboardInterrupt:
            output, ok = '(interrupted)', False
        except Exception as e:  # a failed command is reported like a shell would, never raised
            output, ok = describe_error(e), False
        self.frontend.shell_output(line, output, ok)
        if not (ok and line.split()[:1] == ['cd']):  # a successful cd already started a new session
            note = conversation_note(line, output)
            add_user_content(self.session.messages, [{'type': 'text', 'text': note}])
        self.save()
        return output

    def change_dir(self, path: str) -> str:
        """Switch the workspace, within pycoder's home (a new session: the system prompt names it)."""
        target = self._shell(self.workspace.root, self.home).path(path) if path else self.home
        if not os.path.isdir(target):
            raise ValueError(f'Not a directory: {path}')
        self.save()
        self.new_session(target)
        return f'Workspace: {self.display_path(target)} (new session)'

    def run_turn(self, text: str) -> TurnResult:
        session = self.session
        content: list[Block] = [*self.pending_images, {'type': 'text', 'text': text or '(see the image)'}]
        attached, names = mentions.attach(self.workspace, text)
        content += attached
        images = self.pending_images
        if self.settings.mode == 'plan':  # appended, not put in the system prompt, so history stays valid
            content.append({'type': 'text', 'text': permissions.PLAN_REMINDER})
        self.pending_images = []
        index, offset = len(session.messages), 0
        last = session.messages[-1] if session.messages else None
        if last is not None and last['role'] == 'user':  # this request will be merged into it
            index = len(session.messages) - 1
            offset = 1 if isinstance(last['content'], str) else len(last['content'])
        turn = Turn(session.next_turn_number(), text, index, time.time(), offset)
        session.turns.append(turn)
        self.frontend.request(text, images, names, turn.number)
        session.title = session.title or text[:60]
        session.model = self.settings.model
        self.checkpoints.turn = turn.number
        cost_before, started = session.cost, time.time()
        self.busy = True
        background.hold(True, text[:80])
        self.cancel.reset()  # only here, where the user's request starts (a subagent must not clear a Stop)
        try:
            result = self.agent().run_turn(session.messages, content)
        finally:
            background.hold(False)
            self.busy = False
            self.checkpoints.turn = 0
        if result.rolled_back:
            session.turns.remove(turn)  # nothing of this request is left in the conversation
        elif result.status in ('done', 'exhausted'):
            session.last_usage = result.usage or {}
            self.frontend.turn_done(
                result.model, result.usage or {}, session.cost, session.cost - cost_before
            )
        if time.time() - started > LONG_TURN:
            self._attention(
                f'{"Done" if result.status == "done" else result.status.capitalize()}: {text[:80]}'
            )
        self.save()
        if (
            result.status in ('done', 'exhausted')
            and result.usage
            and compaction.needs_compaction(result.usage, self.settings.compact_at)
        ):
            try:
                self.compact(automatic=True)
            except ApiError as e:  # the turn itself succeeded; just say compaction didn't
                self.frontend.notice(f'Automatic compaction failed: {e}', 'warn')
        return result

    def stop(self) -> None:
        self.cancel.cancel()

    def close(self) -> None:
        """The screen has gone: what runs stops, and nothing starts after it."""
        self.cancel.close()

    def save(self) -> None:
        if self.session.messages:
            self.store.save(self.session)

    def clear_todos(self) -> None:
        self.session.todos = []
        self.frontend.todos_updated([])

    # ---- compaction and rewind

    def compact(self, automatic: bool = False) -> bool:
        """Summarize the conversation (/compact, or after a turn that left it large)."""
        self.cancel.reset()
        return self._compact(automatic)

    def _compact_mid_turn(self) -> bool:
        """The agent's callback when the conversation grows too large during a turn: the turn goes
        on either way (and a Stop pressed meanwhile still stops it)."""
        try:
            return self._compact(automatic=True)
        except ApiError as e:
            self.frontend.notice(f'Automatic compaction failed: {e}', 'warn')
            return False

    def _compact(self, automatic: bool) -> bool:
        session = self.session
        if not compaction.can_compact(session.messages):
            self.frontend.notice('Nothing to compact yet')
            return False
        self.frontend.compacting()
        agent = self.agent()
        assert self.client is not None
        result = self.client.compact(
            agent.request_body(session.messages), compaction.INSTRUCTIONS, self.cancel
        )
        self._add_usage(compaction.total_usage(result.usage), session.model)
        if result.block is None:
            self.frontend.notice(
                f'Compaction returned no summary ({result.stop_reason}); the conversation is unchanged',
                'warn',
            )
            return False
        self.store.save_transcript(session)  # the full conversation stays readable on disk
        session.messages[:] = compaction.apply(result.block)
        note = summary_note(session.todos)  # the numbers todo_update goes by, whatever the summary kept
        if note:
            add_user_content(session.messages, [{'type': 'text', 'text': note}])
        session.compactions += 1
        session.compacted_through = session.turns[-1].number if session.turns else 0
        self.save()
        self.frontend.compacted(str(result.block.get('content', '')))
        if automatic:
            self.frontend.notice('(the conversation was long, so earlier turns were summarized)')
        return True

    def rewindable_turns(self) -> list[Turn]:
        return [t for t in self.session.turns if t.number > self.session.compacted_through]

    def rewind(self, turn_number: int, files: bool = True, conversation: bool = True) -> list[str]:
        """Go back to just before `turn_number`: undo the file changes since then, drop the requests
        since then from the conversation, or both. Returns the restored paths."""
        session = self.session
        turn = next((t for t in self.rewindable_turns() if t.number == turn_number), None)
        if turn is None:
            raise ValueError('Turn %d cannot be rewound' % turn_number)
        lost = self.checkpoints.not_restorable(turn_number) if files else []
        restored = self.checkpoints.restore(turn_number) if files else []
        lost_or_stuck = lost + (self.checkpoints.stuck if files else [])
        if files and self.checkpoints.stuck:
            self.frontend.notice(
                'Not restored (something else is in the way): ' + ', '.join(self.checkpoints.stuck), 'warn'
            )
        if lost:
            self.frontend.notice(
                'Not restored (code or git changed them, and they were too big to keep a copy of): '
                + ', '.join(lost),
                'warn',
            )
        if not conversation:  # code only: tell Claude, or it would trust its memory of the files
            if restored:
                note = 'The user put these files back as they were before request #%d: %s' % (
                    turn_number,
                    ', '.join(restored),
                )
                if lost_or_stuck:
                    note += '; these could not be put back and are as they are now: ' + ', '.join(
                        lost_or_stuck
                    )
                add_user_content(session.messages, [{'type': 'text', 'text': note}])
            self.save()
            return restored
        session.cut_before(turn)
        self.clear_todos()  # the plan went with the conversation that made it
        self.save()
        self._show_session()
        return restored

    def fork(self, turn_number: int) -> None:
        """Go on in a new session with this conversation up to the end of that request; this one
        stays as it is, and so do the files."""
        if not any(t.number == turn_number for t in self.rewindable_turns()):
            raise ValueError('Request %d cannot be forked from' % turn_number)
        self.save()
        fork = self.session.forked_after(turn_number)
        own_set_aside(fork)
        self.store.save(fork)
        self.resume(fork.id)

    def toggle_chapter(self, turn_number: int) -> str:
        """Pin that request as the start of a chapter, or unpin it. Returns the title ('' if unpinned)."""
        session, key = self.session, str(turn_number)
        turn = next((t for t in session.turns if t.number == turn_number), None)
        if turn is None:
            raise ValueError('No request %d' % turn_number)
        title = ''
        if session.chapters.pop(key, None) is None:
            first = (session.reply_text(turn_number) or turn.text).strip().splitlines()[:1]
            title = shorten(first[0].lstrip('# '), 60) if first else f'Request {turn_number}'
            session.chapters[key] = title
        if not self.busy:  # a turn in progress saves it with the next step
            self.save()
        self.frontend.chapter_changed(turn_number, title)
        return title

    def rename(self, title: str) -> None:
        self.session.title = title.strip()[:80]
        self.save()

    def delete_session(self, session_id: str) -> None:
        """Delete a saved session; deleting the current one starts a new session."""
        self.store.delete(session_id)
        if session_id == self.session.id:
            self.new_session()

    def _show_session(self) -> None:
        s = self.session
        self.frontend.session_loaded(
            s.title or s.id,
            s.messages,
            {t.message_index: t.time for t in s.turns},
            {t.message_index: t.number for t in self.rewindable_turns()},
            {int(number): title for number, title in s.chapters.items()},
        )

    # ---- settings and attachments

    def set_setting(self, name: str, raw: object) -> object:
        """Check, apply and save one setting (ValueError if the value is invalid); returns the value."""
        spec = settings.SPEC_BY_NAME.get(name)
        if spec is None:
            raise ValueError(f'Unknown setting {name}; choose from {", ".join(settings.SPEC_BY_NAME)}')
        value = settings.parse(spec, raw)
        setattr(self.settings, name, value)
        settings.save(self.settings_file, self.settings)
        self.frontend.settings_changed()
        return value

    def set_model(self, model: str) -> None:
        # the conversation is kept; the API ignores earlier thinking blocks the new model can't read
        self.set_setting('model', model)

    def attach_image(self, source: str) -> str:
        if source in ('clipboard', 'paste'):
            block = images.from_clipboard()
        elif source in ('photo', 'photos'):
            block = images.from_photos()
        elif source == 'camera':
            block = images.from_camera()
        else:
            block = images.from_path(self.workspace.resolve(source))
        self.pending_images.append(block)
        return images.describe(block)

    def import_for_mention(self) -> str:
        """Let the user pick a file and copy it into the workspace, under a name not in use. Returns
        the @mention that sends it with a message ('' if none was picked)."""
        import dialogs

        picked = dialogs.pick_document(types=['public.item'])
        if not picked:
            return ''
        target = free_name(os.path.join(self.workspace.root, os.path.basename(picked)))
        shutil.copyfile(picked, target)
        rel = self.workspace.rel(target)
        return f'@"{rel}"' if ' ' in rel else f'@{rel}'

    # ---- helpers

    def _add_usage(self, usage: Usage, model: str | None) -> None:
        with self._usage_lock:  # subagents running at once report from their threads
            self._count_usage(usage, model)

    def _count_usage(self, usage: Usage, model: str | None) -> None:
        counts = (
            int(usage.get('input_tokens') or 0),
            int(usage.get('output_tokens') or 0),
            int(usage.get('cache_read_input_tokens') or 0),
            int(usage.get('cache_creation_input_tokens') or 0),
        )
        for key, value in zip(('input', 'output', 'cache_read', 'cache_write'), counts, strict=True):
            self.session.usage[key] = self.session.usage.get(key, 0) + value
        self.session.cost += config.cost_of(usage, model or self.settings.model)

    def folder_label(self) -> str:
        """The workspace as the shell shows it: ~/project, /local/scratch, or its path."""
        return self.display_path(self.workspace.root)

    def display_path(self, path: str) -> str:
        """Any path as the shell shows it (~/… rather than the long iCloud path)."""
        return self._shell(self.workspace.root, self.home).display(path)

    @staticmethod
    def _shell(cwd: str, home: str) -> Shell:
        return Shell(cwd, home)

    def _workspace(self, root: str) -> Workspace:
        """The agent changes files only in its folder, but reads anywhere in the home and on the
        device's local storage (another project, a file to compare with), its own code, which may be
        outside the home, and the Python library with the packages Pythonista bundles."""
        library = os.path.dirname(os.path.realpath(os.__file__))
        readable = (self.home, env.local_documents() or '', config.INSTALL_DIR, library)
        return Workspace(root, readable=readable, home=self.home)

    def _attention(self, message: str) -> None:
        if self.settings.notify:
            env.notify_if_away(message)

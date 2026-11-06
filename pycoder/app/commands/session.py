"""Commands about the conversation: clear, resume, rename, delete, compact, rewind, cd, image, exit."""

from __future__ import annotations

import os
import time

from ...host import env, images
from ...state.session import SessionInfo
from ..controller import Controller
from .base import Command


def _clear(c: Controller, arg: str) -> None:
    c.save()
    c.new_session()
    c.frontend.notice('New session (the previous one is saved; /resume brings it back)')


def _btw(c: Controller, arg: str) -> None:
    if not arg:
        c.frontend.notice('/btw <question>: ask about the work without adding to the conversation')
        return
    c.frontend.side_answer(arg, c.side_question(arg))


def _saved(c: Controller) -> tuple[list[SessionInfo], list[SessionInfo]]:
    """(every saved session that isn't empty, those of this folder), newest first."""
    everything = [s for s in c.store.list() if s.turns or s.id == c.session.id]
    return everything, [s for s in everything if s.root == c.workspace.root]


def _find(sessions: list[SessionInfo], arg: str) -> SessionInfo | None:
    return next((s for s in sessions if s.id == arg or s.id.startswith(arg)), None)


def _pick(
    c: Controller, title: str, sessions: list[SessionInfo], everything: list[SessionInfo]
) -> SessionInfo | None:
    title += '' if sessions is everything else ' in this folder'
    shown = sessions[:30]
    labels = [_session_label(s, c.display_path(s.root) if s.root != c.workspace.root else '') for s in shown]
    current = next((i for i, s in enumerate(shown) if s.id == c.session.id), None)
    choice = c.frontend.choose(title, labels, current)
    return None if choice is None else shown[choice]


def _resume(c: Controller, arg: str) -> None:
    """/resume [id | last | all]: sessions of this folder (all: of every folder); last: the latest."""
    everything, here = _saved(c)
    target: SessionInfo | None
    if arg not in ('', 'last', 'all'):
        target = _find(everything, arg)
        if target is None:
            c.frontend.notice(f'No session {arg}', 'error')
            return
    else:
        sessions = everything if arg == 'all' else [s for s in here if s.id != c.session.id]
        if not sessions:
            c.frontend.notice('No other saved sessions in this folder (/resume all lists every folder)')
            return
        target = sessions[0] if arg == 'last' else _pick(c, 'Resume a session', sessions, everything)
        if target is None:
            return
    c.save()
    c.resume(target.id)


def _compact(c: Controller, arg: str) -> None:
    c.compact()


REWIND_HOW = {
    'both': 'Code and conversation',
    'conversation': 'Conversation only (keep the files as they are)',
    'code': 'Code only (keep the conversation)',
}


def _rewind(c: Controller, arg: str) -> None:
    """/rewind [n] [both|conversation|code]: go back to before request n."""
    turns = c.rewindable_turns()
    if not turns:
        summarized = any(t.number <= c.session.compacted_through for t in c.session.turns)
        c.frontend.notice(
            'Nothing to rewind since the conversation was summarized (/compact)'
            if summarized
            else 'Nothing to rewind yet'
        )
        return
    words = arg.split()
    number = int(words[0]) if words and words[0].isdigit() else None
    how = words[-1] if words and words[-1] in REWIND_HOW else None
    if number is None:
        labels = []
        for t in reversed(turns):
            changed = c.checkpoints.changed_since(t.number)
            files = ' (files: {})'.format(', '.join(changed[:3])) if changed else ''
            labels.append(
                '#%d %s · %s%s'
                % (t.number, time.strftime('%H:%M', time.localtime(t.time)), t.text[:60], files)
            )
        choice = c.frontend.choose('Rewind to before which request?', labels)
        if choice is None:
            return
        number = list(reversed(turns))[choice].number
    if how is None:
        if not c.checkpoints.changed_since(number):
            how = 'conversation'  # no files to put back
        else:
            choice = c.frontend.choose('Restore what?', list(REWIND_HOW.values()))
            if choice is None:
                return
            how = list(REWIND_HOW)[choice]
    try:
        restored = c.rewind(number, files=how != 'conversation', conversation=how != 'code')
    except ValueError as e:
        c.frontend.notice(str(e), 'error')
        return
    files = '; restored ' + ', '.join(restored) if restored else ''
    if how == 'code':
        c.frontend.notice(
            'Files put back as they were before request #%d%s' % (number, files or ' (none changed)')
        )
    else:
        c.frontend.notice('Rewound to before request #%d%s' % (number, files))


def _fork(c: Controller, arg: str) -> None:
    """/fork [n]: go on in a new session with the conversation up to the end of request n."""
    turns = c.rewindable_turns()
    if not turns:
        c.frontend.notice('Nothing to fork yet')
        return
    title = c.session.title or c.session.id
    try:
        c.fork(int(arg) if arg.strip() else turns[-1].number)
    except ValueError as e:
        c.frontend.notice(str(e), 'error')
        return
    c.frontend.notice(f'Forked from {title}. It is still there: /resume')


def _chapters(c: Controller, arg: str) -> None:
    """/chapters: jump to a chapter pinned with the pin under a reply."""
    chapters = sorted((int(number), title) for number, title in c.session.chapters.items())
    if not chapters:
        c.frontend.notice('No chapters yet: pin a reply with the button under it')
        return
    choice = c.frontend.choose('Chapters', [title for _, title in chapters])
    if choice is not None:
        c.frontend.show_chapter(chapters[choice][0])


def _rename(c: Controller, arg: str) -> None:
    title = arg or c.frontend.ask_text('Rename this session', c.session.title) or ''
    if title.strip():
        c.rename(title)
        c.frontend.notice(f'Session renamed: {c.session.title}')


def _delete(c: Controller, arg: str) -> None:
    """/delete [id | all]: pick from this folder's sessions (all: every folder's)."""
    everything, here = _saved(c)
    target: SessionInfo | None
    if arg not in ('', 'all'):
        target = _find(c.store.list(), arg)
        if target is None:
            c.frontend.notice(f'No session {arg}', 'error')
            return
    else:
        sessions = everything if arg == 'all' else here
        if not sessions:
            c.frontend.notice('No saved sessions in this folder (/delete all lists every folder)')
            return
        target = _pick(c, 'Delete which session?', sessions, everything)
        if target is None:
            return
    if c.frontend.choose(f'Delete "{target.title}" for good?', ['Delete', 'Cancel']) != 0:
        return
    c.delete_session(target.id)
    c.frontend.notice(f'Deleted {target.title}')


def _session_label(s: SessionInfo, folder: str = '') -> str:
    """The title, then (on the picker's second line) when, how long and, if asked, where."""
    when = time.strftime('%m-%d %H:%M', time.localtime(s.updated))
    turns = f'{s.turns} request{"" if s.turns == 1 else "s"}'
    return f'{s.title or "(untitled)"} — {when} · {turns}' + (f' · {folder}' if folder else '')


def _cd(c: Controller, arg: str) -> None:
    try:
        c.frontend.notice(c.change_dir(arg))
    except ValueError as e:
        c.frontend.notice(str(e), 'error')


def _image(c: Controller, arg: str) -> None:
    source = arg
    if not source:
        options = ['file', 'photo', 'clipboard'] + ([] if env.on_mac() else ['camera'])
        labels = {
            'file': 'File',
            'photo': 'Photo library',
            'clipboard': 'Clipboard',
            'camera': 'Camera — take a photo now',
        }
        choice = c.frontend.choose('Attach', [labels[o] for o in options])
        if choice is None:
            return
        source = options[choice]
    if source == 'file':
        _attach_file(c)
        return
    try:
        label = c.attach_image(source)
    except (images.ImageError, OSError, ValueError) as e:
        c.frontend.notice(str(e), 'error')
        return
    c.frontend.notice(f'Image attached ({label}); it goes with your next message')


def _attach_file(c: Controller) -> None:
    """Pick a file: a copy goes in the workspace, and an @mention of it in the input, to send with."""
    try:
        mention = c.import_for_mention()
    except OSError as e:
        c.frontend.notice(f'Could not attach it: {e}', 'error')
        return
    if mention:
        c.frontend.add_to_input(mention + ' ')


def _exit(c: Controller, arg: str) -> bool:
    c.save()
    return False


def _dirs(c: Controller) -> list[str]:
    root = c.workspace.root
    return sorted(
        n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)) and not n.startswith('.')
    )


COMMANDS = [
    Command('clear', 'start a new session (the current one is saved)', _clear),
    Command(
        'resume',
        "continue a saved session of this folder (all: any folder's)",
        _resume,
        '[last|all|id]',
        lambda c: ['last', 'all'] + [s.id for s in c.store.list()[:20]],
    ),
    Command('compact', 'summarize the conversation to free up context', _compact),
    Command(
        'btw',
        'a side question, answered without adding to the conversation, even mid-turn',
        _btw,
        '<question>',
    ),
    Command(
        'rewind',
        'go back to before an earlier request: its file changes, the conversation, or both',
        _rewind,
        '[n] [both|conversation|code]',
        lambda c: [str(t.number) for t in c.rewindable_turns()],
    ),
    Command(
        'fork',
        'go on in a new session with the conversation up to a request; this one stays',
        _fork,
        '[n]',
        lambda c: [str(t.number) for t in c.rewindable_turns()],
    ),
    Command('chapters', 'jump to a chapter you pinned', _chapters),
    Command('rename', 'rename this session', _rename, '[title]'),
    Command(
        'delete',
        "delete a saved session of this folder (all: any folder's)",
        _delete,
        '[all|id]',
        lambda c: ['all'] + [s.id for s in c.store.list()[:20]],
    ),
    Command('cd', 'change the workspace folder (new session)', _cd, '[dir]', lambda c: _dirs(c)),
    Command(
        'image',
        'attach a file or an image to the next message',
        _image,
        '[file|photo|clipboard|path]',
        lambda c: ['file', 'photo', 'clipboard'],
    ),
    Command('exit', 'quit (console)', _exit),
]

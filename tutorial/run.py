"""Tap Run: pycoder builds a big demo project by itself, in the chat, while you watch.

Each project is one prompt in this folder. You pick the model, and it is built in ~/demos/<name>-<model>,
without asking anything; REPORT.md there says how it went. A folder named like the project holds what it is
given, and is copied in first. Your settings aren't changed. Running this again carries on with a project
left unfinished.

Before it starts you see what the project wants to use and why, and choose. A project lists that under
"## Permissions" in its prompt; what it doesn't list stays off.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RULES = 'rules.md'
PROMPT = 'PROMPT.md'
REPORT = 'REPORT.md'
ALONE = 'alone'  # the choice of working without asking
TURNED_OFF = ['ask_user', 'save_skill', 'git(push*)']  # nobody can answer; what stays as it is
TOOLS_OF = {  # tools that are off unless their permission was given
    'network': ['web_search', 'web_fetch'],
    'packages': ['install_package'],
    'microphone': ['record_audio'],
}
LABELS = {
    'motion': 'Motion sensors',
    'barometer': 'Barometer',
    'microphone': 'Microphone',
    'camera': 'Camera',
    'notifications': 'Notifications',
    'network': 'Internet',
    'packages': 'Installing packages',
}
MEDIA = {'microphone': 'soun', 'camera': 'vide'}  # those iOS asks about through AVCaptureDevice
MODELS = {  # what the projects are built with: each gets a folder of its own, to compare
    'Haiku, high effort': ('haiku', 'claude-haiku-5-5', 'high'),
    'Opus, high effort': ('opus', 'claude-opus-5-5', 'high'),
}
_blocks: list[Any] = []


@dataclass
class Project:
    name: str  # as the folder is called: neon-drift
    title: str
    path: str
    permissions: dict[str, str]  # what it wants to use, and why


def projects(folder: str = HERE) -> list[Project]:
    """The prompts here, in order: 1-neon-drift.md is the project Neon Drift, its first line its title."""
    found = []
    for file in sorted(os.listdir(folder)):
        if file.endswith('.md') and file[0].isdigit():
            path = os.path.join(folder, file)
            with open(path, encoding='utf-8') as f:
                text = f.read()
            title = text.split('\n', 1)[0].lstrip('# ').strip()
            found.append(Project(file[:-3].split('-', 1)[1], title, path, permissions_in(text)))
    return found


def permissions_in(text: str) -> dict[str, str]:
    """From the "## Permissions" section of a prompt: lines like `- camera: why it is wanted`."""
    section = text.split('## Permissions', 1)[1].split('\n#', 1)[0] if '## Permissions' in text else ''
    found = re.findall(r'^- ([\w-]+): (.+)$', section, re.M)
    return {name: reason.strip() for name, reason in found}


def wanted(queue: list[Project]) -> dict[str, list[str]]:
    """Each permission these projects want, with the reasons, naming the project when there are several."""
    reasons: dict[str, list[str]] = {}
    for project in queue:
        for name, reason in project.permissions.items():
            line = f'{project.title}: {reason}' if len(queue) > 1 else reason
            reasons.setdefault(name, []).append(line)
    return reasons


def state(folder: str) -> str:
    if os.path.exists(os.path.join(folder, REPORT)):
        return 'done'
    return 'started' if os.path.isdir(folder) else 'new'


def permissions_text(project: Project, allowed: dict[str, bool]) -> str:
    lines = [f'- {name}: {"allowed" if allowed.get(name) else "not allowed"}' for name in project.permissions]
    return '\n\n---\n\n# Permissions for this run\n\n' + ('\n'.join(lines) or 'Nothing was asked for.') + '\n'


def tools_off(allowed: dict[str, bool]) -> list[str]:
    off = list(TURNED_OFF)
    for name, tools in TOOLS_OF.items():
        if not allowed.get(name):
            off += tools
    return off


def prepare(project: Project, folder: str, allowed: dict[str, bool], rules_dir: str = HERE) -> None:
    """The folder it is built in: what it is given, and the rules, brief and what's allowed in one file."""
    given = os.path.join(os.path.dirname(project.path), project.name)
    if os.path.isdir(given):
        shutil.copytree(given, folder, dirs_exist_ok=True)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(rules_dir, RULES), encoding='utf-8') as f:
        rules = f.read()
    with open(project.path, encoding='utf-8') as f:
        brief = f.read()
    with open(os.path.join(folder, PROMPT), 'w', encoding='utf-8') as f:
        f.write(rules + brief + permissions_text(project, allowed))


def set_aside(folder: str) -> str:
    """Start over without losing what was built: the old folder gets the next free name."""
    number = 1
    while os.path.exists(f'{folder}-old{number}'):
        number += 1
    os.rename(folder, f'{folder}-old{number}')
    return f'{folder}-old{number}'


def first_message(project: Project) -> str:
    return (
        f'Build {project.title}: read {PROMPT} in this folder to its very end, as it takes several reads, '
        f'and do all of it, until {REPORT} is written.'
    )


CONTINUE = f'Carry on with {PROMPT}: PROGRESS.md says where it got to. Go on until {REPORT} is written.'


def open_chat(
    folder: str, first: str, resume: str, allowed: dict[str, bool], model: tuple[str, str, str]
) -> Any:
    """The chat in that folder, with settings of its own so the user's stay as they are."""
    from pycoder import launch

    launch.prepare()  # forgets what is loaded: the code on disk now

    from objc_util import on_main_thread

    from pycoder import config
    from pycoder.frontends.chat.view import ChatView

    made = []

    def present() -> None:
        view = ChatView(root=folder)
        controller = view.controller
        controller.settings_file = os.path.join(config.DATA_DIR, 'tutorial-settings.json')
        controller.settings.deny = list(controller.settings.deny) + tools_off(allowed)
        controller.set_setting('mode', 'bypass' if allowed.get(ALONE) else controller.settings.mode)
        controller.set_setting('model', model[1])
        controller.set_setting('effort', model[2])
        view.present('fullscreen', hide_title_bar=True)
        view.refresh()
        view.start(first, resume)
        made.append(view)

    on_main_thread(present)()
    return made[0]


def wait_for_turn(view: Any) -> None:
    """Until the chat is closed, or its work is over."""
    while view.on_screen and not view.busy:
        time.sleep(1)
    while view.on_screen and (view.busy or view.queue):
        time.sleep(2)


def folder_for(project: Project, home: str, model: tuple[str, str, str]) -> str:
    return os.path.join(home, 'demos', f'{project.name}-{model[0]}')


def build(queue: list[Project], home: str, allowed: dict[str, bool], model: tuple[str, str, str]) -> None:
    """One after another; a project that stopped before its report stays open, to read why."""
    from objc_util import on_main_thread

    view = None
    for number, project in enumerate(queue):
        folder = folder_for(project, home, model)
        started = state(folder) == 'started'
        prepare(project, folder, allowed)
        first = CONTINUE if started else first_message(project)
        view = open_chat(folder, first, 'last' if started else '', allowed, model)
        wait_for_turn(view)
        if state(folder) == 'done' and number < len(queue) - 1:
            on_main_thread(view.close)()
            time.sleep(1)
        else:
            break
    while view is not None and view.on_screen:
        time.sleep(1)


def ios_state(name: str) -> str:
    """What iOS says about this now, without asking anything: allowed, refused, undecided, none or ''."""
    from objc_util import ObjCClass, load_framework

    if name in MEDIA:
        load_framework('AVFoundation')
        status = ObjCClass('AVCaptureDevice').authorizationStatusForMediaType_(MEDIA[name])
        return {0: 'undecided', 3: 'allowed'}.get(status, 'refused')
    if name == 'barometer':
        load_framework('CoreMotion')
        return '' if ObjCClass('CMAltimeter').isRelativeAltitudeAvailable() else 'none'
    return ''


NOTES = {
    'allowed': 'iOS already allows this.',
    'refused': 'iOS has this turned off: change it in Settings, then run this again.',
    'undecided': 'iOS will ask you right after this form.',
    'none': "This device doesn't have one: a replay stands in.",
}


def ask_ios(name: str, wait: float = 60) -> bool:
    """Let iOS ask now, while someone is here to answer. Whether it is allowed afterwards."""
    import ctypes

    from objc_util import ObjCBlock, ObjCClass

    if name == 'notifications':
        import notification

        notification.cancel(notification.schedule('pycoder', delay=3600, identifier='pycoder-tutorial'))
    if name not in MEDIA or ios_state(name) != 'undecided':
        return ios_state(name) not in ('refused', 'none')

    def answered(_block: Any, _granted: bool) -> None:
        pass

    block = ObjCBlock(answered, restype=None, argtypes=[ctypes.c_void_p, ctypes.c_bool])
    _blocks.append(block)  # iOS keeps its address, and calls it later
    ObjCClass('AVCaptureDevice').requestAccessForMediaType_completionHandler_(
        MEDIA[name], ctypes.addressof(block._as_parameter_)
    )
    deadline = time.monotonic() + wait
    while ios_state(name) == 'undecided' and time.monotonic() < deadline:
        time.sleep(0.3)
    return ios_state(name) == 'allowed'


def choose(queue: list[Project], folder_note: str) -> dict[str, bool] | None:
    """What this run may use, chosen by whoever started it; None if they cancelled."""
    import dialogs

    alone = {'type': 'switch', 'key': ALONE, 'title': 'Work without asking', 'value': True}
    sections: list[Any] = [('pycoder', [alone], folder_note)]
    states = {}
    for name, reasons in wanted(queue).items():
        states[name] = ios_state(name)
        field = {
            'type': 'switch',
            'key': name,
            'title': LABELS.get(name, name.capitalize()),
            'value': states[name] not in ('refused', 'none'),
        }
        footer = '\n'.join(reasons + ([NOTES[states[name]]] if states[name] else []))
        sections.append(('', [field], footer))
    answers = dialogs.form_dialog('This run will use', sections=sections)
    if answers is None:
        return None
    allowed = {key: bool(value) for key, value in answers.items()}
    for name in states:
        if allowed[name]:
            allowed[name] = ask_ios(name)
    return allowed


def main() -> None:
    import console
    import dialogs

    from pycoder import config

    home = config.HOME_DIR
    label = dialogs.list_dialog('Build it with', list(MODELS))
    if not label:
        return
    model = MODELS[label]
    available = projects()
    if len(available) == 1:
        queue = available
    else:
        labels = [f'{p.title} ({state(folder_for(p, home, model))})' for p in available]
        everything = 'All of them, one after another'
        chosen = dialogs.list_dialog('Build a demo project', [*labels, everything])
        if not chosen:
            return
        if chosen == everything:
            queue = [p for p in available if state(folder_for(p, home, model)) != 'done']
        else:
            queue = [available[labels.index(chosen)]]
    try:
        if len(queue) == 1:
            folder = folder_for(queue[0], home, model)
            if state(folder) != 'new':
                again = console.alert(queue[0].title, 'It was built before.', 'Carry on', 'Start over')
                if again == 2:
                    set_aside(folder)
                elif state(folder) == 'done':
                    return
    except KeyboardInterrupt:  # Cancel
        return
    note = (
        f'Builds in {os.path.join(home, "demos")} until the report is written, using your API key and '
        f'{label}. Turned off, it asks you before each step, so you have to stay with it.'
    )
    allowed = choose(queue, note)
    if allowed is not None:
        build(queue, home, allowed, model)


if __name__ == '__main__':
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    main()

"""The tutorial's projects: what the runner finds and prepares."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
FOLDER = ROOT / 'tutorial'


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f'tutorial_{name}', FOLDER / f'{name}.py')
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


run = load('run')


def test_the_project_is_found_with_its_title() -> None:
    found = run.projects()
    assert [p.name for p in found] == ['event-horizon']
    assert [p.title for p in found] == ['Event Horizon']


def test_every_skill_a_project_names_exists() -> None:
    names = {path.name for path in (ROOT / 'skills').iterdir()}
    for project in run.projects():
        text = Path(project.path).read_text(encoding='utf-8')
        skills_line = text.split('Skills:', 1)[1].split('\n\n', 1)[0]
        named = [part.split('`')[1] for part in skills_line.split(',') if '`' in part]
        assert named, project.name
        assert set(named) <= names, project.name


def test_a_project_gets_the_rules_and_its_brief_in_one_file(tmp_path: Path) -> None:
    project = run.projects()[0]
    folder = tmp_path / 'event-horizon'
    assert run.state(str(folder)) == 'new'
    run.prepare(project, str(folder), {})
    text = (folder / run.PROMPT).read_text(encoding='utf-8')
    assert text.startswith('# How this run works')
    assert '# Event Horizon' in text
    assert 'REPORT.md' in text
    assert text.endswith('# Permissions for this run\n\nNothing was asked for.\n')
    assert run.state(str(folder)) == 'started'
    (folder / run.REPORT).write_text('done', encoding='utf-8')
    assert run.state(str(folder)) == 'done'


def test_a_project_is_given_only_its_music(tmp_path: Path) -> None:
    run.prepare(run.projects()[0], str(tmp_path / 'p'), {})
    given = sorted(path.name for path in (tmp_path / 'p').iterdir())
    assert given == ['PROMPT.md', 'grand_organ.py', 'midi_notes.py', 'organ_render.py']


def test_the_brief_describes_and_holds_no_code() -> None:
    text = Path(run.projects()[0].path).read_text(encoding='utf-8')
    assert '```' not in text
    assert 'kernel void' not in text


def test_each_model_builds_in_a_folder_of_its_own() -> None:
    project = run.projects()[0]
    folders = {run.folder_for(project, '/home', model) for model in run.MODELS.values()}
    assert folders == {'/home/demos/event-horizon-haiku', '/home/demos/event-horizon-opus'}


def test_starting_over_keeps_what_was_built(tmp_path: Path) -> None:
    folder = tmp_path / 'p'
    for _ in range(2):
        folder.mkdir()
        (folder / 'made.py').write_text('x', encoding='utf-8')
        run.set_aside(str(folder))
    assert run.state(str(folder)) == 'new'
    assert (tmp_path / 'p-old1' / 'made.py').exists()
    assert (tmp_path / 'p-old2' / 'made.py').exists()


def test_permissions_section_ends_at_the_next_heading() -> None:
    text = '# T\n\n## Permissions\n\n- camera: to see\n- my-thing: mine\n\n## Milestones\n\n- not: this\n'
    assert run.permissions_in(text) == {'camera': 'to see', 'my-thing': 'mine'}
    assert run.permissions_in('# T\n') == {}


def test_several_projects_share_one_question_with_each_reason() -> None:
    one = run.Project('a', 'A', '', {'camera': 'to see'})
    two = run.Project('b', 'B', '', {'camera': 'to read', 'motion': 'to tilt'})
    assert run.wanted([one]) == {'camera': ['to see']}
    assert run.wanted([one, two]) == {'camera': ['A: to see', 'B: to read'], 'motion': ['B: to tilt']}


def test_a_prompt_says_what_was_refused() -> None:
    project = run.Project('a', 'A', '', {'camera': 'to see', 'motion': 'to tilt'})
    text = run.permissions_text(project, {'motion': True, 'camera': False})
    assert '- camera: not allowed' in text
    assert '- motion: allowed' in text


def test_a_tool_stays_off_unless_its_permission_was_given() -> None:
    off = run.tools_off({})
    for tool in ('ask_user', 'git(push*)', 'install_package', 'web_search', 'web_fetch', 'record_audio'):
        assert tool in off
    assert 'web_search' not in run.tools_off({'network': True})
    assert 'record_audio' not in run.tools_off({'microphone': True})


def test_every_project_ends_in_a_video() -> None:
    assert 'demo.mp4' in (FOLDER / 'rules.md').read_text(encoding='utf-8')

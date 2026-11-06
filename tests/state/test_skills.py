"""Skills and Markdown prompt commands."""

from __future__ import annotations

import glob
import os
import re
from typing import Any

import pytest

from pycoder.app import prompt_commands
from pycoder.state import skills


def test_skill_round_trip(tmp_path: Any) -> None:
    library = skills.SkillLibrary(str(tmp_path))
    library.save('pure-wheels', 'Use when  installing wheels', 'Steps')
    assert library.get('pure-wheels') == skills.Skill(
        'pure-wheels', 'Use when installing wheels', 'Steps', str(tmp_path / 'pure-wheels' / 'SKILL.md')
    )
    with pytest.raises(ValueError, match='lowercase'):
        library.save('Bad Name', 'x', 'y')


def test_prompt_command_arguments() -> None:
    cmd = prompt_commands.parse('fix', 'Fix the bug.', 'fix.md')
    assert cmd.render('in app.py') == 'Fix the bug.\n\nin app.py'
    assert cmd.description == 'Fix the bug.'


def test_bundled_skills_say_when_to_use_them() -> None:
    """The prompt lists only each skill's description, so it must say when the skill applies."""
    from pycoder import config

    library = skills.SkillLibrary(config.SKILLS_DIR)
    found = library.all()
    assert {'improving-pycoder', 'live-information'} <= {s.name for s in found}
    for skill in found:
        assert skill.description.startswith('Use when'), skill.name
        assert len(skill.description) < 250, skill.name
        assert skill.body.strip(), skill.name


def yaml_fields(text: str) -> dict[str, str]:
    """The file's header as a YAML parser reads it. compose, as safe_load fails on Pythonista's old
    PyYAML, whatever it is given."""
    yaml = pytest.importorskip('yaml')
    return {key.value: value.value for key, value in yaml.compose(text.split('---')[1]).value}


def test_bundled_skills_stay_short() -> None:
    """One is read whole when a task matches it: split a skill that grows."""
    from pycoder import config

    for path in glob.glob(os.path.join(config.SKILLS_DIR, '*', 'SKILL.md')):
        with open(path, encoding='utf-8') as f:
            text = f.read()
        assert len(text.splitlines()) <= 60, path
        assert len(text) <= 4000, path


def test_bundled_skills_report_no_measurements() -> None:
    """A skill says how to do something, not how fast it was on one device."""
    from pycoder import config

    measured = re.compile(
        r'\b\d+(\.\d+)?\s?(ms|fps|GFLOPS|µs)\b|\bM2 Pro\b|\bA17\b|\d+(\.\d+)?x (on|faster)', re.I
    )
    for path in glob.glob(os.path.join(config.SKILLS_DIR, '*', 'SKILL.md')):
        with open(path, encoding='utf-8') as f:
            assert not measured.search(f.read()), path


def test_bundled_skills_name_only_skills_that_exist() -> None:
    from pycoder import config

    names = {
        os.path.basename(os.path.dirname(p))
        for p in glob.glob(os.path.join(config.SKILLS_DIR, '*', 'SKILL.md'))
    }
    for path in glob.glob(os.path.join(config.SKILLS_DIR, '*', 'SKILL.md')):
        with open(path, encoding='utf-8') as f:
            for word in re.findall(r'`([a-z0-9]+(?:-[a-z0-9]+)+)`', f.read()):
                if word.startswith(
                    ('pythonista-', 'scene-', 'scenekit-', 'checking-', 'sensor-', 'accelerate-', 'vision-')
                ):
                    assert word in names, (path, word)


def test_bundled_skills_are_valid_yaml_for_other_tools() -> None:
    from pycoder import config

    for skill in skills.SkillLibrary(config.SKILLS_DIR).all():
        with open(skill.path, encoding='utf-8') as f:
            assert yaml_fields(f.read())['description'] == skill.description, skill.name


def test_a_description_with_a_colon_is_quoted_and_comes_back(tmp_path: Any) -> None:
    library = skills.SkillLibrary(str(tmp_path))
    for description in ('Use when: a colon', 'Use when "quotes": 中文 # and so on', 'Use when plain'):
        library.save('one', description, 'Body')
        assert library.get('one').description == description  # type: ignore[union-attr]
        with open(tmp_path / 'one' / 'SKILL.md', encoding='utf-8') as f:
            assert yaml_fields(f.read())['description'] == description


def test_quotes_written_by_hand_are_read(tmp_path: Any) -> None:
    folder = tmp_path / 'hand'
    folder.mkdir()
    (folder / 'SKILL.md').write_text(
        "---\nname: hand\ndescription: 'Use when it''s: quoted'\n---\n\nBody\n", encoding='utf-8'
    )
    assert skills.SkillLibrary(str(tmp_path)).get('hand').description == "Use when it's: quoted"  # type: ignore[union-attr]


def test_learned_skills_stay_out_of_the_repository_and_keep_the_format(tmp_path: Any) -> None:
    bundled, learned = tmp_path / 'repo', tmp_path / 'data'
    (bundled / 'a').mkdir(parents=True)
    (bundled / 'a' / 'SKILL.md').write_text(
        '---\nname: a\ndescription: Use when a\n---\nold\n', encoding='utf-8'
    )
    library = skills.SkillLibrary(str(bundled), str(learned))
    library.save('b', 'Use when b', 'body')
    assert (learned / 'b' / 'SKILL.md').exists()
    assert not (bundled / 'b').exists()
    library.save('a', 'Use when a', 'new')  # replaces the bundled one here, leaves the clone alone
    assert [s.name for s in library.all()] == ['a', 'b']
    got = library.get('a')
    assert got is not None
    assert got.body == 'new'
    assert 'old' in (bundled / 'a' / 'SKILL.md').read_text(encoding='utf-8')
    with pytest.raises(ValueError, match='Use when'):
        library.save('c', 'How to do c', 'body')
    with pytest.raises(ValueError, match='under 250'):
        library.save('c', 'Use when ' + 'x' * 250, 'body')


def test_skills_can_be_read_while_ios_keeps_their_folder_closed(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = skills.SkillLibrary(str(tmp_path))
    library.save('open-a-file', 'Use when a file has to be opened', 'How to do it')
    assert library.get('open-a-file') is not None

    def closed(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError(1, 'Operation not permitted')

    monkeypatch.setattr(os, 'listdir', closed)
    monkeypatch.setattr('builtins.open', closed)
    skill = skills.SkillLibrary(str(tmp_path)).get('open-a-file')  # a new one, as each tool call makes
    assert skill is not None
    assert skill.body == 'How to do it'

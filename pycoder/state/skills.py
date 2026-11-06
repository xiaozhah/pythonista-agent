"""Skills: how to do a kind of task, kept as Markdown.

A skill is skills/<name>/SKILL.md with a small header:

    ---
    name: install-pure-python-packages
    description: "Use when a task needs a PyPI package: installing one without pip, and what works on iOS"
    ---
    (the procedure, in plain Markdown)

Only names and descriptions go into the system prompt; read_skill loads one in full when needed.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from ..host import env

_HEADER = re.compile(r'^---\s*\n(.*?)\n---\s*\n?(.*)$', re.S)
_NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
MAX_DESCRIPTION = 250


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: str


def parse(text: str, path: str = '') -> Skill | None:
    m = _HEADER.match(text)
    if not m:
        return None
    fields = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(':')
        fields[key.strip()] = _unquoted(value.strip())
    if not fields.get('name') or not fields.get('description'):
        return None
    return Skill(fields['name'], fields['description'], m.group(2).strip(), path)


def _quoted(value: str) -> str:
    """As YAML takes it: other tools read these files too, and a bare `: ` or ` #` means something there."""
    return json.dumps(value, ensure_ascii=False) if ': ' in value or ' #' in value else value


def _unquoted(value: str) -> str:
    if len(value) > 1 and value[0] == value[-1] == '"':
        try:
            return str(json.loads(value))
        except ValueError:
            return value
    if len(value) > 1 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def render(name: str, description: str, body: str) -> str:
    return '---\nname: {}\ndescription: {}\n---\n\n{}\n'.format(
        name, _quoted(' '.join(description.split())), body.strip()
    )


_seen: dict[str, Skill | None] = {}  # every file read: the repository may be in another app's folder,
# which iOS closes while the phone is locked, and work goes on then


def _skill_files(directory: str) -> list[str]:
    try:
        return [os.path.join(directory, name, 'SKILL.md') for name in os.listdir(directory)]
    except FileNotFoundError:
        return []
    except OSError:
        return [path for path in _seen if os.path.dirname(os.path.dirname(path)) == directory]


def _read(path: str) -> Skill | None:
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            _seen[path] = parse(f.read(), path)
    except (FileNotFoundError, NotADirectoryError):
        _seen.pop(path, None)
        return None
    except OSError:
        pass
    return _seen.get(path)


class SkillLibrary:
    """The skills that come with pycoder (in the repository) and those learned on this device (kept
    with its other data, not in the clone); a learned one replaces a bundled one of its name."""

    def __init__(self, directory: str, learned: str = '') -> None:
        self.directory = directory
        self.learned = learned

    def all(self) -> list[Skill]:
        found: dict[str, Skill] = {}
        for directory in filter(None, (self.directory, self.learned)):
            for path in _skill_files(directory):
                skill = _read(path)
                if skill:
                    found[skill.name] = skill
        return [found[name] for name in sorted(found)]

    def get(self, name: str) -> Skill | None:
        return next((s for s in self.all() if s.name == name), None)

    def save(self, name: str, description: str, body: str) -> str:
        if not _NAME.match(name):
            raise ValueError('Skill names use lowercase letters, digits and hyphens, e.g. install-wheels')
        # every future system prompt carries this line, so it must say when to read the skill
        if not description.startswith('Use when'):
            raise ValueError('A skill description starts with "Use when …": which tasks need it')
        if len(description) >= MAX_DESCRIPTION:
            raise ValueError(f'A skill description is one line, under {MAX_DESCRIPTION} characters')
        path = os.path.join(self.learned or self.directory, name, 'SKILL.md')
        env.write_text(path, render(name, description, body))
        return path

    def prompt_section(self) -> str:
        skills = self.all()
        if not skills:
            return ''
        lines = ['Skills:']
        lines += [f'- {s.name}: {s.description}' for s in skills]
        return '\n'.join(lines)

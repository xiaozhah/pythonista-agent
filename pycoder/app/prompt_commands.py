"""Custom slash commands written as Markdown prompt templates, in the Claude Code format.

commands/<name>.md (next to pycoder) or .claude/commands/<name>.md (in the workspace, shared with
Claude Code). `/name some text` sends the file's text as a message, with $ARGUMENTS replaced by
"some text". An optional header sets the help line:

    ---
    description: Review the current changes
    ---
    Review the uncommitted changes in $ARGUMENTS and list problems by severity.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_HEADER = re.compile(r'^---\s*\n(.*?)\n---\s*\n?', re.S)


@dataclass
class PromptCommand:
    name: str
    description: str
    template: str
    path: str

    def render(self, arguments: str) -> str:
        text = self.template.replace('$ARGUMENTS', arguments)
        if arguments and '$ARGUMENTS' not in self.template:
            text += '\n\n' + arguments
        return text


def parse(name: str, text: str, path: str) -> PromptCommand:
    description = ''
    m = _HEADER.match(text)
    if m:
        for line in m.group(1).splitlines():
            key, _, value = line.partition(':')
            if key.strip() == 'description':
                description = value.strip()
        text = text[m.end() :]
    body = text.strip()
    return PromptCommand(name, description or body.splitlines()[0][:60] if body else name, body, path)


def load(directories: list[str]) -> list[PromptCommand]:
    """Commands from each directory in order; an earlier directory wins a name clash."""
    found: dict[str, PromptCommand] = {}
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        for file in sorted(os.listdir(directory)):
            name, ext = os.path.splitext(file)
            if ext == '.md' and name not in found:
                path = os.path.join(directory, file)
                with open(path, encoding='utf-8-sig', errors='replace') as f:
                    found[name] = parse(name, f.read(), path)
    return list(found.values())

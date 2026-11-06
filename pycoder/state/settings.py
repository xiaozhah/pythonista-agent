"""User settings: what /config can change, how values are checked, and keeping them between runs.

Settings live in .pycoder/settings.json, which stays on this device (it is not in git).
Each setting is described once in SPECS; /config, its Tab completion and the app's settings
panel are all built from that list, so adding a setting means adding one entry here and a field
to Settings below.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from .. import config


@dataclass
class Settings:
    model: str = config.DEFAULT_MODEL
    effort: str = 'medium'  # the models' own default; /effort raises it for hard problems
    mode: str = 'default'  # permission mode: default, acceptEdits, plan or bypass (see agent/permissions.py)
    allow: list[str] = field(default_factory=list)  # permission rules, e.g. git(status*) or edit_file(src/*)
    ask: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    web: bool = True  # offer web_search / web_fetch (fixed per session)
    memory: bool = True  # auto memory: notes kept between sessions (fixed per session)
    auto_update: bool = True  # fetch new versions in the background; installed at the next start
    notify: bool = True  # a notification when a long request ends or needs you while you're away
    # prompt cache lifetime. 1h: writing costs 2x input instead of 1.25x, but one pause of 5-60 minutes
    # (common on a phone) would otherwise rewrite the whole context, so 1h is cheaper over a session
    cache_ttl: str = '1h'
    compact_at: int = 200_000  # compact once a request's context reaches this many tokens
    font_size: int = 16  # app chat text, in points
    code_font: str = 'SF Mono'  # code in the chat: SF Mono, Menlo or Courier
    theme: str = 'auto'  # app colours: auto (follow iOS), light or dark


@dataclass(frozen=True)
class SettingSpec:
    name: str
    label: str
    kind: str  # 'choice', 'int' or 'bool'
    help: str
    choices: tuple[str, ...] = ()
    minimum: int = 0
    maximum: int = 0
    step: int = 1


SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(
        'font_size', 'Font size', 'int', 'chat text size in the app, in points', minimum=12, maximum=26
    ),
    SettingSpec(
        'code_font',
        'Code font',
        'choice',
        'for code, diffs and commands in the chat',
        choices=('SF Mono', 'Menlo', 'Courier'),
    ),
    SettingSpec('theme', 'Theme', 'choice', 'app colours', choices=('auto', 'light', 'dark')),
    SettingSpec(
        'model', 'Model', 'choice', 'the model for new requests', choices=tuple(m.id for m in config.MODELS)
    ),
    SettingSpec('effort', 'Thinking effort', 'choice', 'how hard the model thinks', choices=config.EFFORTS),
    SettingSpec(
        'mode',
        'Permission mode',
        'choice',
        'when to ask before changing files or running code',
        choices=('default', 'acceptEdits', 'plan', 'bypass'),
    ),
    SettingSpec('web', 'Web tools', 'bool', 'web search and fetch (from the next session)'),
    SettingSpec('memory', 'Auto memory', 'bool', 'keep notes between sessions (from the next session)'),
    SettingSpec(
        'auto_update', 'Auto-update', 'bool', 'get new versions of pycoder; installed at the next start'
    ),
    SettingSpec(
        'notify',
        'Notifications',
        'bool',
        'when a request finishes or needs approval while you are in another app',
    ),
    SettingSpec(
        'cache_ttl',
        'Prompt cache',
        'choice',
        '1h costs more to write but survives pauses; 5m is cheaper if you always reply within minutes',
        choices=config.CACHE_TTLS,
    ),
    SettingSpec(
        'compact_at',
        'Auto-compact at',
        'int',
        'tokens of context before summarizing (0 = never)',
        minimum=0,
        maximum=900_000,
        step=10_000,
    ),
)
SPEC_BY_NAME = {s.name: s for s in SPECS}
RULE_LISTS = ('allow', 'ask', 'deny')  # permission rules: saved too, changed with /permissions


def parse(spec: SettingSpec, raw: Any) -> Any:
    """A checked value for `spec` from user input (text or an already-typed value); ValueError if invalid."""
    if spec.kind == 'bool':
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ('on', 'true', 'yes', '1'):
            return True
        if text in ('off', 'false', 'no', '0'):
            return False
        raise ValueError(f'{spec.name} is on or off')
    if spec.kind == 'int':
        try:
            value = int(str(raw).replace(',', '').replace('_', '').strip())
        except ValueError:
            raise ValueError(f'{spec.name} must be a whole number') from None
        if not spec.minimum <= value <= spec.maximum:
            raise ValueError(f'{spec.name} must be between {spec.minimum} and {spec.maximum}')
        return value
    text = str(raw).strip()
    if spec.name == 'model':
        text = config.resolve_model(text) or text
    if text not in spec.choices:
        raise ValueError(f'{spec.name} must be one of {", ".join(spec.choices)}')
    return text


def display(spec: SettingSpec, value: Any) -> str:
    if spec.kind == 'bool':
        return 'on' if value else 'off'
    if spec.kind == 'int' and value >= 10_000:
        return f'{value:,}'
    return str(value)


def load(path: str) -> Settings:
    """Saved settings over the defaults; unknown or invalid entries are ignored."""
    settings = Settings()
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return settings
    if not isinstance(data, dict):
        return settings
    for name in RULE_LISTS:
        value = data.get(name)
        if isinstance(value, list):
            setattr(settings, name, [str(r) for r in value])
    for name, raw in data.items():
        spec = SPEC_BY_NAME.get(name)
        if spec is not None:
            try:
                setattr(settings, name, parse(spec, raw))
            except ValueError:
                pass  # e.g. a model that no longer exists: keep the default
    return settings


def save(path: str, settings: Settings) -> None:
    """Saves the permission rules and the settings that differ from the defaults, so a better
    default reaches everyone who never chose otherwise."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    defaults = Settings()
    data = {
        f.name: getattr(settings, f.name)
        for f in fields(settings)
        if f.name in RULE_LISTS
        or (f.name in SPEC_BY_NAME and getattr(settings, f.name) != getattr(defaults, f.name))
    }
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def as_dict(settings: Settings) -> dict[str, Any]:
    return asdict(settings)

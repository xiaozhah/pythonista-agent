"""Commands that change how pycoder works: model, effort, permission mode and rules, settings."""

from __future__ import annotations

from ... import config
from ...agent import permissions
from ...state import settings
from .. import reports
from ..controller import Controller
from .base import Command


def _model(c: Controller, arg: str) -> None:
    model = config.resolve_model(arg) if arg else None
    if model is None:
        labels = [f'{m.short} — {m.description}' for m in config.MODELS]
        ids = [m.id for m in config.MODELS]
        current = ids.index(c.settings.model) if c.settings.model in ids else None
        choice = c.frontend.choose('Choose a model', labels, current)
        if choice is None:
            return
        model = config.MODELS[choice].id
    c.set_model(model)
    c.frontend.notice(f'Model: {model} (conversation kept)')


EFFORT_HELP = {
    'low': 'quickest and cheapest, for simple questions',
    'medium': 'the default: a balance of speed and care',
    'high': 'more careful, for tricky changes',
    'xhigh': 'more thorough, for hard problems',
    'max': 'thinks the longest',
}


def _effort(c: Controller, arg: str) -> None:
    """/effort [level]: without a level, pick one from a list."""
    if not arg:
        labels = [f'{e} — {EFFORT_HELP.get(e, "")}' for e in config.EFFORTS]
        current = config.EFFORTS.index(c.settings.effort) if c.settings.effort in config.EFFORTS else None
        choice = c.frontend.choose('How hard should the model think?', labels, current)
        if choice is None:
            return
        arg = config.EFFORTS[choice]
    try:
        c.set_setting('effort', arg)
    except ValueError as e:
        c.frontend.notice(str(e), 'error')
        return
    c.frontend.notice(f'Thinking effort: {c.settings.effort}')


def pick_mode(c: Controller) -> None:
    """The permission mode, picked from a list (the mode button, the ⋯ menu and /mode)."""
    labels = [f'{permissions.MODE_LABELS[m]} — {permissions.MODE_HELP[m]}' for m in permissions.MODES]
    current = permissions.MODES.index(c.settings.mode) if c.settings.mode in permissions.MODES else None
    picked = c.frontend.choose('When should pycoder ask you?', labels, current)
    if picked is not None:
        _mode(c, permissions.MODES[picked])


def _mode(c: Controller, arg: str) -> None:
    """/mode [mode]: without a mode, pick one from a list."""
    if not arg:
        pick_mode(c)
        return
    mode = arg
    try:
        c.policy.set_mode(mode)
    except ValueError as e:
        c.frontend.notice(str(e), 'error')
        return
    c.frontend.notice(f'{permissions.MODE_LABELS[mode]}: {permissions.MODE_HELP[mode]}')


def _plan(c: Controller, arg: str) -> None:
    _mode(c, 'plan')
    if arg:  # /plan <task> starts planning it right away
        c.run_turn(arg)


ON_OFF = ['on', 'off']


def _switch(c: Controller, arg: str, now: bool) -> bool | None:
    """on / off from the argument, or the opposite of `now` without one; None (reported) if invalid."""
    if not arg:
        return not now
    if arg.lower() not in ('on', 'off'):
        c.frontend.notice('Say on or off', 'error')
        return None
    return arg.lower() == 'on'


def _bypass(c: Controller, arg: str) -> None:
    on = _switch(c, arg, c.settings.mode == 'bypass')
    if on is not None:
        _mode(c, 'bypass' if on else 'default')


def _permissions(c: Controller, arg: str) -> None:
    words = arg.split(None, 2)
    if len(words) >= 2 and words[0] in ('allow', 'ask', 'deny'):
        kind, rule = words[0], ' '.join(words[1:])
        try:
            c.policy.edit_rules(kind, rule)
        except ValueError as e:
            c.frontend.notice(str(e), 'error')
            return
        c.frontend.notice(f'Added {kind} rule {rule}')
        return
    if len(words) >= 3 and words[0] == 'remove':
        try:
            c.policy.edit_rules(words[1], words[2], remove=True)
        except ValueError as e:
            c.frontend.notice(str(e), 'error')
            return
        c.frontend.notice(f'Removed {words[1]} rule {words[2]}')
        return
    s = c.settings
    lines = [f'Mode: {permissions.MODE_LABELS[s.mode]} — {permissions.MODE_HELP[s.mode]}  (/mode to change)']
    for kind in ('deny', 'ask', 'allow'):
        rules = getattr(s, kind)
        lines.append(f'{kind}: ' + (', '.join(_rule_label(r) for r in rules) if rules else '(none)'))
    lines.append(
        'Rules: tool or tool(pattern), e.g. git(status*), edit_file(src/*), run_python() for inline code. '
        'Deny wins over ask, ask over allow.'
    )
    lines.append('/permissions allow|ask|deny <rule> · /permissions remove allow|ask|deny <rule>')
    c.frontend.notice('\n'.join(lines))


def _rule_label(rule: str) -> str:
    try:
        permissions.parse_rule(rule)
    except ValueError:
        return f'{rule} ✗ (not a valid rule; ignored)'
    return rule


def _web(c: Controller, arg: str) -> None:
    on = _switch(c, arg, c.settings.web)
    if on is None:
        return
    c.set_setting('web', on)
    c.frontend.notice(
        'Web tools: %s, from the next session (/clear); tools are fixed within a session'
        % ('on' if c.settings.web else 'off')
    )


def _config(c: Controller, arg: str) -> None:
    name, _, value = arg.partition(' ')
    if name and value:
        try:
            result = c.set_setting(name, value.strip())
        except ValueError as e:
            c.frontend.notice(str(e), 'error')
            return
        c.frontend.notice(f'{name} = {settings.display(settings.SPEC_BY_NAME[name], result)}')
        return
    if name:
        spec = settings.SPEC_BY_NAME.get(name)
        if spec is None:
            c.frontend.notice(f'Unknown setting {name}', 'error')
            return
        c.frontend.notice(f'{name} = {settings.display(spec, getattr(c.settings, name))}  ({spec.help})')
        return
    tabs = {'Status': reports.status(c), 'Usage': reports.usage(c)}
    edited = c.frontend.edit_settings(settings.SPECS, settings.as_dict(c.settings), tabs)
    if edited == {}:  # cancelled
        return
    if edited is None:  # no settings panel here: list them
        lines = ['Settings (/config <name> <value> to change):']
        lines += [
            f'  {s.name:<11} {settings.display(s, getattr(c.settings, s.name)):<18} {s.help}'
            for s in settings.SPECS
        ]
        c.frontend.notice('\n'.join(lines))
        return
    changed = []
    for name_, raw in edited.items():
        if name_ in settings.SPEC_BY_NAME and raw != getattr(c.settings, name_):
            try:
                c.set_setting(name_, raw)
                changed.append(name_)
            except ValueError as e:
                c.frontend.notice(str(e), 'error')
    c.frontend.notice('Saved: ' + ', '.join(changed) if changed else 'No changes')


def _config_options(c: Controller) -> list[str]:
    options = []
    for s in settings.SPECS:
        options.append(s.name)
        values = s.choices if s.kind == 'choice' else ('on', 'off') if s.kind == 'bool' else ()
        options += [f'{s.name} {v}' for v in values]
    return options


def _key(c: Controller, arg: str) -> None:
    c.reset_api_key()


COMMANDS = [
    Command('model', 'switch model', _model, '[name]', lambda c: [m.short for m in config.MODELS]),
    Command('effort', 'thinking effort', _effort, '[level]', lambda c: list(config.EFFORTS)),
    Command('config', 'settings: font size, theme, model, …', _config, '[name] [value]', _config_options),
    Command(
        'mode',
        'permission mode: default, acceptEdits, plan, bypass (no argument: pick one)',
        _mode,
        '[mode]',
        lambda c: list(permissions.MODES),
    ),
    Command('plan', 'plan mode: research and propose a plan before changing anything', _plan, '[task]'),
    Command(
        'permissions',
        'show or edit allow / ask / deny rules',
        _permissions,
        '[allow|ask|deny|remove ...]',
        lambda c: ['allow ', 'ask ', 'deny ', 'remove '],
    ),
    Command('bypass', 'bypass mode on or off (no argument: switch)', _bypass, '[on|off]', lambda c: ON_OFF),
    Command('web', 'web search and fetch on or off (next session)', _web, '[on|off]', lambda c: ON_OFF),
    Command('key', 'replace the API key', _key),
]

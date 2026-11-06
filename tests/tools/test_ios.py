"""Device tools, run on the Mac against fake Pythonista modules."""

from __future__ import annotations

import sys
import types
from typing import Any, ClassVar

import pytest

from pycoder.agent import permissions
from pycoder.agent.loop import tool_result
from pycoder.host import env
from pycoder.tools import ios, registry
from tests.conftest import FakeTransport, RecordingFrontend, text_reply, tool_reply


def tool(name: str) -> Any:
    return next(t for t in ios.COMMON + ios.PYTHONISTA if t.name == name)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Install a fake module: fake('clipboard', get=lambda: 'x')."""

    def install(name: str, **attrs: Any) -> types.ModuleType:
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    return install


@pytest.fixture
def ctx(make_controller: Any) -> Any:
    from pycoder.tools.base import ToolContext

    c = make_controller()
    return ToolContext(c.workspace, c.frontend, c.session, c.checkpoints, c.cancel)


def test_ask_user_through_the_frontend(make_controller: Any) -> None:
    question = {'question': 'Which database?', 'options': ['sqlite', 'postgres']}
    api = FakeTransport([tool_reply('ask_user', question), text_reply('ok')])
    c = make_controller(api, RecordingFrontend(choice=1))
    c.run_turn('set up storage')
    assert api.requests[1]['messages'][-1]['content'][0]['content'] == 'The user chose: postgres'
    assert 'ask_user' in [t['name'] for t in api.requests[0]['tools']]


def test_device_tools_only_in_pythonista(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env, 'IN_PYTHONISTA', False)
    assert 'location' not in [t.name for t in registry.main_tools()]
    monkeypatch.setattr(env, 'IN_PYTHONISTA', True)
    assert 'location' in [t.name for t in registry.main_tools()]


def test_private_tools_ask_first() -> None:
    def action(name: str, inp: dict[str, Any]) -> str:
        return permissions.decide(tool(name), inp, 'default', [], [], []).action

    assert action('location', {}) == 'ask'
    assert action('clipboard_read', {}) == 'ask'
    assert action('photos', {'action': 'recent'}) == 'ask'
    assert action('photos', {'action': 'pick'}) == 'allow'  # the user picks in the system picker
    assert action('speak', {'text': 'hi'}) == 'allow'
    assert (
        action('location', {}) == permissions.decide(tool('location'), {}, 'acceptEdits', [], [], []).action
    )


def test_clipboard_image_comes_back_as_an_image(ctx: Any, fake: Any) -> None:
    from PIL import Image

    fake('clipboard', get=lambda: '', get_image=lambda: Image.new('RGB', (4, 4)))
    result = tool('clipboard_read').run(ctx)
    assert result[0]['type'] == 'image'
    block = tool_result('t1', result)
    assert block['content'][1]['text'] == 'The clipboard holds this image'


def test_recent_photos_newest_first(ctx: Any, fake: Any) -> None:
    from PIL import Image

    def asset(n: int) -> Any:
        return types.SimpleNamespace(creation_date=f'day {n}', get_image=lambda: Image.new('RGB', (2, 2)))

    fake('photos', get_assets=lambda kind: [asset(1), asset(2), asset(3)])
    result = tool('photos').run(ctx, action='recent', count=2)
    assert [b['text'] for b in result if b['type'] == 'text'] == ['taken day 3', 'taken day 2']


def test_recording_is_transcribed_and_deleted(ctx: Any, fake: Any) -> None:
    import os

    paths: list[str] = []

    class Recorder:
        meters: ClassVar[dict[str, tuple[float, float]]] = {'average': (-40.0, -42.0), 'peak': (-12.0, -15.0)}

        def __init__(self, path: str) -> None:
            paths.append(path)

        def record(self) -> None:
            with open(paths[0], 'w') as f:
                f.write('audio')

        def stop(self) -> None: ...

    fake('sound', Recorder=Recorder)
    fake('speech', recognize=lambda path: [('hello there', 0.9), ('hello their', 0.4)])
    out = tool('record_audio').run(ctx, seconds=1)
    assert out.startswith('Level: average -40 dB, peak -12 dB')
    assert out.endswith('Transcript: hello there')
    assert not os.path.exists(paths[0])


def test_shortcut_output_comes_back_through_the_clipboard(ctx: Any, fake: Any) -> None:
    opened: list[str] = []
    board = ['before']
    fake('clipboard', get=lambda: board[0])

    def open_url(url: str) -> None:
        opened.append(url)
        board[0] = 'shortcut output'

    fake('webbrowser', open=open_url)
    result = tool('run_shortcut').run(ctx, name='Make GIF', input='a b', wait=5)
    assert opened == ['shortcuts://run-shortcut?name=Make%20GIF&input=text&text=a%20b']
    assert result.endswith('shortcut output')


def test_location_with_address(ctx: Any, fake: Any) -> None:
    fix = {'latitude': 31.2, 'longitude': 121.5, 'horizontal_accuracy': 10.0}
    fake(
        'location',
        start_updates=lambda: None,
        stop_updates=lambda: None,
        get_location=lambda: fix,
        reverse_geocode=lambda f: [{'Street': 'Nanjing Rd', 'City': 'Shanghai', 'Country': 'China'}],
    )
    result = tool('location').run(ctx)
    assert 'latitude=31.2' in result
    assert result.endswith('address: Nanjing Rd, Shanghai')


def test_ask_user_notifies_when_away(make_controller: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeTransport([tool_reply('ask_user', {'question': 'Which port?'}), text_reply('ok')])
    c = make_controller(api)
    calls: list[str] = []
    monkeypatch.setattr(c, '_attention', calls.append)
    c.run_turn('serve it')
    assert calls == ['Which port?']


@pytest.mark.skipif(not env.IN_PYTHONISTA, reason='needs the screen')
def test_look_at_screen_returns_an_image() -> None:
    text, image = ios.look_at_screen(None, wait=0)  # type: ignore[arg-type]
    assert text['text'] == 'The screen now:'
    assert image['type'] == 'image'
    assert image['source']['data']

"""recognize_text, run on the Mac against fake Vision objects."""

from __future__ import annotations

import os
import sys
import types
from typing import Any

import pytest

from pycoder.tools import vision
from pycoder.tools.base import ToolError


class Fake:
    """An Objective-C object: any selector is a method; set_* calls are recorded."""

    def __init__(self, calls: dict[str, Any], **methods: Any) -> None:
        self.calls = calls
        self.methods = methods

    def __getattr__(self, name: str) -> Any:
        if name in self.methods:
            return self.methods[name]

        def record(*args: Any) -> Fake:
            self.calls[name] = args
            return self

        return record


@pytest.fixture
def vision_fake(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {'lines': ['Hello pycoder', '今天多云']}

    def candidate(text: str) -> Fake:
        return Fake(calls, string=lambda: text)

    def observation(text: str) -> Fake:
        return Fake(calls, topCandidates_=lambda n: [candidate(text)])

    request = Fake(
        calls,
        respondsToSelector_=lambda sel: calls.get('auto_supported', True),
        results=lambda: [observation(t) for t in calls['lines']],
    )

    def perform(requests: Any, error: Any) -> bool:
        calls['performed'] = calls['url']
        return bool(calls.get('ok', True))

    handler = Fake(calls, performRequests_error_=perform)

    def objc_class(name: str) -> Any:
        if name == 'VNRecognizeTextRequest':
            return Fake(calls, alloc=lambda: Fake(calls, init=lambda: request))

        def init_with_url(url: str, options: Any) -> Fake:
            calls['url'] = url
            return handler

        return Fake(calls, alloc=lambda: Fake(calls, initWithURL_options_=init_with_url))

    module = types.ModuleType('objc_util')
    module.ObjCClass = objc_class  # type: ignore[attr-defined]
    module.ns = lambda obj: obj  # type: ignore[attr-defined]
    module.nsurl = lambda path: path  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'objc_util', module)
    return calls


@pytest.fixture
def ctx(make_controller: Any) -> Any:
    from pycoder.tools.base import ToolContext

    c = make_controller()
    return ToolContext(c.workspace, c.frontend, c.session, c.checkpoints, c.cancel)


def test_reads_a_workspace_image_with_automatic_languages(ctx: Any, vision_fake: dict[str, Any]) -> None:
    with open(os.path.join(ctx.workspace.root, 'receipt.png'), 'wb') as f:
        f.write(b'png')
    assert vision.recognize_text(ctx, path='receipt.png') == 'Hello pycoder\n今天多云'
    assert vision_fake['performed'].endswith('receipt.png')
    assert vision_fake['setAutomaticallyDetectsLanguage_'] == (True,)
    assert 'setRecognitionLanguages_' not in vision_fake


def test_without_automatic_detection_chinese_is_still_read(ctx: Any, vision_fake: dict[str, Any]) -> None:
    """Vision's default is English alone, which drops Chinese lines without a word."""
    vision_fake['auto_supported'] = False
    with open(os.path.join(ctx.workspace.root, 'a.png'), 'wb') as f:
        f.write(b'png')
    vision.recognize_text(ctx, path='a.png')
    assert vision_fake['setRecognitionLanguages_'] == (vision.FALLBACK_LANGUAGES,)
    vision.recognize_text(ctx, path='a.png', languages='ja-JP, en-US')
    assert vision_fake['setRecognitionLanguages_'] == (['ja-JP', 'en-US'],)


def test_clipboard_image_goes_through_a_temporary_file(
    ctx: Any, vision_fake: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[str] = []

    class Image:
        def save(self, path: str) -> None:
            saved.append(path)
            open(path, 'wb').close()

    board = types.ModuleType('clipboard')
    board.get_image = lambda: Image()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'clipboard', board)
    vision_fake['lines'] = []
    assert vision.recognize_text(ctx, source='clipboard') == 'No text found in the image'
    assert vision_fake['performed'] == saved[0]
    assert not os.path.exists(saved[0])
    board.get_image = lambda: None  # type: ignore[attr-defined]
    assert vision.recognize_text(ctx, source='clipboard') == 'There is no image on the clipboard'


def test_bad_input_and_unreadable_images(ctx: Any, vision_fake: dict[str, Any]) -> None:
    with pytest.raises(ToolError):
        vision.recognize_text(ctx)
    with pytest.raises(ToolError):
        vision.recognize_text(ctx, path='a.png', source='clipboard')
    with pytest.raises(ToolError, match='No such file'):
        vision.recognize_text(ctx, path='missing.png')
    with open(os.path.join(ctx.workspace.root, 'notes.txt'), 'w') as f:
        f.write('text')
    vision_fake['ok'] = False
    with pytest.raises(ToolError, match='could not read'):
        vision.recognize_text(ctx, path='notes.txt')


def test_asks_only_for_private_sources() -> None:
    tool = vision.TOOLS[0]
    assert not tool.needs_confirmation({'path': 'a.png'})
    assert not tool.needs_confirmation({'source': 'pick'})
    assert tool.needs_confirmation({'source': 'clipboard'})
    assert tool.needs_confirmation({'source': 'screenshot'})

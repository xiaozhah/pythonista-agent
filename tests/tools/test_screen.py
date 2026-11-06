"""use_screen: what a window holds, and pressing it does what a finger would."""

from __future__ import annotations

import sys
import threading
import types
from typing import Any

import pytest

from pycoder.tools import screen
from pycoder.tools.base import ToolError


class View:
    def __init__(self, frame: tuple[float, float, float, float] = (0, 0, 100, 100), **attrs: Any) -> None:
        self.frame = frame
        self.width, self.height = frame[2], frame[3]
        self.subviews: list[Any] = []
        self.hidden = False
        self.alpha = 1.0
        self.__dict__.update(attrs)


class Button(View):
    def __init__(self, title: str, frame: Any = (0, 0, 50, 20), **attrs: Any) -> None:
        super().__init__(frame, title=title, enabled=True, **attrs)
        self.pressed = 0
        self.action: Any = self.count

    def count(self, sender: Any) -> None:
        self.pressed += 1


class Switch(View):
    action = None
    value = False


class SegmentedControl(View):
    action = None
    segments = ('One', 'Two')
    selected_index = 0


class TextField(View):
    text = ''
    action = None


class Slider(View):
    action = None
    value = 0.0


class TableView(View):
    data_source: Any = None
    delegate: Any = None
    row_height = 40


class MovesOnly(View):
    def __init__(self) -> None:
        super().__init__((0, 0, 100, 100))
        self.moved = 0

    def touch_moved(self, touch: Any) -> None:
        self.moved += 1


class Painter(View):
    def __init__(self, frame: Any = (0, 0, 100, 100)) -> None:
        super().__init__(frame)
        self.touches: list[tuple[str, Any]] = []

    def touch_began(self, touch: Any) -> None:
        self.touches.append(('began', touch.location))

    def touch_moved(self, touch: Any) -> None:
        self.touches.append(('moved', touch.location))

    def touch_ended(self, touch: Any) -> None:
        self.touches.append(('ended', touch.location))


def window(*subviews: Any, size: tuple[float, float] = (300, 400)) -> View:
    root = View((0, 0, *size))
    root.subviews = list(subviews)
    return root


def test_a_button_is_listed_and_pressed_by_text_or_number() -> None:
    ok = Button('OK', (10, 20, 50, 20))
    items = screen.items_of(window(ok))
    assert '#1 button' in items[0].line()
    assert '(10, 20)' in items[0].line()
    screen.press(screen.find(items, 'ok'))
    screen.press(screen.find(items, '#1'))
    assert ok.pressed == 2


def test_what_a_finger_cannot_reach_is_marked_and_refused() -> None:
    below = Button('Below', (0, 500, 50, 20))
    half = Button('Half', (0, 390, 50, 20))
    gone = Button('Gone', hidden=True)
    items = screen.items_of(window(below, half, gone))
    notes = {i.label: i.note for i in items}
    assert notes['Below'] == 'outside the window'
    assert notes['Half'] == 'cut off: only 50% shows'
    assert notes['Gone'] == 'hidden'
    with pytest.raises(ToolError, match='could not reach'):
        screen.press(screen.find(items, 'Below'))
    assert below.pressed == 0


def test_inside_a_small_parent_is_cut_off_even_within_the_window() -> None:
    box = View((0, 0, 100, 30))
    inner = Button('Inner', (0, 40, 50, 20))
    box.subviews = [inner]
    assert screen.items_of(window(box))[0].note == 'outside the window'


def test_a_disabled_button_is_refused() -> None:
    off = Button('Off')
    off.__dict__['enabled'] = False
    with pytest.raises(ToolError, match='disabled'):
        screen.press(screen.items_of(window(off))[0])


def test_unclear_or_missing_names_say_what_there_is() -> None:
    items = screen.items_of(window(Button('Save'), Button('Save as')))
    assert screen.find(items, 'save').label == 'Save'  # the exact one wins
    with pytest.raises(ToolError, match='could be any'):
        screen.find(screen.items_of(window(Button('Save a'), Button('Save b'))), 'save')
    with pytest.raises(ToolError, match="Nothing on screen called 'nope'"):
        screen.find(items, 'nope')


def test_switch_segment_field_and_slider_change_and_tell_their_action() -> None:
    called: list[Any] = []
    switch = Switch(action=called.append)
    segments = SegmentedControl((0, 30, 100, 20), action=called.append)
    field = TextField((0, 60, 100, 20), action=called.append)
    slider = Slider((0, 90, 100, 20), action=called.append)
    items = screen.items_of(window(switch, segments, field, slider))
    screen.press(next(i for i in items if i.kind == 'switch'))
    assert switch.value is True
    screen.press(screen.find(items, 'Two'))
    assert segments.selected_index == 1
    screen.put_text(next(i for i in items if i.kind == 'field'), 'hello')
    assert field.text == 'hello'
    screen.put_text(next(i for i in items if i.kind == 'slider'), '0.5')
    assert slider.value == 0.5
    assert called == [switch, segments, field, slider]


def test_a_table_lists_its_rows_and_selects_them() -> None:
    class Source:
        items: Any = ({'title': 'Apple'}, 'Pear')
        action: Any = None
        selected_row = -1

    picked: list[int] = []
    source = Source()
    source.action = lambda s: picked.append(s.selected_row)
    items = screen.items_of(window(TableView((0, 0, 100, 200), data_source=source)))
    assert [i.label for i in items] == ['Apple', 'Pear']
    screen.press(screen.find(items, 'Pear'))
    assert picked == [1]


def test_a_control_with_no_action_says_so() -> None:
    idle = Button('Idle')
    idle.action = None
    assert 'does nothing' in screen.press(screen.items_of(window(idle))[0])


def test_a_drag_goes_to_the_view_under_it_in_its_own_points() -> None:
    painter = Painter((10, 20, 100, 100))
    root = window(painter)
    screen.drag_or_tap(root, [(20.0, 30.0), (40.0, 30.0)])
    assert painter.touches == [('began', (10, 10)), ('moved', (30, 10)), ('ended', (30, 10))]
    with pytest.raises(ToolError, match='takes touches'):
        screen.drag_or_tap(root, [(299.0, 399.0)])


def test_the_top_view_gets_it_and_a_hidden_one_does_not() -> None:
    under, over, gone = Painter(), Painter(), Painter()
    gone.hidden = True
    screen.drag_or_tap(window(under, over, gone), [(5.0, 5.0)])
    assert over.touches
    assert not under.touches
    assert not gone.touches


def test_a_key_goes_to_the_view_that_takes_keys() -> None:
    got: list[Any] = []

    class Game(View):
        def key_command(self, sender: Any) -> None:
            got.append(sender['input'])

    screen.press_key(window(Game()), 'left')
    assert got == ['left']
    with pytest.raises(ToolError, match='takes keys'):
        screen.press_key(window(), 'left')


def test_a_press_reports_what_changed_as_text() -> None:
    before = ["#1 label '1' at (0, 0)", "#2 button '+' at (0, 9)"]
    assert (
        screen._changes(before, ["#1 label '12' at (0, 0)", before[1]]) == "Changed:\n#1 label '12' at (0, 0)"
    )
    assert screen._changes(before, before).startswith('Nothing in the list changed')
    assert screen._changes(before, [before[1]]) == f'The screen now:\n{before[1]}'
    assert screen._changes(before, []) == 'No window is open now.'


def test_a_press_that_never_finishes_does_not_hold_the_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    monkeypatch.setitem(sys.modules, 'objc_util', types.SimpleNamespace(on_main_thread=lambda fn: fn))
    monkeypatch.setattr(screen, 'PRESS_LIMIT', 0.05)
    monkeypatch.setattr(screen, '_lines', list)
    monkeypatch.setattr(screen, '_operate', lambda *args: release.wait(5) and '')
    with pytest.raises(ToolError, match='has not finished'):
        screen.use_screen(None, action='tap', target='#1')  # type: ignore[arg-type]
    release.set()


def test_the_bar_of_a_widget_preview_is_not_the_programs() -> None:
    class _WidgetSimulatorView(View):
        pass

    root = _WidgetSimulatorView(
        right_button_items=[types.SimpleNamespace(title='Use in "Today"', action=None)]
    )
    assert screen.items_of(root) == []


def test_a_tap_at_a_point_presses_the_button_there() -> None:
    root = View((0, 0, 200, 200))
    button = Button('Go', (20, 20, 100, 40))
    root.subviews = [button]
    assert screen.drag_or_tap(root, [(50, 40)]) == 'Called its action'
    assert button.pressed == 1
    with pytest.raises(ToolError, match='takes touches'):
        screen.drag_or_tap(root, [(150, 150)])


def test_a_view_that_only_follows_moves_takes_a_drag() -> None:
    view = MovesOnly()
    assert screen.handles_touches(view)
    screen.drag_or_tap(view, [(10.0, 10.0), (20.0, 20.0), (30.0, 30.0)])
    assert view.moved == 2

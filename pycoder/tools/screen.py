"""use_screen: operate the windows a program opened, so the model can check what it built does what it
should, not only how its first screen looks. It lists what is on screen, and presses, drags and types
by calling what a finger would have reached: a control's action, a view's or a scene's touch methods.
So it can't tell whether a finger would fit; it does say what is hidden or cut off."""

from __future__ import annotations

import threading
import time
import traceback
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .base import Tool, ToolContext, ToolError, prop

MAX_ITEMS = 150
MAX_ROWS = 30  # of a table, listed
DRAG_STEPS = 6
TOUCH_ID = 1
PRESS_LIMIT = 15  # seconds a press may take before the tool stops waiting for it
WIDGET_PREVIEW = '_WidgetSimulatorView'
CONTROLS = ('button', 'switch', 'segment', 'row', 'field', 'slider')


@dataclass
class Item:
    number: int
    kind: str  # button, switch, slider, segments, field, row, bar button, label, view, scene
    label: str
    frame: tuple[float, float, float, float]  # in the window's points
    view: Any
    extra: Any = None  # a row's number, a segment's, a bar button
    note: str = ''

    def line(self) -> str:
        x, y, w, h = self.frame
        note = f'  [{self.note}]' if self.note else ''
        return f'#{self.number} {self.kind} {self.label!r} at ({x:.0f}, {y:.0f}) size {w:.0f}x{h:.0f}{note}'


def kind_of(view: Any) -> str:
    """By class name, so that subclasses count and it can be tested without Pythonista's ui."""
    names = {c.__name__ for c in type(view).__mro__}
    for name, kind in (
        ('Button', 'button'),
        ('Switch', 'switch'),
        ('Slider', 'slider'),
        ('SegmentedControl', 'segments'),
        ('TextField', 'field'),
        ('TextView', 'field'),
        ('TableView', 'table'),
        ('Label', 'label'),
        ('SceneView', 'scene'),
    ):
        if name in names:
            return kind
    if getattr(view, 'scene', None) is not None:
        return 'scene'
    return 'view'


def handles_touches(view: Any) -> bool:
    """A custom view with touch methods of its own."""
    return (
        any(
            any(hasattr(c, f'touch_{phase}') for phase in ('began', 'moved', 'ended'))
            for c in type(view).__mro__
            if c.__module__ != 'ui'
        )
        and kind_of(view) == 'view'
    )


def _title(view: Any) -> str:
    for attribute in ('title', 'text', 'name', 'placeholder'):
        value = getattr(view, attribute, None)
        if value:
            return str(value)[:60]
    return ''


def _hidden(view: Any) -> bool:
    return bool(getattr(view, 'hidden', False)) or float(getattr(view, 'alpha', 1.0)) < 0.02


def _cut(
    frame: tuple[float, float, float, float], clip: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    x, y, w, h = frame
    cx, cy, cw, ch = clip
    left, top = max(x, cx), max(y, cy)
    right, bottom = min(x + w, cx + cw), min(y + h, cy + ch)
    return left, top, max(0, right - left), max(0, bottom - top)


def items_of(root: Any) -> list[Item]:
    """What is on this window, top down, with where it is and what might keep a finger from it."""
    items: list[Item] = []

    def add(kind: str, label: str, frame: Any, view: Any, extra: Any = None, note: str = '') -> None:
        if len(items) < MAX_ITEMS:
            items.append(Item(len(items) + 1, kind, label, frame, view, extra, note))

    # the preview of a widget has Pythonista's own bar: its button changes the user's settings
    sides = () if type(root).__name__ == WIDGET_PREVIEW else ('left_button_items', 'right_button_items')
    for side in sides:
        for button in getattr(root, side, None) or ():
            add('bar button', _title(button), (0, 0, 0, 0), root, button)

    def walk(view: Any, ox: float, oy: float, clip: Any, hidden: bool) -> None:
        x, y, w, h = view.frame if view is not root else (0, 0, view.width, view.height)
        frame = (ox + x, oy + y, w, h)
        seen = _cut(frame, clip)
        hidden = hidden or _hidden(view)
        area, shown = w * h, seen[2] * seen[3]
        note = (
            'hidden'
            if hidden
            else 'outside the window'
            if area and not shown
            else f'cut off: only {shown / area:.0%} shows'
            if area and shown < area * 0.95
            else ''
        )
        kind = kind_of(view)
        if kind == 'segments':
            segments = list(getattr(view, 'segments', ()))
            width = w / max(1, len(segments))
            for i, segment in enumerate(segments):
                add('segment', str(segment), (frame[0] + i * width, frame[1], width, h), view, i, note)
        elif kind == 'table':
            _add_rows(view, frame, note, add)
        elif kind == 'scene':
            add('scene', type(getattr(view, 'scene', None)).__name__, frame, view, None, note)
            _add_nodes(view, frame, add)
        elif kind in ('button', 'switch', 'slider', 'field') or kind == 'label' or handles_touches(view):
            value = f' = {view.value}' if kind in ('switch', 'slider') else ''
            add(kind, _title(view) + value, frame, view, None, note)
        offset = getattr(view, 'content_offset', (0, 0)) or (0, 0)
        inner_x, inner_y = frame[0] - offset[0], frame[1] - offset[1]
        for sub in getattr(view, 'subviews', ()) or ():
            walk(sub, inner_x, inner_y, seen, hidden)

    walk(root, 0, 0, (0, 0, root.width, root.height), False)
    return items


def _add_rows(table: Any, frame: Any, note: str, add: Callable[..., None]) -> None:
    source = getattr(table, 'data_source', None)
    row_height = float(getattr(table, 'row_height', 44) or 44)
    if source is None:
        return
    rows = getattr(source, 'items', None)
    count = (
        len(rows)
        if rows is not None
        else int(source.tableview_number_of_rows(table, 0))
        if hasattr(source, 'tableview_number_of_rows')
        else 0
    )
    for row in range(min(count, MAX_ROWS)):
        place = (frame[0], frame[1] + row * row_height, frame[2], row_height)
        add('row', _row_title(table, source, rows, row), place, table, row, note)


def _row_title(table: Any, source: Any, rows: Any, row: int) -> str:
    if rows is not None:
        item = rows[row]
        return str(item.get('title', '') if isinstance(item, dict) else item)[:60]
    if hasattr(source, 'tableview_title_for_row'):
        return str(source.tableview_title_for_row(table, 0, row))[:60]
    if hasattr(source, 'tableview_cell_for_row'):
        cell = source.tableview_cell_for_row(table, 0, row)
        return str(getattr(getattr(cell, 'text_label', None), 'text', '') or '')[:60]
    return ''


def _add_nodes(view: Any, frame: Any, add: Callable[..., None]) -> None:
    """A scene's text: what a game's menus and buttons usually are."""
    scene = getattr(view, 'scene', None)
    if scene is None:
        return
    height = float(scene.size[1])

    def walk(node: Any) -> None:
        text = getattr(node, 'text', None)
        if text and not getattr(node, 'hidden', False):
            x, y = node.point_to_scene((0, 0))
            place = (frame[0] + x - 20, frame[1] + height - y - 10, 40, 20)
            add('label', str(text)[:60], place, view, tuple(frame))  # touches go to the scene's view
        for child in getattr(node, 'children', ()) or ():
            walk(child)

    walk(scene)


def find(items: list[Item], target: str) -> Item:
    """By its number (#3), by its text, or the only one whose text has this in it."""
    target = target.strip()
    if target.startswith('#') and target[1:].isdigit():
        found = [i for i in items if i.number == int(target[1:])]
    else:
        low = target.lower()
        found = [i for i in items if i.label.lower() == low and i.kind != 'scene']
        found = found or [i for i in items if low in i.label.lower() and i.kind != 'scene']
    if not found:
        raise ToolError(f'Nothing on screen called {target!r}. On screen:\n' + _listing(items))
    if len(found) > 1:
        raise ToolError(f'{target!r} could be any of these: give its number.\n' + _listing(found))
    return found[0]


def _listing(items: list[Item]) -> str:
    return '\n'.join(i.line() for i in items) or '(nothing that can be operated)'


def _touch(x: float, y: float, px: float, py: float, phase: str, height: float | None) -> Any:
    """The touch a scene gets (its y goes up), or a view (its y goes down)."""
    if height is not None:
        import scene

        return scene.Touch(x, height - y, px, height - py, TOUCH_ID)
    return types.SimpleNamespace(
        location=(x, y), prev_location=(px, py), touch_id=TOUCH_ID, phase=phase, timestamp=time.time()
    )


def _receiver(view: Any) -> tuple[Any, float | None]:
    """What gets the touches of this view, and the height to turn y round for a scene."""
    scene = getattr(view, 'scene', None)
    return (scene, float(scene.size[1])) if scene is not None else (view, None)


def _send(view: Any, frame: Any, path: list[tuple[float, float]]) -> None:
    """A finger along these points of the window: down, along, up."""
    receiver, height = _receiver(view)
    points = [(x - frame[0], y - frame[1]) for x, y in path]
    previous = points[0]
    for i, point in enumerate(points):
        phase = 'began' if i == 0 else 'moved'
        method = getattr(receiver, f'touch_{phase}', None)
        if method is not None:
            method(_touch(*point, *previous, phase, height))
        previous = point
    method = getattr(receiver, 'touch_ended', None)
    if method is not None:
        method(_touch(*points[-1], *previous, 'ended', height))


def press(item: Item) -> str:
    """Do to this what a tap would, and say what was done."""
    if item.note.startswith(('hidden', 'outside')):
        raise ToolError(f'A finger could not reach it: {item.line()}')
    view = item.view
    if item.kind == 'bar button':
        return _call(item.extra.action, item.extra, 'its action')
    if item.kind == 'button':
        if not getattr(view, 'enabled', True):
            raise ToolError(f'It is disabled: {item.line()}')
        return _call(view.action, view, 'its action')
    if item.kind == 'switch':
        view.value = not view.value
        return _call(view.action, view, f'switched to {view.value}; its action')
    if item.kind == 'segment':
        view.selected_index = item.extra
        return _call(view.action, view, 'its action')
    if item.kind == 'row':
        return _select_row(view, item.extra)
    if item.kind == 'field':
        return 'A field: use type to put text in it'
    if item.kind == 'slider':
        return 'A slider: use type with its new value, from 0 to 1'
    if item.kind == 'label' and item.extra is None:
        return 'A label: tapping it does nothing'
    x, y, w, h = item.frame
    _send(view, item.extra or item.frame, [(x + w / 2, y + h / 2)])
    return f'Tapped ({x + w / 2:.0f}, {y + h / 2:.0f})'


def _call(action: Any, sender: Any, what: str) -> str:
    if action is None:
        return f'{what} is not set: tapping it does nothing'
    action(sender)
    return f'Called {what}'


def _select_row(table: Any, row: int) -> str:
    source, delegate = getattr(table, 'data_source', None), getattr(table, 'delegate', None)
    if source is not None and hasattr(source, 'items') and getattr(source, 'action', None):
        source.selected_row = row
        source.action(source)
        return f'Selected row {row}'
    if delegate is not None and hasattr(delegate, 'tableview_did_select'):
        delegate.tableview_did_select(table, 0, row)
        return f'Selected row {row}'
    return 'Selecting a row does nothing: its table has no delegate'


def put_text(item: Item, text: str) -> str:
    view = item.view
    if item.kind == 'slider':
        view.value = float(text)
        return _call(view.action, view, f'set to {view.value}; its action')
    if item.kind != 'field':
        raise ToolError(f'Text can only go in a field or a slider: {item.line()}')
    view.text = text
    delegate = getattr(view, 'delegate', None)
    names = ('textfield_did_change', 'textview_did_change')
    for name in names:
        if delegate is not None and hasattr(delegate, name):
            getattr(delegate, name)(view)
    action = getattr(view, 'action', None)
    return _call(action, view, f'typed {text!r}; its action') if action else f'Typed {text!r}'


def at_point(root: Any, x: float, y: float) -> tuple[Any, tuple[float, float, float, float]] | None:
    """The topmost scene or touch-handling view at this point of the window, and where it is."""

    def search(view: Any, ox: float, oy: float) -> tuple[Any, Any] | None:
        vx, vy, w, h = view.frame if view is not root else (0, 0, view.width, view.height)
        frame = (ox + vx, oy + vy, w, h)
        if _hidden(view) or not (frame[0] <= x <= frame[0] + w and frame[1] <= y <= frame[1] + h):
            return None
        offset = getattr(view, 'content_offset', (0, 0)) or (0, 0)
        for sub in reversed(list(getattr(view, 'subviews', ()) or ())):
            found = search(sub, frame[0] - offset[0], frame[1] - offset[1])
            if found is not None:
                return found
        return (view, frame) if kind_of(view) == 'scene' or handles_touches(view) else None

    return search(root, 0, 0)


def control_at(root: Any, x: float, y: float) -> Item | None:
    """The topmost control at this point of the window, which a tap there presses."""
    for item in reversed(items_of(root)):
        ix, iy, w, h = item.frame
        if item.kind in CONTROLS and ix <= x <= ix + w and iy <= y <= iy + h:
            return item
    return None


def drag_or_tap(root: Any, path: list[tuple[float, float]]) -> str:
    control = control_at(root, *path[0]) if len(path) == 1 else None
    if control is not None:
        return press(control)
    found = at_point(root, *path[0])
    if found is None:
        raise ToolError(f'Nothing at {path[0]} takes touches')
    _send(found[0], found[1], path)
    return f'Touched from {path[0]} to {path[-1]}' if len(path) > 1 else f'Tapped {path[0]}'


def press_key(root: Any, key: str) -> str:
    """Hardware keys go to key_command, on the window or a view in it."""

    def search(view: Any) -> Any:
        if hasattr(view, 'key_command'):
            return view
        for sub in getattr(view, 'subviews', ()) or ():
            found = search(sub)
            if found is not None:
                return found
        return None

    target = search(root)
    if target is None:
        raise ToolError('Nothing in this window takes keys: it has no key_command')
    target.key_command({'input': key})
    return f'Pressed {key!r}'


def _windows() -> list[Any]:
    from .ios import presented_windows

    return presented_windows()


def _operate(action: str, target: str, x: Any, y: Any, to_x: Any, to_y: Any, text: str) -> str:
    """On the main thread, as a finger's would be. What fails comes back as text, for the model."""
    windows = _windows()
    if not windows:
        raise ToolError('No window of a program is open: open one first, with run_python')
    root = windows[-1]
    items = items_of(root)
    head = f'{type(root).__name__}, {root.width:.0f}x{root.height:.0f} points.'
    if action == 'list':
        return f'{head}\n{_listing(items)}'
    if action == 'key':
        return press_key(root, text or target)
    if action == 'type':
        return put_text(find(items, target), text)
    if action == 'tap' and x is None:
        return press(find(items, target))
    if x is None or y is None:
        raise ToolError(f'{action} needs x and y, in the points of the list')
    if action == 'tap':
        return drag_or_tap(root, [(float(x), float(y))])
    if action == 'drag':
        if to_x is None or to_y is None:
            raise ToolError('drag needs to_x and to_y too')
        steps = range(DRAG_STEPS + 1)
        return drag_or_tap(
            root,
            [
                (
                    float(x) + (float(to_x) - float(x)) * i / DRAG_STEPS,
                    float(y) + (float(to_y) - float(y)) * i / DRAG_STEPS,
                )
                for i in steps
            ],
        )
    raise ToolError(f'Unknown action {action}: list, tap, drag, type or key')


def _on_main(fn: Callable[[], None]) -> bool:
    """Run fn on the main thread, as a finger would, and say if it finished in time. A dialog a press
    opens keeps it there until someone answers, and a tool that waited for that could not be stopped."""
    from objc_util import on_main_thread

    done = threading.Event()

    def call() -> None:
        try:
            fn()
        finally:
            done.set()

    threading.Thread(target=on_main_thread(call), daemon=True).start()
    return done.wait(PRESS_LIMIT)


def _lines() -> list[str]:
    windows = _windows()
    return _listing(items_of(windows[-1])).splitlines() if windows else []


def _changes(before: list[str], after: list[str]) -> str:
    """What pressing did, as text: a picture for every press costs far more, and most need none."""
    if not after:
        return 'No window is open now.'
    if len(before) != len(after):
        return 'The screen now:\n' + '\n'.join(after)
    changed = [line for line in after if line not in before]
    if changed:
        return 'Changed:\n' + '\n'.join(changed)
    return 'Nothing in the list changed. If a drawing should have, look_at_screen shows it.'


def use_screen(
    ctx: ToolContext,
    action: str = 'list',
    target: str = '',
    x: float | None = None,
    y: float | None = None,
    to_x: float | None = None,
    to_y: float | None = None,
    text: str = '',
    wait: float = 0.5,
) -> str:
    result: dict[str, str] = {}
    before: list[str] = []

    def run() -> None:
        try:
            before.extend(_lines())
            result['text'] = _operate(action, target, x, y, to_x, to_y, text)
        except ToolError as e:
            result['refused'] = str(e)
        except Exception:
            result['text'] = 'What this triggered in the program failed:\n' + traceback.format_exc(limit=8)

    if not _on_main(run):
        raise ToolError(
            f'What this pressed has not finished after {PRESS_LIMIT} s, so nothing else can run on the '
            'screen: it may have opened a dialog use_screen cannot reach. look_at_screen shows it. '
            'Say so and leave it to the user.'
        )
    if 'refused' in result:
        raise ToolError(result['refused'])
    if 'text' not in result:
        raise ToolError('The call to the main thread did not run: try again')
    report = result['text']
    if action == 'list':
        return report
    time.sleep(min(max(wait, 0), 10))  # what was pressed may still be sliding in
    seen: list[list[str]] = []
    _on_main(lambda: seen.append(_lines()))
    return f'{report}\n{_changes(before, seen[0])}' if seen else report


TOOLS = [
    Tool(
        'use_screen',
        'Operate the window your program opened, to check it works and not only how it looks. list '
        'shows its controls with numbers and places, and marks what is hidden or cut off. tap presses '
        'target (its number, as "#3", or its text) or the point x, y; drag touches from x, y to to_x, '
        'to_y; type puts text in target (a field; for a slider, its value); key sends a hardware key '
        '(text: "left", "\\r"). Each action returns what changed in the list and any error the program '
        'raised, as text; call look_at_screen only when how it looks matters. Points are those of '
        'list, not of pixels in an image. It calls what a finger would reach, so a '
        'person still has to judge how it feels; it reaches ui windows and scenes, not console dialogs.',
        {
            'action': prop('string', 'list (the default), tap, drag, type or key'),
            'target': prop('string', 'A control: its number from list, like "#3", or its text'),
            'x': prop('number', 'Where to tap, or where a drag starts'),
            'y': prop('number', 'Where to tap, or where a drag starts'),
            'to_x': prop('number', 'Where a drag ends'),
            'to_y': prop('number', 'Where a drag ends'),
            'text': prop('string', 'For type, the text or value; for key, the key'),
            'wait': prop('number', 'Seconds to wait before reading the screen (default 0.5)'),
        },
        use_screen,
        readonly=False,
    ),
]

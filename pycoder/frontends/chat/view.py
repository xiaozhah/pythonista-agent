"""ChatView: the screen. A WebView for the chat, an input bar and a top bar of its own.

From Claude Code: a command palette that opens as you type / or !, a status line under the input
(model · effort · workspace) and a tappable permission mode.

Turns run on a background thread; anything touching ui goes through the main thread.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

import clipboard
import console
import ui
from objc_util import ObjCInstance, on_main_thread

from ... import __version__, config
from ...agent import compaction
from ...app import mentions
from ...app.commands import all_commands, complete, suggestions
from ...app.commands.options import pick_mode
from ...app.controller import Controller, normalize_input
from ...events import Frontend
from ...state import settings
from ...tools import jobs
from .. import fonts, glyphs, keys, theme, widgets
from . import render
from .files_pane import FilesPanel
from .frontend import LINK, AppFrontend
from .page import page
from .pane import Pane
from .picker import Picker
from .render import elapsed
from .session_pane import SessionPanel
from .side import SidePanel

FIELD_SIDE = widgets.SIDE
TOP_HEIGHT = widgets.TOP_HEIGHT
STATUS_HEIGHT = 24
STATUS_FONT = widgets.BAR_FONT
RING_SIZE = 18
RING_COLOR = '#2f6fde'  # the one colour in the bar, as in Claude Code
SOFTWARE_KEYBOARD = 150  # taller than the shortcut bar shown with a hardware keyboard
MODE_LABELS = {
    'default': 'Ask first',
    'acceptEdits': 'Accept edits',
    'plan': 'Plan',
    'bypass': 'Bypass permissions',
}
SHORT_MODE_LABELS = {**MODE_LABELS, 'bypass': 'Bypass'}  # where the status line has little room
STATUS_ROOM = 500  # points of width below which it does
PALETTE_ROW = 50
PALETTE_ROWS = 6
PANES = [
    ('Files: the code, and what changed', '/files'),
    ('Side chat', '/btw'),
    ('Session: context, background tasks, outputs', '/session'),
]
MENU = [
    *PANES,
    ('Chapters…', '/chapters'),
    ('Model…', '/model'),
    ('Thinking effort…', '/effort'),
    ('Settings (font size, theme, …)', '/config'),
    ('Permission mode…', '/mode'),
    ('Plan mode', '/plan'),
    ('Permission rules', '/permissions'),
    ('Attach an image…', '/image'),
    ('Context usage', '/context'),
    ('Status', '/status'),
    ('Compact the conversation', '/compact'),
    ('Rewind…', '/rewind'),
    ('Resume a saved session…', '/resume'),
    ('Todo list', '/todos'),
    ('Skills', '/skills'),
    ('Usage and cost', '/cost'),
    ('Help', '/help'),
]


@on_main_thread
def ui_call(fn: Callable[[], None]) -> None:
    fn()


def in_thread(fn: Callable[[], None]) -> None:
    """Run fn (which asks with a dialog) off the main thread. Not ui.in_background: that queues
    work on Pythonista's script thread, which a running script (such as the bridge) keeps busy."""

    def run() -> None:
        try:
            fn()
        except Exception as e:  # on a thread nobody sees it, and the tap seems to do nothing
            console.hud_alert(str(e)[:80], 'error', 2)
            raise

    threading.Thread(target=run, daemon=True).start()


# the side chat: beside the chat on screens at least SIDE_BESIDE wide, taking SIDE_SHARE of it
SIDE_BESIDE, SIDE_SHARE, SIDE_MIN = 760, 0.42, 340


ACTIVITY_ROW = 18  # a line of what runs in the background, in the box above the input
PLAN_ROW = 28  # a step of the plan in that box
PLAN_ROWS = 6  # shown at most, around the current step
PLAN_ROWS_TYPING = 3  # with an on-screen keyboard up on a phone, which leaves little room
PLAN_MARK = 20


class ChatView(ui.View):
    """The agent's chat screen. The console's `pycoder` command opens it, passing the folder to work
    in and what to do on /exit (without one, /exit closes the screen)."""

    def __init__(self, root: str | None = None, on_exit: Callable[[], None] | None = None) -> None:
        self.on_exit = on_exit
        self.dark = ui.get_ui_style() == 'dark'
        self.background_color = '#111111' if self.dark else '#ededed'
        self.kb_height = 0.0
        self.busy = False
        self.queue: list[tuple[int, str]] = []  # messages sent while a turn runs, to run after it
        self.send_look: tuple[bool, bool, bool] | None = None  # what the send button last showed
        self.lock = threading.Lock()  # guards busy and queue between the UI and the worker thread

        self.web = ui.WebView()
        self.web.delegate = self
        self.web.load_html(page())
        self.add_subview(self.web)
        keys.hide_keyboard_on_drag(self.web)

        self.top = widgets.TopBar(
            [
                widgets.glyph_button('close', self.on_close, 'Close'),
                widgets.word_button('New', self.on_new),
            ],
            [
                widgets.glyph_button('folder', lambda sender: self.toggle_files(), 'Files'),
                widgets.glyph_button('more', self.on_menu, 'Menu'),
            ],
        )
        self.add_subview(self.top)

        self.bar = ui.View(background_color='#1e1e1e' if self.dark else '#f7f7f7')
        self.add_subview(self.bar)
        self.input = widgets.InputBox(self.on_send, self.on_plus)
        self.input.on_resize = self.layout
        self.bar.add_subview(self.input)
        self.field, self.send, self.hint = self.input.field, self.input.send, self.input.hint
        assert self.input.plus is not None
        self.plus = self.input.plus
        self.field.delegate = self
        self.command_length = 0  # how much of the input is a slash command, shown in blue
        self.status = ui.Label(font=('<system>', STATUS_FONT), text_color='#8c8c8c')
        self.bar.add_subview(self.status)
        # the status line is tappable: it switches the model
        self.model_label = ui.Label(font=('<system>', STATUS_FONT))
        self.bar.add_subview(self.model_label)
        self.effort_label = ui.Label(font=('<system>', STATUS_FONT))
        self.bar.add_subview(self.effort_label)
        self.status_tap = ui.Button(action=self.on_status)
        self.bar.add_subview(self.status_tap)
        self.effort_tap = ui.Button(action=self.on_effort)
        self.bar.add_subview(self.effort_tap)
        self.mode = ui.Button(font=('<system>', STATUS_FONT), action=self.on_mode)
        self.context_ring = ui.Button(action=self.on_context)
        self.bar.add_subview(self.context_ring)
        self.ring_shown: tuple[int, bool] | None = None  # what the ring last showed
        self.bar.add_subview(self.mode)

        # what runs in the background (subagents, jobs), pinned above the input so it stays in view
        self.activity = ui.View(hidden=True)
        self.activity_box = ui.View(corner_radius=16, border_width=0.5)
        self.activity.add_subview(self.activity_box)
        self.plan_rows: list[tuple[ui.ImageView, ui.Label]] = []
        self.plan_look: list[tuple[str, str]] | None = None  # the steps the rows last showed
        self.activity_text = ui.Label(font=('<system>', 13), number_of_lines=0)
        self.activity_box.add_subview(self.activity_text)
        self.activity_tap = ui.Button(action=lambda sender: self.open_session())  # opens the details
        theme.label(self.activity_tap, 'What runs in the background. Open the session pane')
        self.activity_box.add_subview(self.activity_tap)
        self.add_subview(self.activity)
        self.ticking = False

        self.palette = ui.TableView(row_height=PALETTE_ROW, hidden=True, corner_radius=14, border_width=0.5)
        self.palette_source = PaletteSource(self)
        self.palette.data_source = self.palette_source
        self.palette.delegate = self.palette_source
        self.add_subview(self.palette)

        # the real frontend needs the controller's cancel token, so it is attached right after
        self.controller = Controller(Frontend(), root=root or config.HOME_DIR)
        self.fe = AppFrontend(
            self,
            self.controller.cancel,
            self.ask_text,
            self.choose,
            self.refresh_soon,
            header=self.header_lines,
            cover_input=self.cover_input,
            side=self.show_side,
            session_pane=self.open_session,
            files_pane=self.open_files,
            on_activity=self.refresh_activity,
            add_to_input=self.add_to_input,
        )
        # the panes on the right, made when first opened; one is on screen at a time
        self.side: SidePanel | None = None
        self.session_panel: SessionPanel | None = None
        self.files_panel: FilesPanel | None = None
        self.pane: Pane | None = None
        self.controller.frontend = self.fe
        # ↑ ↓ through what was sent before; typed holds the / and ! lines, which aren't requests
        self.typed: list[tuple[float, str]] = []
        self.history_pos = 0
        self.draft = ''
        self.recalled = ''  # the entry ↑ ↓ put in the field; editing it starts a new draft
        self.covered = False  # a sheet in the page (/config) covers the input bar
        keys.intercept(self.field, self.on_field_key)  # built on the main thread (open_agent)
        self.refresh()

    # ---- layout and keyboard

    def layout(self) -> None:
        w, h = self.width, self.height
        # above the keyboard, or else above the iPhone's home indicator
        bottom = int(
            h - (self.kb_height or self.safe_bottom())
        )  # whole points: a web view leaves a dark line
        top = widgets.safe_top(self) + TOP_HEIGHT
        self.top.frame = (0, 0, w, top)
        if self.pane is not None:
            # beside the chat when there is room for both, over it on a phone
            side_w = max(SIDE_MIN, round(w * SIDE_SHARE)) if w >= SIDE_BESIDE else w
            self.pane.inset = h - bottom  # it fills the screen; what it shows stops above this
            # over it, it has the only top bar: two would mean two ✕ that close different things
            beside = side_w < w
            pane_y = top if beside else widgets.safe_top(self)
            self.pane.divider.hidden = not beside
            self.pane.frame = (w - side_w, pane_y, side_w, h - pane_y)
            w = w - side_w if beside else w
        field_h = self.input.field_height
        bar_h = 8 + field_h + 8 + STATUS_HEIGHT + 10
        plan_h = len(self.plan_look or ()) * PLAN_ROW
        text_h = len((self.activity_text.text or '').splitlines()) * ACTIVITY_ROW
        box_h = plan_h + text_h + 16
        strip_h = 0 if self.activity.hidden else box_h + 8
        box_w = w - 2 * FIELD_SIDE
        self.activity.frame = (0, bottom - bar_h - strip_h, w, strip_h)
        self.activity_box.frame = (FIELD_SIDE, 6, box_w, box_h)
        for i, (mark, label) in enumerate(self.plan_rows):
            y = 8 + i * PLAN_ROW
            mark.frame = (14, y + (PLAN_ROW - PLAN_MARK) / 2, PLAN_MARK, PLAN_MARK)
            label.frame = (14 + PLAN_MARK + 8, y, box_w - 14 - PLAN_MARK - 8 - 12, PLAN_ROW)
        self.activity_text.frame = (14, 8 + plan_h, box_w - 28, text_h)
        self.activity_tap.frame = (0, 0, box_w, box_h)
        # a sheet in the page (/config) covers the input bar, so the page goes down to where it was
        self.web.frame = (0, top, w, (h if self.covered else bottom - bar_h - strip_h) - top)
        self.bar.frame = (0, bottom - bar_h, w, bar_h + (h - bottom if not self.kb_height else 0))
        self.input.frame = (FIELD_SIDE, 8, w - 2 * FIELD_SIDE, field_h)
        # the folder on the left; on the right the model, its effort and the mode, as in Claude Code
        line = 8 + field_h + 8
        labels = MODE_LABELS if w >= STATUS_ROOM else SHORT_MODE_LABELS
        mode_title = labels.get(self.controller.settings.mode, self.controller.settings.mode)
        if self.mode.title != mode_title:
            self.mode.title = mode_title
        mode_w = ui.measure_string(self.mode.title or '', font=self.mode.font)[0] + 24  # a button's margins
        self.context_ring.frame = (
            w - FIELD_SIDE - 8 - RING_SIZE,
            line + (STATUS_HEIGHT - RING_SIZE) / 2,
            RING_SIZE,
            RING_SIZE,
        )
        self.mode.frame = (self.context_ring.x - 4 - mode_w, line, mode_w, STATUS_HEIGHT)
        effort_w = ui.measure_string(self.effort_label.text or '', font=self.effort_label.font)[0] + 8
        self.effort_label.frame = (self.mode.x - 6 - effort_w, line, effort_w, STATUS_HEIGHT)
        model_w = ui.measure_string(self.model_label.text or '', font=self.model_label.font)[0] + 8
        self.model_label.frame = (self.effort_label.x - 6 - model_w, line, model_w, STATUS_HEIGHT)
        self.status_tap.frame = self.model_label.frame
        self.effort_tap.frame = self.effort_label.frame
        self.status.frame = (
            FIELD_SIDE + 8,
            line,
            max(0, self.model_label.x - FIELD_SIDE - 16),
            STATUS_HEIGHT,
        )
        rows = min(len(self.palette_source.items), PALETTE_ROWS)
        width = min(w - 46 - 8, 560)
        self.palette.frame = (46, bottom - bar_h - rows * PALETTE_ROW - 6, width, rows * PALETTE_ROW)

    # ---- what runs in the background

    def activity_lines(self) -> list[str]:
        now = time.time()
        lines = []
        running = list(self.fe.running.values())
        lines += [f'Subagent · {r.description} · {elapsed(now - r.started)}' for r in running]
        lines += [f'Job {j.number} · {j.label} · {elapsed(now - j.run.started)}' for j in jobs.running()]
        return lines

    def plan_steps(self) -> list[tuple[str, str]]:
        typing = self.kb_height > SOFTWARE_KEYBOARD and self.width < STATUS_ROOM
        return render.strip_steps(self.fe.todos, PLAN_ROWS_TYPING if typing else PLAN_ROWS)

    def show_plan(self, steps: list[tuple[str, str]], t: dict[str, str]) -> None:
        while len(self.plan_rows) < len(steps):
            row = (ui.ImageView(), ui.Label(font=('<system>', STATUS_FONT)))
            self.activity_box.add_subview(row[0])
            self.activity_box.add_subview(row[1])
            self.plan_rows.append(row)
        while len(self.plan_rows) > len(steps):
            for view in self.plan_rows.pop():
                self.activity_box.remove_subview(view)
        for (mark, label), (status, text) in zip(self.plan_rows, steps, strict=True):
            mark.image = glyphs.todo_mark(status, t['fg'], t['dim'], t['bg'])
            label.text = text
            label.text_color = t['dim'] if status == 'completed' else t['fg']

    @on_main_thread
    def refresh_activity(self) -> None:
        """Show the plan and what runs, and keep the times current once a second while anything does."""
        lines = self.activity_lines()
        steps = self.plan_steps()
        t = theme.colors(self.dark)
        self.activity.background_color = t['bg']
        self.activity_box.background_color = t['bg']
        self.activity_box.border_color = theme.mix(t['line'], t['bg'], 0.7)
        self.activity_text.text_color = t['dim']
        before = (
            self.activity.hidden,
            len((self.activity_text.text or '').splitlines()),
            len(self.plan_look or ()),
        )
        if steps != self.plan_look:
            self.show_plan(steps, t)
            self.plan_look = steps
        self.activity_text.text = '\n'.join(lines)
        self.activity.hidden = not lines and not steps
        if (self.activity.hidden, len(lines), len(steps)) != before:
            self.layout()
        if lines and not self.ticking:
            self.ticking = True
            threading.Thread(target=self._tick, daemon=True).start()

    def _tick(self) -> None:
        time.sleep(1)
        self.ticking = False
        if self.on_screen:
            self.refresh_activity()

    def safe_bottom(self) -> float:
        """The height the home indicator takes at the bottom of an iPhone screen (0 elsewhere)."""
        try:
            return float(ObjCInstance(self).safeAreaInsets().bottom)
        except Exception:
            return 0.0

    def keyboard_frame_did_change(self, frame: tuple[float, float, float, float]) -> None:
        if frame[3] == 0 or not self.on_screen:
            self.kb_height = 0
        else:
            top = ui.convert_point((0, frame[1]), None, self)[1]
            self.kb_height = max(0.0, self.height - top)
        self.layout()
        if not self.covered:  # a sheet is open: scrolling under it would shift it (old WebKit)
            self.eval_js('toBottom()')

    def will_close(self) -> None:
        with self.lock:
            self.queue.clear()
        self.controller.close()
        self.close_pane()  # its loop runs for as long as it has a place on this screen
        if not self.busy:  # a running turn saves when it ends; saving now could race with it
            self.controller.save()

    # ---- page and controls (main thread)

    @on_main_thread
    def eval_js(self, code: str) -> str:
        return self.web.eval_js(code)

    def wait_for_page(self) -> None:
        for _ in range(100):
            if self.eval_js('typeof add') == 'function':
                return
            time.sleep(0.05)

    def refresh(self) -> None:
        s = self.controller.settings
        model = config.MODEL_BY_ID[s.model].short if s.model in config.MODEL_BY_ID else s.model
        self.top.title_label.text = self.controller.session.title or ''
        folder = self.controller.folder_label()
        working = (
            (f' · working… ({len(self.queue)} queued)' if self.queue else ' · working…') if self.busy else ''
        )
        self.status.text = f'{folder}{working}'
        self.model_label.text = model.capitalize()
        self.effort_label.text = s.effort.capitalize()
        theme.label(self.effort_tap, f'{s.effort} effort. Change the effort')
        theme.label(self.status_tap, f'{model}. Switch the model')
        self.fe.call('setHtml', 'header-model', render.escape(self.model_line()))
        self.apply_appearance()
        t = theme.colors(self.dark)
        self.mode.tint_color = t['fg']
        theme.label(self.mode, f'Permission mode: {self.mode.title}')
        self.draw_context_ring(t)
        self.layout()
        # the page shows a pulsing dot in a reply that has nothing in it yet
        self.eval_js(f"document.documentElement.classList.toggle('busy', {json.dumps(self.busy)})")
        # images waiting for the next message show on the + button
        waiting = len(self.controller.pending_images)
        self.plus.image = ui.Image.named('iob:images_24') if waiting else glyphs.glyph('plus')
        self.plus.title = str(waiting) if waiting else ''
        self.plus.font = ('<system-bold>', 12)
        theme.label(self.plus, f'Attach an image ({waiting} attached)' if waiting else 'Attach an image')

    def zoom(self, step: int) -> None:
        """⌘+ / ⌘−: change the chat text size by step points (0: the default)."""
        spec = settings.SPEC_BY_NAME['font_size']
        current = self.controller.settings.font_size
        size = settings.Settings().font_size if step == 0 else current + step
        self.controller.set_setting('font_size', min(spec.maximum, max(spec.minimum, size)))
        self.refresh_soon()

    def apply_appearance(self) -> None:
        """Font size and theme from the settings, for the page and the native controls."""
        s = self.controller.settings
        self.dark = s.theme == 'dark' or (s.theme == 'auto' and ui.get_ui_style() == 'dark')
        t = theme.colors(self.dark)
        self.background_color = t['bg']
        self.web.background_color = t['bg']
        self.top.style(t)
        self.bar.background_color = t['bg']
        if self.input.style(t):
            self.color_command(normalize_input(self.field.text), again=True)
        self.status.text_color = t['dim']
        self.model_label.text_color = t['fg']
        self.effort_label.text_color = t['dim']
        self.palette.background_color = t['surface']
        self.palette.border_color = t['line']
        self.palette_source.colors = t
        self.style_send()
        self.eval_js(f'setAppearance({int(s.font_size)}, {json.dumps(s.theme)})')
        self.eval_js(f'setMono({json.dumps(fonts.css(s.code_font))})')
        self.style_panes()

    @on_main_thread
    def cover_input(self, covered: bool) -> None:
        # out of sight and out of reach, but not hidden: a hidden field leaves the responder chain,
        # and Esc (a key command) needs the focus to stay on this screen
        self.covered = covered
        self.bar.alpha = 0.0 if covered else 1.0
        self.bar.touch_enabled = not covered
        self.layout()
        # an on-screen keyboard would cover the sheet, so it goes; a hardware keyboard stays
        if covered and self.kb_height > SOFTWARE_KEYBOARD:
            self.field.end_editing()

    def style_send(self) -> None:
        """Send: filled with something to send, grey without; a stop square while a reply runs and
        nothing is typed."""
        self.input.show_hint()
        has_text = bool(self.field.text.strip() or self.controller.pending_images)
        stopping = self.busy and not has_text
        look = (has_text, stopping, self.dark)
        if look == self.send_look:
            return
        self.send_look = look
        self.send.image = glyphs.glyph('stop') if stopping else None
        self.send.title = '' if stopping else '↵'
        theme.label(self.send, 'Stop the reply' if stopping else 'Send')

    @on_main_thread
    def refresh_soon(self) -> None:
        self.refresh()

    def context_used(self) -> float:
        """How much of the context window the last request took, 0 to 1."""
        usage = self.controller.session.last_usage
        return min(1.0, compaction.context_tokens(usage) / config.CONTEXT_WINDOW) if usage else 0.0

    def draw_context_ring(self, t: dict[str, str]) -> None:
        """A ring that fills as the context does, as in Claude Code: tap it for the details."""
        percent = round(self.context_used() * 100)
        if self.ring_shown == (percent, self.dark):
            return
        self.ring_shown = (percent, self.dark)
        center, radius = RING_SIZE / 2, RING_SIZE / 2 - 2
        with ui.ImageContext(RING_SIZE, RING_SIZE) as ctx:
            ui.set_color(t['line'])
            circle = ui.Path.oval(2, 2, 2 * radius, 2 * radius)
            circle.line_width = 2
            circle.stroke()
            ui.set_color(RING_COLOR)
            arc = ui.Path()
            arc.move_to(center, center - radius)  # from the top, clockwise
            for step in range(1, max(percent, 2) + 1):
                angle = 2 * math.pi * step / 100
                arc.line_to(center + radius * math.sin(angle), center - radius * math.cos(angle))
            arc.line_width = 2
            arc.stroke()
            image = ctx.get_image()
        self.context_ring.image = image.with_rendering_mode(ui.RENDERING_MODE_ORIGINAL)
        theme.label(self.context_ring, f'{percent}% of the context used')

    def on_context(self, sender: object) -> None:
        if self.busy:
            console.hud_alert(f'{round(self.context_used() * 100)}% of the context used', duration=1.2)
        else:
            self.run_in_background('/context')

    # ---- input

    def header_lines(self) -> list[str]:
        """The session header, like Claude Code's start screen."""
        c = self.controller
        skills = len(c.skills.all())
        return [
            f'pycoder v{__version__}',
            self.model_line(),
            f'{skills} skill{"" if skills == 1 else "s"}',
            'Type / for commands, ! for the shell',
        ]

    def model_line(self) -> str:
        s = self.controller.settings
        model = config.MODEL_BY_ID.get(s.model)
        folder = self.controller.folder_label()
        return f'{model.short if model else s.model} · {s.effort} effort · {folder}'

    def textview_did_change(self, textview: Any) -> None:
        """Open the command palette while a / or ! line, or an @path, is being typed."""
        if self.history_pos and textview.text != self.recalled:
            self.history_pos = 0  # an edited entry is the new draft: the next ↑ keeps it
        text = normalize_input(textview.text)
        typing = (text.startswith(('/', '!')) and '\n' not in text) or mentions.partial(text) is not None
        items = suggestions(self.controller, text) if typing else []
        # at each key: anything set or laid out again here, changed or not, makes the text shake
        if items != self.palette_source.items:
            rows_changed = min(len(items), PALETTE_ROWS) != min(len(self.palette_source.items), PALETTE_ROWS)
            self.palette_source.items = items
            self.palette_source.selected = -1  # nothing highlighted until ↑ or ↓
            self.palette.hidden = not items
            self.palette.reload_data()
            if rows_changed:
                self.layout()
        self.input.fit()
        self.style_send()
        self.color_command(text)

    def color_command(self, text: str, again: bool = False) -> None:
        """A slash command that exists shows in blue, as in Claude Code. Only when there is one or
        was one: anything set at each key makes the text shake."""
        word = text.split(' ', 1)[0]
        known = text.startswith('/') and word[1:].lower() in {c.name for c in all_commands(self.controller)}
        length = len(word) if known else 0
        # and the rest of the line, once its colour is set, keeps it by itself
        if again or length != self.command_length or (length and len(text) <= length):
            t = theme.colors(self.dark)
            keys.color_start(self.field, length, t['command'], t['fg'])
        self.command_length = length

    # ---- hardware keyboard (keys.py hands these over before the field sees them)

    def on_field_key(self, key: str, shift: bool) -> bool:
        """↑ ↓ move through the palette when it is open, otherwise through earlier messages (from
        the first or last line on screen, so the caret still moves inside a long message); Return
        takes the highlighted suggestion; Esc drops an input method's composition, else closes the
        palette or stops a reply."""
        if key == 'escape' and keys.cancel_composition(self.field):
            return True
        if self.covered and key != 'escape':  # a sheet is open: only Esc (to close it) means anything
            return True
        palette = not self.palette.hidden and bool(self.palette_source.items)
        if palette and key in ('up', 'down'):
            self.palette_source.move(-1 if key == 'up' else 1)
            return True
        if key == 'return' and not shift and self.take_highlighted():
            return True
        if key == 'escape':
            if palette:
                self.palette.hidden = True
            elif self.pane is not None:
                self.close_pane()
                return True
            elif self.busy:
                self.on_stop(None)
            return palette or self.busy
        if key not in ('up', 'down'):
            return False
        text = self.field.text
        # an empty field, or one showing an entry ↑ ↓ put there, goes on through the history
        browsing = not text or (self.history_pos != 0 and text == self.recalled)
        start, end = (keys.utf16_to_index(text, i) for i in self.field.selected_range)
        first, last = (True, True) if browsing else keys.caret_on_edges(self.field, text, start, end)
        if key == 'up' and first:
            return self.browse_history(-1)
        if key == 'down' and last and self.history_pos:
            return self.browse_history(1)
        return False

    def take_highlighted(self) -> bool:
        """Return with a palette row highlighted fills it in. Called from the key (iPad) and from
        the typed line break (on a Mac the break comes first); whichever is first takes it."""
        source = self.palette_source
        if self.palette.hidden or not 0 <= source.selected < len(source.items):
            return False
        self.pick_suggestion(source.items[source.selected][0])
        return True

    def get_key_commands(self) -> list[dict[str, str]]:
        """Shortcuts, listed when ⌘ is held. Esc is on this screen itself: when a sheet covers the
        input, the focus rests here.
        Return and ↑ ↓ are here for the list (and for when the field isn't focused): a focused
        field takes them first, and keys.py hands them to on_field_key."""
        return [
            {'input': '\r', 'title': 'Send (⇧↵ or ⌥↵: new line)'},
            {'input': '\r', 'modifiers': 'cmd'},
            {'input': 'up', 'title': 'Previous message'},
            {'input': 'down', 'title': 'Next message'},
            {'input': '.', 'modifiers': 'cmd', 'title': 'Stop the reply'},
            {'input': 'esc', 'title': 'Stop the reply · close the list'},
            {'input': 'k', 'modifiers': 'cmd', 'title': 'Clear the screen'},
            {'input': 'n', 'modifiers': 'cmd,shift', 'title': 'New chat'},
            {'input': 'e', 'modifiers': 'cmd', 'title': 'Files: the code, and what changed'},
            {'input': ';', 'modifiers': 'cmd', 'title': 'Side chat'},
            {'input': 'i', 'modifiers': 'cmd', 'title': 'Session: context, background tasks, outputs'},
            {'input': '=', 'modifiers': 'cmd', 'title': 'Bigger text'},
            {'input': '+', 'modifiers': 'cmd'},
            {'input': '-', 'modifiers': 'cmd', 'title': 'Smaller text'},
            {'input': '0', 'modifiers': 'cmd', 'title': 'Default text size'},
            {'input': 'c', 'modifiers': 'ctrl', 'title': 'Stop the reply'},
        ]

    def key_command(self, sender: dict[str, str]) -> None:
        key = sender.get('input')
        if key == 'esc':
            self.on_field_key('escape', False)
        elif key in ('=', '+', '-', '0'):
            self.zoom({'=': 1, '+': 1, '-': -1}.get(key, 0))
        elif self.covered:
            return  # a sheet is open: it has the keys
        elif key == '\r':
            if not self.take_highlighted():
                self.on_send()
        elif key in ('up', 'down'):
            self.on_field_key(key, False)
        elif key in ('.', 'c'):
            self.on_stop(None)
        elif key == 'k' and not self.busy:
            self.fe.show_header()  # the conversation goes on; only the screen is cleared
        elif key == 'n':
            self.on_new(None)
        elif key == 'e':
            self.toggle_files()
        elif key in (';', 'i'):  # each opens its pane, or closes it when it is open
            opened = self.pane is not None and self.pane is (self.side if key == ';' else self.session_panel)
            if opened:
                self.close_pane()
            elif key == ';':
                self.open_side()
            else:
                self.open_session()

    def input_history(self) -> list[str]:
        """Requests of this session (also after /resume) and the / and ! lines typed here, oldest
        first, without repeats in a row."""
        entries = sorted([(t.time, t.text) for t in self.controller.session.turns] + self.typed)
        out: list[str] = []
        for _, text in entries:
            if text and (not out or out[-1] != text):
                out.append(text)
        return out

    def browse_history(self, step: int) -> bool:
        history = self.input_history()
        if not history:
            return False
        if self.history_pos == 0:
            self.draft = self.field.text  # what was being typed comes back after the newest
        self.history_pos = max(-len(history), min(0, self.history_pos + step))
        text = history[self.history_pos] if self.history_pos else self.draft
        self.recalled = text
        keys.replace(self.field, 0, len(self.field.text), text)  # ⌘Z brings back what was there
        self.palette.hidden = True
        self.input.fit()
        return True

    def pick_suggestion(self, insert: str) -> None:
        keys.replace(self.field, 0, len(self.field.text), insert)
        self.textview_did_change(self.field)
        if not suggestions(self.controller, insert) or insert.endswith(' '):
            self.palette.hidden = True

    def on_mode(self, sender: object) -> None:
        """Pick the permission mode from a list (bypass is a deliberate choice, never a tap away)."""
        in_thread(self._pick_mode)

    def _pick_mode(self) -> None:
        pick_mode(self.controller)
        self.refresh_soon()

    def textview_did_begin_editing(self, textview: Any) -> None:
        keys.forget_modifiers()

    def textview_did_end_editing(self, textview: Any) -> None:
        keys.forget_modifiers()

    def textview_should_change(self, textview: Any, range: tuple[int, int], replacement: str) -> bool:
        """Return sends, or adds a line (see adds_line); Tab takes the highlighted palette row or
        completes /commands, !commands and @paths at the caret; everything else types normally."""
        if self.covered:
            return False  # typing while a sheet covers the input goes nowhere
        if replacement == '\n':
            if self.adds_line(textview.text):
                return True
            if self.take_highlighted():
                return False
            self.on_send()
            return False
        if replacement != '\t':
            return True
        if self.take_highlighted():
            return False
        text = textview.text
        start, end = (keys.utf16_to_index(text, i) for i in textview.selected_range)  # what Tab replaces
        completed, options = complete(self.controller, normalize_input(text[:start]))
        keys.replace(textview, *keys.completion_edit(text, start, end, completed))
        self.textview_did_change(textview)
        if len(options) > 1:
            console.hud_alert('  '.join(options[:8]), duration=1.5)
        return False

    def adds_line(self, text: str) -> bool:
        """Whether Return adds a line instead of sending: with ⇧ or ⌥ held on a hardware keyboard,
        and always from the on-screen keyboard, which has no other way to type one (the Send button
        sends there), except on a / or ! line, which is one line by nature."""
        if keys.newline_held():
            return True
        return self.kb_height > SOFTWARE_KEYBOARD and not normalize_input(text).startswith(('/', '!'))

    def on_send(self, sender: object = None) -> None:
        """Send, or while a turn runs, queue the message to go next (as in Claude Code)."""
        text = self.field.text.strip()
        if not (text or self.controller.pending_images):
            if self.busy:  # the button is a stop square then
                self.on_stop(None)
            return
        self.field.text = ''
        self.history_pos = 0
        if text.startswith(('/', '!')):
            self.typed.append((time.time(), text))
        self.textview_did_change(self.field)
        command, _, question = normalize_input(text).partition(' ')
        if command == '/session':
            self.open_session()
        elif command == '/files':
            self.open_files()
        elif command == '/btw':  # the side chat answers now, even while a turn runs
            self.open_side()
            if question.strip():
                assert self.side is not None
                self.side.question(question.strip())
        elif not self.run_in_background(text):
            self.refresh()  # the status line shows how many are queued

    # ---- the side chat

    @on_main_thread
    def show_pane(self, pane: Pane | None) -> None:
        """Put this pane on the right (None: no pane), in place of the one that was there."""
        if self.pane is pane:
            return
        if self.pane is not None:
            self.remove_subview(self.pane)
        self.pane = pane
        if pane is not None:
            self.add_subview(pane)
        self.layout()
        if pane is not None:
            pane.opened()
        else:
            self.field.begin_editing()

    @on_main_thread
    def open_side(self) -> None:
        if self.side is None:
            c = self.controller
            self.side = SidePanel(c.side_question, lambda: c.session.id, self.close_pane, self.dark)
            self.style_panes()
        self.show_pane(self.side)

    @on_main_thread
    def open_session(self) -> None:
        if self.session_panel is None:
            self.session_panel = SessionPanel(self.controller, self.fe, self.close_pane, self.dark)
            self.style_panes()
        self.show_pane(self.session_panel)

    @on_main_thread
    def open_files(self) -> None:
        if self.files_panel is None:
            self.files_panel = FilesPanel(self.controller, self.close_pane, self.dark)
            self.style_panes()
        self.show_pane(self.files_panel)

    def toggle_files(self) -> None:
        if self.pane is not None and self.pane is self.files_panel:
            self.close_pane()
        else:
            self.open_files()

    def close_pane(self) -> None:
        self.show_pane(None)

    @on_main_thread
    def show_side(self, question: str, answer: str) -> None:
        """A /btw that went through the controller (a command run from the queue)."""
        self.open_side()
        assert self.side is not None
        self.side.show(question, answer)

    def style_panes(self) -> None:
        s = self.controller.settings
        for pane in (self.side, self.session_panel, self.files_panel):
            if pane is not None:
                pane.dark = self.dark
                pane.style()
                pane.run(
                    f'setAppearance({int(s.font_size)}, {json.dumps(s.theme)})',
                    f'setMono({json.dumps(fonts.css(s.code_font))})',
                )

    def run_in_background(self, text: str) -> bool:
        """Start handling text, or queue it when something is already running (returns False)."""
        with self.lock:
            start = not self.busy
            self.busy = True
        if not start:
            number = self.fe.queued(text)  # not under the lock: it waits for the main thread
            with self.lock:
                start = not self.busy  # the turn ended meanwhile: nothing would take it from the queue
                self.busy = True
                if not start:
                    self.queue.append((number, text))
                    return False
            self.fe.unqueued(number)
        self.refresh_soon()  # may be called from a background thread (the ⋯ menu)
        threading.Thread(target=self._run, args=(text,), daemon=True).start()
        return True

    def _run(self, text: str) -> None:
        released = False  # busy was given up: another turn may be running by the end of this one
        try:
            while True:
                try:
                    if not self.controller.submit(text):  # /exit
                        self.leave()
                        return
                except KeyboardInterrupt:  # a Stop that came between a turn's own steps
                    self.fe.notice('Interrupted')
                except Exception as e:
                    self.fe.notice(f'✗ {type(e).__name__}: {e}', 'error')
                with self.lock:
                    if not self.queue:
                        self.busy = False
                        released = True
                        break
                    number, text = self.queue.pop(0)
                self.fe.unqueued(number)
                self.refresh_soon()
        finally:
            if not released:
                with self.lock:
                    self.busy = False
            self.refresh_soon()

    def start(self, first: str = '', resume: str = '', notes: Sequence[str] = ()) -> None:
        """Once the page is up: the header, the API key, then `resume` ('last' or 'pick') and the
        first message, if any (from `claude <prompt>` in the console)."""

        def run() -> None:
            self.wait_for_page()
            self.refresh_soon()  # applies the saved font size and theme now that the page can take them
            # WebKit on iOS shows :active (a pressed button) only on pages that listen for touches
            self.eval_js("document.addEventListener('touchstart', function() {}, {passive: true})")
            if keys.focus_on_open():
                ui_call(self.field.begin_editing)
            self.fe.show_header()
            for note in notes:
                self.fe.notice(note, 'warn')
            try:
                self.controller.connect()
            except Exception as e:
                self.fe.notice(f'No API key: {e}', 'error')
                return
            if resume:
                self.run_in_background('/resume ' + ('' if resume == 'pick' else 'last'))
            if first:
                self.run_in_background(first)

        threading.Thread(target=run, daemon=True).start()

    def leave(self) -> None:
        """/exit: back to the console, or close when presented by itself."""
        self.controller.save()
        if self.on_exit is not None:
            ui_call(self.on_exit)
        else:
            ui_call(self.close)

    # ---- the buttons under a message

    def webview_should_start_load(self, webview: object, url: str, nav_type: str) -> bool:
        if not url.startswith(LINK):
            return True
        action, _, turn = url[len(LINK) :].partition('/')
        in_thread(lambda: self.message_action(action, int(turn)))
        return False

    def message_action(self, action: str, turn: int) -> None:
        if action in ('queue-cancel', 'queue-now'):
            self.queued_action(action, turn)
            return
        session = self.controller.session
        request = next((t.text for t in session.turns if t.number == turn), '')
        if action in ('copy-request', 'copy-reply'):
            # on the main thread: off it clipboard.set waits for that thread and holds Python's lock,
            # so Pythonista freezes if the main thread is waiting for the lock
            on_main_thread(clipboard.set)(request if action == 'copy-request' else session.reply_text(turn))
            console.hud_alert('Copied', duration=0.8)
        elif action == 'pin':
            self.controller.toggle_chapter(turn)
        elif self.busy:
            console.hud_alert('Wait for this reply to finish', 'error', 1.2)
        elif action == 'fork':
            self.run_in_background(f'/fork {turn}')
        elif action == 'rewind':
            self.run_in_background(f'/rewind {turn}')
            self.wait_until_idle()
            if not any(t.number == turn for t in self.controller.session.turns):
                self.edit_again(request)

    def queued_action(self, action: str, number: int) -> None:
        """A message waiting for this reply to end: take it back to edit, or stop the reply for it."""
        with self.lock:
            found = next((q for q in self.queue if q[0] == number), None)
            if found is None:
                return  # it has just started
            self.queue.remove(found)
            if action == 'queue-now':
                self.queue.insert(0, found)
        if action == 'queue-now':
            self.controller.stop()
            return
        self.fe.unqueued(number)
        self.edit_again(found[1])
        self.refresh_soon()

    @on_main_thread
    def add_to_input(self, text: str) -> None:
        before = self.field.text
        self.field.text = f'{before.rstrip()} {text}' if before.strip() else text
        self.textview_did_change(self.field)
        self.field.begin_editing()

    def wait_until_idle(self) -> None:
        while self.busy:
            time.sleep(0.05)

    @on_main_thread
    def edit_again(self, request: str) -> None:
        """A request taken back goes into the field, to change and send again (over no draft)."""
        if not self.field.text.strip():
            self.field.text = request
            self.textview_did_change(self.field)
            self.field.begin_editing()

    def on_stop(self, sender: object) -> None:
        with self.lock:
            dropped, self.queue[:] = list(self.queue), []
        for number, _ in dropped:
            self.fe.unqueued(number)
        if dropped:
            self.fe.notice(f'Dropped {len(dropped)} queued message(s)')
        self.controller.stop()

    def on_close(self, sender: object) -> None:
        (self.superview or self).close()

    def on_new(self, sender: object) -> None:
        if not self.busy:
            self.run_in_background('/clear')

    def on_plus(self, sender: object) -> None:
        if not self.busy:
            self.run_in_background('/image')

    def on_status(self, sender: object) -> None:
        """Tapping the status line switches the model."""
        if self.busy:
            console.hud_alert('Switch the model when this request is done', 'error', 1.2)
            return
        self.run_in_background('/model')

    def on_effort(self, sender: object) -> None:
        if self.busy:
            console.hud_alert('Change the effort when this request is done', 'error', 1.2)
            return
        self.run_in_background('/effort')

    def on_menu(self, sender: object) -> None:
        in_thread(self._menu)

    def _menu(self) -> None:
        items = PANES if self.busy else MENU  # the panes work while a reply runs
        picked = self.choose('pycoder', [label for label, _ in items])
        if picked is None:
            return
        command = items[picked][1]
        if command == '/btw':
            self.open_side()
        elif command == '/session':
            self.open_session()
        elif command == '/files':
            self.open_files()
        else:
            self.run_in_background(command)

    # ---- questions (called from background threads)

    # the input field gets the keyboard back after each of these, so typing can go on

    def choose(self, title: str, options: Sequence[str], current: int | None = None) -> int | None:
        typing = self.typing()
        if typing and self.kb_height <= SOFTWARE_KEYBOARD:
            # with a hardware keyboard the field behind the list would still take Return (and send
            # a draft); an on-screen keyboard can't be reached under the list, so it may stay
            ui_call(self.field.end_editing)
        try:
            return Picker(title, options, current, theme.colors(self.dark)).pick()
        finally:
            ui_call(lambda: self.after_dialog(typing))

    def ask_text(self, title: str, message: str = '', secret: bool = False) -> str | None:
        typing = self.typing()
        try:
            if secret:
                return console.password_alert(title, message)
            return console.input_alert(title, message)
        except KeyboardInterrupt:
            return None
        finally:
            ui_call(lambda: self.after_dialog(typing))

    @on_main_thread
    def typing(self) -> bool:
        return bool(ObjCInstance(self.field).isFirstResponder())

    def after_dialog(self, typing: bool) -> None:
        """The keyboard comes back only if it was up (on an iPhone it would otherwise cover half the
        screen after every list)."""
        if typing:
            self.field.begin_editing()


class PaletteSource:
    """Rows of the command palette: the command and what it does; tapping one fills the input."""

    def __init__(self, view: ChatView) -> None:
        self.view = view
        self.items: list[tuple[str, str, str]] = []
        self.colors = theme.LIGHT
        self.selected = -1  # the row ↑ ↓ highlighted; Return takes it

    def move(self, step: int) -> None:
        if not self.items:
            return
        if self.selected < 0:  # the first ↓ takes the top row, the first ↑ the bottom one
            self.selected = 0 if step > 0 else len(self.items) - 1
        else:
            self.selected = (self.selected + step) % len(self.items)
        self.view.palette.reload_data()
        self.view.palette.selected_row = (0, self.selected)  # also scrolls it into view

    def tableview_number_of_rows(self, tableview: Any, section: int) -> int:
        return len(self.items)

    def tableview_cell_for_row(self, tableview: Any, section: int, row: int) -> ui.TableViewCell:
        _, title, help_ = self.items[row]
        command, _, arguments = title.partition(' ')  # /resume [last|all|id]: the arguments go below
        title, help_ = command, f'{arguments}  ·  {help_}' if arguments else help_
        cell = ui.TableViewCell('subtitle')
        cell.background_color = self.colors['surface_2' if row == self.selected else 'surface']
        cell.text_label.text = title
        cell.text_label.font = ('<system>', 16)
        cell.text_label.text_color = self.colors['fg']
        cell.detail_text_label.text = help_
        cell.detail_text_label.font = ('<system>', 13)
        cell.detail_text_label.text_color = self.colors['dim']
        return cell

    def tableview_did_select(self, tableview: Any, section: int, row: int) -> None:
        self.view.pick_suggestion(self.items[row][0])

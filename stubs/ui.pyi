from collections.abc import Callable
from typing import Any, TypeVar

_F = TypeVar('_F', bound=Callable[..., Any])

AUTOCAPITALIZE_NONE: int
KEYBOARD_DEFAULT: int

def get_ui_style() -> str: ...
def in_background(func: _F) -> _F: ...
def delay(func: Callable[[], Any], seconds: float) -> None: ...
def cancel_delays() -> None: ...
def convert_point(
    point: tuple[float, float] = ..., from_view: View | None = ..., to_view: View | None = ...
) -> tuple[float, float]: ...

class View:
    name: str
    frame: tuple[float, float, float, float]
    bounds: tuple[float, float, float, float]
    width: float
    height: float
    x: float
    y: float
    flex: str
    superview: View | None
    background_color: Any
    tint_color: Any
    corner_radius: float
    border_width: float
    border_color: Any
    hidden: bool
    alpha: float
    touch_enabled: bool
    on_screen: bool
    left_button_items: list[ButtonItem]
    right_button_items: list[ButtonItem]
    def __init__(self, **kwargs: Any) -> None: ...
    def add_subview(self, view: View) -> None: ...
    def remove_subview(self, view: View) -> None: ...
    def present(
        self, style: str = ..., animated: bool = ..., hide_title_bar: bool = ..., **kwargs: Any
    ) -> None: ...
    def close(self) -> None: ...
    def wait_modal(self) -> None: ...
    def set_needs_display(self) -> None: ...
    def bring_to_front(self) -> None: ...

class WebView(View):
    delegate: Any
    def load_html(self, html: str) -> None: ...
    def load_url(self, url: str) -> None: ...
    def eval_js(self, js: str) -> str: ...

class TextView(View):
    text: str
    font: tuple[str, float]
    text_color: Any
    delegate: Any
    autocapitalization_type: int
    autocorrection_type: bool
    spellchecking_type: bool
    selected_range: tuple[int, int]
    def replace_range(self, range: tuple[int, int], text: str) -> None: ...
    editable: bool
    def begin_editing(self) -> None: ...
    def end_editing(self) -> None: ...

class Label(View):
    text: str
    font: tuple[str, float]
    text_color: Any
    alignment: int
    number_of_lines: int

class Button(View):
    title: str
    font: tuple[str, float]
    enabled: bool
    action: Callable[[Any], Any] | None
    image: Any

class ButtonItem:
    title: str
    enabled: bool
    tint_color: Any
    action: Callable[[Any], Any] | None
    def __init__(
        self,
        title: str | None = ...,
        image: Any = ...,
        action: Callable[[Any], Any] | None = ...,
        enabled: bool = ...,
        tint_color: Any = ...,
    ) -> None: ...

class TableViewCell(View):
    text_label: Label
    detail_text_label: Label
    selectable: bool
    selected_background_view: View | None
    accessory_type: str
    def __init__(self, style: str = ...) -> None: ...

class TableView(View):
    data_source: Any
    delegate: Any
    row_height: float
    separator_color: Any
    selected_row: tuple[int, int]
    def reload_data(self) -> None: ...

def get_screen_size() -> tuple[float, float]: ...

class Image:
    @staticmethod
    def named(name: str) -> Image | None: ...

def measure_string(
    string: str,
    max_width: float = ...,
    font: tuple[str, float] = ...,
    alignment: int = ...,
    line_break_mode: int = ...,
) -> tuple[float, float]: ...

class ImageContext:
    def __init__(self, width: float, height: float, scale: float = 0) -> None: ...
    def __enter__(self) -> ImageContext: ...
    def __exit__(self, *args: Any) -> None: ...
    def get_image(self) -> Any: ...

class ImageView(View):
    image: Image | None

RENDERING_MODE_ORIGINAL: int

def set_color(color: Any) -> None: ...

class Path:
    @staticmethod
    def rounded_rect(x: float, y: float, w: float, h: float, r: float) -> Path: ...
    def fill(self) -> None: ...
    line_cap_style: int
    line_join_style: int
    def set_line_dash(self, sequence: list[float], phase: float = 0) -> None: ...
    line_width: float
    @staticmethod
    def oval(x: float, y: float, width: float, height: float) -> Path: ...
    def move_to(self, x: float, y: float) -> None: ...
    def line_to(self, x: float, y: float) -> None: ...
    def close(self) -> None: ...
    def stroke(self) -> None: ...

class TextField(View): ...
class Switch(View): ...
class Slider(View): ...
class SegmentedControl(View): ...
class DatePicker(View): ...

LINE_CAP_ROUND: int
LINE_JOIN_ROUND: int

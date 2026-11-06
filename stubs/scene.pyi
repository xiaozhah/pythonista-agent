from typing import Any

class Touch:
    def __init__(self, x: float, y: float, prev_x: float, prev_y: float, touch_id: int) -> None: ...
    location: Any
    prev_location: Any
    touch_id: int

"""Picker: a list to choose one option from, in pycoder's colours. The native list dialog follows the
system's appearance instead of pycoder's theme and has no room to explain an option.

An option written "label — what it means" shows the meaning as a second, dimmer line; the option in
use gets a checkmark.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import ui
from objc_util import on_main_thread

from .. import theme

WIDTH = 440
ROW = 44
ROW_WITH_HELP = 58
MAX_HEIGHT = 560
PRESENT_WAIT = 5  # seconds to wait for a sheet that is still going away (over a second on iPhone)


class Picker(ui.View):
    def __init__(
        self, title: str, options: Sequence[str], current: int | None, colors: dict[str, str]
    ) -> None:
        self.name = title
        self.colors = colors
        self.rows = [tuple(option.split(' — ', 1)) if ' — ' in option else (option, '') for option in options]
        self.current = current
        self.picked: int | None = None
        row = ROW_WITH_HELP if any(help_ for _, help_ in self.rows) else ROW
        self.frame = (0, 0, WIDTH, min(MAX_HEIGHT, row * len(self.rows)))
        self.background_color = colors['surface']  # on an iPhone the sheet is taller than the rows
        table = ui.TableView(frame=self.bounds, flex='WH')
        table.row_height = row
        table.background_color = colors['surface']
        table.separator_color = colors['line']
        table.tint_color = colors['fg']
        table.data_source = table.delegate = self
        self.add_subview(table)
        self.table = table
        self.highlighted = current if current is not None else -1

    def pick(self) -> int | None:
        """Show the list and wait for a choice; call it off the main thread."""
        waited = 0.0
        while True:
            try:
                self.present(
                    'sheet',
                    title_bar_color=self.colors['bar'],
                    title_color=self.colors['fg'],
                    hide_title_bar=False,
                )
                break
            except ValueError:  # the sheet before this one is still going away
                if waited >= PRESENT_WAIT:
                    raise
                time.sleep(0.1)
                waited += 0.1
        self.style_bar()
        self.wait_modal()
        return self.picked

    # ---- hardware keyboard: ↑ ↓ move, Return chooses, Esc closes

    def get_key_commands(self) -> list[dict[str, str]]:
        return [{'input': 'up'}, {'input': 'down'}, {'input': '\r'}, {'input': 'esc'}]

    def key_command(self, sender: dict[str, str]) -> None:
        key = sender.get('input')
        if key in ('up', 'down') and self.rows:
            step = -1 if key == 'up' else 1
            start = self.highlighted if self.highlighted >= 0 else (-1 if step > 0 else len(self.rows))
            self.highlighted = (start + step) % len(self.rows)
            self.table.selected_row = (0, self.highlighted)
        elif key == '\r' and self.highlighted >= 0:
            self.tableview_did_select(self.table, 0, self.highlighted)
        elif key == 'esc':
            self.close()

    @on_main_thread
    def style_bar(self) -> None:
        theme.style_title_bar(self, self.colors)  # the × in the text colour

    def tableview_number_of_rows(self, tableview: Any, section: int) -> int:
        return len(self.rows)

    def tableview_cell_for_row(self, tableview: Any, section: int, row: int) -> ui.TableViewCell:
        label, help_ = self.rows[row]
        cell = ui.TableViewCell('subtitle' if help_ else 'default')
        cell.background_color = self.colors['surface']
        cell.selected_background_view = ui.View(background_color=self.colors['surface_2'])
        cell.text_label.text = label
        cell.text_label.font = ('<system>', 17)  # the checkmark marks the current one
        cell.text_label.text_color = self.colors['fg']
        if help_:
            cell.detail_text_label.text = help_
            cell.detail_text_label.font = ('<system>', 13)
            cell.detail_text_label.text_color = self.colors['dim']
        if row == self.current:
            cell.accessory_type = 'checkmark'
        return cell

    def tableview_did_select(self, tableview: Any, section: int, row: int) -> None:
        self.picked = row
        self.close()

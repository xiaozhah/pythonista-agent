---
name: pythonista-ui-apps
description: "Use when building a screen or app with Pythonista's ui module: structure, layout, threads, tables, text input and the usual traps."
---

Exact signatures: look them up with pythonista_docs (page="ui", section_name="View", "TableView", …) instead of guessing. To see and operate what you built, read `checking-a-ui`; for drawing, web views and `.pyui`, `pythonista-ui-drawing-and-web`.

## Structure

- Subclass `ui.View`. Create subviews in `__init__` and add them with `add_subview`; position them in `layout()`, which runs whenever the size changes, using `self.width` and `self.height`. For simple cases `flex` ('W', 'H', 'LR', 'TB'…) is enough.
- Show it with `view.present('fullscreen')`. On an iPad or Mac a sheet or popover takes the view's own size, and a view starts at 100x100: set `view.frame` first, or the form opens as a sliver.
- `present()` returns at once. `view.wait_modal()` blocks until it closes, which suits a form that returns a value.
- Title: `view.name`. Title-bar buttons: `view.right_button_items`, lists of `ui.ButtonItem(title=…, action=…)`. Actions receive the sender.
- `will_close()` runs when the user closes the view: stop threads and timers, save state.
- Repeating work: set `update_interval` and implement `update()`, or `ui.delay(fn, seconds)`.

## Threads: the most common bug

- Actions and delegate methods run on the main thread. Anything slow there freezes the screen: use a `threading.Thread`, or `@ui.in_background` (one shared queue, so calls run one after another).
- Dialogs and alerts wait for the answer: call them from a background thread or an `@ui.in_background` method, never straight from an action.
- A background thread touching UIKit through `objc_util` wraps that code in `@objc_util.on_main_thread`.

## Lists

- Simple: `ds = ui.ListDataSource(items)`, `table.data_source = table.delegate = ds`, `ds.action = handler`. Changing `ds.items` reloads the table.
- Custom: `tableview_number_of_rows(tableview, section)` and `tableview_cell_for_row(tableview, section, row)`, plus delegate methods such as `tableview_did_select`; call `reload_data()` after a change.

## Text

- One line: `ui.TextField` (its delegate's `textfield_should_return` handles Return). Several: `ui.TextView`; `textview_should_change(textview, range, replacement)` can swallow keys.
- Keep the input above the keyboard: implement `keyboard_frame_did_change(frame)` on the presented view, and move things in `layout()`.
- To make a label fit its width, let UIKit do it: `native = ObjCInstance(label)`, `native.setAdjustsFontSizeToFitWidth_(True)`, `native.setMinimumScaleFactor_(0.1)`. `ui.measure_string` misjudges system fonts.

## Traps

- Pythonista keeps imported modules between runs: when the app is split into modules, remove them from `sys.modules` at the start of the main script, or edits seem to have no effect.
- Presenting a view while another is on screen fails: close it first.
- `open()` defaults to ASCII here: always pass `encoding='utf-8'`.

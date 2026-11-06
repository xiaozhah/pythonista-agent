# Hands-on QA tour

One small project, built with pycoder the way a user would, that touches every feature: the
console, every tool, every slash command, every button and dialog. Run it after big changes, on
the Mac and on the iPhone, with haiku (cheap) unless a step says otherwise. Look at each screen as a
user would: wrong colours, cramped or tiny text, things that jump, noise, wording.

The project is `~/qa-tour`: a "device dashboard" script that reads the sensors and prints a
humanized report.

## 1. Console

| Do | Check |
| --- | --- |
| `cd ~ && git clone https://github.com/python-humanize/humanize` | no token asked (public repo) |
| `mkdir qa-tour && cd qa-tour && ls`, `touch a.txt`, `cp`, `mv`, `rm`, `cat`, `head`, `tree`, `pwd`, `cd -`, `cd /local`, `cd ~` | chains stop at a failure; only the error is red |
| `python -c "print(1+1)"`, `pip install humanize` | |
| `frobnicate`, `a | b` | clear errors |
| Tab on a command and on a path; ↑ ↓; Ctrl+C on a typed line and during `python -c "import time; time.sleep(9)"`; `1+1`, `ls = 5`, `ls` (then `del ls`) | Python stays Python |
| `bridge`, `bridge stop` | the console stays usable meanwhile |
| `cd ~/qa-tour && pycoder` | the chat opens in that folder |
| `help`, `history`, `clear`, `pycoder update` | |

## 2. Chat basics (mode: ask first)

| Prompt or action | Covers |
| --- | --- |
| Status line → pick **haiku**; ⋯ → Thinking effort → low | picker, header updates |
| "Look at ~/humanize: what does naturalsize do? Run it on 123456789." | list_files, search, read_file, run_python, Allow / Deny cards |
| "Write dashboard.py: battery, model and storage from device_info, formatted with humanize; run it." | write_file (preview card), run_python, install_package |
| "Change the title line to bold capitals." | edit_file diff card, "Always" rule |
| `@dashboard.py what does this do?` | @mention palette |
| Plant a bug by hand (e.g. a `KeyError` in a helper three calls deep, and an off-by-one that only shows in the output), then "dashboard.py crashes and the percentages look wrong; debug it." | debugging: reproduces first, reads the traceback and locals, narrows down with prints or a small test, fixes the cause (not the symptom), reruns to confirm |
| "Write tests for the helpers and run them." | tests without pytest installed or with it |
| `!ls` and `!git status` | shell cards |
| Stop while it streams; send while busy (queue) | interrupted note, queue |

## 3. Device and iOS

| Prompt | Covers |
| --- | --- |
| "Where am I and how is the phone being held? Add both to the dashboard." | location, motion, device_info |
| "Read the dashboard aloud, then copy it to the clipboard and read the clipboard back." | speak, clipboard_write, clipboard_read |
| "Remind me in 1 minute to stretch." | notify (also check the turn-done notification with Pythonista in the background) |
| "Record 3 seconds of audio and tell me how loud it was." | record_audio |
| "Look at my latest screenshot and describe it." / + button → Photo library | photos, /image, the image bubble |
| "Read the text in my latest screenshot." / "What does this receipt say?" (pick a photo) | recognize_text (Vision OCR, Chinese and English) |
| "Let me pick a file to import." | import_file |
| "Share the report." / "Open dashboard.py in the editor." / "Open apple.com." | share, open_in_editor, open_url |
| "Run my Shortcut called <name>." | run_shortcut |
| "Ask me which colour the title should be." | ask_user (list and free text) |

## 4. Knowledge and planning

| Prompt or command | Covers |
| --- | --- |
| "How do I show this in a ui.TableView? Check the Pythonista docs, then build ui_dashboard.py." | pythonista_docs, pythonista-ui-apps skill |
| "What's the weather in Manchester today?" | web search, live-information skill |
| `/plan` then "add a history graph"; Keep planning (note dialog), then approve | plan mode, exit_plan_mode card |
| "Make a todo list for the remaining work." / `/todos` | todo_write, todo_update, todo_add |
| "Use a subagent to summarise ~/humanize/tests." | task |
| "With two subagents, add a docstring to each of these two functions." then `/rewind` | task with writes, its merge and undo |
| "Remember for every project that I like short answers." / `/memory`; "What do you remember?"; "Forget it." | remember (global), recall, forget |
| "Make a skill of how you built the dashboard." / `/skills` | save_skill, read_skill |
| "Where is main defined, and who calls it?" | python_code |
| Open the dashboard's window: "Press its buttons and check them." | use_screen, look_at_screen |
| "Move hello.py to old/hello.py, then delete old." then `/rewind` | move_file, delete_file |
| `git init`, then `/commit` | git tool, Markdown prompt commands |

## 5. Every slash command and screen

`/help` `/status` `/context` `/cost` `/usage` `/model` `/effort` `/mode` `/bypass` `/plan`
`/permissions` `/config` (all tabs, Save and Cancel) `/web` `/key` (cancel it)
`/skills` `/memory` `/todos` `/session` `/crashes` `/btw` `/fork` `/chapters` `/rename` `/compact`
`/rewind` (both restore choices) `/resume` `/delete`
`/image` `/pip` `/cd` `/clear` `/update` `/exit`, then `pycoder -c` and `pycoder -r` from the console.

Buttons: ✕, New, ⋯ (every menu entry), +, ↵ (send and stop), the status line, the mode pill, Thinking
toggles, `code` / `output` disclosures, Allow / Deny / Always, and ⌘= / ⌘- zoom. Check each in the
light and dark theme.

## 6. Hardware keyboard (iPad with a keyboard, or the Mac)

| Where | Keys | Expect |
| --- | --- | --- |
| Console | ↑ ↓, Tab, Ctrl+C | history, completion, clears the line or stops the command |
| Chat input | ↑ ↓ (first/last line), Shift+Return, Return, Esc | earlier messages with the draft kept, a line break, send, stop the reply |
| Chat input, multi-line | ↑ on the second line | the caret moves; no history |
| Chinese input method | ↑ ↓ Esc while choosing a candidate | the input method keeps them |
| Command palette | ↓ ↓ Return, Esc | highlight moves, Return fills it in, Esc closes |
| Pickers | ↑ ↓ Return, Esc | choose, close; typing goes on without clicking the field |
| /config sheet | Esc | closes like Cancel; the input bar is hidden while it is open |

## 7. When things go wrong

| Try | Expect |
| --- | --- |
| run_python `while True: pass`, and `time.sleep(1000)` | stops at the timeout; a C-level wait is reported as still running |
| run_python printing millions of lines | the start and end kept (about 40 KB), the app stays responsive |
| run_python growing a list of big buffers | stopped with MemoryError before iOS closes Pythonista |
| Edit GBK, Windows-1252, UTF-16 and CRLF files | edited; encoding, BOM and line endings kept |
| Wi-Fi off mid-reply / a stalled stream | retries with a note; Stop works during the wait |
| Location or microphone denied, camera on a Mac | a clear message, no crash |

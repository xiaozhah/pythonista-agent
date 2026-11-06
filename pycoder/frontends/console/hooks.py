"""Teaches Pythonista's console the shell, by replacing methods of its native classes for as long as
the app runs: what a typed line runs as, Tab, what completions it offers, and Ctrl+C. Whatever goes
wrong here, the line goes on to Python as it would have.

This code stays for as long as the app runs, while Pythonista forgets imported modules between
scripts, so what a line means is asked of lines.py afresh every time.
"""

from __future__ import annotations

import ctypes
import importlib
import os
import sys
import traceback
from collections.abc import Callable
from typing import Any

from ...host import env

LINES = 'pycoder.frontends.console.lines'
INSTALL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CONTROL = 1 << 18  # UIKeyModifierControl


def lines() -> Any:
    if INSTALL_DIR not in sys.path:
        sys.path.append(INSTALL_DIR)
    return importlib.import_module(LINES)


IMPORT_SHIM = """# Written by pycoder, so that a script started with Pythonista's Run button can import it:
# its folder isn't on sys.path by then, and this one always is. It loads the real package.
import importlib.util
import sys

_root = {root!r}
if _root not in sys.path:
    sys.path.append(_root)
_spec = importlib.util.spec_from_file_location(
    __name__, _root + '/pycoder/__init__.py', submodule_search_locations=[_root + '/pycoder']
)
_module = importlib.util.module_from_spec(_spec)
sys.modules[__name__] = _module
_spec.loader.exec_module(_module)
"""


def write_import_shim(folder: str, root: str) -> None:
    """Let `import pycoder` work from anywhere, as the program pycoder writes will be run by hand."""
    path = os.path.join(folder, 'pycoder.py')
    text = IMPORT_SHIM.format(root=root)
    try:
        with open(path, encoding='utf-8') as f:
            if f.read() == text:
                return
    except OSError:
        pass
    os.makedirs(folder, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def install() -> None:
    """Once per process: the replaced methods can't be replaced again without keeping what they were."""
    kept: list[Any] = env.process_wide('console_hooks', [])
    if kept:
        return
    write_import_shim(os.path.expanduser('~/Documents/site-packages'), INSTALL_DIR)

    from objc_util import NSRange, ObjCClass, ObjCInstance, ns, sel

    runtime = ctypes.CDLL(None)  # not objc_util's: what is declared on a library object stays on it
    runtime.class_getInstanceMethod.restype = ctypes.c_void_p
    runtime.class_getInstanceMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    runtime.method_getImplementation.restype = ctypes.c_void_p
    runtime.method_getImplementation.argtypes = [ctypes.c_void_p]
    runtime.method_setImplementation.restype = ctypes.c_void_p
    runtime.method_setImplementation.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    def replace(class_name: str, method: str, kind: Any, make: Callable[[Any], Callable[..., Any]]) -> None:
        found = runtime.class_getInstanceMethod(ObjCClass(class_name).ptr, sel(method))
        old = kind(runtime.method_getImplementation(found))
        new = kind(make(old))
        kept.extend([old, new])
        runtime.method_setImplementation(found, ctypes.cast(new, ctypes.c_void_p))

    def line_of(editor: Any) -> str:
        return str(editor.textView().text()).rstrip('\n')  # its text always ends with a line break

    def is_console(editor: Any) -> bool:
        provider = editor.completionProvider()  # an editor that offers no completions has none
        return provider is not None and bool(
            provider.isKindOfClass_(ObjCClass('PA2ConsoleCompletionProvider'))
        )

    def offers(editor: Any) -> bool:
        return bool(editor.completionSuggestions() and editor.completionSuggestions().count())

    def make_run(old: Any) -> Callable[..., None]:
        def run(self: int, cmd: int, text: int) -> None:
            code = None
            try:
                line = str(ObjCInstance(text))
                if lines().is_command(line):
                    code = ns(f'__import__("importlib").import_module({LINES!r}).run({line!r})')
            except Exception:
                traceback.print_exc()
            old(self, cmd, code.ptr if code is not None else text)

        return run

    def make_should_change(old: Any) -> Callable[..., bool]:
        def should_change(self: int, cmd: int, editor: int, where: NSRange, text: int) -> bool:
            try:
                if str(ObjCInstance(text)) == '\t':
                    view = ObjCInstance(editor)
                    line = line_of(view)
                    # for a first word the completions on screen are what Tab takes: they have both
                    done = lines().complete(line) if ' ' in line or not offers(view) else None
                    if done is not None:
                        new, options = done
                        view.textView().setText_(ns(new))
                        view.textView().setSelectedRange_(NSRange(len(new.encode('utf-16-le')) // 2, 0))
                        if len(options) > 1:
                            lines().say('  '.join(options[:40]), 'dim')
                        return False
            except Exception:
                traceback.print_exc()
            return bool(old(self, cmd, editor, where, text))

        return should_change

    def make_suggestions(old: Any) -> Callable[..., None]:
        def set_suggestions(self: int, cmd: int, found: int) -> None:
            combined = None
            try:
                editor = ObjCInstance(self)
                if is_console(editor):
                    line = line_of(editor)
                    names = lines().suggest(line)
                    if names:
                        matched = ObjCClass('NSIndexSet').indexSetWithIndexesInRange_(NSRange(0, len(line)))
                        ours = [
                            {
                                'name': name,
                                'type': 'statement',
                                'rank': 0,
                                'fuzzy': False,
                                'isFuzzy': False,
                                'isKeyword': True,
                                'caseMatches': True,
                                'underscores': 0,
                                'matchedRanges': matched,
                            }
                            for name in names
                        ]
                        combined = ns(ours)
                        if found:
                            combined = combined.arrayByAddingObjectsFromArray_(ObjCInstance(found))
            except Exception:
                traceback.print_exc()
            old(self, cmd, combined.ptr if combined is not None else found)

        return set_suggestions

    def make_key_commands(old: Any) -> Callable[..., int]:
        interrupt = ObjCClass('UIKeyCommand').keyCommandWithInput_modifierFlags_action_(
            'c', CONTROL, sel('stop:')
        )
        kept.append(interrupt)

        def key_commands(self: int, cmd: int) -> int:
            others = old(self, cmd)
            return int(
                ObjCInstance(others).arrayByAddingObject_(interrupt).ptr if others else ns([interrupt]).ptr
            )

        return key_commands

    def make_stop(old: Any) -> Callable[..., None]:
        def stop(self: int, cmd: int, sender: int) -> None:
            try:
                screen = ObjCInstance(self)
                if not screen.isInterpreterRunning():  # as in a shell: what was typed stays on screen
                    editor = screen.promptEditorView()
                    lines().say(f'>>> {line_of(editor)}^C')
                    editor.textView().setText_(ns(''))
                    return
                lines().interrupt()
            except Exception:
                traceback.print_exc()
            old(self, cmd, sender)

        return stop

    pointer = ctypes.c_void_p
    replace('PYK3Interpreter', 'runREPL:', ctypes.CFUNCTYPE(None, pointer, pointer, pointer), make_run)
    screen = 'PA2ConsoleViewController'
    replace(
        screen,
        'editorView:shouldChangeTextInRange:replacementText:',
        ctypes.CFUNCTYPE(ctypes.c_bool, pointer, pointer, pointer, NSRange, pointer),
        make_should_change,
    )
    replace(
        'OMTextEditorView',
        'setCompletionSuggestions:',
        ctypes.CFUNCTYPE(None, pointer, pointer, pointer),
        make_suggestions,
    )
    replace(screen, 'keyCommands', ctypes.CFUNCTYPE(pointer, pointer, pointer), make_key_commands)
    replace(screen, 'stop:', ctypes.CFUNCTYPE(None, pointer, pointer, pointer), make_stop)

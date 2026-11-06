"""
Run this once in Pythonista (and again if this folder moves). From then on the console understands
`pycoder` and the shell's commands (`ls`, `cd`, `git`, …) whenever the app starts, next to Python.
It adds a few lines to pythonista_startup.py, which Pythonista runs by itself, and leaves the rest of
that file alone.
"""

import os
import sys

STARTUP = os.path.expanduser('~/Documents/site-packages/pythonista_startup.py')
BEGIN = '# pycoder begin'
END = '# pycoder end'
BLOCK = """def _pycoder():
    import sys

    if {root!r} not in sys.path:
        sys.path.append({root!r})
    try:
        from pycoder.frontends.console.hooks import install

        install()
    except Exception as e:
        print('The console has no pycoder commands:', type(e).__name__, e)


_pycoder()
del _pycoder
"""


def with_block(text: str, root: str) -> str:
    """The startup file's text with pycoder's block in it, in place of any it had."""
    start, end = text.find(BEGIN), text.find(END)
    if start >= 0 and end >= 0:
        text = text[:start] + text[end + len(END) :].lstrip('\n')
    if text and not text.endswith('\n'):
        text += '\n'
    return f'{text}{BEGIN}, written by {root}/install.py\n{BLOCK.format(root=root)}{END}\n'


def main() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(STARTUP, encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        text = ''
    os.makedirs(os.path.dirname(STARTUP), exist_ok=True)
    with open(STARTUP, 'w', encoding='utf-8') as f:
        f.write(with_block(text, root))
    if root not in sys.path:
        sys.path.append(root)
    from pycoder.frontends.console.hooks import install

    install()
    print('Done. Type pycoder in the console, here and every time Pythonista starts.')


if __name__ == '__main__':
    main()

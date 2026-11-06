"""pythonista_docs: Pythonista's own documentation, read on demand.

Pythonista ships its full documentation inside the app (Documentation.zip next to the executable):
the iOS modules (ui, scene, photos, dialogs, objc_util, …) and the Python standard library, as the
reStructuredText sources of the Sphinx pages. Reading them here matches the installed version
exactly and costs nothing until Claude asks: a page, one class or function, or a search.
"""

from __future__ import annotations

import re
import zipfile
from functools import lru_cache

from ..host import env
from .base import Tool, ToolContext, ToolError, prop

SOURCES = 'py3/_sources/'
MAX_CHARS = 40_000
MAX_HITS = 60
# The module pages of Pythonista 3.4's documentation, for the tool description (the archive lists
# them all, guides included, when the tool is called without arguments)
IOS_MODULES = (
    'appex',
    'canvas',
    'cb',
    'clipboard',
    'console',
    'contacts',
    'dialogs',
    'editor',
    'keyboard',
    'keychain',
    'linguistictagger',
    'location',
    'motion',
    'notification',
    'objc_util',
    'photos',
    'reminders',
    'scene',
    'scene_drawing',
    'sound',
    'speech',
    'twitter',
    'ui',
)
_DIRECTIVE = re.compile(
    r'^(\s*)\.\. (?:class|function|method|classmethod|staticmethod|attribute|data|exception|module)::'
    r'\s+([\w.]+)'
)
_TOP_LEVEL = re.compile(r'^\.\. (\w+)::\s+(\w+)\b(?!\.)')


@lru_cache(maxsize=1)
def _archive(path: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(path)


def _zip() -> zipfile.ZipFile:
    path = env.docs_archive()
    if path is None:
        raise ToolError("Pythonista's documentation is only available inside Pythonista")
    return _archive(path)


def pages() -> dict[str, str]:
    """Page name → archive path: 'ui', 'scene', … for the iOS modules, 'library/json' and so on."""
    out = {}
    for name in _zip().namelist():
        if name.startswith(SOURCES) and name.endswith('.rst.txt'):
            rel = name[len(SOURCES) : -len('.rst.txt')]
            out[rel.removeprefix('ios/')] = name
    return out


def ios_pages() -> list[str]:
    return sorted(n for n, path in pages().items() if path.startswith(SOURCES + 'ios/'))


def read_page(page: str) -> str:
    known = pages()
    path = known.get(page) or known.get(page.removeprefix('ios/')) or known.get(f'library/{page}')
    if path is None:  # 'pythonista-keyboard' for the keyboard module
        path = known.get(page.lower().replace('pythonista', '').strip('-_ '))
    if path is None:
        close = [p for p in known if page.lower() in p.lower()][:15]
        hint = (
            f'did you mean {", ".join(close)}?'
            if close
            else 'the iOS module pages are ' + ', '.join(ios_pages())
        )
        raise ToolError(f'No page {page!r}; {hint}')
    return _zip().read(path).decode('utf-8', 'replace')


def section(text: str, name: str) -> str:
    """One class, function, method or attribute with everything under it, or a titled section of
    the page (such as "Building Custom Views"); ToolError listing what the page has when neither is
    there."""
    found = _find_section(text, name) or _titled_section(text, name)
    if found is None:
        mentions = _mentions(text, name.split('.')[-1])
        if mentions:
            return f'{name} has no section of its own on this page. Lines that mention it:\n{mentions}'
        raise ToolError(
            f'No section {name!r} on this page. Its classes and functions: {", ".join(names(text))}; '
            f'its sections: {", ".join(title for title, _, _ in _headings(text.splitlines()))}'
        )
    if len(found) > MAX_CHARS:
        found = found[:MAX_CHARS] + '\n… (the section goes on; ask for one class or function in it)'
    return found


def _mentions(text: str, word: str) -> str:
    """The lines with this word, for what the docs only mention (View.layout, Action.remove)."""
    pattern = re.compile(rf'\b{re.escape(word)}\b')
    lines = enumerate(text.splitlines(), 1)
    found = [f'{n}: {line.strip()[:160]}' for n, line in lines if pattern.search(line)]
    return '\n'.join(found[:MAX_HITS])


def _headings(lines: list[str]) -> list[tuple[str, int, int]]:
    """(title, line index, level) of each reStructuredText heading: a title underlined with = - ~ …
    The level is the order in which the page first uses each underline character."""
    found: list[tuple[str, int, int]] = []
    levels: list[str] = []
    for i in range(len(lines) - 1):
        title, under = lines[i].strip(), lines[i + 1].rstrip()
        if not title or lines[i][0].isspace() or not under or under[0].isspace():
            continue
        if len(set(under)) == 1 and under[0] in '=-~^*#"+' and len(under) >= len(title) * 0.8:
            if set(title) == set(under):  # an overline, not a title
                continue
            if under[0] not in levels:
                levels.append(under[0])
            found.append((title, i, levels.index(under[0])))
    return found


def _titled_section(text: str, name: str) -> str | None:
    """A titled section with its subsections, up to the next heading of its level or above."""
    lines = text.splitlines()
    headings = _headings(lines)
    for k, (title, start, level) in enumerate(headings):
        if title.lower() != name.strip().lower():
            continue
        end = next((i for _, i, lv in headings[k + 1 :] if lv <= level), len(lines))
        return '\n'.join(lines[start:end]).rstrip()
    return None


def _find_section(text: str, name: str) -> str | None:
    """One class, function, method or attribute with everything under it (sub-headings such as
    "Methods" included), up to the next directive that isn't one of its members."""
    lines = text.splitlines()
    short = name.split('.')[-1]
    for i, line in enumerate(lines):
        m = _DIRECTIVE.match(line)
        if not m or not (m.group(2) in (name, short) or m.group(2).endswith('.' + name)):
            continue
        indent, found = len(m.group(1)), m.group(2)
        end = len(lines)
        for j in range(i + 1, len(lines)):
            n = _DIRECTIVE.match(lines[j])
            if n and len(n.group(1)) <= indent and not n.group(2).startswith(found + '.'):
                end = j
                break
        body = lines[i:end]
        while body and (not body[-1].strip() or _is_heading_end(body)):
            body = body[:-2] if _is_heading_end(body) else body[:-1]  # the next section's title
        return '\n'.join(body).rstrip()
    return None


def names(text: str) -> list[str]:
    """The classes and functions a page defines (not their members)."""
    found = (m for m in map(_TOP_LEVEL.match, text.splitlines()) if m)
    return list(dict.fromkeys(m.group(2) for m in found if m.group(1) in ('class', 'function', 'exception')))


def find_anywhere(name: str) -> str:
    """A class or function looked up in every iOS module page (or in the page its prefix names)."""
    prefix = name.split('.')[0]
    targets = [prefix] if '.' in name and prefix in ios_pages() else ios_pages()
    found = []
    for page in targets:
        text = _find_section(read_page(page), name)
        if text is not None:
            found.append(f'From page {page}:\n{text}')
    if not found:
        raise ToolError(f'No class or function {name!r} in the iOS module pages; search for it with query')
    out = '\n\n'.join(found)
    return out if len(out) <= MAX_CHARS else out[:MAX_CHARS] + '\n… (more; give a page)'


def _is_heading_end(lines: list[str]) -> bool:
    last = lines[-1]
    return (
        len(lines) > 1
        and bool(last.strip())
        and set(last.strip()) <= set('=-~^*#"')
        and not last[0].isspace()
    )


def search(query: str, page: str = '') -> str:
    """Lines with every word of the query, from one page or from every iOS module page; when no
    line has them all, the lines with the most of them."""
    words = query.lower().split()
    if not words:
        raise ToolError('Give words to search for')
    targets = [page] if page else ios_pages()
    scored = []
    for name in targets:
        for number, line in enumerate(read_page(name).splitlines(), 1):
            low = line.lower()
            score = sum(word in low for word in words)
            if score:
                scored.append((score, f'{name}:{number}: {line.strip()[:160]}'))
    if not scored:
        return f'Nothing found for {query!r}'
    best = max(score for score, _ in scored)
    hits = [hit for score, hit in scored if score == best]
    note = '' if best == len(words) else f'(no line has all of {query!r}; these have {best} of the words)\n'
    if len(hits) > MAX_HITS:
        return note + '\n'.join(hits[:MAX_HITS]) + '\n… (more; narrow the search or give a page)'
    return note + '\n'.join(hits)


def pythonista_docs(ctx: ToolContext, page: str = '', section_name: str = '', query: str = '') -> str:
    if query:
        return search(query, page)
    if section_name and not page:
        return find_anywhere(section_name)
    if not page:
        return (
            'iOS module pages: ' + ', '.join(ios_pages()) + '\n'
            'Standard library pages are library/<module> (e.g. library/json); also tutorial/…, howto/…, '
            'reference/…. Ask for a page, a section of it, or search.'
        )
    text = read_page(page)
    if section_name:
        return section(text, section_name)
    if len(text) > MAX_CHARS:
        return (
            text[:MAX_CHARS]
            + f'\n… (the page is {len(text)} characters; ask for a section, e.g. section_name="TableView")'
        )
    return text


TOOLS = [
    Tool(
        'pythonista_docs',
        "Pythonista's official documentation for the installed version: the iOS modules and the "
        'standard library. Look things up here before writing code with these modules instead of '
        'relying on memory. The iOS module pages: ' + ', '.join(IOS_MODULES) + '; standard library '
        'pages are library/<module>. No arguments lists every page; page alone reads it; section_name '
        'reads one class or function, from the given page or, without one, from whichever iOS page '
        'defines it (e.g. section_name="TableView"); query searches.',
        {
            'page': prop('string', 'A page such as ui, scene, photos, or library/json'),
            'section_name': prop(
                'string', 'A class, function or attribute, e.g. TableView or View.present (page optional)'
            ),
            'query': prop('string', 'Words to search for (in the given page, or in every iOS module page)'),
        },
        pythonista_docs,
    ),
]

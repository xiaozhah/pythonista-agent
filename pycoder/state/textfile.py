"""Text files as they are on disk. Reading finds the encoding, a byte-order mark and Windows line
endings; writing puts them back. So editing a GBK, UTF-16 or CRLF file changes only what was
edited, and the model always works with plain text and \\n line endings.

A format is accepted only if writing the decoded text back gives the very same bytes, so an
unchanged part of a file can never be damaged, whatever the guess.
"""

from __future__ import annotations

from dataclasses import dataclass

BOM = '\ufeff'  # the byte-order mark, as a character
BOMS = (
    (b'\xef\xbb\xbf', 'utf-8'),
    (b'\xff\xfe', 'utf-16-le'),
    (b'\xfe\xff', 'utf-16-be'),
)
NAMES = {
    'utf-8': 'UTF-8',
    'utf-16-le': 'UTF-16',
    'utf-16-be': 'UTF-16 (big-endian)',
    'gb18030': 'GBK/GB18030',
    'cp1252': 'Windows-1252',
    'latin-1': 'Latin-1',
}


class BinaryFile(Exception):
    """Not text: NUL bytes with no UTF-16 byte-order mark."""


@dataclass(frozen=True)
class TextFormat:
    encoding: str = 'utf-8'
    bom: bool = False
    crlf: bool = False  # every line ends with \r\n; the text is kept with \n

    def encode(self, text: str) -> bytes:
        if self.crlf:
            text = text.replace('\n', '\r\n')
        return ((BOM if self.bom else '') + text).encode(self.encoding)

    def describe(self) -> str:
        """How the file is stored, for the model, when that isn't plain UTF-8 with \\n endings."""
        parts = []
        if self.encoding != 'utf-8' or self.bom:
            parts.append(
                NAMES.get(self.encoding, self.encoding) + (' with a byte-order mark' if self.bom else '')
            )
        if self.crlf:
            parts.append('Windows (CRLF) line endings')
        return ', '.join(parts)


UTF8 = TextFormat()


def decode(data: bytes) -> tuple[str, TextFormat]:
    """The text of a file and how it is stored; BinaryFile if it isn't text."""
    for bom, encoding in BOMS:
        if data.startswith(bom):
            found = _try(data[len(bom) :], encoding, bom=True)
            if found:
                return found
    if b'\0' in data[:8192]:
        raise BinaryFile()
    for encoding in _candidates(data):
        found = _try(data, encoding, bom=False)
        if found:
            return found
    raise BinaryFile()  # unreachable: Latin-1 takes any bytes


def _try(body: bytes, encoding: str, bom: bool) -> tuple[str, TextFormat] | None:
    try:
        text = body.decode(encoding)
    except UnicodeDecodeError:
        return None
    crlf = '\r\n' in text and text.count('\r\n') == text.count('\n')
    fmt = TextFormat(encoding, bom, crlf)
    if crlf:
        text = text.replace('\r\n', '\n')
    full = (_bom_bytes(encoding) if bom else b'') + body
    return (text, fmt) if fmt.encode(text) == full else None


def _bom_bytes(encoding: str) -> bytes:
    return next(b for b, e in BOMS if e == encoding)


def _candidates(data: bytes) -> list[str]:
    """UTF-8 first; then GBK or Windows-1252, whichever reads more like text; Latin-1 takes anything."""
    if _decodes(data, 'utf-8'):
        return ['utf-8']
    gbk, western = _decodes(data, 'gb18030'), _decodes(data, 'cp1252')
    if gbk is not None and western is not None:
        # Chinese characters are pairs of high bytes; accented Western letters mostly stand alone
        order = ['cp1252', 'gb18030'] if _isolated_share(western) >= 0.6 else ['gb18030', 'cp1252']
    else:
        order = [e for e, text in (('gb18030', gbk), ('cp1252', western)) if text is not None]
    return [*order, 'latin-1']


def _decodes(data: bytes, encoding: str) -> str | None:
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return None


def _isolated_share(text: str) -> float:
    """Of the non-ASCII characters, the share with ASCII (or nothing) on both sides."""
    high = [i for i, ch in enumerate(text) if ord(ch) > 127]
    if not high:
        return 1.0
    lone = sum(
        1
        for i in high
        if (i == 0 or ord(text[i - 1]) < 128) and (i + 1 == len(text) or ord(text[i + 1]) < 128)
    )
    return lone / len(high)

"""Images for a message: from a file, the clipboard or the photo library, as API image blocks."""

from __future__ import annotations

import base64
import functools
import io
import os
from typing import Any

from ..types import Block
from .env import IN_PYTHONISTA
from .main_thread import call_on_main

MAX_EDGE = 1568  # pixels; the API scales larger images down to this anyway, after paying to send them
MAX_PNG = 512 * 1024  # bytes; a larger image with transparency is sent as a JPEG on white instead
THUMB_EDGE = 480  # pixels; the chat shows images at most 220 points wide
MEDIA_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
}


class ImageError(Exception):
    pass


def block_from_pil(image: Any) -> Block:
    """Scale down if needed and encode: PNG when there is transparency, unless that PNG is big (a
    screenshot), which goes as a JPEG on white; otherwise JPEG."""
    image = _scaled(image, MAX_EDGE)
    if image.mode in ('RGBA', 'LA', 'P'):
        out = io.BytesIO()
        image.save(out, 'PNG')
        if out.tell() <= MAX_PNG:
            return block_from_bytes(out.getvalue(), 'image/png')
        image = _on_white(image)
    return block_from_bytes(_jpeg(image, 85), 'image/jpeg')


def _scaled(image: Any, edge: int) -> Any:
    if max(image.size) > edge:
        image = image.copy()
        image.thumbnail((edge, edge))
    return image


def _on_white(image: Any) -> Any:
    from PIL import Image

    image = image.convert('RGBA')
    flat = Image.new('RGB', image.size, 'white')
    flat.paste(image, mask=image.getchannel('A'))
    return flat


def _jpeg(image: Any, quality: int) -> bytes:
    out = io.BytesIO()
    image.convert('RGB').save(out, 'JPEG', quality=quality)
    return out.getvalue()


@functools.lru_cache(maxsize=32)
def thumbnail(media_type: str, data: str) -> tuple[str, str]:
    """A small JPEG of a base64 image, for showing it in the chat: (media type, base64). The image
    itself when it is small already or can't be decoded here."""
    if len(data) < 64 * 1024:
        return media_type, data
    try:
        from PIL import Image

        with Image.open(io.BytesIO(base64.b64decode(data))) as image:
            image = _scaled(image, THUMB_EDGE)
            small = _jpeg(_on_white(image) if image.mode in ('RGBA', 'LA', 'P') else image, 80)
    except Exception:  # no PIL, or not an image it can read: show it as it is
        return media_type, data
    return 'image/jpeg', base64.b64encode(small).decode('ascii')


def block_from_bytes(data: bytes, media_type: str) -> Block:
    return {
        'type': 'image',
        'source': {
            'type': 'base64',
            'media_type': media_type,
            'data': base64.b64encode(data).decode('ascii'),
        },
    }


def from_path(path: str) -> Block:
    ext = os.path.splitext(path)[1].lower()
    if ext not in MEDIA_TYPES:
        raise ImageError(f'Not a supported image type: {path}')
    try:
        from PIL import Image
    except ImportError:
        with open(path, 'rb') as f:
            return block_from_bytes(f.read(), MEDIA_TYPES[ext])
    with Image.open(path) as image:
        return block_from_pil(image)


def from_clipboard() -> Block:
    if not IN_PYTHONISTA:
        raise ImageError('The clipboard is only available in Pythonista')
    import clipboard

    image = call_on_main(clipboard.get_image)
    if image is None:
        raise ImageError('There is no image on the clipboard')
    return block_from_pil(image)


def from_photos() -> Block:
    if not IN_PYTHONISTA:
        raise ImageError('The photo library is only available in Pythonista')
    import photos

    asset = photos.pick_asset(title='Attach a photo')
    if asset is None:
        raise ImageError('No photo chosen')
    from PIL import Image

    with Image.open(asset.get_image_data()) as image:
        return block_from_pil(image)


def from_camera() -> Block:
    if not IN_PYTHONISTA:
        raise ImageError('The camera is only available in Pythonista')
    import photos

    image = photos.capture_image()
    if image is None:
        raise ImageError('No photo taken')
    return block_from_pil(image)


def describe(block: Block) -> str:
    size = len(block['source']['data']) * 3 // 4
    return '%s, %d KB' % (block['source']['media_type'].split('/')[1], size // 1024)

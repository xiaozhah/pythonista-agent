"""Images as API blocks: their size, format, and the thumbnails the chat shows."""

from __future__ import annotations

import base64
import io
import os

from PIL import Image

from pycoder.host import images


def decoded(data: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data)))


def test_images_are_capped_at_the_size_the_api_uses() -> None:
    block = images.block_from_pil(Image.new('RGB', (4000, 3000), 'red'))
    assert block['source']['media_type'] == 'image/jpeg'
    assert decoded(block['source']['data']).size == (1568, 1176)


def test_transparency_stays_png_unless_that_is_big() -> None:
    small = images.block_from_pil(Image.new('RGBA', (100, 100), (0, 0, 0, 0)))
    assert small['source']['media_type'] == 'image/png'
    noise = Image.frombytes('RGBA', (1000, 1000), os.urandom(4_000_000))  # a PNG of several MB
    big = images.block_from_pil(noise)
    assert big['source']['media_type'] == 'image/jpeg'


def test_the_chat_shows_a_small_copy() -> None:
    block = images.block_from_pil(Image.frombytes('RGB', (1500, 1000), os.urandom(4_500_000)))
    kind, data = images.thumbnail(block['source']['media_type'], block['source']['data'])
    assert kind == 'image/jpeg'
    assert max(decoded(data).size) == images.THUMB_EDGE
    assert len(data) < len(block['source']['data']) / 3
    assert images.thumbnail('image/png', 'not an image' * 10_000)[1].startswith('not an image')

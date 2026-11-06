"""recognize_text: read the words in an image on the device, with Apple's Vision framework.

Vision's text recognizer ships with iOS and runs on the Neural Engine: it costs nothing, works
offline, and the image never leaves the device. When only the words in an image matter (a
receipt, a screenshot of an error, a sign) it is cheaper than sending the image to the model.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from ..host.main_thread import call_on_main
from .base import Tool, ToolContext, ToolError, prop

SOURCES = ('clipboard', 'pick', 'screenshot', 'camera')
# without automatic detection (before iOS 16) Vision reads only the languages it is given; its
# default is English alone, which silently drops Chinese lines
FALLBACK_LANGUAGES = ['zh-Hans', 'zh-Hant', 'en-US']


def recognize_text(ctx: ToolContext, path: str = '', source: str = '', languages: str = '') -> str:
    if bool(path) == bool(source):
        raise ToolError('Give either path (a workspace image) or source (' + ', '.join(SOURCES) + ')')
    if path:
        full = ctx.workspace.resolve_readable(path)
        if not os.path.isfile(full):
            raise ToolError(f'No such file: {path}')
        return _recognize(full, languages)
    image = _image_from(source)
    if image is None:
        return {
            'clipboard': 'There is no image on the clipboard',
            'pick': 'The user did not pick a photo',
            'screenshot': 'There are no screenshots',
            'camera': 'The user cancelled the camera',
        }[source]
    tmp = os.path.join(tempfile.gettempdir(), 'pycoder-ocr.png')
    image.save(tmp)
    try:
        return _recognize(tmp, languages)
    finally:
        os.remove(tmp)


def _image_from(source: str) -> Any:
    """A PIL image from the clipboard, the photo library or the camera, or None."""
    if source == 'clipboard':
        import clipboard

        return call_on_main(clipboard.get_image)
    import photos

    if source == 'pick':
        asset = photos.pick_asset(title='Pick an image to read')
        return asset.get_image() if asset else None
    if source == 'screenshot':
        album = photos.get_screenshots_album()
        assets = album.assets if album else []
        return assets[-1].get_image() if assets else None
    if source == 'camera':
        return photos.capture_image()
    raise ToolError('source must be one of ' + ', '.join(SOURCES))


def _recognize(path: str, languages: str) -> str:
    from objc_util import ObjCClass, ns, nsurl

    request = ObjCClass('VNRecognizeTextRequest').alloc().init()
    request.setRecognitionLevel_(0)  # accurate rather than fast
    wanted = [code.strip() for code in languages.split(',') if code.strip()]
    if wanted:
        request.setRecognitionLanguages_(ns(wanted))
    elif request.respondsToSelector_('setAutomaticallyDetectsLanguage:'):
        request.setAutomaticallyDetectsLanguage_(True)
    else:
        request.setRecognitionLanguages_(ns(FALLBACK_LANGUAGES))
    handler = ObjCClass('VNImageRequestHandler').alloc().initWithURL_options_(nsurl(path), ns({}))
    # performRequests runs synchronously; never pass Vision a completion block: a callback into
    # Python from another thread can crash Pythonista
    if not handler.performRequests_error_(ns([request]), None):
        raise ToolError('Vision could not read this image (is it an image file?)')
    lines = [str(o.topCandidates_(1)[0].string()) for o in request.results() or []]
    return '\n'.join(lines) if lines else 'No text found in the image'


TOOLS = [
    Tool(
        'recognize_text',
        'Read the text in an image on the device with Apple Vision (OCR on the Neural Engine: free, '
        'offline, Chinese, English and 28 other languages). From a workspace image (path), or a '
        'source: clipboard, pick (the user picks a photo), screenshot (the latest one), camera. '
        'Returns the text line by line. Use it instead of looking at an image when only its words '
        'matter: it costs nothing and the image stays on the device.',
        {
            'path': prop('string', 'A workspace image (png, jpg, heic)'),
            'source': prop('string', 'Where else the image comes from', enum=list(SOURCES)),
            'languages': prop(
                'string', 'Comma-separated codes such as zh-Hans,en-US (default: detected automatically)'
            ),
        },
        recognize_text,
        readonly=False,  # the clipboard and the screenshots are private
        # a workspace file, or an image the user picks or takes themself: nothing to ask
        safe_input=lambda inp: bool(inp.get('path')) or inp.get('source') in ('pick', 'camera'),
    ),
]

"""Make an MP4 on the device, with sound, and with no person involved (ReplayKit needs one to approve it).

Two ways in, sharing one writer. `record` draws a window as it runs. `FrameWriter` takes frames a program
renders itself, one at a time, so a heavy film comes out smooth however long each frame took. Either can carry
a WAV file as its sound track, which iOS encodes to AAC. What a program plays while it runs isn't captured:
the track is a file it already has. Draw one window, not the whole screen, which slows the program far more.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
import wave
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

BGRA = 0x42475241  # kCVPixelFormatType_32BGRA
BITMAP_INFO = 8198  # kCGImageAlphaNoneSkipFirst | kCGBitmapByteOrder32Little
TIMESCALE = 600
MP4 = 'public.mpeg-4'
MAX_SIDE = 1280  # pixels: a bigger frame costs more than it shows
LPCM = 0x6C70636D  # 'lpcm'
AAC = 0x61616320  # 'aac '
SIGNED_PACKED = 12  # kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked
AUDIO_CHUNK = 0.1  # seconds of sound handed over at a time
WAIT_LIMIT = 15.0  # seconds to wait for the encoder before giving up
WRITER_FAILED = 3  # AVAssetWriterStatusFailed


class CMTime(ctypes.Structure):
    _fields_ = [
        ('value', ctypes.c_int64),
        ('timescale', ctypes.c_int32),
        ('flags', ctypes.c_uint32),
        ('epoch', ctypes.c_int64),
    ]


class StreamDescription(ctypes.Structure):
    _fields_ = [
        ('sample_rate', ctypes.c_double),
        ('format_id', ctypes.c_uint32),
        ('format_flags', ctypes.c_uint32),
        ('bytes_per_packet', ctypes.c_uint32),
        ('frames_per_packet', ctypes.c_uint32),
        ('bytes_per_frame', ctypes.c_uint32),
        ('channels', ctypes.c_uint32),
        ('bits_per_channel', ctypes.c_uint32),
        ('reserved', ctypes.c_uint32),
    ]


def media_time(seconds: float) -> CMTime:
    return CMTime(round(seconds * TIMESCALE), TIMESCALE, 1, 0)


def video_size(width: float, height: float, scale: float = 2.0, largest: int = MAX_SIDE) -> tuple[int, int]:
    """The size in pixels: at most `largest` on the long side, and even, as H.264 requires."""
    scale = min(scale, largest / max(width, height, 1))
    return max(2, int(width * scale) & ~1), max(2, int(height * scale) & ~1)


@dataclass
class Sound:
    """A WAV file's samples, ready to hand over."""

    rate: int
    channels: int
    data: bytes

    @property
    def frames(self) -> int:
        return len(self.data) // (2 * self.channels)


def read_sound(path: str) -> Sound:
    with wave.open(path, 'rb') as f:
        if f.getsampwidth() != 2:
            raise ValueError(f'{path}: the sound track must be 16-bit PCM, not {f.getsampwidth() * 8}-bit')
        return Sound(f.getframerate(), f.getnchannels(), f.readframes(f.getnframes()))


def frames_to_send(done: int, total: int, rate: int, until: float) -> int:
    """How many sound frames to hand over next, to reach `until` seconds, one chunk at a time."""
    wanted = min(total, round(until * rate)) - done
    return max(0, min(wanted, round(AUDIO_CHUNK * rate)))


@dataclass
class Recording:
    path: str
    frames: int
    seconds: float
    size: int  # bytes
    error: str = ''
    sound_seconds: float = 0.0


def _native() -> Any:
    """The C functions, with their types: a wrong one crashes the app rather than raising."""
    from ctypes import c_double, c_int32, c_long, c_size_t, c_uint32, c_uint64, c_void_p

    video = ctypes.CDLL('/System/Library/Frameworks/CoreVideo.framework/CoreVideo')
    video.CVPixelBufferCreate.argtypes = [c_void_p, c_size_t, c_size_t, c_uint32, c_void_p, c_void_p]
    video.CVPixelBufferCreate.restype = c_int32
    video.CVPixelBufferLockBaseAddress.argtypes = [c_void_p, c_uint64]
    video.CVPixelBufferUnlockBaseAddress.argtypes = [c_void_p, c_uint64]
    video.CVPixelBufferGetBaseAddress.argtypes = [c_void_p]
    video.CVPixelBufferGetBaseAddress.restype = c_void_p
    video.CVPixelBufferGetBytesPerRow.argtypes = [c_void_p]
    video.CVPixelBufferGetBytesPerRow.restype = c_size_t
    video.CVPixelBufferRelease.argtypes = [c_void_p]
    video.CVPixelBufferRelease.restype = None

    graphics = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    graphics.CGColorSpaceCreateDeviceRGB.restype = c_void_p
    graphics.CGColorSpaceRelease.argtypes = [c_void_p]
    graphics.CGColorSpaceRelease.restype = None
    graphics.CGBitmapContextCreate.argtypes = [
        c_void_p,
        c_size_t,
        c_size_t,
        c_size_t,
        c_size_t,
        c_void_p,
        c_uint32,
    ]
    graphics.CGBitmapContextCreate.restype = c_void_p
    graphics.CGContextRelease.argtypes = [c_void_p]
    graphics.CGContextRelease.restype = None
    graphics.CGContextTranslateCTM.argtypes = [c_void_p, c_double, c_double]
    graphics.CGContextTranslateCTM.restype = None
    graphics.CGContextScaleCTM.argtypes = [c_void_p, c_double, c_double]
    graphics.CGContextScaleCTM.restype = None

    kit = ctypes.CDLL('/System/Library/Frameworks/UIKit.framework/UIKit')
    kit.UIGraphicsPushContext.argtypes = [c_void_p]
    kit.UIGraphicsPushContext.restype = None
    kit.UIGraphicsPopContext.restype = None

    media = ctypes.CDLL('/System/Library/Frameworks/CoreMedia.framework/CoreMedia')
    media.CMAudioFormatDescriptionCreate.argtypes = [
        c_void_p,
        ctypes.POINTER(StreamDescription),
        c_size_t,
        c_void_p,
        c_size_t,
        c_void_p,
        c_void_p,
        c_void_p,
    ]
    media.CMAudioFormatDescriptionCreate.restype = c_int32
    media.CMBlockBufferCreateWithMemoryBlock.argtypes = [
        c_void_p,
        c_void_p,
        c_size_t,
        c_void_p,
        c_void_p,
        c_size_t,
        c_size_t,
        c_uint32,
        c_void_p,
    ]
    media.CMBlockBufferCreateWithMemoryBlock.restype = c_int32
    media.CMBlockBufferReplaceDataBytes.argtypes = [c_void_p, c_void_p, c_size_t, c_size_t]
    media.CMBlockBufferReplaceDataBytes.restype = c_int32
    media.CMAudioSampleBufferCreateReadyWithPacketDescriptions.argtypes = [
        c_void_p,
        c_void_p,
        c_void_p,
        c_long,
        CMTime,
        c_void_p,
        c_void_p,
    ]
    media.CMAudioSampleBufferCreateReadyWithPacketDescriptions.restype = c_int32

    foundation = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    foundation.CFRelease.argtypes = [c_void_p]
    foundation.CFRelease.restype = None
    return video, graphics, kit, media, foundation


class _Movie:
    """One AVAssetWriter: a video track, and a sound track if there is a file for one."""

    def __init__(self, path: str, size: tuple[int, int], audio: str, live: bool) -> None:
        from objc_util import ObjCClass, load_framework, ns, nsurl

        load_framework('AVFoundation')
        self.video, self.graphics, self.kit, self.media, self.foundation = _native()
        self.path = os.path.abspath(path)
        self.size = size
        self.frames = 0
        self.last_time = 0.0
        if os.path.exists(self.path):
            os.remove(self.path)
        self.writer = ObjCClass('AVAssetWriter').assetWriterWithURL_fileType_error_(
            nsurl(self.path), MP4, None
        )
        settings = {'AVVideoCodecKey': 'avc1', 'AVVideoWidthKey': size[0], 'AVVideoHeightKey': size[1]}
        make_input = ObjCClass('AVAssetWriterInput').assetWriterInputWithMediaType_outputSettings_
        self.input = make_input('vide', ns(settings))
        self.input.setExpectsMediaDataInRealTime_(live)
        self.adaptor = ObjCClass(
            'AVAssetWriterInputPixelBufferAdaptor'
        ).assetWriterInputPixelBufferAdaptorWithAssetWriterInput_sourcePixelBufferAttributes_(
            self.input, None
        )
        self.writer.addInput_(self.input)

        self.sound: Sound | None = read_sound(audio) if audio else None
        self.sent = 0
        self.sound_finished = False
        self.format = ctypes.c_void_p()
        self.audio_input: Any = None
        if self.sound is not None:
            layout = {
                'AVFormatIDKey': AAC,
                'AVSampleRateKey': self.sound.rate,
                'AVNumberOfChannelsKey': self.sound.channels,
                'AVEncoderBitRateKey': 128000 * self.sound.channels,
            }
            self.audio_input = make_input('soun', ns(layout))
            self.audio_input.setExpectsMediaDataInRealTime_(live)
            self.writer.addInput_(self.audio_input)
            frame_bytes = 2 * self.sound.channels
            description = StreamDescription(
                self.sound.rate, LPCM, SIGNED_PACKED, frame_bytes, 1, frame_bytes, self.sound.channels, 16, 0
            )
            status = self.media.CMAudioFormatDescriptionCreate(
                None, ctypes.byref(description), 0, None, 0, None, None, ctypes.byref(self.format)
            )
            if status != 0:
                raise RuntimeError(f'CMAudioFormatDescriptionCreate failed: {status}')

        if not self.writer.startWriting():
            raise RuntimeError(f'Could not start writing {self.path}: {self.writer.error()}')
        self.writer.startSessionAtSourceTime_(media_time(0), argtypes=[CMTime], restype=None)

    def send_sound(self, until: float) -> None:
        """Hand over the sound up to this time, as far as the encoder will take it now."""
        sound = self.sound
        if sound is None or self.sound_finished:
            return
        frame_bytes = 2 * sound.channels
        while self.audio_input.isReadyForMoreMediaData():
            count = frames_to_send(self.sent, sound.frames, sound.rate, until)
            if not count:
                break
            start = self.sent * frame_bytes
            self._append_sound(sound.data[start : start + count * frame_bytes], count, self.sent / sound.rate)
            self.sent += count
        if self.sent >= sound.frames:  # the writer would otherwise keep frames waiting for more of it
            self.audio_input.markAsFinished()
            self.sound_finished = True

    def _append_sound(self, data: bytes, count: int, at: float) -> None:
        block = ctypes.c_void_p()
        sample = ctypes.c_void_p()
        status = self.media.CMBlockBufferCreateWithMemoryBlock(
            None, None, len(data), None, None, 0, len(data), 1, ctypes.byref(block)
        )
        if status == 0:
            status = self.media.CMBlockBufferReplaceDataBytes(data, block, 0, len(data))
        if status == 0:
            status = self.media.CMAudioSampleBufferCreateReadyWithPacketDescriptions(
                None, block, self.format, count, media_time(at), None, ctypes.byref(sample)
            )
        if status != 0:
            raise RuntimeError(f'Could not make a sound buffer: {status}')
        self.audio_input.appendSampleBuffer_(sample, argtypes=[ctypes.c_void_p], restype=ctypes.c_bool)
        self.foundation.CFRelease(sample)
        self.foundation.CFRelease(block)

    def add_buffer(self, buffer: Any, seconds: float) -> bool:
        added = self.adaptor.appendPixelBuffer_withPresentationTime_(
            buffer, media_time(seconds), argtypes=[ctypes.c_void_p, CMTime], restype=ctypes.c_bool
        )
        self.frames += bool(added)
        self.last_time = max(self.last_time, seconds)
        return bool(added)

    def wait_for_video(self, until: float) -> None:
        """Until the encoder takes a frame. It may be holding frames back until sound catches up, and past
        them: so sound goes further ahead for as long as this waits."""
        deadline = time.monotonic() + WAIT_LIMIT
        ahead = until
        while not self.input.isReadyForMoreMediaData():
            ahead += AUDIO_CHUNK
            self.send_sound(ahead)
            if self.writer.status() == WRITER_FAILED or time.monotonic() > deadline:
                raise RuntimeError(f'The encoder stopped taking frames: {self.writer.error()}')
            time.sleep(0.002)

    def finish(self, seconds: float) -> Recording:
        """The sound stops with the picture, so a longer track doesn't leave a blank end."""
        sound = self.sound
        if sound is not None:
            end = min(sound.frames, round(seconds * sound.rate))
            deadline = time.monotonic() + WAIT_LIMIT
            while self.sent < end and time.monotonic() < deadline:
                self.send_sound(seconds)
                time.sleep(0.001)
            if not self.sound_finished:
                self.audio_input.markAsFinished()
        self.input.markAsFinished()
        self.writer.endSessionAtSourceTime_(media_time(seconds), argtypes=[CMTime], restype=None)
        self.writer.finishWriting()  # waits, where the newer call needs a block kept alive
        if sound is not None:
            self.foundation.CFRelease(self.format)
        error = self.writer.error()
        size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        heard = min(self.sent / sound.rate, seconds) if sound is not None else 0.0
        return Recording(self.path, self.frames, seconds, size, str(error) if error else '', heard)


class FrameWriter:
    """Frames a program renders itself. `add` takes a height x width x 4 numpy array of BGRA bytes."""

    def __init__(self, path: str, width: int, height: int, fps: float = 30.0, audio: str = '') -> None:
        self.size = (width & ~1, height & ~1)
        self.fps = fps
        self.count = 0
        self.movie = _Movie(path, self.size, audio, live=False)

    def add(self, bgra: Any) -> None:
        movie = self.movie
        width, height = self.size
        at = self.count / self.fps
        until = (self.count + 1) / self.fps
        movie.send_sound(until)
        movie.wait_for_video(until)
        video = movie.video
        buffer = ctypes.c_void_p()
        if video.CVPixelBufferCreate(None, width, height, BGRA, None, ctypes.byref(buffer)) != 0:
            raise RuntimeError('Could not make a pixel buffer')
        video.CVPixelBufferLockBaseAddress(buffer, 0)
        base = video.CVPixelBufferGetBaseAddress(buffer)
        row = video.CVPixelBufferGetBytesPerRow(buffer)
        source, stride = bgra.ctypes.data, bgra.strides[0]
        for y in range(height):
            ctypes.memmove(base + y * row, source + y * stride, width * 4)
        video.CVPixelBufferUnlockBaseAddress(buffer, 0)
        movie.add_buffer(buffer, at)
        video.CVPixelBufferRelease(buffer)
        self.count += 1

    def finish(self) -> Recording:
        return self.movie.finish(self.count / self.fps)


@dataclass
class Recorder:
    """Call start(), then stop() for the Recording. `view` is a ui.View on screen; its first size is kept."""

    view: Any
    path: str
    fps: float = 15.0
    audio: str = ''
    result: Recording | None = None  # after stop()
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _started: float = 0.0

    def start(self) -> None:
        from objc_util import ObjCInstance, on_main_thread

        self._native_view = ObjCInstance(self.view)
        bounds = on_main_thread(lambda: self._native_view.bounds().size)()
        self._points = (float(bounds.width), float(bounds.height))
        self._size = video_size(*self._points)
        self._movie = _Movie(self.path, self._size, self.audio, live=True)
        self._colors = self._movie.graphics.CGColorSpaceCreateDeviceRGB()
        self._grab = on_main_thread(self._frame)
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def frames(self) -> int:
        return self._movie.frames

    def _run(self) -> None:
        every = 1 / self.fps
        next_frame = self._started
        while not self._stop.is_set():
            self._grab(time.monotonic() - self._started)
            next_frame = max(next_frame + every, time.monotonic())
            self._stop.wait(max(0.0, next_frame - time.monotonic()))

    def _frame(self, seconds: float) -> None:
        """On the main thread: draw the view into a new pixel buffer, and hand it to the encoder."""
        movie = self._movie
        movie.send_sound(seconds + AUDIO_CHUNK)
        if self._stop.is_set() or not movie.input.isReadyForMoreMediaData():
            return  # a frame is dropped rather than held up: the times keep the video's speed right
        video, graphics, kit = movie.video, movie.graphics, movie.kit
        width, height = self._size
        buffer = ctypes.c_void_p()
        if video.CVPixelBufferCreate(None, width, height, BGRA, None, ctypes.byref(buffer)) != 0:
            return
        video.CVPixelBufferLockBaseAddress(buffer, 0)
        context = graphics.CGBitmapContextCreate(
            video.CVPixelBufferGetBaseAddress(buffer),
            width,
            height,
            8,
            video.CVPixelBufferGetBytesPerRow(buffer),
            self._colors,
            BITMAP_INFO,
        )
        graphics.CGContextTranslateCTM(context, 0.0, float(height))
        graphics.CGContextScaleCTM(context, width / self._points[0], -height / self._points[1])
        kit.UIGraphicsPushContext(context)
        self._native_view.drawViewHierarchyInRect_afterScreenUpdates_(self._native_view.bounds(), False)
        kit.UIGraphicsPopContext()
        graphics.CGContextRelease(context)
        video.CVPixelBufferUnlockBaseAddress(buffer, 0)
        movie.add_buffer(buffer, seconds)
        video.CVPixelBufferRelease(buffer)

    def stop(self) -> Recording:
        if self.result is not None:
            return self.result
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
        seconds = time.monotonic() - self._started
        self.result = self._movie.finish(seconds)
        self._movie.graphics.CGColorSpaceRelease(self._colors)
        return self.result


@contextmanager
def record(view: Any, path: str, fps: float = 15.0, audio: str = '') -> Iterator[Recorder]:
    """`with record(view, 'demo.mp4') as recorder:`; afterwards recorder.result says what came of it."""
    recorder = Recorder(view, path, fps, audio)
    recorder.start()
    try:
        yield recorder
    finally:
        recorder.stop()

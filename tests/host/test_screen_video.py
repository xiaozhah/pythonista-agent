"""Making a video: the parts that need no device, and the whole thing inside Pythonista."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from pycoder.host import env, screen_video


def _wav(path: Path, seconds: float = 1.0, rate: int = 44100, width: int = 2) -> str:
    samples = (np.sin(2 * np.pi * 440 * np.arange(int(rate * seconds)) / rate) * 20000).astype(np.int16)
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(2)
        f.setsampwidth(width)
        f.setframerate(rate)
        f.writeframes(
            np.stack([samples, samples], 1).tobytes() if width == 2 else bytes(int(rate * seconds) * 2)
        )
    return str(path)


def test_video_size_is_even_and_bounded() -> None:
    assert screen_video.video_size(500, 500) == (1000, 1000)
    assert screen_video.video_size(333, 777) == (548, 1280)
    assert screen_video.video_size(982, 1197) == (1050, 1280)
    width, height = screen_video.video_size(1001, 3)
    assert width % 2 == 0
    assert height % 2 == 0


def test_a_tiny_view_still_has_a_size() -> None:
    assert screen_video.video_size(0, 0) == (2, 2)


def test_media_time_keeps_fractions_of_a_second() -> None:
    time = screen_video.media_time(1.5)
    assert time.value == 900
    assert time.timescale == 600
    assert time.flags == 1


def test_a_wav_is_read_with_its_format(tmp_path: Path) -> None:
    sound = screen_video.read_sound(_wav(tmp_path / 'a.wav', 0.5))
    assert (sound.rate, sound.channels, sound.frames) == (44100, 2, 22050)


def test_a_track_that_isnt_16_bit_says_so(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='16-bit'):
        screen_video.read_sound(_wav(tmp_path / 'a.wav', 0.5, width=1))


def test_sound_goes_in_chunks_up_to_the_time_asked() -> None:
    chunk = round(screen_video.AUDIO_CHUNK * 44100)
    assert screen_video.frames_to_send(0, 88200, 44100, 1.0) == chunk
    assert screen_video.frames_to_send(44000, 88200, 44100, 1.0) == 100
    assert screen_video.frames_to_send(44100, 88200, 44100, 1.0) == 0
    assert screen_video.frames_to_send(88000, 88200, 44100, 5.0) == 200
    assert screen_video.frames_to_send(88200, 88200, 44100, 5.0) == 0


@pytest.mark.skipif(not env.IN_PYTHONISTA, reason='needs Pythonista')
def test_frames_and_a_track_make_a_video_with_sound(tmp_path: Path) -> None:
    from objc_util import ObjCClass, load_framework, nsurl

    load_framework('AVFoundation')
    path = str(tmp_path / 'a.mp4')
    writer = screen_video.FrameWriter(path, 64, 36, fps=30, audio=_wav(tmp_path / 'a.wav'))
    frame = np.zeros((36, 64, 4), dtype=np.uint8)
    for i in range(30):
        frame[:, :, 2] = i * 8
        writer.add(frame)
    result = writer.finish()
    assert result.error == ''
    assert result.frames == 30
    assert abs(result.sound_seconds - 1.0) < 0.01
    asset = ObjCClass('AVURLAsset').URLAssetWithURL_options_(nsurl(path), None)
    assert asset.tracksWithMediaType_('vide').count() == 1
    assert asset.tracksWithMediaType_('soun').count() == 1


@pytest.mark.skipif(not env.IN_PYTHONISTA, reason='needs Pythonista')
def test_a_short_track_doesnt_hold_up_a_longer_picture(tmp_path: Path) -> None:
    writer = screen_video.FrameWriter(
        str(tmp_path / 'a.mp4'), 64, 36, fps=30, audio=_wav(tmp_path / 'a.wav', 0.2)
    )
    frame = np.zeros((36, 64, 4), dtype=np.uint8)
    for _ in range(45):
        writer.add(frame)
    result = writer.finish()
    assert result.error == ''
    assert result.frames == 45


@pytest.mark.skipif(not env.IN_PYTHONISTA, reason='needs Pythonista')
def test_a_long_track_stops_with_the_picture(tmp_path: Path) -> None:
    writer = screen_video.FrameWriter(
        str(tmp_path / 'a.mp4'), 64, 36, fps=30, audio=_wav(tmp_path / 'a.wav', 3.0)
    )
    frame = np.zeros((36, 64, 4), dtype=np.uint8)
    for _ in range(30):
        writer.add(frame)
    result = writer.finish()
    assert result.error == ''
    assert result.seconds == 1.0
    assert result.sound_seconds <= 1.0

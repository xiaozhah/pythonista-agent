# ruff: noqa
# fmt: off
"""A MIDI file played on a synthesized pipe organ, to a WAV file. An organ has no touch dynamics: it gets louder by
drawing more stops, so the registration follows how busy the music is, as an organist's would."""

import os
import wave

import numpy as np

from midi_notes import read_midi

SR = 44100
STOPS = {  # footage: (pitch multiple, harmonic levels)
    '16': (0.5, [1, 0.5, 0.25, 0.12]),
    '8': (1, [1, 0.62, 0.4, 0.26, 0.16, 0.1, 0.06]),
    '4': (2, [1, 0.5, 0.28, 0.14, 0.08]),
    '2': (4, [1, 0.35, 0.16]),
    'mix': (6, [1, 0.5, 0.2]),
}


def registration(level):
    """The stops drawn at a level from 0 to 1."""
    return {
        '8': 1.0,
        '4': float(np.clip((level - 0.2) / 0.3, 0, 1)) * 0.7,
        '2': float(np.clip((level - 0.5) / 0.25, 0, 1)) * 0.5,
        'mix': float(np.clip((level - 0.7) / 0.25, 0, 1)) * 0.3,
    }


def add_pipe(out, key, start, dur, stops, gain, pan, rng):
    n = len(out)
    i = int(start * SR)
    count = min(int((dur + 0.14) * SR), n - i)
    if count <= 0:
        return
    t = np.arange(count) / SR
    freq = 440.0 * 2 ** ((key - 69) / 12)
    s = np.zeros(count)
    for name, level in stops.items():
        if level <= 0.01:
            continue
        mult, harmonics = STOPS[name]
        for k, a in enumerate(harmonics, 1):
            f = freq * mult * k
            if f < SR / 2.5:
                s += level * a * np.sin(2 * np.pi * f * t + rng.random() * 6.283)
    # A pipe speaks gently, a low one slowest. No burst of noise on each note: on a low repeated note, that's a drum.
    attack = 0.09 if key < 50 else 0.05
    env = (0.5 - 0.5 * np.cos(np.pi * np.minimum(t / attack, 1.0))) * np.clip((dur + 0.14 - t) / 0.14, 0, 1)
    x = s * env * gain
    out[i : i + count, 0] += x * (1 - pan * 0.45)
    out[i : i + count, 1] += x * (1 + pan * 0.45)


def hall_response(seed, seconds=5.0, delay=0.045):
    rng = np.random.default_rng(seed)
    m = int(SR * seconds)
    y = rng.standard_normal(m) * np.exp(-np.arange(m) / (SR * 1.05))
    spectrum = np.fft.rfft(y)
    spectrum *= np.exp(-((np.fft.rfftfreq(m, 1 / SR) / 5200) ** 2))
    y = np.fft.irfft(spectrum, m)
    return np.concatenate([np.zeros(int(delay * SR)), y / np.sqrt((y**2).sum())])


def convolve(x, response):
    m = len(x) + len(response)
    return np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(response, m), m)[: len(x)]


def render(midi_path, wav_path, end=None, tail=4.0, seed=5):
    """Writes the WAV; returns (level curve per second, seconds). `end` cuts the piece there, with the hall ringing on."""
    notes = read_midi(midi_path)[0]
    last = max(n[1] for n in notes)
    end = last if end is None else min(end, last)
    notes = [n for n in notes if n[0] < end]
    seconds = end + tail
    rng = np.random.default_rng(seed)

    # how busy each moment is, smoothed over a few bars and spread to 0..1: this is the registration
    busy = np.zeros(int(seconds) + 2)
    for n in notes:
        busy[int(n[0])] += 1
    width = 9
    smooth = np.convolve(busy, np.hanning(width) / np.hanning(width).sum(), 'same')
    level = np.clip((smooth - 2.0) / (np.percentile(smooth[: int(end)], 95) - 2.0), 0, 1)

    out = np.zeros((int(seconds * SR), 2))
    for start, stop, key, _velocity, _track in notes:
        at = level[int(start)]
        stops = registration(at)
        dur = min(stop, end) - start
        gain = 0.09 * (0.55 + 0.45 * at)
        if key < 50:  # the pedal: heavy, in the middle
            add_pipe(out, key, start, dur, {'16': 0.8 * min(1.0, 0.3 + at), '8': 0.6}, 0.15 * (0.6 + 0.4 * at), 0.0, rng)
        else:
            add_pipe(out, key, start, dur, stops, gain, float(np.clip((key - 62) / 22, -1, 1)) * 0.8, rng)
    wet = np.stack(
        [out[:, 0] * 0.6 + convolve(out[:, 0], hall_response(1)) * 0.6, out[:, 1] * 0.6 + convolve(out[:, 1], hall_response(2)) * 0.6],
        1,
    )
    # no sound a speaker can't play; the swell box opens with the music
    spectrum = np.fft.rfft(wet, axis=0)
    freqs = np.fft.rfftfreq(len(wet), 1 / SR)
    spectrum *= (1 - np.exp(-((freqs / 45.0) ** 4)))[:, None]
    wet = np.fft.irfft(spectrum, len(wet), axis=0)
    t = np.arange(len(wet)) / SR
    swell = np.interp(t, np.arange(len(level)), 0.32 + 0.68 * level)
    wet *= swell[:, None]
    wet *= np.clip(t / 0.6, 0, 1)[:, None]
    wet *= np.clip((seconds - t) / 1.5, 0, 1)[:, None]
    wet = wet / np.abs(wet).max() * 0.95
    wet = np.tanh(wet * 1.15) / np.tanh(1.15)
    with wave.open(wav_path, 'wb') as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((wet * 32767).astype(np.int16).tobytes())
    return level, seconds


def plot(wav_path, png_path):
    """Instead of listening: the STFT magnitude, and the loudness under it."""
    import matplotlib

    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    with wave.open(wav_path, 'rb') as f:
        rate = f.getframerate()
        x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).reshape(-1, 2) / 32767
    mono = x.mean(1)
    size, hop = 4096, 2048
    window = np.hanning(size)
    starts = np.arange(0, len(mono) - size, hop)
    spec = np.array([np.abs(np.fft.rfft(mono[i : i + size] * window)) for i in starts]).T
    db = 20 * np.log10(spec / spec.max() + 1e-6)
    freqs = np.fft.rfftfreq(size, 1 / rate)
    times = (starts + size / 2) / rate
    fig, ax = plt.subplots(2, 1, figsize=(14, 7.5), sharex=True, gridspec_kw={'height_ratios': [3, 1]})
    mesh = ax[0].pcolormesh(times[::2], freqs[1:], db[1:, ::2], vmin=-90, vmax=0, cmap='magma', shading='auto')
    ax[0].set_yscale('log')
    ax[0].set_ylim(30, 16000)
    ax[0].set_ylabel('Hz (log)')
    ax[0].set_title('STFT magnitude (dB)')
    rms = np.sqrt((mono[: len(starts) * hop].reshape(len(starts), -1) ** 2).mean(1))
    ax[1].plot(times, 20 * np.log10(rms + 1e-6))
    ax[1].set_ylim(-70, 0)
    ax[1].set_ylabel('RMS dB')
    ax[1].set_xlabel('seconds')
    ax[1].grid(True)
    fig.colorbar(mesh, ax=ax, shrink=0.7, label='dB')
    fig.savefig(png_path, dpi=90, bbox_inches='tight')
    plt.close(fig)
    bands = {name: (lo, hi) for name, lo, hi in (('<60', 20, 60), ('60-250', 60, 250), ('250-2k', 250, 2000), ('2k+', 2000, 16000))}
    total = (spec**2).sum(0)
    share = {k: round(float((spec[(freqs >= lo) & (freqs < hi)] ** 2).sum() / total.sum()), 3) for k, (lo, hi) in bands.items()}
    return {
        'seconds': round(len(mono) / rate, 1),
        'peak': round(float(np.abs(x).max()), 3),
        'lr_corr': round(float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]), 3),
        'energy_share': share,
    }

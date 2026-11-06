# ruff: noqa
# fmt: off
"""The same notes played bigger: what makes an organ grand is more pipes, more room and a longer way to climb.
Octaves added above and below as the music opens, a sustained wash of each bar's harmony, a 32-foot pedal, a long
cathedral, and quiet that is really quiet, so the full instrument has somewhere to arrive."""

import wave

import numpy as np

from midi_notes import read_midi
from organ_render import STOPS, SR, add_pipe, convolve, registration

STOPS.setdefault('32', (0.25, [1, 0.55, 0.3, 0.14]))


def cathedral(seed, seconds=9.0, decay=1.9, delay=0.07):
    """A long tail, darker as it goes, after a few early reflections off stone."""
    rng = np.random.default_rng(seed)
    m = int(SR * seconds)
    t = np.arange(m) / SR
    y = rng.standard_normal(m) * np.exp(-t / decay)
    spectrum = np.fft.rfft(y)
    spectrum *= np.exp(-((np.fft.rfftfreq(m, 1 / SR) / 4200) ** 2))
    y = np.fft.irfft(spectrum, m)
    y /= np.sqrt((y**2).sum())
    for at, gain in ((0.023, 0.12), (0.041, 0.09), (0.067, 0.07), (0.097, 0.05)):
        y[int((at + seed * 0.003) * SR)] += gain
    return np.concatenate([np.zeros(int(delay * SR)), y])


def wash(out, key, start, dur, gain, rng):
    """One held voice of the harmony: soft strings of pipes, slowly swelling and a little out of tune with itself."""
    i = int(start * SR)
    n = min(int((dur + 1.2) * SR), len(out) - i)
    if n <= 0:
        return
    t = np.arange(n) / SR
    f = 440.0 * 2 ** ((key - 69) / 12)
    s = np.zeros(n)
    for detune in (-0.0016, 0.0, 0.0016):
        for k, a in enumerate((1, 0.5, 0.33, 0.2, 0.12), 1):
            s += a * np.sin(2 * np.pi * f * k * (1 + detune) * t + rng.random() * 6.283)
    env = np.minimum(t / 0.7, 1.0) * np.clip((dur + 1.2 - t) / 1.2, 0, 1)
    out[i : i + n] += (s * env * gain)[:, None]


def render(midi_path, wav_path, end, tail=4.0, seed=5):
    notes = [n for n in read_midi(midi_path)[0] if n[0] < end]
    seconds = end + tail
    rng = np.random.default_rng(seed)
    busy = np.zeros(int(seconds) + 2)
    for n in notes:
        busy[int(n[0])] += 1
    window = np.hanning(9) / np.hanning(9).sum()
    smooth = np.convolve(busy, window, 'same')
    level = np.clip((smooth - 2.0) / (np.percentile(smooth[: int(end)], 95) - 2.0), 0, 1)

    out = np.zeros((int(seconds * SR), 2))
    for start, stop, key, _velocity, _track in notes:
        at = float(level[int(start)])
        dur = min(stop, end) - start
        gain = 0.07 * (0.5 + 0.5 * at)
        if key < 50:
            pedal = {'16': 0.8, '8': 0.5}
            if at > 0.35:
                pedal['32'] = min(1.0, (at - 0.35) * 2.2)
            add_pipe(out, key, start, dur, pedal, 0.16 * (0.55 + 0.45 * at), 0.0, rng)
        else:
            pan = float(np.clip((key - 62) / 22, -1, 1)) * 0.7
            add_pipe(out, key, start, dur, registration(at), gain, pan, rng)
            if at > 0.45:  # the octave above comes in as it opens
                add_pipe(out, key + 12, start, dur, {'8': 0.8, '4': 0.5}, gain * min(1.0, (at - 0.45) * 2.5) * 0.55, -pan, rng)
            if at > 0.7 and key < 68:  # and the one below, at the very top
                add_pipe(out, key - 12, start, dur, {'8': 1.0, '4': 0.3}, gain * (at - 0.7) * 2.2, 0.0, rng)
    # each bar's harmony, held: its lowest notes and what sounds most
    bar = 2.0
    bed = np.zeros_like(out)
    for b in range(int(end / bar)):
        here = [n[2] for n in notes if b * bar <= n[0] < (b + 1) * bar]
        if not here:
            continue
        counts = {}
        for k in here:
            counts[k % 12] = counts.get(k % 12, 0) + 1
        common = sorted(counts, key=counts.get, reverse=True)[:4]
        at = float(level[int(b * bar)])
        for pc in common:
            key = 48 + (pc - 48) % 12
            wash(bed, key, b * bar, bar, 0.012 + 0.03 * at, rng)
            if at > 0.5:
                wash(bed, key + 12, b * bar, bar, 0.018 * at, rng)
    mix = out + bed
    wet = np.stack(
        [mix[:, 0] * 0.72 + convolve(mix[:, 0], cathedral(1)) * 0.5, mix[:, 1] * 0.72 + convolve(mix[:, 1], cathedral(2)) * 0.5], 1
    )
    spectrum = np.fft.rfft(wet, axis=0)
    freqs = np.fft.rfftfreq(len(wet), 1 / SR)
    spectrum *= (1 - np.exp(-((freqs / 30.0) ** 4)))[:, None]
    wet = np.fft.irfft(spectrum, len(wet), axis=0)
    t = np.arange(len(wet)) / SR
    swell = np.interp(t, np.arange(len(level)), 0.14 + 0.86 * level**1.3)  # the swell box: far more range
    wet *= swell[:, None] * np.clip(t / 0.6, 0, 1)[:, None] * np.clip((seconds - t) / 1.5, 0, 1)[:, None]
    wet = wet / np.abs(wet).max() * 0.97
    wet = np.tanh(wet * 1.25) / np.tanh(1.25)
    with wave.open(wav_path, 'wb') as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((wet * 32767).astype(np.int16).tobytes())
    return level

# ruff: noqa
# fmt: off
"""Notes from a standard MIDI file, with their times in seconds. Pure Python."""

import struct


def _varlen(data, i):
    value = 0
    while True:
        byte = data[i]
        i += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, i


def read_midi(path):
    """(notes, tempos, names, programs): notes are (start seconds, end seconds, key, velocity, track)."""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] != b'MThd':
        raise ValueError('not a MIDI file')
    length, fmt, count, division = struct.unpack('>IHHH', data[4:14])
    if division & 0x8000:
        raise ValueError('SMPTE time is not supported')
    i, events, names, programs, tempos = 8 + length, [], [], [], []
    for track in range(count):
        if data[i:i + 4] != b'MTrk':
            raise ValueError('bad track')
        size = struct.unpack('>I', data[i + 4:i + 8])[0]
        j, end, tick, status = i + 8, i + 8 + size, 0, 0
        while j < end:
            delta, j = _varlen(data, j)
            tick += delta
            if data[j] & 0x80:
                status = data[j]
                j += 1
            kind = status & 0xF0
            if status == 0xFF:
                meta = data[j]
                n, j = _varlen(data, j + 1)
                body = data[j:j + n]
                j += n
                if meta == 0x51:
                    tempos.append((tick, int.from_bytes(body, 'big')))
                elif meta == 3:
                    names.append(body.decode('latin-1'))
            elif status in (0xF0, 0xF7):
                n, j = _varlen(data, j)
                j += n
            elif kind in (0xC0, 0xD0):
                if kind == 0xC0:
                    programs.append(data[j])
                j += 1
            else:
                events.append((tick, kind, data[j], data[j + 1], track, status & 15))
                j += 2
        i = end
    tempos = sorted(tempos) or [(0, 500000)]

    def seconds(tick):
        total, last, us = 0.0, 0, tempos[0][1] if tempos[0][0] == 0 else 500000
        for at, value in tempos:
            if at >= tick:
                break
            total += (at - last) * us / division
            last, us = at, value
        return (total + (tick - last) * us / division) / 1e6

    open_notes, notes = {}, []
    for tick, kind, key, value, track, channel in sorted(events, key=lambda e: (e[0], e[1] == 0x90)):
        where = (track, channel, key)
        if kind == 0x90 and value:
            open_notes.setdefault(where, []).append((tick, value))
        elif kind in (0x80, 0x90) and open_notes.get(where):
            start, velocity = open_notes[where].pop(0)
            notes.append((seconds(start), seconds(tick), key, velocity, track))
    notes.sort()
    return notes, [(seconds(t), 60e6 / u) for t, u in tempos], names, programs

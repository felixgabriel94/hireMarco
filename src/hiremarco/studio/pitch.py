"""Marco's pitch ear: the notes of a vocal run, how far off each one is, and the run as it should go.

Plain signal processing, no model: the YIN pitch detector (de Cheveigné and
Kawahara, 2002) on 40 ms frames every 10 ms gives the sung pitch; steady
stretches become notes; each note is compared with the song's key, so
"the third note is 30 cents flat, it wants the A" is a measurement, not a
guess. ``guide`` renders the corrected run as a soft piano-like tone Marco
can play in the headphones, and ``to_midi`` writes it for a Logic track.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)
FRAME_S = 0.040
HOP_S = 0.010
FMIN, FMAX = 70.0, 1100.0


@dataclass(frozen=True)
class Note:
    start: float      # seconds into the audio
    end: float
    midi: float       # sung pitch, fractional MIDI note number
    target: int       # nearest note in the key

    @property
    def cents_off(self) -> int:
        return int(round((self.midi - self.target) * 100))

    @property
    def name(self) -> str:
        return midi_name(self.target)


def midi_name(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def hz_to_midi(hz: float) -> float:
    return 69 + 12 * np.log2(hz / 440.0)


def midi_to_hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def parse_key(key: str) -> tuple[int, tuple[int, ...]]:
    """'F minor', 'C# major', 'Bbm', 'A' -> (tonic pitch class, scale degrees)."""
    m = re.match(r"^\s*([A-Ga-g])([#b]?)\s*(major|maj|minor|min|m)?\s*$", key.strip(), re.IGNORECASE)
    if not m:
        raise ValueError(f"not a key: {key!r}")
    name = m.group(1).upper() + m.group(2)
    name = FLATS.get(name, name)
    if name not in NOTE_NAMES:  # Cb, Fb, E#, B#
        raise ValueError(f"not a key: {key!r}")
    quality = (m.group(3) or "major").lower()
    return NOTE_NAMES.index(name), (MINOR if quality in ("minor", "min", "m") else MAJOR)


def snap(midi: float, key: str) -> int:
    tonic, scale = parse_key(key)
    candidates = [n for n in range(int(midi) - 2, int(midi) + 3) if (n - tonic) % 12 in scale]
    return min(candidates, key=lambda n: (abs(n - midi), n))


def _mono(audio: np.ndarray) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float64)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if np.issubdtype(np.asarray(audio).dtype, np.integer):
        data = data / 32768.0
    return data


def yin(frame: np.ndarray, rate: int, threshold: float = 0.15) -> float:
    """Pitch of one frame in Hz, or 0.0 when the frame has no clear pitch."""
    n = frame.size // 2
    lo, hi = int(rate / FMAX), min(int(rate / FMIN), n - 1)
    if hi <= lo or not np.any(frame):
        return 0.0
    # Difference function for every lag at once: energy terms from cumulative sums, the cross term by FFT.
    x = frame[: n + hi + 1]
    head = x[:n]
    squares = np.concatenate([[0.0], np.cumsum(x ** 2)])
    lags = np.arange(hi + 1)
    size = 1 << int(np.ceil(np.log2(x.size + n)))
    cross = np.fft.irfft(np.fft.rfft(x, size) * np.conj(np.fft.rfft(head, size)), size)[: hi + 1]
    diff = squares[n] + (squares[lags + n] - squares[lags]) - 2 * cross
    diff[0] = 0.0
    cmnd = np.ones_like(diff)
    running = np.cumsum(diff[1:])
    cmnd[1:] = diff[1:] * np.arange(1, hi + 1) / np.where(running == 0, 1, running)
    below = np.where(cmnd[lo:hi] < threshold)[0]
    if below.size == 0:
        return 0.0
    tau = lo + below[0]
    while tau + 1 < hi and cmnd[tau + 1] < cmnd[tau]:
        tau += 1
    if 0 < tau < hi:  # parabolic interpolation for sub-sample accuracy
        a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
        denom = a - 2 * b + c
        tau = tau + 0.5 * (a - c) / denom if denom else tau
    return rate / tau


def track(audio: np.ndarray, rate: int) -> np.ndarray:
    """Pitch every HOP_S seconds as fractional MIDI, NaN where there is no voiced pitch."""
    data = _mono(audio)
    frame, hop = int(FRAME_S * rate), int(HOP_S * rate)
    quiet = 10 ** (-45 / 20)
    out = []
    for start in range(0, max(data.size - frame, 0) + 1, hop):
        f = data[start:start + frame]
        if f.size < frame or np.sqrt(np.mean(f ** 2)) < quiet:
            out.append(np.nan)
            continue
        hz = yin(f, rate)
        out.append(hz_to_midi(hz) if FMIN <= hz <= FMAX else np.nan)
    return np.array(out)


def notes(audio: np.ndarray, rate: int, key: str, *, min_s: float = 0.06, split_semitones: float = 0.6) -> list[Note]:
    """Steady stretches of pitch become notes; each is named against the key."""
    contour = track(audio, rate)
    found: list[Note] = []
    start, values = None, []

    def close(end_index: int) -> None:
        if start is not None and (end_index - start) * HOP_S >= min_s:
            sung = float(np.median(values))
            found.append(Note(round(start * HOP_S, 3), round(end_index * HOP_S + FRAME_S, 3), sung, snap(sung, key)))

    for i, value in enumerate(contour):
        if np.isnan(value):
            close(i)
            start, values = None, []
        elif start is None:
            start, values = i, [value]
        elif abs(value - np.median(values)) > split_semitones:
            close(i)
            start, values = i, [value]
        else:
            values.append(value)
    close(len(contour))
    return found


def describe(run: list[Note], tolerance_cents: int = 20) -> str:
    """A producer's line from the measurements: which notes are off, and where they want to land."""
    off = [(i, n) for i, n in enumerate(run, 1) if abs(n.cents_off) > tolerance_cents]
    if not run:
        return "I couldn't hear a clear pitch in that run."
    if not off:
        return f"All {len(run)} notes of that run sit in tune."
    ordinal = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth"}
    parts = [f"the {ordinal.get(i, f'number {i}')} note is {abs(n.cents_off)} cents {'flat' if n.cents_off < 0 else 'sharp'}, "
             f"it wants the {NOTE_NAMES[n.target % 12]}" for i, n in off[:3]]
    line = "; ".join(parts)
    return line[0].upper() + line[1:] + "."


def guide(run: list[Note], rate: int = 24000, gap_s: float = 0.03) -> np.ndarray:
    """The corrected run as a soft piano-like tone, the sung rhythm kept, int16 mono."""
    if not run:
        return np.zeros(0, dtype="<i2")
    t0 = run[0].start
    total = int((run[-1].end - t0 + 0.4) * rate)
    out = np.zeros(total)
    for n in run:
        begin = int((n.start - t0) * rate)
        length = max(int((n.end - n.start - gap_s) * rate), int(0.08 * rate))
        t = np.arange(length) / rate
        f = midi_to_hz(n.target)
        tone = sum(np.sin(2 * np.pi * f * k * t) / k ** 1.5 for k in (1, 2, 3, 4))
        envelope = np.minimum(1, t / 0.005) * np.exp(-t * 3.0)
        segment = tone * envelope
        out[begin:begin + length] += segment[: max(0, min(length, total - begin))]
    peak = np.max(np.abs(out)) or 1
    return (out / peak * 0.4 * 32767).astype("<i2")


def to_midi(run: list[Note], path, *, bpm: float = 120.0) -> None:
    """The corrected run as a one-track MIDI file, the sung timing kept."""
    import mido

    mid = mido.MidiFile(ticks_per_beat=480)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    ticks = lambda s: int(round(s * bpm / 60 * 480))  # noqa: E731
    t0, now = run[0].start if run else 0.0, 0
    for n in run:
        on, off = ticks(n.start - t0), ticks(n.end - t0)
        tr.append(mido.Message("note_on", note=n.target, velocity=80, time=max(0, on - now)))
        tr.append(mido.Message("note_off", note=n.target, velocity=0, time=max(0, off - on)))
        now = off
    mid.save(path)


def _words_of(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def locate(lyric: str, turns, *, pad_s: float = 0.25) -> tuple[float, float] | None:
    """Where a sung phrase sits in a take, from the transcript's timed turns, in seconds.

    The transcript times whole turns, not words, so inside a turn the phrase's
    place is estimated from its share of the turn's words, then padded; the
    note finder only keeps voiced notes inside that window. An estimate, and
    it says so when Marco reports it.
    """
    want = _words_of(lyric)
    if not want:
        return None
    for turn in turns:
        words = _words_of(turn.text)
        for i in range(len(words) - len(want) + 1):
            if words[i:i + len(want)] == want:
                span = (turn.end_ms - turn.start_ms) / 1000
                start = turn.start_ms / 1000 + span * i / len(words)
                end = turn.start_ms / 1000 + span * (i + len(want)) / len(words)
                return max(0.0, start - pad_s), end + pad_s
    return None


def run_in(audio: np.ndarray, rate: int, key: str, window: tuple[float, float] | None = None) -> list[Note]:
    """The notes inside a window of the take (the whole take when no window), timed from the window's start."""
    data = _mono(audio)
    offset = 0.0
    if window:
        a, b = int(window[0] * rate), int(window[1] * rate)
        data, offset = data[a:b], window[0]
    return [Note(round(n.start + offset, 3), round(n.end + offset, 3), n.midi, n.target)
            for n in notes(data, rate, key)]

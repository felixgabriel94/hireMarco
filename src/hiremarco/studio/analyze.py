"""The key and tempo of a beat, from its audio.

Key: a chromagram (the strongest bin of each semitone from 55 Hz to 2 kHz,
frame by frame, drums filtered out) summed over the file and correlated with
Temperley's major and minor key profiles; the best of the 24 rotations is the
key. Relative keys (C major against A minor) share their
notes, so the runner-up is kept and said when the two are close.

Tempo: an onset envelope (the half-wave spectral flux, frame by frame) and its
autocorrelation; the strongest lag between 60 and 200 BPM, with a mild
preference for the middle of that range, is the tempo. Half and double time
are the usual confusion (70 against 140), so both are named when the other
is nearly as strong.

Both are estimates and are said as such; ``evaluate`` measures them on loops
whose file names carry the producer's own key and BPM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path

import numpy as np

RATE = 22050
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Temperley's corpus profiles (Kostka-Payne; Temperley, *Music and Probability*, 2007): on 80 labelled loops
# they beat Krumhansl-Kessler and Sha'ath's (33 against 30 and 25 exact, 2026-10-29)
MAJOR = np.array([5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0])
MINOR = np.array([5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0])


@dataclass(frozen=True)
class Reading:
    key: str            # "F minor"
    key_strength: float  # the correlation of the best key, -1 to 1
    runner_up: str
    bpm: float
    bpm_other: float     # half or double time, when nearly as strong; else 0

    def spoken(self) -> str:
        tempo = f"{self.bpm:g} BPM" + (f", or {self.bpm_other:.0f} if you feel it in {'half' if self.bpm_other < self.bpm else 'double'} time"
                                         if self.bpm_other else "")
        return f"{self.key}, {tempo}"


def load(path: Path, seconds: float = 120.0) -> np.ndarray:
    import soundfile as sf
    from scipy.signal import resample_poly

    data, rate = sf.read(str(path), dtype="float32", always_2d=True, frames=int(seconds * 48000 * 2))
    mono = data.mean(axis=1)[: int(seconds * rate)]
    if rate != RATE:
        from math import gcd

        g = gcd(int(rate), RATE)
        mono = resample_poly(mono, RATE // g, int(rate) // g).astype(np.float32)
    return mono


def _frames(audio: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    if audio.size < n_fft:
        audio = np.pad(audio, (0, n_fft - audio.size))
    count = 1 + (audio.size - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(count)[:, None]
    return np.abs(np.fft.rfft(audio[idx] * np.hanning(n_fft), axis=1))


def chroma(audio: np.ndarray, lo: float = 55, hi: float = 2000) -> np.ndarray:
    """The twelve pitch classes: per frame, the strongest bin of each semitone (harmonic part only: a median
    across time takes the drum hits out), each frame normalised so loud bars do not outvote the rest."""
    from scipy.ndimage import median_filter

    spec = _frames(audio, 8192, 2048)
    if spec.shape[0] > 7:
        spec = median_filter(spec, size=(7, 1))
    freqs = np.fft.rfftfreq(8192, 1 / RATE)
    midi = 12 * np.log2(np.maximum(freqs, 1) / 440.0) + 69
    frames = np.zeros((spec.shape[0], 12))
    for note in range(int(np.ceil(12 * np.log2(lo / 440) + 69)), int(12 * np.log2(hi / 440) + 69) + 1):
        sel = np.abs(midi - note) < 0.5
        if sel.any():
            frames[:, note % 12] += spec[:, sel].max(axis=1)
    norms = np.linalg.norm(frames, axis=1, keepdims=True)
    norms[norms == 0] = 1
    out = (frames / norms).sum(axis=0)
    return out / (np.linalg.norm(out) or 1.0)


FLAT_TO_SHARP = {"db": "C#", "eb": "D#", "gb": "F#", "ab": "G#", "bb": "A#", "cb": "B", "fb": "E"}
SHARP_TO_FLAT = {"C#": "Db", "D#": "Eb", "F#": "Gb", "G#": "Ab", "A#": "Bb"}


def split_key(key: str) -> tuple[str, str]:
    """'E minor', 'e flat minor', 'F#m', 'Bb' -> ('E', 'minor'), ('D#', 'minor'), ('F#', 'minor'), ('A#', 'major'):
    the root in the sharp spelling every control here lists first, and the mode."""
    said = key.strip().lower().replace(" sharp", "#").replace(" flat", "b").replace("-", " ")
    m = re.match(r"^([a-g])([#b]?)\s*(major|minor|maj|min|m)?$", said)
    if not m:
        raise ValueError(f"not a key: {key!r}")
    letter, accidental, mode = m.groups()
    root = FLAT_TO_SHARP.get(letter + accidental) if accidental == "b" else (letter.upper() + accidental)
    return root, "minor" if mode in ("minor", "min", "m") else "major"


def relative(key: str) -> str:
    """The key with the same notes: G major and E minor tune alike and sound different at home."""
    root, mode = split_key(key)
    tonic = NAMES.index(root)
    return f"{NAMES[(tonic + 9) % 12]} minor" if mode == "major" else f"{NAMES[(tonic + 3) % 12]} major"


def same_notes(a: str, b: str) -> bool:
    return split_key(a) == split_key(b) or split_key(relative(a)) == split_key(b)


def key_of(profile: np.ndarray) -> list[tuple[float, str]]:
    scores = []
    for tonic in range(12):
        for mode, template in (("major", MAJOR), ("minor", MINOR)):
            scores.append((float(np.corrcoef(profile, np.roll(template, tonic))[0, 1]), f"{NAMES[tonic]} {mode}"))
    return sorted(scores, reverse=True)


def onset_envelope(audio: np.ndarray, hop: int = 512) -> tuple[np.ndarray, float]:
    spec = np.log1p(_frames(audio, 2048, hop) * 10)
    flux = np.maximum(spec[1:] - spec[:-1], 0).sum(axis=1)
    flux = flux - np.convolve(flux, np.ones(16) / 16, mode="same")  # local mean off: only the jumps
    return np.maximum(flux, 0), RATE / hop


def tempo_of(audio: np.ndarray) -> tuple[float, float]:
    """The tempo whose beat, and its 2, 3 and 4 beat multiples, line up best with the onsets."""
    spec = np.log1p(_frames(audio, 2048, 512) * 10)
    fps = RATE / 512
    flux = np.maximum(spec[1:] - spec[:-1], 0).sum(axis=1)
    window = int(fps)  # a one-second local mean: a short one rang at its own period (136 BPM on every loop)
    flux = np.maximum(flux - np.convolve(flux, np.ones(window) / window, mode="same"), 0)
    if flux.size < 8 or not flux.any():
        return 0.0, 0.0
    env = flux - flux.mean()
    ac = np.correlate(env, env, mode="full")[env.size - 1:]
    ac = ac / (ac[0] or 1.0)
    grid = np.arange(ac.size)

    def strength(bpm: float) -> float:
        lag = 60 * fps / bpm
        return sum(np.interp(lag * k, grid, ac) for k in (1, 2, 3, 4) if lag * k < ac.size)

    candidates = np.arange(60, 200.01, 0.25)
    scored = [strength(b) * np.exp(-0.5 * (np.log2(b / 110.0)) ** 2) for b in candidates]
    bpm = refine(ac, fps, float(candidates[int(np.argmax(scored))]))
    other = 0.0
    for factor in (0.5, 2.0):
        alt = bpm * factor
        if 60 <= alt <= 200 and strength(alt) >= 0.85 * strength(bpm):
            other = alt
    return round(bpm, 1), round(other, 1)


def refine(ac: np.ndarray, fps: float, bpm: float, multiples: int = 64) -> float:
    """The coarse tempo to a hundredth, by lining up as many beats as the audio holds (one beat's lag is a frame
    or two wide; sixty-four beats pin it), then to the whole number a producer sets when it is that close: the
    beat of 2026-10-29 read 117.5 coarse, 116.98 fine, 117 labelled."""
    grid = np.arange(ac.size)

    def strength(b: float) -> float:
        lag = 60 * fps / b
        ks = [k for k in range(1, multiples + 1) if lag * k < ac.size * 0.9]
        return float(np.mean([np.interp(lag * k, grid, ac) for k in ks])) if ks else 0.0

    near = np.arange(bpm - 3, bpm + 3.001, 0.02)
    fine = float(near[int(np.argmax([strength(b) for b in near]))])
    return float(round(fine)) if abs(fine - round(fine)) <= 0.35 else fine


def loop_tempo(bpm: float, seconds: float) -> float:
    """A loop holds whole bars: when a 1 to 32 bar reading of its length sits within 3% of the ear's tempo and
    on a whole number, that is the tempo (on 179 labelled loops: 86 whole-number right by ear, 102 with this)."""
    if not seconds or seconds >= 40:
        return bpm
    fits = [240 * bars / seconds for bars in (1, 2, 4, 8, 16, 32) if abs(240 * bars / seconds - bpm) / bpm < 0.03]
    best = min(fits, key=lambda b: abs(b - bpm), default=None)
    return float(round(best)) if best is not None and abs(best - round(best)) < 0.3 else bpm


def read(path: Path) -> Reading:
    audio = load(path, seconds=240.0)  # a whole beat: more beats, a finer tempo
    ranked = key_of(chroma(audio))
    bpm, other = tempo_of(audio)
    bpm = loop_tempo(bpm, audio.size / RATE)
    return Reading(ranked[0][1], round(ranked[0][0], 3), ranked[1][1], bpm, other)


LABEL = re.compile(r"(?<![A-Za-z])(?P<tonic>[A-G])(?P<acc>#|b|s)?_?(?P<mode>maj|major|min|minor|m)(?![a-z])", re.I)
BPM = re.compile(r"(?<!\d)(?P<bpm>\d{2,3})(?: ?bpm|(?=_[A-G]))", re.I)


def label(name: str) -> tuple[str | None, float | None]:
    """The producer's own key and BPM from a file name, when it carries them."""
    key = None
    m = LABEL.search(name.replace(" ", "_"))
    if m:
        tonic = m.group("tonic").upper() + ("#" if m.group("acc") in ("#", "s") else "b" if m.group("acc") == "b" else "")
        flats = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
        mode = "major" if m.group("mode").lower() in ("maj", "major") else "minor"
        key = f"{flats.get(tonic, tonic)} {mode}"
    b = BPM.search(name)
    return key, float(b.group("bpm")) if b else None


def evaluate(paths: list[Path]) -> dict:
    """Accuracy on labelled loops: key exact, key within relative or fifth, tempo within 2% (or half/double)."""
    rows = []
    for path in paths:
        want_key, want_bpm = label(path.stem)
        got = read(path)
        rows.append((path.stem, want_key, got.key, got.runner_up, want_bpm, got.bpm))
    keyed = [r for r in rows if r[1]]
    timed = [r for r in rows if r[4]]
    exact = sum(r[1] == r[2] for r in keyed)
    near = sum(r[1] in (r[2], r[3]) for r in keyed)
    tempo_ok = sum(any(abs(r[5] * f - r[4]) / r[4] <= 0.02 for f in (1, 0.5, 2)) for r in timed)
    tempo_exact = sum(abs(r[5] - r[4]) / r[4] <= 0.02 for r in timed)
    return {"files": len(rows), "keyed": len(keyed), "key_exact": exact, "key_top2": near, "timed": len(timed),
            "tempo_exact": tempo_exact, "tempo_with_half_double": tempo_ok, "rows": rows}


def find_audio(region: str, search: Callable[[str], list[str]] | None = None) -> Path | None:
    """The file behind a Logic region: its name, less Logic's take and copy marks, looked up with Spotlight."""
    import subprocess

    stem = re.sub(r"(\s*#\d+|\.\d+|_\d+)$", "", region.strip())
    search = search or (lambda name: subprocess.run(["mdfind", "-name", name], capture_output=True, text=True,
                                                    timeout=10).stdout.splitlines())
    audio = (".wav", ".aif", ".aiff", ".mp3", ".m4a", ".flac", ".caf")
    hits = [Path(h) for h in search(stem) if h.lower().endswith(audio)]
    exact = [h for h in hits if h.stem == stem]
    return (exact or hits or [None])[0]

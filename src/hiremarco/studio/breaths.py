"""Breaths cleaned out of a take: found in its audio, cut from that one region, removed, and the phrases faded.

Owner 2026-10-31: he keeps a breath very rarely; the vocal is clean, and it still sounds natural. A breath is a short
noise with no pitch that sits in a gap between phrases. What separates it from a sung consonant: it is not touching a
sung note on its left (it follows a pause), and its noise is lower than a sibilant's ("s", "sh" sit higher). Each
breath is cut out with only its own region selected (the song's sections never move), deleted, and the phrase before
it gets a short fade-out and the phrase after a subtle fade-in, so nothing clicks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

FRAME_S = 0.02
HOP_S = 0.01
MIN_S, MAX_S = 0.12, 1.2          # how long a breath lasts
GAP_BEFORE_S = 0.12               # a breath follows a pause; a consonant touches its note
SIBILANT_HZ = 4500.0              # a breath's noise centres below this; an "s" above it
EDGE_S = 0.02                     # kept clear of the sung notes on both sides
FADE_OUT_MS, FADE_IN_MS = 15, 5   # the phrase before fades out a little; the one after fades in barely


@dataclass(frozen=True)
class Breath:
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def _frames(audio: np.ndarray, rate: int):
    size, hop = int(FRAME_S * rate), int(HOP_S * rate)
    count = max(0, 1 + (len(audio) - size) // hop)
    window = np.hanning(size)
    for i in range(count):
        yield i * hop / rate, audio[i * hop:i * hop + size] * window


def _voiced(frame: np.ndarray, rate: int) -> bool:
    """A sung note: a strong repeat between 70 Hz and 1 kHz in the frame's autocorrelation."""
    x = frame - frame.mean()
    energy = float(np.dot(x, x))
    if energy <= 1e-9:
        return False
    ac = np.correlate(x, x, "full")[len(x) - 1:]
    lo, hi = int(rate / 1000), int(rate / 70)
    return float(ac[lo:hi].max()) / energy > 0.5


def find(audio: np.ndarray, rate: int) -> list[Breath]:
    """The breaths in a take, in seconds from its start."""
    audio = np.asarray(audio, dtype="float64")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    rows = []
    for t, frame in _frames(audio, rate):
        rms = float(np.sqrt(np.mean(frame ** 2)) + 1e-12)
        spectrum = np.abs(np.fft.rfft(frame))
        freqs = np.fft.rfftfreq(len(frame), 1 / rate)
        centroid = float((spectrum * freqs).sum() / (spectrum.sum() + 1e-12))
        rows.append((t, 20 * np.log10(rms), _voiced(frame, rate), centroid))
    if not rows:
        return []
    levels = np.array([r[1] for r in rows])
    floor = float(np.percentile(levels, 10))
    noisy = [(t, db > floor + 10 and not v, c) for t, db, v, c in rows]
    breaths, i = [], 0
    while i < len(noisy):
        if not noisy[i][1]:
            i += 1
            continue
        j = i
        while j + 1 < len(noisy) and noisy[j + 1][1]:
            j += 1
        start, end = rows[i][0], rows[j][0] + FRAME_S
        centroid = float(np.median([noisy[k][2] for k in range(i, j + 1)]))
        before = [r for r in rows[max(0, i - int(GAP_BEFORE_S / HOP_S)):i] if r[2]]
        if MIN_S <= end - start <= MAX_S and centroid < SIBILANT_HZ and not before:
            breaths.append(Breath(start + EDGE_S, end - EDGE_S))
        i = j + 1
    return breaths


class Cleaner:
    """Each breath cut out of its one region, deleted, and the phrases on each side faded. ``at(seconds)`` turns a
    time in the take into Logic's position; the rest are the Logic steps the word lift already uses."""

    def __init__(self, *, at: Callable[[float], object], go: Callable[[object], object],
                 deselect: Callable[[str], object], select: Callable[[str], str], split: Callable[[], None],
                 delete: Callable[[], object], param: Callable[[str, float], str],
                 sleep: Callable[[float], None] = lambda s: None):
        self.at, self.go, self.deselect, self.select = at, go, deselect, select
        self.split, self.delete, self.param, self.sleep = split, delete, param, sleep

    def _pick(self, track: str, seconds: float) -> str:
        self.go(self.at(seconds))
        self.deselect("all")  # only this region: never an arrangement marker with it
        return self.select(track)

    def clean(self, track: str, breaths: list[Breath], keep: set[int] = frozenset()) -> list[int]:
        """The breaths removed, by their number counting from 1; ``keep`` names the ones he wants left."""
        removed = []
        for n, b in enumerate(breaths, start=1):
            if n in keep:
                continue
            for edge in (b.start, b.end):
                self._pick(track, edge)
                self.split()
                self.sleep(0.3)
            self._pick(track, (b.start + b.end) / 2)
            self.delete()
            self.sleep(0.3)
            try:
                self._pick(track, b.start - 0.05)
                self.param("Fade-Out", FADE_OUT_MS)
            except Exception:  # nothing before it (the take starts with the breath): no fade to give
                pass
            try:
                self._pick(track, b.end + 0.05)
                self.param("Fade-In", FADE_IN_MS)
            except Exception:
                pass
            removed.append(n)
        return removed

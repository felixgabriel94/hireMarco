"""Timing read like a drummer reads it: where each syllable's attack lands against the grid.

Owner 2026-10-31: his vocal is a drum part, the cadence intentional, every attack on the beat, rapping or singing; and
quantizing whole notes squashes or stretches words. So Marco reads the attacks, not the notes: each onset in the take
is placed on Logic's grid (the take's start position and tempo), measured against the nearest sixteenth (or 32nd),
and reported by bar and beat with how many milliseconds early or late. Fixing comes after, attack by attack, only where
he says the take is off; this module only measures.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Hit:
    seconds: float      # into the take
    bar: int
    beat: int
    division: int       # the sixteenth (1 to 4) of the grid line it belongs to
    off_ms: float       # + late, - early

    def said(self) -> str:
        side = "late" if self.off_ms > 0 else "early"
        return f"bar {self.bar} beat {self.beat}: {abs(self.off_ms):.0f} ms {side}"


def onsets(audio: np.ndarray, rate: int) -> list[float]:
    """The attacks in a take, in seconds: librosa's onset finder, walked back to where each attack begins."""
    import librosa

    y = np.asarray(audio, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    return [float(t) for t in librosa.onset.onset_detect(y=y, sr=rate, units="time", backtrack=True)]


def place(times: list[float], start_beats: float, tempo: float, *, per_beat: int = 4,
          beats_per_bar: int = 4) -> list[Hit]:
    """Each attack against the grid. ``start_beats`` is where the take began, in beats from bar 1 beat 1 (Logic's
    position), ``per_beat`` the grid (4 for sixteenths, 8 for 32nds)."""
    hits = []
    for t in times:
        beats = start_beats + t * tempo / 60.0
        line = round(beats * per_beat) / per_beat
        off_ms = (beats - line) * 60.0 / tempo * 1000.0
        bar, in_bar = divmod(line, beats_per_bar)
        beat = int(in_bar) + 1
        division = int(round((in_bar - int(in_bar)) * 4)) + 1
        hits.append(Hit(t, int(bar) + 1, beat, min(division, 4), off_ms))
    return hits


def report(hits: list[Hit], tolerance_ms: float = 15.0, worst: int = 3) -> str:
    """One spoken line: how tight it is and the few attacks furthest off."""
    if not hits:
        return "I couldn't hear any attacks in that take."
    off = [h for h in hits if abs(h.off_ms) > tolerance_ms]
    if not off:
        return f"All {len(hits)} attacks land within {tolerance_ms:.0f} ms of the grid."
    off.sort(key=lambda h: -abs(h.off_ms))
    named = "; ".join(h.said() for h in off[:worst])
    return f"{len(hits) - len(off)} of {len(hits)} attacks are on the grid. Furthest off: {named}."

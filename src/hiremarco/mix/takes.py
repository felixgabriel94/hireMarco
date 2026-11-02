"""Abnormal peaks per take, found on their own and judged against the key.

The artist's rule (2026-11-02): bothersome frequencies are removed per take,
selectively, and detected automatically. A take is read in one-second
windows; a bin that stands over its octave in a window is a candidate, and
the share of windows it stands in says what it is: a peak that stays
through the take is a static cut (a Notch or a narrow Bell), a peak that
comes and goes is a dynamic band (the cut moves only when the note rings).
Each peak is named by its note and its relation to the song's key, so a ring
on a chord tone is reported as tone before it is reported as a problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from hiremarco.mix import audit, key as keys

WINDOW_S = 1.0
STAYS = 0.6        # share of windows a peak must stand in to be "stays"
COMES_AND_GOES = 0.15
ABOVE_DB = 5.0     # per window; the votes across windows guard against a one-window fluke


@dataclass
class Peak:
    hz: float
    note: str
    cents: int
    relation: str          # against the key, "" without one
    above_db: float        # the median excess over the octave in the windows it stands in
    share: float           # share of windows it stands in
    kind: str              # "stays" or "comes and goes"
    windows: list[int] = field(default_factory=list)

    @property
    def move(self) -> str:
        """The handbook's move for this kind: a static narrow cut, or a dynamic band; a chord tone that comes and
        goes under 9 dB is the part playing its notes, and gets no cut."""
        if self.kind == "comes and goes" and self.relation in ("the tonic", "a chord tone") and self.above_db < 9:
            return f"no cut: {self.note} is {self.relation}, sounding when the part plays it; tone, not a ring"
        if self.kind == "stays":
            return f"Pro-Q 3 Bell at {self.note} ({self.hz:g} Hz), narrow (Q 6 to 12), gain scaled to the {self.above_db} dB excess"
        return (f"Pro-Q 3 dynamic Bell at {self.note} ({self.hz:g} Hz), dynamic range negative and scaled to the "
                f"{self.above_db} dB excess, auto threshold, so the cut moves only when the note rings")


def peaks(audio: np.ndarray, rate: int, song_key: str = "", *, window_s: float = WINDOW_S,
          above_db: float = ABOVE_DB, per_octave: int = 12) -> list[Peak]:
    """The peaks of a take, by their persistence: loudest excess first."""
    data = np.asarray(audio, dtype=np.float64)
    mono = data.mean(axis=1) if data.ndim > 1 else data
    step = max(int(window_s * rate), 1024)
    hits: dict[int, list[tuple[int, float, float]]] = {}   # quarter-tone grid cell -> (window, excess, hz)
    count = 0
    for start in range(0, max(mono.size - step + 1, 1), step):
        chunk = mono[start:start + step]
        if chunk.size < step // 2 or float(np.max(np.abs(chunk))) < 1e-4:
            continue   # silence does not vote
        count += 1
        centers, levels = audit.smoothed_spectrum(chunk, rate, per_octave)
        for r in audit.named(audit.resonances(centers, levels, per_octave, above_db), "", chunk, rate, per_octave):
            # the line inside the bin votes in a quarter-tone cell, so one ring is one peak across the windows
            cell = int(round(np.log2(r.hz) * 24))
            hits.setdefault(cell, []).append((count - 1, r.above_db, r.hz))
    found = []
    for votes in hits.values():
        share = len(votes) / count if count else 0.0
        if share < COMES_AND_GOES:
            continue
        hz = round(float(np.median([h for _, _, h in votes])), 1)
        note, cents = keys.note_of(hz)
        relation = keys.relation(hz, song_key) if song_key else ""
        found.append(Peak(hz, note, cents, relation, round(float(np.median([v for _, v, _ in votes])), 1),
                          round(share, 2), "stays" if share >= STAYS else "comes and goes", [w for w, _, _ in votes]))
    return sorted(found, key=lambda p: -p.above_db)


def describe(found: list[Peak], song_key: str = "") -> list[str]:
    """One line per peak, the way the plan and the log read it."""
    lines = []
    for p in found:
        where = f", {p.relation} of {song_key}" if p.relation else ""
        cents = f" {p.cents:+d} cents" if p.cents else ""
        lines.append(f"{p.hz:g} Hz ({p.note}{cents}{where}): {p.above_db} dB over its octave, {p.kind} "
                     f"({p.share:.0%} of the take); {p.move}")
    return lines

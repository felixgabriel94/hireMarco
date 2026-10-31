"""Timing read like a drummer: each attack against the grid (Owner 2026-10-31)."""

import numpy as np

from hiremarco.studio.timing import onsets, place, report

RATE = 22050


def clicks(times, seconds=4.0):
    y = np.zeros(int(seconds * RATE), dtype="float32")
    for t in times:
        i = int(t * RATE)
        n = int(0.08 * RATE)
        env = np.exp(-np.arange(n) / (0.01 * RATE))
        y[i:i + n] += 0.6 * env * np.sin(2 * np.pi * 300 * np.arange(n) / RATE)
    return y


def test_attacks_are_measured_against_the_sixteenth_grid():
    # 120 BPM: a beat is 0.5 s, a sixteenth 125 ms; the take starts on bar 2 beat 1 (4 beats in)
    hits = place([0.0, 0.52, 1.0, 1.24], start_beats=4.0, tempo=120.0)
    assert [(h.bar, h.beat, h.division) for h in hits] == [(2, 1, 1), (2, 2, 1), (2, 3, 1), (2, 3, 3)]
    assert [round(h.off_ms) for h in hits] == [0, 20, 0, -10]
    assert report(hits) == "3 of 4 attacks are on the grid. Furthest off: bar 2 beat 2: 20 ms late."


def test_onsets_are_found_where_the_attacks_begin():
    found = onsets(clicks([0.5, 1.0, 1.75]), RATE)
    assert len(found) == 3 and all(abs(a - b) < 0.03 for a, b in zip(found, [0.5, 1.0, 1.75]))

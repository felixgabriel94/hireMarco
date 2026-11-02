"""Abnormal peaks per take: found, named by note and key, told apart by whether they stay."""

import numpy as np

from hiremarco.mix import takes


def pink(n, rng):
    white = rng.standard_normal(n)
    spectrum = np.fft.rfft(white)
    spectrum[1:] /= np.sqrt(np.arange(1, spectrum.size))
    return np.fft.irfft(spectrum, n) * 0.5


def test_a_ring_that_stays_and_one_that_comes_and_goes(rate=22050):
    rng = np.random.default_rng(3)
    seconds = 8
    t = np.arange(seconds * rate) / rate
    bed = pink(seconds * rate, rng)
    stays = 0.4 * np.sin(2 * np.pi * 254.0 * t)                       # B3, a little sharp, the whole take
    gate = ((t % 4.0) < 1.0).astype(float)                            # one second in four
    goes = 0.6 * np.sin(2 * np.pi * 1046.5 * t) * gate                # C6 on its hits
    found = takes.peaks(bed + stays + goes, rate, "C major")
    by_note = {p.note: p for p in found}
    assert "B3" in by_note and by_note["B3"].kind == "stays" and by_note["B3"].share >= 0.6
    assert by_note["B3"].relation == "in the key" and 40 <= by_note["B3"].cents <= 55
    assert "C6" in by_note and by_note["C6"].kind == "comes and goes" and by_note["C6"].relation == "the tonic"
    assert by_note["C6"].above_db >= 9 and "dynamic Bell at C6" in by_note["C6"].move and "Bell at B3" in by_note["B3"].move
    quiet = takes.Peak(1046.5, "C6", 0, "the tonic", 7.0, 0.3, "comes and goes")
    assert quiet.move.startswith("no cut: C6 is the tonic")
    lines = takes.describe(found, "C major")
    assert any(line.startswith("254") and "stays" in line for line in lines)
    assert any("comes and goes" in line and "C6" in line for line in lines)


def test_silence_votes_for_nothing(rate=22050):
    assert takes.peaks(np.zeros(4 * rate), rate) == []

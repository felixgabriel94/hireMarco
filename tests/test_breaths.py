"""Breaths found and cleaned (Owner 2026-10-31): a breath is unpitched noise in a pause, never a sung consonant."""

import numpy as np

from hiremarco.studio.breaths import Breath, Cleaner, find

RATE = 48000


def tone(seconds, hz=220.0, level=0.3):
    t = np.arange(int(seconds * RATE)) / RATE
    return level * np.sin(2 * np.pi * hz * t)


def noise(seconds, level, low, high, seed):
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(int(seconds * RATE))
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / RATE)
    spectrum[(freqs < low) | (freqs > high)] = 0
    y = np.fft.irfft(spectrum, len(x))
    return level * y / (np.abs(y).max() + 1e-12)


def silence(seconds):
    return np.zeros(int(seconds * RATE)) + 1e-5 * np.random.default_rng(9).standard_normal(int(seconds * RATE))


def test_a_breath_in_a_pause_is_found_and_a_sibilant_on_a_word_is_not():
    take = np.concatenate([
        silence(0.3), tone(1.0), silence(0.3),
        noise(0.4, 0.05, 300, 3000, 1),          # the breath: 1.6 s to 2.0 s
        tone(1.0), noise(0.15, 0.08, 5000, 11000, 2),  # "...yes": the s touches the note
        silence(0.4), tone(0.5),
    ])
    found = find(take, RATE)
    assert len(found) == 1
    assert 1.55 < found[0].start < 1.7 and 1.9 < found[0].end < 2.05


def test_a_silent_take_has_no_breaths():
    assert find(silence(2.0), RATE) == []


def test_each_breath_is_cut_from_its_region_alone_deleted_and_the_phrases_faded():
    calls = []
    cleaner = Cleaner(at=lambda s: round(s, 2), go=lambda p: calls.append(("go", p)),
                      deselect=lambda w: calls.append(("deselect", w)), select=lambda t: calls.append(("select", t)),
                      split=lambda: calls.append(("split",)), delete=lambda: calls.append(("delete",)),
                      param=lambda name, v: calls.append(("param", name, v)))
    removed = cleaner.clean("Lead Vox", [Breath(1.6, 2.0), Breath(5.0, 5.3)], keep={2})
    assert removed == [1]
    kinds = [c[0] for c in calls]
    assert kinds.count("split") == 2 and kinds.count("delete") == 1
    assert all(calls[i - 1] == ("deselect", "all") for i, c in enumerate(calls) if c[0] == "select")  # one region
    assert ("param", "Fade-Out", 15) in calls and ("param", "Fade-In", 5) in calls
    assert ("go", 1.8) in calls                                           # the deleted piece is picked mid-breath


def test_a_stack_is_cleaned_voice_by_voice_and_a_voice_holding_through_is_not_cut():
    from hiremarco.studio.booth import Booth, Tape
    from hiremarco.studio.commands import Command
    from hiremarco.studio.position import Position

    cuts = []

    class Lift:
        go = staticmethod(lambda spot: None)
        deselect = staticmethod(lambda which: None)
        split = staticmethod(lambda: None)
        selected = staticmethod(lambda: "Harmony 1")

        def __init__(self):
            self.track = ""

        def select(self, track):
            self.track = track
            return "r"

    lift = Lift()
    b = Booth(understand=lambda line: None, logic=lambda c: c.describe(), say=lambda t: None,
              feedback=lambda take, rate: None, tape=Tape(RATE, seconds=1), log=lambda line: None, lifter=lift)
    start = (Position(13, 1, 1, 1), 120.0, 4)
    breathing = np.concatenate([silence(0.3), tone(1.0), silence(0.3), noise(0.4, 0.05, 300, 3000, 1), tone(1.0)])
    holding = np.concatenate([silence(0.3), tone(3.0, hz=330.0)])                # sings straight through
    b.voice_takes = {"Harmony 1": (breathing, start), "Harmony 2": (holding, start)}
    import hiremarco.studio.gain as gain

    gain_osa = gain._osa
    gain._osa = lambda script, args: cuts.append((lift.track, args[0])) or "ok"
    try:
        line = b.handle(Command("clean_breaths", track="harmonies"))
    finally:
        gain._osa = gain_osa
    assert "breaths removed: 1 of 1" in line and "Harmony 1 1" in line and "Harmony 2 0" in line
    assert {t for t, what in cuts if what == "delete"} == {"Harmony 1"}

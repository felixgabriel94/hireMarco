import numpy as np

from hiremarco.studio import tune

RATE = 48000
FPS = RATE / tune.HOP


def track(notes):
    """A pitch track: (midi, seconds, cents off, vibrato) per note, unvoiced gaps between."""
    midi, voiced = [], []
    for m, secs, off, vib in notes:
        t = np.arange(int(secs * FPS)) / FPS
        midi.append(m + off / 100 + (0.4 * np.sin(2 * np.pi * 5.5 * t) if vib else np.zeros(t.size)))
        voiced.append(np.ones(t.size, bool))
        midi.append(np.full(5, np.nan))
        voiced.append(np.zeros(5, bool))
    return np.concatenate(midi), np.concatenate(voiced)


def test_each_note_moves_its_center_toward_the_key_by_the_amount_asked():
    t = track([(60, 0.6, 30, False), (62, 0.6, -40, False)])
    p = tune.plan(np.zeros(1), RATE, "C major", center=80, drift=0, track=t)
    assert [n.target for n in p.notes] == [60, 62]
    first, second = p.notes
    mid = (first.start + first.end) // 2
    assert abs(p.offsets[mid] - (-0.30 * 0.8)) < 0.01 and abs(p.offsets[(second.start + second.end) // 2] - 0.32) < 0.01


def test_a_wide_vibrato_stays_one_note_and_is_left_swinging():
    t = track([(64, 1.0, 20, True)])
    p = tune.plan(np.zeros(1), RATE, "C major", center=100, drift=100, track=t)
    assert len(p.notes) == 1 and p.notes[0].target == 64 and p.notes[0].vibrato
    inside = p.offsets[p.notes[0].start + 10:p.notes[0].end - 10]
    assert inside.std() < 0.1  # the correction is steady: the 5.5 Hz swing is not flattened


def test_out_of_key_notes_go_to_the_nearest_scale_note():
    assert tune.nearest_in_key(60.7, (0, 2, 4, 5, 7, 9, 11), 0) == 60   # a sharp C stays a C in C major
    assert tune.nearest_in_key(61.2, (0, 2, 4, 5, 7, 9, 11), 0) == 62   # past the middle of C#, it is a D
    assert tune.nearest_in_key(66.6, (0, 2, 3, 5, 7, 8, 10), 5) == 67   # F minor: between F# and G, G


def test_the_shifters_delay_is_taken_out():
    original = np.zeros((48000, 1), np.float32)
    original[10000:12000] = 1
    shifted = np.vstack([np.zeros((1200, 1), np.float32), original])
    out = tune.align(original, shifted)
    assert out.shape == original.shape and np.argmax(out[:, 0]) == np.argmax(original[:, 0])


def test_the_booth_asks_for_the_key_then_tunes_the_selected_take(monkeypatch, tmp_path):
    from hiremarco.studio import analyze
    from hiremarco.studio.booth import Booth, Tape
    from hiremarco.studio.commands import Command, understand

    said = []

    class Tracks:
        def regions(self):
            return ["Lead Vox#03"]

    take = tmp_path / "Lead Vox#03.wav"
    monkeypatch.setattr(analyze, "find_audio", lambda region: take)
    monkeypatch.setattr(tune, "first_pass", lambda path, key, center, drift: (
        tmp_path / "Lead Vox#03 (Marco tuned).wav", {"notes": 6, "median_cents_off": 35.0, "vibrato_notes": 1},
        {"notes": 6, "median_cents_off": 9.2, "vibrato_notes": 4}))
    monkeypatch.setattr("hiremarco.studio.booth.subprocess.run", lambda *a, **k: None)
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(), say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None, tracks=Tracks())
    assert understand("Marco, give me a first pass", client=None) == Command("tune_take")
    assert "asked for the key" in b.hear("Marco, tune my take") and said[-1] == "What key are we in?"
    b.key = "F minor"
    result = b.hear("Marco, tune my take")
    assert "35.0 to 9.2 cents" in result and "Lead Vox#03 (Marco tuned).wav" in result and "9.2" in said[-1]

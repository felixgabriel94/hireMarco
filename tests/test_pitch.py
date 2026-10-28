import mido
import numpy as np
import pytest

from hiremarco.studio.pitch import (describe, guide, midi_name, midi_to_hz, notes, parse_key, snap, to_midi,
                                    track, yin)

RATE = 24000


def sung(parts, rate=RATE):
    """Sustained vowel-like tones: (midi, seconds) with a little vibrato and harmonics; None is a rest."""
    out = []
    for midi, seconds in parts:
        t = np.arange(int(seconds * rate)) / rate
        if midi is None:
            out.append(np.zeros_like(t))
            continue
        f = midi_to_hz(midi) * (1 + 0.003 * np.sin(2 * np.pi * 5.5 * t))
        phase = 2 * np.pi * np.cumsum(f) / rate
        out.append(0.3 * (np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.25 * np.sin(3 * phase)))
    return np.concatenate(out)


def test_yin_finds_a_steady_pitch():
    t = np.arange(int(0.04 * RATE)) / RATE
    assert yin(np.sin(2 * np.pi * 220 * t), RATE) == pytest.approx(220, rel=0.01)
    assert yin(np.zeros(960), RATE) == 0.0


def test_keys_and_snapping():
    assert parse_key("F minor") == (5, (0, 2, 3, 5, 7, 8, 10))
    assert parse_key("Bbm")[0] == 10 and parse_key("C#")[0] == 1
    assert snap(61.2, "C major") in (60, 62)   # C#4 is not in C major
    assert snap(68.9, "F minor") == 68          # G#4 / Ab4 is in F minor
    with pytest.raises(ValueError):
        parse_key("H major")


def test_a_run_becomes_notes_with_how_far_off_each_is():
    # A4 in tune, C5 thirty cents flat, a rest, then B4 fifteen cents sharp, in A minor.
    audio = sung([(69, 0.3), (71.7, 0.3), (None, 0.1), (71.15, 0.3)])
    run = notes(audio, RATE, "A minor")
    assert [n.target for n in run] == [69, 72, 71]
    assert [midi_name(n.target) for n in run] == ["A4", "C5", "B4"]
    assert abs(run[0].cents_off) <= 5
    assert -36 <= run[1].cents_off <= -24
    assert 9 <= run[2].cents_off <= 21
    assert run[2].start > run[1].end  # the rest is kept


def test_describe_names_the_notes_that_are_off():
    run = notes(sung([(69, 0.3), (71.7, 0.3), (71.0, 0.3)]), RATE, "A minor")
    line = describe(run)
    assert line.startswith("The second note is") and "flat" in line and "wants the C" in line
    assert describe(notes(sung([(69, 0.3), (72, 0.3)]), RATE, "A minor")).startswith("All 2 notes")
    assert "couldn't hear" in describe([])


def test_silence_has_no_pitch():
    assert np.all(np.isnan(track(np.zeros(RATE), RATE)))


def test_guide_plays_the_corrected_notes(tmp_path):
    run = notes(sung([(69, 0.3), (71.7, 0.3)]), RATE, "A minor")
    tone = guide(run, RATE)
    assert tone.dtype == np.dtype("<i2") and tone.size > 0.6 * RATE
    heard = notes(tone, RATE, "A minor", min_s=0.05)
    assert [n.target for n in heard][:2] == [69, 72]  # the guide itself is in tune
    path = tmp_path / "run.mid"
    to_midi(run, path, bpm=90)
    msgs = [m for m in mido.MidiFile(path).tracks[0] if m.type == "note_on"]
    assert [m.note for m in msgs] == [69, 72]


def test_locate_estimates_the_phrase_inside_its_turn():
    from hiremarco.hearing import Turn
    from hiremarco.studio.pitch import locate

    turns = [Turn(0, 2000, "baby you should"), Turn(2000, 6000, "you should let me love you tonight")]
    start, end = locate("love you", turns, pad_s=0)
    # "love you" is words 5-6 of 7 in a four-second turn that starts at 2 s
    assert start == pytest.approx(2 + 4 * 4 / 7) and end == pytest.approx(2 + 4 * 6 / 7)
    assert locate("hold me", turns) is None
    assert locate("", turns) is None


def test_run_in_keeps_take_time():
    from hiremarco.studio.pitch import run_in

    audio = sung([(None, 1.0), (69, 0.3), (71.7, 0.3), (None, 0.5)])
    run = run_in(audio, RATE, "A minor", window=(0.8, 1.9))
    assert [n.target for n in run] == [69, 72] and run[0].start >= 0.95

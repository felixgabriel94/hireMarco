import mido
import numpy as np

from hiremarco.studio import drums
from hiremarco.studio.drums import Hit


def _pattern(bars):
    hits = []
    for bar in range(bars):
        for s in range(16):
            step = bar * 16 + s
            if s % 4 == 0:
                hits.append(Hit("kick", step, 100))
            if s in (3, 6, 11, 14):
                hits.append(Hit("snare", step, 90))
            if s % 2 == 0:
                hits.append(Hit("hat", step, 60 + (bar % 3)))
    return hits


def test_the_main_loop_outvotes_an_intro_and_a_fill():
    intro = [Hit("hat", s, 50) for s in range(0, 64, 2)]                     # two 2-bar windows of hats alone
    body = [Hit(h.kind, h.step + 64, h.velocity) for h in _pattern(12)]      # six windows of the loop
    fill = [Hit("snare", s, 110) for s in range(256, 288)]                   # one window of a snare roll
    loop = drums.groove(intro + body + fill, bars=2)
    want = {(h.kind, h.step) for h in _pattern(2)}
    assert {(h.kind, h.step) for h in loop} == want


def test_a_pattern_becomes_a_midi_loop_at_its_tempo_on_the_drum_channel(tmp_path):
    path = drums.to_midi(_pattern(2), tmp_path / "loop.mid", 99.0, length_steps=32)
    midi = mido.MidiFile(str(path))
    ons = [m for m in midi.tracks[0] if m.type == "note_on"]
    assert len(ons) == len(_pattern(2)) and all(m.channel == 9 for m in ons)
    assert {m.note for m in ons} == {36, 38, 42}
    assert abs(midi.length - 2 * 4 * 60 / 99.0) < 0.01                     # exactly two bars long


def test_the_grid_reads_like_a_step_sequencer():
    rows = drums.grid(_pattern(1), bars=1).splitlines()
    assert rows[0].split()[-1] == "x...x...x...x..."
    assert rows[1].split()[-1] == "...x..x....x..x."


def test_each_attack_is_named_by_the_ear_and_placed_on_the_grid():
    rate, bpm = 48000, 120.0
    step_s = 60 / bpm / 4
    y = np.zeros(int(rate * 2.5), dtype=np.float32)
    rng = np.random.default_rng(0)
    for step in (0, 4, 8, 12):
        at = int((0.25 + step * step_s) * rate)
        y[at:at + 2400] += rng.normal(0, 0.5, 2400).astype(np.float32) * np.linspace(1, 0, 2400, dtype=np.float32)

    class Ear:  # hears every attack as a kick
        def predict_proba(self, x):
            return np.tile([0.9, 0.1, 0.2], (len(x), 1))

    hits = drums.transcribe(y, rate, bpm, one=0.25, model=Ear())
    assert [(h.kind, h.step) for h in hits] == [("kick", 0), ("kick", 4), ("kick", 8), ("kick", 12)]

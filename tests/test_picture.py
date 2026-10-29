import numpy as np

from hiremarco.mix.picture import draw

RATE = 48000


def tone(freqs, amp=0.1):
    t = np.arange(RATE * 2) / RATE
    rng = np.random.default_rng(1)
    return sum(amp * np.sin(2 * np.pi * f * t) for f in freqs) + 0.0005 * rng.standard_normal(t.size)


def test_kick_and_bass_overlap_is_shaded_low_and_the_svg_is_written(tmp_path):
    out = tmp_path / "kick_bass.svg"
    spans = draw(("Kick", tone([60]), RATE), ("Bass", tone([60, 1000], amp=0.1), RATE), out)
    text = out.read_text()
    assert text.startswith("<svg") and "Kick" in text and "Bass" in text and "where they collide" in text
    assert spans and all(hi > lo for lo, hi in spans)
    assert any(lo <= 60 <= hi for lo, hi in spans)      # the shared 60 Hz region
    assert not any(lo < 1000 < hi for lo, hi in spans)  # only the bass has 1 kHz

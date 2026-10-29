import numpy as np

from hiremarco.mix.picture import draw

RATE = 48000
T = np.arange(RATE * 3) / RATE
RNG = np.random.default_rng(1)


def kick():
    x = np.zeros_like(T)
    for s in range(0, len(T), RATE // 2):
        n = np.arange(min(RATE // 4, len(T) - s))
        x[s:s + len(n)] += 0.6 * np.sin(2 * np.pi * (55 + 90 * np.exp(-n / 800)) * n / RATE) * np.exp(-n / 5000)
    return x + 0.002 * RNG.standard_normal(len(T))


def bass(weight=1.0):
    return weight * 0.3 * np.sin(2 * np.pi * 55 * T) + 0.15 * np.sin(2 * np.pi * 110 * T) + 0.002 * RNG.standard_normal(len(T))


def test_kick_and_bass_collide_low_and_the_picture_is_written(tmp_path):
    out = tmp_path / "kick_bass.svg"
    found = draw(("Kick", kick(), RATE), ("Bass", bass(), RATE), out)
    text = out.read_text()
    assert text.startswith("<svg") and "Kick vs Bass" in text and "where they fight" in text
    assert any(r.lo_hz <= 55 <= r.hi_hz for r in found)
    assert all(r.hi_hz < 300 for r in found)  # nothing above the low end: the tracks do not meet there
    assert "SUB" in text and "AIR" in text and "Hz" in text


def test_after_a_pass_the_resolved_collision_says_so(tmp_path):
    k = kick()
    out = tmp_path / "after.svg"
    found = draw(("Kick", k, RATE), ("Bass", bass(0.1), RATE), out, before=(k, bass()))
    resolved = [r for r in found if r.gap_db == float("inf")]
    assert resolved and any(r.lo_hz <= 55 <= r.hi_hz for r in resolved)
    assert "now clear" in out.read_text() and "dashed: before" in out.read_text()

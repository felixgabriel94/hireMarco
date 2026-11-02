"""Verification before done: pumping, tone and crest against the mix; the manifest of the output strip."""

import numpy as np
import soundfile as sf

from hiremarco.mix import verify
from hiremarco.studio.stereo_out import Insert, same_plugin

RATE = 48000


def noise(seconds=12.0, seed=1):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((int(seconds * RATE), 2)) * 0.05).astype("float32")


def ducked(audio, bpm=120.0, depth_db=4.0):
    t = np.arange(audio.shape[0]) / RATE
    beat = 60.0 / bpm
    gain_db = -depth_db * (((t % beat) / beat) < 0.3)      # the first third of every beat pulled down
    return (audio * (10 ** (gain_db / 20))[:, None]).astype("float32")


def test_a_ducker_on_the_output_fails_the_comparison(tmp_path):
    mix = noise()
    sf.write(tmp_path / "mix.wav", mix, RATE, subtype="FLOAT")
    sf.write(tmp_path / "pumped.wav", ducked(mix) * 1.4, RATE, subtype="FLOAT")        # louder and pumping
    v = verify.compare(tmp_path / "mix.wav", tmp_path / "pumped.wav", 120.0)
    assert not v.passed and any("pumps at the beat rate" in r for r in v.reasons)
    assert v.numbers["modulation_beat_new_db"] > verify.PUMP_LIMIT_DB
    assert v.text().startswith("NOT VERIFIED")


def test_a_louder_but_unchanged_master_passes(tmp_path):
    mix = noise()
    sf.write(tmp_path / "mix.wav", mix, RATE, subtype="FLOAT")
    sf.write(tmp_path / "master.wav", np.clip(mix * 2.0, -0.99, 0.99), RATE, subtype="FLOAT")   # 6 dB up, no shaping
    v = verify.compare(tmp_path / "mix.wav", tmp_path / "master.wav", 100.0)
    assert v.passed and v.numbers["master_lufs"] > v.numbers["mix_lufs"] + 5
    assert v.text().startswith("verified") and "loudness-matched" in v.text()


def test_a_band_moved_far_beyond_the_plan_fails(tmp_path):
    from scipy import signal

    mix = noise()
    sos = signal.butter(4, 300, "highpass", fs=RATE, output="sos")
    thin = signal.sosfilt(sos, mix, axis=0).astype("float32")              # the whole low end gone
    sf.write(tmp_path / "mix.wav", mix, RATE, subtype="FLOAT")
    sf.write(tmp_path / "thin.wav", thin, RATE, subtype="FLOAT")
    v = verify.compare(tmp_path / "mix.wav", tmp_path / "thin.wav", 100.0, tonal_only=True)
    assert not v.passed and any("sub moved" in r or "bass moved" in r for r in v.reasons)


def test_the_manifest_tells_yours_planned_and_stray_apart():
    inserts = [Insert("Ozone 11 Ma", False, 585, 160), Insert("Gain", False, 585, 180), Insert("Pro-L 2", False, 585, 197),
               Insert("Kickstart ", True, 585, 214)]
    ledger = [{"name": "Gain", "plugin": "Gain", "stray": False}, {"name": "Pro-L 2", "plugin": "Pro-L 2", "stray": False},
              {"name": "Kickstart ", "plugin": "Gain (misfire)", "stray": True}]
    rows = verify.manifest(inserts, ledger, {"Gain", "Pro-L 2"}, same_plugin)
    assert [(r["name"], r["status"]) for r in rows] == [("Ozone 11 Ma", "yours"), ("Gain", "planned"), ("Pro-L 2", "planned"), ("Kickstart ", "stray")]

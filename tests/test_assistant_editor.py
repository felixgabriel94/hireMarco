"""Assistant editor: time parsing, timecode, audio sync, FCPXML shape."""
import importlib.util
import sys
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

_p = Path(__file__).resolve().parents[1] / "scripts" / "assistant_editor.py"
_spec = importlib.util.spec_from_file_location("assistant_editor", _p)
ae = importlib.util.module_from_spec(_spec)
sys.modules["assistant_editor"] = ae
_spec.loader.exec_module(ae)

TZ = ZoneInfo("America/New_York")


def test_time_tags():
    a = ae.parse_time_tag("2026-11-03T10:04:05-0500", TZ)
    b = ae.parse_time_tag("2026-11-03T15:04:05Z", TZ)
    c = ae.parse_time_tag("2026-11-03T10:04:05", TZ, assume_local=True)
    assert a == b == c


def test_drop_frame_timecode():
    s, drop = ae.tc_to_seconds("00:01:00;02", Fraction(30000, 1001))
    assert drop
    # 00:01:00;02 is frame 1800 in drop-frame counting
    assert abs(s - 1800 * 1001 / 30000) < 1e-9


def test_gcc_phat_finds_offset():
    rng = np.random.default_rng(1)
    ref = rng.standard_normal(ae.SR * 20)
    lag = 12345
    sig = ref[lag:lag + ae.SR * 3] * 0.3 + rng.standard_normal(ae.SR * 3) * 0.05
    got, z = ae.gcc_phat(ae.prep(sig), ae.prep(ref))
    assert got == lag and z > ae.MIN_Z


def test_rational_time():
    tb = ae.Timebase(Fraction(30000, 1001))
    assert tb.t(1.0) == "30030/30000s".replace("30030/30000", "1001/1000")
    assert ae.rt(Fraction(3600)) == "3600s"


def test_skewed_sony_rate_snaps_to_29_97():
    # a real A7R III clip reports avg_frame_rate 15300000/511511 (29.91); it is 29.97
    assert ae.snap_fps(Fraction(15300000, 511511), strict=True) == Fraction(30000, 1001)
    assert ae.snap_fps(Fraction(1252950, 24161), strict=True) is None  # 51.9 fps variable-rate screen recording


def test_unrelated_recordings_do_not_agree():
    rng = np.random.default_rng(3)
    t = np.arange(ae.SR * 40) / ae.SR
    hum = np.sin(2 * np.pi * 60 * t) * 0.05
    ref = hum + rng.standard_normal(len(t)) * 0.01
    other = hum[: ae.SR * 20] + rng.standard_normal(ae.SR * 20) * 0.01
    lags = [ae.gcc_phat(ae.prep(other[i * ae.SR * 5:(i + 1) * ae.SR * 5]), ae.prep(ref))[0] for i in range(3)]
    # independent probes of an unrelated recording must not land on one start
    starts = [lag - i * ae.SR * 5 for i, lag in enumerate(lags)]
    assert len({round(s / (ae.SR * 0.005)) for s in starts}) > 1


def test_audio_lead_shifts_clip_start(tmp_path):
    """A file whose audio starts 32 ms after its video: the clip start is the video start."""
    sr = ae.SR
    rng = np.random.default_rng(5)
    room = rng.standard_normal(sr * 30).astype(np.float32)
    anchor = ae.Clip(path=tmp_path / "a.wav", device="booth", duration=30.0, has_video=False, has_audio=True)
    anchor.start = 1000.0
    late = ae.Clip(path=tmp_path / "b.mov", device="cam", duration=10.0, has_video=True, has_audio=True)
    late.audio_lead = 0.032
    late.raw_start = 1005.0
    cache = ae.AudioCache(tmp_path / "cache")
    cache.memo[anchor.path] = room / np.abs(room).max()
    seg = room[int((5.0 + 0.032) * sr): int((15.0 + 0.032) * sr)]
    cache.memo[late.path] = seg / np.abs(seg).max()
    start, z, _ = ae.try_sync(late, [anchor], cache, 1004.0, 5.0)
    assert abs(start - 1005.0) < 0.0015 and z >= ae.MIN_Z


def test_short_clip_locks_despite_a_louder_unrelated_neighbour(tmp_path):
    """A 10 s clip placed after a 40 s clip from the same room: the true match against the
    anchor must win even though the 40 s clip, which does not contain this sound, sits in the window."""
    sr = ae.SR
    rng = np.random.default_rng(11)
    t = np.arange(sr * 120) / sr
    env = (np.sin(2 * np.pi * 2.7 * t) ** 2) * (rng.random(120)[t.astype(int)] > 0.3)
    room = (np.convolve(rng.standard_normal(len(t)), np.ones(10) / 10, "same") * env).astype(np.float32)
    cache = ae.AudioCache(tmp_path / "cache")

    def clip(name, a, b, dev, filt):
        c = ae.Clip(path=tmp_path / name, device=dev, duration=b - a, has_video=False, has_audio=True)
        seg = np.convolve(room[int(a * sr): int(b * sr)], filt, "same") + rng.standard_normal(int((b - a) * sr)).astype(np.float32) * 0.05
        x = ae.prep(seg)
        cache.memo[c.path] = (x / np.abs(x).max()).astype(np.float32)
        return c

    anchor = clip("apollo.wav", 0, 120, "apollo", [1.0])
    anchor.start = 1000.0
    cam40 = clip("cam40.mov", 37.25, 77.25, "cam40", [0.5, 0.3, 0.2])
    cam40.start = 1037.25
    cam10 = clip("cam10.mov", 80.5, 90.5, "cam10", [0.2, 0.3, 0.5])
    cam10.raw_start = 1070.0
    r = ae.try_sync(cam10, [anchor, cam40], cache, 1070.0, 300.0)
    assert r is not None and abs(r[0] - 1080.5) < 0.0015 and r[2] == "apollo"


def test_countin_is_found_in_noisy_room_audio():
    rng = np.random.default_rng(21)
    sr = ae.SR
    x = rng.standard_normal(sr * 30) * 0.1
    t = np.arange(len(x)) / sr
    x += np.sin(2 * np.pi * 220 * t) * 0.3 * (np.sin(2 * np.pi * 0.5 * t) > 0)  # a hummed note on and off
    cue = ae.countin_template(sr) * 0.5
    at = int(7.3 * sr)
    x[at: at + len(cue)] += cue
    hits = ae.find_countins(x, sr)
    assert hits and abs(hits[0][0] - (7.3 + 1.5)) < 0.003
    assert ae.find_countins(x[: at - sr], sr) == []


def test_partial_countin_is_rejected():
    rng = np.random.default_rng(22)
    sr = ae.SR
    x = rng.standard_normal(sr * 20) * 0.1
    cue = ae.countin_template(sr) * 0.5
    at = int(5.0 * sr)
    x[at: at + len(cue)] += cue
    cut = x[at + int(0.3 * sr):]  # the camera started after the first beat
    assert ae.find_countins(cut, sr) == []
    faint = rng.standard_normal(sr * 20) * 0.3
    faint[at: at + len(cue)] += cue * 0.03  # count buried in the room sound
    hits = ae.find_countins(faint, sr)
    assert all(abs(h[0] - 6.5) < 0.003 for h in hits)  # found right or not at all

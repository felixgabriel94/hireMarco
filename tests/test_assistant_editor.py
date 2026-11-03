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

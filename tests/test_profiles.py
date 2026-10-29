import pytest

from hiremarco.mix.profiles import DB, HZ, PRO_Q3, Q, profile_for
from hiremarco.studio.plugins import parse

PRO_Q = ("plugin\tFabFilter Pro-Q 3\n"
         "Band 1 Used\t1\t0\t1\nBand 1 Enabled\t1\t0\t1\nBand 1 Frequency\t2907\t0\t11551\n"
         "Band 1 Gain\t30000\t0\t60000\nBand 1 Dynamic Range\t30000\t0\t60000\nBand 1 Dynamics Enabled\t1\t0\t1\n"
         "Band 1 Threshold\t10000\t0\t10000\nBand 1 Q\t4308\t0\t10000\nBand 1 External Side Chain\t0\t0\t1\n"
         "Band 2 Used\t0\t0\t1\nBand 2 Frequency\t6644\t0\t11551\n")


def test_units_read_the_defaults_logic_reported():
    assert HZ.to_unit(6644) == pytest.approx(1000, rel=0.002)   # Pro-Q's default band frequency
    assert HZ.to_unit(11551) == pytest.approx(30000, rel=0.002) and HZ.to_unit(0) == 10
    assert DB.to_unit(30000) == 0 and DB.to_unit(31000) == 1
    assert Q.to_unit(5000) == pytest.approx(1.0, rel=0.001)
    for u, v in ((HZ, 62.0), (DB, -4.0), (Q, 1.4)):
        assert u.to_unit(u.to_raw(v)) == pytest.approx(v, rel=0.01)


def test_the_profile_fits_only_a_plugin_with_its_controls():
    state = parse(PRO_Q)
    assert profile_for(state.plugin, list(state.params)) is PRO_Q3
    assert profile_for("FabFilter Pro-Q 3", ["Band 1 Gain"]) is None   # missing controls: not used
    assert profile_for("Pro-C 2", list(state.params)) is None


def test_the_model_sees_real_units_and_the_recipes():
    view = parse(PRO_Q).for_model()
    assert view["in_units"]["Band 1 Frequency"] == "75.0 Hz" and view["in_units"]["Band 1 Gain"] == "0.0 dB"
    assert "duck the bass under the kick" in view["expert"]["recipes"]
    assert "Band 2 Frequency" not in view["in_units"]  # an unused band stays folded


def test_an_answer_in_hz_lands_on_the_right_raw_value():
    state = parse(PRO_Q)
    percent = state.percent_of("Band 1 Frequency", 62, "Hz")
    assert state.raw("Band 1 Frequency", percent) == pytest.approx(HZ.to_raw(62), abs=1)
    assert state.percent_of("Band 1 Gain", 40, "%") == 40
    assert state.percent_of("Band 1 Gain", -4, "dB") == pytest.approx((26000 / 60000) * 100)

from hiremarco.mix.ears import EarsReport, TrackReport
from hiremarco.mix.session import (Hardware, against_target, build, collision_grid, masked_bands, role_of, summary,
                                   where_to_fix)


def track(name, lufs, bands, low_mono=1.0, clipped=0):
    full = {b: -40.0 for b in ("sub", "bass", "low mids", "mids", "upper mids", "presence", "air")}
    full.update(bands)
    return TrackReport(name, 10.0, lufs, -6.0, -6.0, 10.0, full, 1.0, low_mono, clipped)


KICK = track("Kick", -9, {"sub": -6, "bass": -1})   # the loudest thing in the room, as in most records
BASS = track("Bass", -11, {"sub": -4, "bass": -2, "low mids": -10})
VOX = track("Lead Vox", -12, {"mids": -4, "upper mids": -1, "presence": -8})
PAD = track("Pad", -13, {"mids": -3, "upper mids": -2})
HATS = track("Hi Hats", -28, {"air": -1})
QUIET = track("Empty", -80, {})


def test_roles_come_from_names_then_from_the_measurement():
    assert role_of("Lead Vox") == ("lead vocal", "name")
    assert role_of("808 Sub") == ("kick", "name")
    assert role_of("Mystery", track("Mystery", -20, {"bass": -1})) == ("bass", "guess")
    assert role_of("Mystery", track("Mystery", -20, {"mids": -1})) == ("other", "guess")


def test_the_grid_ranks_fights_by_energy_and_skips_silence():
    fights = collision_grid([KICK, BASS, VOX, PAD, HATS, QUIET])
    assert fights[0].a == "Kick" and fights[0].b == "Bass" and fights[0].band == "bass"
    assert {(f.a, f.b) for f in fights} >= {("Kick", "Bass"), ("Lead Vox", "Pad")}
    assert all("Empty" not in (f.a, f.b) for f in fights)


def test_masking_names_where_the_rest_of_the_mix_buries_a_track():
    assert "upper mids" in masked_bands(track("Soft Gtr", -24, {"upper mids": -1}), [VOX, PAD])
    assert masked_bands(VOX, [HATS]) == []


def test_targets_are_relative_to_the_lead_vocal():
    notes = against_target("hats", track("Hi Hats", -14, {"air": -1}), vocal_lufs=-12)
    assert any("loud for a hats" in n for n in notes)
    assert against_target("kick", track("Kick", -14, {"sub": -6, "bass": -1}), vocal_lufs=-12) == []
    wide = track("Bass", -16, {"bass": -1}, low_mono=0.3)
    assert any("mono below 120 Hz" in n for n in against_target("bass", wide, -12))
    assert any("usually lives in the bass" in n for n in against_target("kick", track("Kick", -14, {"mids": -1}), -12))


def test_build_and_summary_hold_everything_including_hardware():
    report = EarsReport(tracks=[KICK, BASS, VOX, PAD], mix_notes=["true peak -1 dBFS: leave headroom"])
    hw = [Hardware("UA 6176", "mic preamp and compressor", {"gain": "35", "ratio": "4:1"}),
          Hardware("Manley Reference", "mic", {"pattern": "cardioid"})]
    view = build(report, hw)
    text = summary(view)
    assert "Lead Vox (lead vocal)" in text and "fight: Kick and Bass in the bass" in text
    assert "hardware: UA 6176" in text and "mix: true peak" in text
    assert view.as_dict()["tracks"][2]["role"] == "lead vocal"


def test_where_a_fix_lives():
    hw = [Hardware("UA 6176", "mic preamp and compressor", {}, live=True)]
    assert where_to_fix(hw, already_recorded=True).startswith("in Logic")
    assert where_to_fix(hw, already_recorded=False).startswith("on the hardware first (UA 6176)")
    assert where_to_fix([], already_recorded=False).startswith("in Logic")

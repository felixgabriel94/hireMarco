"""The handbook's situations: parsed from their files, picked by the audit, handed to the plan with their IDs."""

from pathlib import Path

from hiremarco.master import handbook

SAMPLE = '''id: S-TEST-01
role: corrective_eq
job: mastering
triggers: ["finding: resonance at", "problem_bands_db.mud > -8"]
claims: [R-AUD-0006, R-AUD-0007]

# A resonance

**What to look for.** A peak.
'''


def test_parse_reads_the_header_and_the_title():
    s = handbook.parse(SAMPLE)
    assert (s.id, s.role, s.job) == ("S-TEST-01", "corrective_eq", "mastering")
    assert s.triggers == ["finding: resonance at", "problem_bands_db.mud > -8"]
    assert s.claims == ["R-AUD-0006", "R-AUD-0007"] and s.title == "A resonance" and s.body.startswith("# A resonance")


def test_triggers_fire_on_finding_words_and_on_measures():
    findings = ["resonance at 254 Hz, 6.3 dB over its octave", "77.08 s of silence at the tail"]
    measures = {"tilt_db_per_octave": -4.58, "problem_bands_db": {"mud": -6.3}, "lufs": -18.0, "target": -10.0,
                "loudness_range": 4.4}
    assert handbook.fires("finding: resonance at", findings, measures)
    assert not handbook.fires("finding: clicks or dropouts", findings, measures)
    assert handbook.fires("problem_bands_db.mud > -8", findings, measures)
    assert handbook.fires("tilt_db_per_octave < -4.5", findings, measures)
    assert handbook.fires("lufs < target - 0.5", findings, measures)
    assert not handbook.fires("loudness_range > 8", findings, measures)
    assert not handbook.fires("nowhere.at.all > 1", findings, measures)


def test_pick_returns_the_fired_situations_with_what_fired(tmp_path):
    (tmp_path / "a.md").write_text(SAMPLE)
    (tmp_path / "b.md").write_text(SAMPLE.replace("S-TEST-01", "S-TEST-02").replace('"finding: resonance at", ', "")
                                   .replace("problem_bands_db.mud > -8", "loudness_range > 8"))
    chosen = handbook.pick(["resonance at 254 Hz, 6.3 dB over its octave"], {"problem_bands_db": {"mud": -12.0},
                           "loudness_range": 4.4}, handbook.load(tmp_path))
    assert [s.id for s in chosen] == ["S-TEST-01"] and chosen[0].fired == ["finding: resonance at"]
    shown = handbook.text(chosen)
    assert shown.startswith("[S-TEST-01] (role corrective_eq; fired on: finding: resonance at; claims R-AUD-0006, R-AUD-0007)")
    assert "**What to look for.** A peak." in shown


def test_measures_come_from_the_audit_dict_with_the_target():
    audit = {"base": {"lufs": -18.0, "true_peak_db": -1.2, "name": "x", "bands_db": {"sub": -5.0}},
             "tilt_db_per_octave": -4.58, "problem_bands_db": {"mud": -6.3}, "resonances": [], "loudness_range": 4.4}
    m = handbook.measures_of(audit, -10.0)
    assert m["lufs"] == -18.0 and m["target"] == -10.0 and m["problem_bands_db"]["mud"] == -6.3 and "name" not in m
    assert m["bands_db"]["sub"] == -5.0


def test_the_shipped_situations_parse_and_name_real_claims():
    shipped = handbook.load()
    assert len(shipped) >= 8 and all(s.id.startswith("S-MASTER-") for s in shipped)
    claims = {p.stem for p in (handbook.ROOT / "claims").glob("R-AUD-*.md")}
    for s in shipped:
        assert s.triggers and s.claims, s.id
        assert set(s.claims) <= claims, (s.id, set(s.claims) - claims)
        for heading in ("**What to look for.**", "**Threshold.**", "**Why.**", "**When it applies.**",
                        "**When it does not.**", "**The move.**", "**Expected effect.**", "**Verify.**"):
            assert heading in s.body, (s.id, heading)
    run31 = ["114 clicks or dropouts", "low end below 120 Hz is wide (correlation 0.59)",
             "resonance at 254 Hz, 6.3 dB over its octave", "77.08 s of silence at the tail"]
    measures = {"lufs": -18.0, "target": -10.0, "tilt_db_per_octave": -4.58, "problem_bands_db": {"mud": -6.3},
                "loudness_range": 4.4, "true_peak_db": -1.2}
    ids = [s.id for s in handbook.pick(run31, measures, shipped)]
    assert ids == ["S-MASTER-01", "S-MASTER-02", "S-MASTER-03", "S-MASTER-04", "S-MASTER-05", "S-MASTER-08"]

import json

from hiremarco.studio import ledger


def test_base_name_drops_logic_channel_suffixes():
    assert ledger.base_name("CLA-76 (s) (s/s)") == "CLA-76"
    assert ledger.base_name("UAD Neve 1073 (s/s)") == "UAD Neve 1073"
    assert ledger.base_name("Pro-Q 3") == "Pro-Q 3"


def test_strings_in_finds_plugin_names_inside_binary_files(tmp_path):
    strip = tmp_path / "vocal.cst"
    strip.write_bytes(b"\x00\x01bplist\x00Pro-Q 3\x00\x02RVox\x00")
    assert ledger.strings_in([strip], {"Pro-Q 3", "RVox", "soothe2"}) == {"Pro-Q 3", "RVox"}


def test_registered_ni_keeps_names_not_keys(tmp_path):
    (tmp_path / "Massive.xml").write_text("<Product><Name>Massive</Name><RegKey>ABCD-1234</RegKey></Product>")
    (tmp_path / "Kontakt Player.xml").write_text("<Product><Name>Kontakt Player</Name><RegKey></RegKey></Product>")
    assert ledger.registered_ni(tmp_path) == {"Massive"}


def test_build_grades_evidence_and_honours_refusals():
    names = ["UAD Teletronix LA-2A Silver (s/s)", "UAD 4K Buss Compressor (s/s)", "Pro-Q 3 (s/s)",
             "Melodyne (s/s)", "Pro-R 2 (s/s)", "Massive (s/s)", "Mystery Verb (s/s)"]
    rows = ledger.build(names, uad_ok={"UAD Teletronix LA-2A Silver"},
                        uad_all={"UAD Teletronix LA-2A Silver", "UAD 4K Buss Compressor"},
                        not_owned={"Melodyne"}, used={"Pro-Q 3", "Melodyne"}, presets=set(),
                        registered={"Massive"}, present={"Pro-R 2"})
    status = {name: row["status"] for name, row in rows.items()}
    assert status == {"UAD Teletronix LA-2A Silver (s/s)": "owned", "UAD 4K Buss Compressor (s/s)": "not_owned",
                      "Pro-Q 3 (s/s)": "owned", "Melodyne (s/s)": "not_owned", "Pro-R 2 (s/s)": "unknown",
                      "Massive (s/s)": "owned", "Mystery Verb (s/s)": "unknown"}
    assert rows["Pro-R 2 (s/s)"]["evidence"] == ["installed"]


def test_mark_records_a_scratch_test_result(tmp_path):
    path = tmp_path / "license_ledger.json"
    path.write_text(json.dumps({"Mystery Verb (s/s)": {"status": "unknown", "evidence": []}}))
    ledger.mark(path, "Mystery Verb (s/s)", "not_owned", "tried: license window")
    row = json.loads(path.read_text())["Mystery Verb (s/s)"]
    assert row == {"status": "not_owned", "evidence": ["tried: license window"]}


def test_logic_own_plugins_lead_the_list_and_count_as_owned():
    names = ["Channel EQ (s/s)", "ChromaGlow (s/s)", "UAD Neve 1073 (s/s)", "Mystery Verb (s/s)"]
    rows = ledger.build(names, set(), {"UAD Neve 1073"}, set(), set(), set(), set(), set())
    assert rows["Channel EQ (s/s)"] == {"status": "owned", "evidence": ["logic"]}
    assert rows["Mystery Verb (s/s)"]["status"] == "unknown"

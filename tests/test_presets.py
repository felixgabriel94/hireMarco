import pytest

from hiremarco import gate
from hiremarco.studio.commands import Command, understand
from hiremarco.studio.logic import Logic
from hiremarco.studio.presets import PresetError, list_presets, load, match

NAMES = ["000-ABUELO'S VOCAL CHAIN", "001-ACOUSTIC GUITAR NEW!", "002-MY CHAIN!", "003-JONATHAN ELECTRIC 2!",
         "004-BASS!", "005-ADLIB"]


@pytest.fixture
def folder(tmp_path):
    for n in NAMES:
        (tmp_path / f"{n}.cst").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("not a preset")
    return tmp_path


def test_presets_are_read_from_the_files(folder):
    assert list_presets(folder) == NAMES
    assert list_presets(folder / "missing") == []


@pytest.mark.parametrize("said, expected", [
    ("my chain", "002-MY CHAIN!"),
    ("my adlib preset", "005-ADLIB"),
    ("adlib", "005-ADLIB"),
    ("the bass preset", "004-BASS!"),
    ("preset 3", "003-JONATHAN ELECTRIC 2!"),
    ("abuelo's vocal chain", "000-ABUELO'S VOCAL CHAIN"),
    ("my harmony preset", None),
    ("", None),
])
def test_match_names_one_preset_or_none(said, expected):
    assert match(said, NAMES) == expected


def test_spoken_preset_skips_the_model():
    assert understand("Marco, use my adlib preset.", client=None) == Command("preset", text="my adlib preset")
    assert understand("Marco, give me my chain", client=None) == Command("preset", text="my chain")


def rules(tmp_path):
    p = tmp_path / "RULES.md"
    p.write_text("send: logic -> * ; Logic ; until 2099-01-01\n")
    return p


def test_logic_loads_the_matched_preset_through_the_gate(tmp_path, folder, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    loaded = []
    logic = Logic(conn=gate.connect(":memory:"), rules_path=rules(tmp_path), preset_dir=folder,
                  load_preset=lambda name: loaded.append(name) or "after: ok")
    assert logic.do(Command("preset", text="my adlib preset")) == "preset 005-ADLIB"
    assert loaded == ["005-ADLIB"]


def test_unknown_preset_is_refused_and_nothing_runs(tmp_path, folder, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    loaded = []
    logic = Logic(conn=gate.connect(":memory:"), rules_path=rules(tmp_path), preset_dir=folder,
                  load_preset=loaded.append)
    with pytest.raises(gate.Refused, match="no saved preset"):
        logic.do(Command("preset", text="my harmony preset"))
    assert loaded == []


def test_dry_run_plans_the_preset(folder):
    logic = Logic(dry_run=True, preset_dir=folder)
    assert logic.do(Command("preset", text="my chain")) == "dry run: preset 002-MY CHAIN!"


def test_load_reports_a_stop_as_an_error():
    with pytest.raises(PresetError, match="did not open"):
        load("005-ADLIB", run=lambda args: "before: x\nstopped: the Performance submenu did not open; menus closed")
    assert "after" in load("005-ADLIB", run=lambda args: "before: x\nafter: y")


def test_load_passes_the_scripts_and_name():
    seen = []
    load("002-MY CHAIN!", run=lambda args: seen.append(args) or "after: ok")
    script, helper, name = seen[0]
    assert script.endswith("load_preset.applescript") and helper.endswith("menu_open.js") and name == "002-MY CHAIN!"

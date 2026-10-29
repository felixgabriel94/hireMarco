import json
import math

import pytest

from hiremarco.studio.console import AUTO_TUNE, Console, ConsoleError

KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALES = ["CHROMATIC", "MINOR", "MAJOR", "DORIAN"]


class Engine:
    """A stand-in for the UA Mixer Engine: the paths, replies and value maps seen live on 2026-10-29."""

    def __init__(self):
        self.authorized = {"UAD Teletronix LA-2A Silver": True, "UAD Teletronix LA-2A Gray": True,
                           "UAD Teletronix LA-2A Legacy": True, AUTO_TUNE: True, "UAD Neve 1073": True,
                           "UAD Fairchild 670": False}
        self.slots = {0: "", 1: AUTO_TUNE, 2: "", 3: "", 4: ""}
        self.norm = {"Key": 0.0, "Scale": 0.0, "Retune Speed": 0.0096, "Flex-Tune": 0.19, "Humanize": 0.18,
                     "Natural Vibrato": 0.66}
        self.sent = []

    def shown(self, name):
        v = self.norm[name]
        if name == "Key":
            return KEYS[min(11, math.floor(v * 11))]
        if name == "Scale":
            return SCALES[min(len(SCALES) - 1, math.floor(v * (len(SCALES) - 1)))]
        if name == "Retune Speed":
            return f"{400 * v ** 1.5:.0f}"  # not linear, like the real control
        if name == "Natural Vibrato":
            return f"{(v - 0.5) * 24:.1f}"
        return f"{v * 100:.0f}"

    def slot_of(self, path):
        if "/preamps/0/effects/0" in path:
            return 0
        return int(path.split("/effects/")[1].split("/")[0]) + 1

    def __call__(self, command):
        self.sent.append(command)
        verb, rest = command.split(" ", 1)
        if verb == "get":
            return json.dumps({"path": rest, "data": self.get(rest)})
        path, value = rest.split(" ", 1) if " " in rest else (rest, "")
        return json.dumps(self.put(path, value))

    def get(self, path):
        names = list(self.norm)
        if path == "/plugins":
            return {"children": {str(i): {} for i in range(len(self.authorized))}}
        if path.startswith("/plugins/"):
            name = list(self.authorized)[int(path.rsplit("/", 1)[1])]
            return {"properties": {"Name": {"value": name}, "Authorized": {"value": self.authorized[name]}}}
        if path.endswith("/Name/value"):
            return "ANALOG 1"
        slot = self.slot_of(path)
        if path.endswith("/EffectName/value"):
            return self.slots[slot]
        if path.endswith("/parameters"):
            return {"children": {str(i): {} for i in range(len(names))}}
        if "/parameters/" in path:
            name = names[int(path.split("/parameters/")[1].split("/")[0])]
            if path.endswith("/StringValue/value"):
                return self.shown(name)
            return {"properties": {"Name": {"value": name}, "StringValue": {"value": self.shown(name)},
                                   "NormalizedValue": {"value": self.norm[name]}}}
        return {"properties": {"EffectName": {"value": self.slots[slot]}, "Power": {"value": bool(self.slots[slot])}}}

    def put(self, path, value):
        if path.endswith("/EffectName/value"):
            if value and value not in self.authorized:
                return {"path": path, "error": "Unable to set value.  Status = -3"}
            self.slots[self.slot_of(path)] = value
            return {"path": path, "data": value}
        if path.endswith("/StringValue/value"):
            return {"path": path, "error": "Unable to set value.  Status = -1"}
        name = list(self.norm)[int(path.split("/parameters/")[1].split("/")[0])]
        self.norm[name] = float(value)
        return {"path": path, "data": float(value)}


@pytest.fixture
def engine():
    return Engine()


@pytest.fixture
def console(engine):
    return Console(send=engine, settle=0)


def test_get_raises_on_an_engine_error():
    console = Console(send=lambda c: json.dumps({"path": "/x", "error": "Unable to resolve path for get."}), settle=0)
    with pytest.raises(ConsoleError, match="resolve"):
        console.get("/x")


def test_slots_list_unison_and_the_four_inserts(console):
    slots = console.slots(0)
    assert [s.number for s in slots] == [0, 1, 2, 3, 4]
    assert slots[1].name == AUTO_TUNE and slots[1].power and not slots[2].power


def test_find_plugin_matches_words_and_skips_legacy_and_unauthorized(console):
    assert console.find_plugin("la-2a silver") == "UAD Teletronix LA-2A Silver"
    assert console.find_plugin("neve 1073") == "UAD Neve 1073"
    with pytest.raises(ConsoleError, match="matches 3"):
        console.find_plugin("la-2a")
    with pytest.raises(ConsoleError, match="no authorized"):
        console.find_plugin("fairchild")


def test_load_writes_the_full_name_and_reads_it_back(console, engine):
    assert console.load(0, 2, "LA-2A Silver") == "UAD Teletronix LA-2A Silver"
    assert engine.slots[2] == "UAD Teletronix LA-2A Silver"
    assert any(c == "set /devices/0/inputs/0/effects/1/EffectName/value UAD Teletronix LA-2A Silver"
               for c in engine.sent)


def test_unison_slot_is_the_preamp_path(console, engine):
    console.load(0, 0, "neve 1073")
    assert engine.slots[0] == "UAD Neve 1073"
    assert any("/preamps/0/effects/0/EffectName" in c for c in engine.sent)


def test_unload_empties_the_slot(console, engine):
    engine.slots[3] = "UAD Neve 1073"
    console.unload(0, 3)
    assert engine.slots[3] == ""


def test_slot_out_of_range_is_refused(console):
    with pytest.raises(ConsoleError, match="1 to 4"):
        console.load(0, 5, "la-2a silver")


def test_set_param_finds_a_key_by_its_band(console, engine):
    for key in ("E", "C", "B", "A#"):
        assert console.set_param(0, 1, "Key", key) == key
        assert engine.shown("Key") == key


def test_set_param_bisects_a_curved_numeric_control(console, engine):
    shown = console.set_param(0, 1, "Retune Speed", 40)
    assert abs(float(shown) - 40) <= 1
    assert console.set_param(0, 1, "Natural Vibrato", 0) in ("0.0", "-0.0")


def test_set_param_refuses_unknown_controls_and_out_of_range(console):
    with pytest.raises(ConsoleError, match="no control"):
        console.set_param(0, 1, "Formant", 3)
    with pytest.raises(ConsoleError, match="outside"):
        console.set_param(0, 1, "Retune Speed", 900)
    with pytest.raises(ConsoleError, match="never showed"):
        console.set_param(0, 1, "Key", "H")


def test_tune_finds_auto_tune_and_sets_the_gentle_base(console, engine):
    done = console.tune(0, "e", "minor")
    assert done["Key"] == "E" and done["Scale"] == "MINOR"
    assert abs(float(done["Retune Speed"]) - 40) <= 1
    assert done["Flex-Tune"] == "30" and done["Humanize"] == "15"


def test_tune_without_auto_tune_says_so(console, engine):
    engine.slots[1] = ""
    with pytest.raises(ConsoleError, match="no UAD Auto-Tune"):
        console.tune(0, "E", "minor")


def test_a_control_blank_at_its_ends_is_still_bisected(console, engine):
    real = engine.shown

    def blank_ends(name):
        v = engine.norm[name]
        return "" if name == "Retune Speed" and v in (0.0, 1.0) else real(name)

    engine.shown = blank_ends
    assert abs(float(console.set_param(0, 1, "Retune Speed", 40)) - 40) <= 1


def test_may_run_judges_uad_names_by_console_and_leaves_others_alone(engine, console):
    engine.authorized["UAD Neve 1084"] = False
    assert console.may_run("UAD Teletronix LA-2A Silver (s/s)")
    assert not console.may_run("UAD Fairchild 670 (s/s)")
    assert not console.may_run("UAD Neve 1084 (s/s)")
    assert console.may_run("Pro-Q 3 (s/s)") and console.may_run("CLA-76 (s) (s/s)")

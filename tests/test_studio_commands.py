import json

import httpx
import pytest

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.studio.commands import Command, fast_match, strip_wake, understand
from hiremarco.studio.logic import Knobs, Logic, plan


def model_says(payload, tmp_path, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "muse-spark-1.3",
            "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 20},
        })

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def full(**over):
    base = {"action": "unknown", "section": "", "bar": 0, "track": "", "knob": "", "direction": "", "steps": 0, "text": ""}
    base.update(over)
    return base


def test_wake_word():
    assert strip_wake("Marco, record.") == "record"
    assert strip_wake("hey Marco: more reverb!") == "more reverb"
    assert strip_wake("record") is None
    assert strip_wake("I told Marcos about it") is None


def test_fast_path_needs_no_model(tmp_path):
    def boom(request):
        raise AssertionError("no model call expected")

    client = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(boom))
    assert understand("Marco, record.", client) == Command("record")
    assert understand("Marco, new track", client) == Command("new_track")
    assert fast_match("from the top") == Command("go_to_start")
    assert understand("just talking to myself", client) is None


def test_model_maps_knob_with_bounds(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    seen = []
    cmd = understand("Marco, tighten the auto-tune a lot", model_says(full(action="knob", knob="tuning", direction="up", steps=9), tmp_path, seen))
    assert cmd == Command("knob", knob="tuning", direction="up", steps=3)
    assert cmd.describe() == "tuning +3 steps"
    assert seen[0]["reasoning_effort"] == "minimal" and seen[0]["response_format"]["type"] == "json_schema"


def test_model_off_list_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    assert understand("Marco, delete everything", model_says(full(action="delete_all"), tmp_path)) == Command("unknown")
    assert understand("Marco, more chorus effect", model_says(full(action="knob", knob="chorus", direction="up", steps=1), tmp_path)) == Command("unknown")


def test_punch_plan_uses_locators_and_pre_roll():
    presses = plan(Command("punch", bar=5, track="second harmony")).presses
    typed = [p.then_type for p in presses if p.then_type]
    assert typed == ["5 1 1 1", "6 1 1 1", "4 1 1 1"]
    assert presses[-1].key == "r" and presses[-1].modifiers == ()


def test_section_needs_a_marker(tmp_path, monkeypatch):
    markers = tmp_path / "markers.json"
    markers.write_text(json.dumps({"Chorus": 33}))
    monkeypatch.setenv("HIREMARCO_MARKERS", str(markers))
    assert plan(Command("go_to_section", section="chorus")).presses[0].then_type == "33 1 1 1"
    with pytest.raises(gate.Refused, match="no marker"):
        plan(Command("go_to_section", section="bridge"))


def test_dry_run_touches_nothing():
    logic = Logic(dry_run=True, run_script=lambda s: pytest.fail("no script in a dry run"))
    assert logic.do(Command("new_track")) == "dry run: new track"
    assert 'keystroke "a" using {option down, command down}' in logic.planned[0]


def test_live_run_passes_the_gate_and_sends(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    rules_path = tmp_path / "RULES.md"
    rules_path.write_text("(none)\n")
    scripts, midi = [], []
    knobs = Knobs(send=lambda cc, v: midi.append((cc, v)), state_path=tmp_path / "knobs.json")
    logic = Logic(conn=gate.connect(":memory:"), run_script=scripts.append, knobs=knobs, rules_path=rules_path)
    with pytest.raises(gate.Refused, match="no send switch for logic"):
        logic.do(Command("record"))
    rules_path.write_text("send: logic -> * ; the session ; until 2099-01-01\n")
    assert logic.do(Command("record")) == "record"
    assert logic.do(Command("record")) == "record"  # repeating record is fine
    assert logic.do(Command("knob", knob="reverb", direction="up", steps=1)) == "reverb +1 step (72)"
    assert midi == [(21, 72)] and len(scripts) == 2
    assert 'tell application "Logic Pro" to activate' in scripts[0]


def test_knobs_stay_in_range(tmp_path):
    sent = []
    k = Knobs(send=lambda cc, v: sent.append(v), state_path=tmp_path / "k.json")
    for _ in range(20):
        k.move("delay", "up", 3)
    assert sent[-1] == 100
    assert Knobs(send=lambda c, v: None, state_path=tmp_path / "k.json").values["delay"] == 100


@pytest.mark.parametrize("line, knob, percent", [
    ("Marco, reverb at 60%", "reverb", 60),
    ("Marco, set the delay to twenty percent", "delay", 20),
    ("Marco, 100 percent reverb", "reverb", 100),
    ("Marco, put the verb at sixty five percent", "reverb", 65),
    ("Marco, tuning to 0%", "tuning", 0),
])
def test_exact_knob_settings_skip_the_model(line, knob, percent):
    assert understand(line, client=None) == Command("knob", knob=knob, direction="set", percent=percent)


def test_exact_setting_maps_percent_to_the_full_cc_range(tmp_path):
    from hiremarco.studio.logic import Knobs

    sent = []
    knobs = Knobs(send=lambda cc, value: sent.append((cc, value)), state_path=tmp_path / "k.json")
    assert knobs.move("reverb", "set", 100) == 127  # an exact ask passes the soft step range
    assert knobs.move("reverb", "set", 60) == 76
    assert knobs.move("reverb", "up", 1) == 84       # steps continue from the exact setting
    assert sent == [(21, 127), (21, 76), (21, 84)]
    assert Command("knob", knob="reverb", direction="set", percent=60).describe() == "reverb to 60%"


def test_a_doubled_wake_word_is_stripped():
    assert understand("Marco, Marco, we're on a harmony.", client=None) == Command("label_track", text="harmony")
    assert understand("Marco,Marco, record.", client=None) == Command("record")
    assert understand("hey Marco, Marco, stop", client=None) == Command("stop")


@pytest.mark.parametrize("line, knob, direction, steps", [
    ("Marco, more verb", "reverb", "up", 1),
    ("Marco, less delay", "delay", "down", 1),
    ("Marco, a lot more reverb", "reverb", "up", 3),
    ("Marco, turn up the tune", "tuning", "up", 1),
    ("Marco, bring down the verb a bit", "reverb", "down", 1),
])
def test_knob_steps_skip_the_model(line, knob, direction, steps):
    assert understand(line, client=None) == Command("knob", knob=knob, direction=direction, steps=steps)


def test_a_doubled_word_is_heard_once():
    assert understand("Marco, new track track for harmonies.", client=None) == Command("new_track", text="harmony")


def test_track_names_read_as_a_header_would():
    from hiremarco.studio.booth import track_title

    assert track_title("harmony one") == "Harmony 1" and track_title("lead vox") == "Lead Vox"
    assert track_title("AdLib two") == "AdLib 2"


def test_conversation_is_answered_from_what_happened_and_nothing_is_done():
    from hiremarco.studio.booth import Booth, Tape

    seen = []

    def hears(line):
        if "did you rename" in line.lower():
            seen.append(list(b.history))
            return Command("chat", text="Not yet. The track's there, I didn't name it. Want Harmony 1?")
        return understand(line, client=None)

    said, did = [], []
    b = Booth(understand=hears, logic=lambda c: did.append(c) or c.describe(), say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None)
    b.hear("Marco, new track")
    b.hear("Marco, did you rename it?")
    assert said[-1].startswith("Not yet") and did == [Command("new_track")]  # talking performs nothing
    assert "new track" in seen[0][-1] and "artist: Marco, new track" in seen[0][-1]


def test_a_new_track_for_a_role_is_found_inside_a_longer_line():
    assert understand("Marco, correct, the new track for harmonies.", client=None) == Command("new_track", text="harmony")


@pytest.mark.parametrize("line", ["Marco, create a new track.", "Marco, open a new track", "Marco, make a new track",
                                  "Marco, new track", "Marco, add a new track please", "Marco, another track"])
def test_create_a_new_track_skips_the_model(line):
    assert understand(line, client=None) == Command("new_track")


@pytest.mark.parametrize("line", ["Marco, duplicate this track.", "Marco, duplicate the track", "Marco, duplicate it",
                                  "Marco, can you duplicate this track"])
def test_duplicate_this_track_is_not_a_new_track(line):
    assert understand(line, client=None) == Command("duplicate_track")


def test_duplicate_presses_new_track_with_duplicate_setting():
    keys = [(p.key, p.modifiers) for p in plan(Command("duplicate_track")).presses]
    assert keys == [("d", ("command",)), ("r", ("control",))]


def _performances(tmp_path):
    folder = tmp_path / "Performance"
    folder.mkdir()
    for name in ("002-MY CHAIN!", "005-MY CHAIN CONSOLE!"):
        (folder / f"{name}.cst").write_text("")
    return folder


def test_a_new_track_starts_on_my_chain_console(tmp_path, monkeypatch):
    import hiremarco.studio.logic as logic_mod

    monkeypatch.setattr(logic_mod, "NEW_TRACK_SETTLE", 0)
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    rules_path = tmp_path / "RULES.md"
    rules_path.write_text("send: logic -> * ; the session ; until 2099-01-01\n")
    scripts, loaded = [], []
    logic = Logic(conn=gate.connect(":memory:"), run_script=scripts.append, rules_path=rules_path,
                  preset_dir=_performances(tmp_path), load_preset=loaded.append)
    assert logic.do(Command("new_track")) == "new track with 005-MY CHAIN CONSOLE!"
    assert loaded == ["005-MY CHAIN CONSOLE!"]  # never 002-MY CHAIN!
    assert logic.do(Command("duplicate_track")) == "duplicate this track"
    assert loaded == ["005-MY CHAIN CONSOLE!"]  # a duplicate keeps the chain it copied
    (tmp_path / "d").mkdir()
    dry = Logic(dry_run=True, preset_dir=_performances(tmp_path / "d"))
    assert dry.do(Command("new_track")) == "dry run: new track with 005-MY CHAIN CONSOLE!"


def test_a_new_track_is_made_even_when_the_chain_will_not_load(tmp_path, monkeypatch):
    import hiremarco.studio.logic as logic_mod

    monkeypatch.setattr(logic_mod, "NEW_TRACK_SETTLE", 0)
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    rules_path = tmp_path / "RULES.md"
    rules_path.write_text("send: logic -> * ; the session ; until 2099-01-01\n")

    def broken(name):
        raise RuntimeError("menu did not open")

    logic = Logic(conn=gate.connect(":memory:"), run_script=lambda s: None, rules_path=rules_path,
                  preset_dir=_performances(tmp_path), load_preset=broken)
    assert "did not load" in logic.do(Command("new_track"))
    empty = tmp_path / "none"
    empty.mkdir()
    logic = Logic(conn=gate.connect(":memory:"), run_script=lambda s: None, rules_path=rules_path, preset_dir=empty)
    assert logic.do(Command("new_track")) == "new track (no 'my chain console' preset saved)"

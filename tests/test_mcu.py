import mido

from hiremarco.studio import mcu
from hiremarco.studio.mcu import HEADER, Screen, Surface, handshake_reply


def lcd(offset, text):
    return mido.Message("sysex", data=HEADER + [0x12, offset] + list(text.encode()))


def test_screen_writes_at_offsets_and_splits_strips():
    screen = Screen()
    screen.write(0, "ins117 Inst 1 OS_6x_")
    screen.write(56, "--     UADA-T")
    top, bottom = screen.lines
    assert top.startswith("ins117 Inst 1 OS_6x_") and len(top) == 56
    assert screen.strip(1) == ("Inst 1", "UADA-T")


def test_handshake_answers_device_query_and_version_only():
    assert handshake_reply(HEADER + [0x00])[:5] == HEADER + [0x01]
    assert handshake_reply(HEADER + [0x13]) == HEADER + [0x14] + list(b"V1.02")
    assert handshake_reply(HEADER + [0x0A, 0x01]) is None
    assert handshake_reply([0x00, 0x00, 0x66, 0x15, 0x00]) is None  # an extender query is not ours


def test_receive_updates_the_screen_and_answers_the_query():
    sent = []
    surface = Surface(send=sent.append)
    surface.receive(lcd(56, "--     Pro-Q3"))
    surface.receive(mido.Message("sysex", data=HEADER + [0x00]))
    assert surface.screen.strip(1)[1] == "Pro-Q3" and surface.version == 1
    assert sent and list(sent[0].data)[4] == 0x01


def test_press_and_turn_send_the_mackie_messages():
    sent = []
    surface = Surface(send=sent.append)
    surface.press("vpot", 1, hold=0)
    surface.turn(2, -3)
    assert [(m.type, m.note, m.velocity) for m in sent[:2]] == [("note_on", 0x21, 0x7F), ("note_on", 0x21, 0)]
    assert (sent[2].control, sent[2].value) == (0x12, 0x43)


class FakeLogic:
    """Answers V-Pot turns on strip 1 by moving through a plug-in list, swallowing every third click like Logic."""

    def __init__(self, names):
        self.names, self.at, self.clicks = ["--", *names], 0, 0
        self.surface = Surface(send=self.hear)

    def hear(self, message):
        if message.type != "control_change":
            return
        clicks = message.value & 0x3F
        self.clicks += 1
        if message.value & 0x40:
            self.at = max(0, self.at - clicks)
        elif self.clicks % 3:
            self.at = min(len(self.names) - 1, self.at + clicks)
        self.surface.receive(lcd(56 + 7, self.names[self.at].ljust(49)))


def test_seek_steps_past_swallowed_clicks_and_stops_on_the_name(monkeypatch):
    monkeypatch.setattr(mcu.time, "sleep", lambda s: None)
    logic = FakeLogic(["Parametric EQ (s/s)", "Low Pass Filter (s/s)", "UAD Teletronix LA-2A Silver (s/s)"])
    assert mcu.seek(logic.surface, 1, "uad teletronix la-2a silver") == "UAD Teletronix LA-2A Silver (s/s)"


def test_seek_reports_a_name_logic_does_not_have(monkeypatch):
    monkeypatch.setattr(mcu.time, "sleep", lambda s: None)
    logic = FakeLogic(["Parametric EQ (s/s)"])
    try:
        mcu.seek(logic.surface, 1, "Melodyne")
    except LookupError as missing:
        assert "Melodyne" in str(missing)
    else:
        raise AssertionError("seek found a plug-in that is not there")


class JumpyLogic(FakeLogic):
    """Moves a turn of n clicks by about two thirds of n, like Logic's V-Pot acceleration (live 2026-10-29)."""

    def hear(self, message):
        if message.type != "control_change":
            return
        clicks = message.value & 0x3F
        moved = clicks if clicks <= 2 else max(1, round(clicks * 0.66))
        self.at += -moved if message.value & 0x40 else moved
        self.at = max(0, min(len(self.names) - 1, self.at))
        self.surface.receive(lcd(56 + 7, self.names[self.at].ljust(49)))


def test_pick_prefers_exact_then_stereo_current_versions():
    names = ["CLA-76 (m) (s/s)", "CLA-76 (s) (s/s)", "UAD Neve 1073 Legacy (s/s)", "UAD Neve 1073 (s/s)", "Pro-Q 3 (s/s)"]
    assert names[mcu.pick(names, "neve 1073")] == "UAD Neve 1073 (s/s)"
    assert names[mcu.pick(names, "cla-76")] == "CLA-76 (s) (s/s)"
    assert names[mcu.pick(names, "Pro-Q 3")] == "Pro-Q 3 (s/s)"


def test_jump_converges_despite_uneven_turns(monkeypatch):
    monkeypatch.setattr(mcu.time, "sleep", lambda s: None)
    names = [f"Plug {i:04d} (s/s)" for i in range(1200)]
    logic = JumpyLogic(names)
    assert mcu.jump(logic.surface, 1, names, "Plug 1039 (s/s)") == "Plug 1039 (s/s)"
    assert mcu.jump(logic.surface, 1, names, "Plug 0234 (s/s)") == "Plug 0234 (s/s)"


def test_jump_learns_a_name_the_index_missed(monkeypatch):
    monkeypatch.setattr(mcu.time, "sleep", lambda s: None)
    real = [f"Plug {i:04d} (s/s)" for i in range(300)]
    logic = JumpyLogic(real)
    index = [n for n in real if n != "Plug 0150 (s/s)"]
    logic.at = 151  # the display sits on the missing name ("--" is entry 0)
    logic.surface.receive(lcd(56 + 7, "Plug 0150 (s/s)".ljust(49)))
    assert mcu.jump(logic.surface, 1, index, "Plug 0200 (s/s)") == "Plug 0200 (s/s)"
    assert index == real


def test_mode_display_gives_the_insert_slot():
    surface = Surface(send=lambda m: None)
    for control, value in ((0x4B, 0x10), (0x4A, 0x32)):  # "P", "2"
        surface.receive(mido.Message("control_change", control=control, value=value))
    assert surface.mode == ["P", "2"] and mcu.slot_now(surface) == 2
    surface.receive(mido.Message("control_change", control=0x4A, value=0x0E))  # "N": Pan mode, "PN"
    assert mcu.slot_now(surface) is None


def test_strip_of_matches_logic_short_names_inside_the_full_name():
    surface = Surface(send=lambda m: None)
    surface.screen.write(0, "ins117 Inst 1 OS_6x_ St Out Master ")
    assert mcu.strip_of(surface, "OS_6ix_149_vocal_remnants_Em") == 2
    assert mcu.strip_of(surface, "instrumental 117") == 0
    assert mcu.strip_of(surface, "3") == 3


def test_bundles_lists_audio_units(tmp_path):
    (tmp_path / "Pro-R 2.component").mkdir()
    (tmp_path / "notes.txt").write_text("")
    assert mcu.bundles([str(tmp_path)]) == {"Pro-R 2.component"}


def make_learner(tmp_path, installed, found):
    import threading

    index = tmp_path / "logic_plugins.json"
    index.with_name("plugin_bundles.json").write_text('["Old.component"]')
    surface = Surface(send=lambda m: None)
    calls = []

    def fake_relearn(surface, path):
        calls.append(path)
        return list(found)

    learner = mcu.Learner(surface, threading.Lock(), index, relearn=fake_relearn, bundles=lambda: set(installed))
    learner.later = lambda seconds: learner.learn()  # run at once instead of after the settle delay
    surface.on_hello = lambda: learner.later(0)
    surface.on_idle = lambda: learner.later(0)
    return learner, surface, calls


def test_nothing_happens_until_a_plugin_is_installed(tmp_path):
    learner, surface, calls = make_learner(tmp_path, {"Old.component"}, [])
    learner.changed()
    assert calls == [] and not learner.pending


def test_a_new_bundle_is_learned_once(tmp_path):
    import json

    learner, surface, calls = make_learner(tmp_path, {"Old.component", "Pro-R 2.component"}, ["Pro-R 2 (s/s)"])
    learner.changed()
    learner.changed()
    assert len(calls) == 1 and not learner.pending
    assert json.loads((tmp_path / "learned_plugins.json").read_text())["new"] == ["Pro-R 2 (s/s)"]
    assert "Pro-R 2.component" in json.loads((tmp_path / "plugin_bundles.json").read_text())


def test_learning_waits_for_the_take_to_end(tmp_path):
    learner, surface, calls = make_learner(tmp_path, {"Old.component", "New.component"}, ["New (s/s)"])
    surface.receive(mido.Message("note_on", note=mcu.NOTE["record"], velocity=0x7F))
    learner.changed()
    assert calls == []
    surface.receive(mido.Message("note_on", note=mcu.NOTE["record"], velocity=0))
    assert len(calls) == 1 and not learner.pending


def test_a_plugin_logic_has_not_validated_waits_for_logic_to_launch(tmp_path):
    learner, surface, calls = make_learner(tmp_path, {"Old.component", "New.component"}, [])
    learner.changed()
    assert len(calls) == 1 and learner.pending == {"New.component"}
    learner._relearn = lambda s, p: calls.append(p) or ["New (s/s)"]
    surface.receive(mido.Message("sysex", data=HEADER + [0x00]))  # Logic launched and queried the surface
    assert len(calls) == 2 and not learner.pending


def test_insert_refuses_an_unauthorized_uad_plugin_before_touching_logic():
    sent = []
    surface = Surface(send=sent.append)
    names = ["UAD 4K Buss Compressor (s/s)", "Pro-Q 3 (s/s)"]
    try:
        mcu.insert(surface, names, "1", 3, "4k buss", may_run=lambda name: not name.startswith("UAD"))
    except LookupError as refused:
        assert "not authorized" in str(refused)
    else:
        raise AssertionError("inserted an unauthorized plug-in")
    assert sent == []


def test_best_tries_an_unknown_on_scratch_and_falls_back_when_it_hits_a_wall(tmp_path, monkeypatch):
    import json

    from hiremarco.studio import ledger

    names = ["Pro-DS (s/s)", "UAD Precision De-Esser (s/s)", "DeEsser 2 (s/s)"]
    book = tmp_path / "license_ledger.json"
    rows = {"UAD Precision De-Esser (s/s)": {"status": "owned", "evidence": ["console"]}}
    book.write_text(json.dumps(rows))
    inserted, trials = [], []

    def fake_trial(surface, names, track, slot, name, windows=None, settle=0):
        trials.append((track, slot, name))
        return "Logic Pro: Pro-DS license"

    monkeypatch.setattr(mcu, "trial", fake_trial)
    monkeypatch.setattr(mcu, "insert", lambda s, n, track, slot, name, replace=False, may_run=None:
                        inserted.append((track, slot, name)) or f"{name} in insert {slot}")
    done = mcu.best(Surface(send=lambda m: None), names, rows, book, "de-esser", "vocal", 9, "scratch")
    assert trials == [("scratch", 15, "Pro-DS (s/s)")]
    assert inserted == [("vocal", 9, "UAD Precision De-Esser (s/s)")]
    assert "skipped Pro-DS" in done
    assert json.loads(book.read_text())["Pro-DS (s/s)"]["status"] == "not_owned"
    assert ledger.read_ledger(book)["Pro-DS (s/s)"]["evidence"] == ["tried: Logic Pro: Pro-DS license"]


def test_the_selected_strip_is_the_lit_select_button():
    surface = Surface(send=lambda m: None)
    try:
        mcu.strip_of(surface, "selected")
    except LookupError as none:
        assert "no single track" in str(none)
    else:
        raise AssertionError("named a strip with nothing selected")
    surface.receive(mido.Message("note_on", note=mcu.NOTE["select"] + 2, velocity=0x7F))
    assert mcu.strip_of(surface, "selected") == 2


def test_first_empty_reads_slot_by_slot(monkeypatch):
    surface = Surface(send=lambda m: None)
    filled = {1: "ProQ3", 2: "CLA76", 3: "--"}
    at = {"slot": 0}

    def go(s, slot):
        at["slot"] = slot
        s.screen.write(56, f"{filled.get(slot, '--'):<7}")

    monkeypatch.setattr(mcu, "go_slot", go)
    assert mcu.first_empty(surface, 0) == 3


def test_meters_are_not_logged():
    lines = []
    surface = Surface(send=lambda m: None, log=lines.append)
    surface.receive(mido.Message("aftertouch", channel=0, value=35))
    assert lines == []


def test_to_empty_keeps_turning_until_the_empty_choice_shows(monkeypatch):
    surface = Surface(send=lambda m: None)
    turns = {"n": 0}
    monkeypatch.setattr(mcu.time, "sleep", lambda s: None)

    def turn(strip, clicks):
        turns["n"] += 1
        surface.screen.write(56 + 7 * strip, "--     " if turns["n"] >= 35 else "UADOcW ")

    surface.turn = turn
    mcu.to_empty(surface, 2)
    assert turns["n"] == 40 and mcu.slot_text(surface.screen, 2).startswith("--")  # twenty turns stopped short


def test_send_steps_the_destination_to_the_bus_and_confirms(monkeypatch):
    sent = []
    surface = Surface(send=sent.append)
    monkeypatch.setattr(mcu.time, "sleep", lambda s: None)
    monkeypatch.setattr(mcu, "mixer_view", lambda s: None)
    monkeypatch.setattr(mcu, "send_mode_slot", lambda s, n: None)
    surface.screen.write(0, "ins117 Inst 1  OS_6x_ St Out Master ")
    choices = ["--", "Output 1", "Output 2", "Bus 1", "Bus 2"]
    at = {"i": 0}

    def turn(strip, clicks):
        at["i"] = max(0, min(len(choices) - 1, at["i"] + (1 if clicks > 0 else -1)))
        surface.screen.write(56 + 7 * strip, f"{choices[at['i']]:<7}")
        surface.version += 1

    surface.turn = turn
    surface.screen.write(56 + 14, "--     ")
    assert mcu.send(surface, "2", 2, 2) == "send 2 to Bus 2"
    assert sent[-2].type == "note_on" and sent[-2].note == mcu.NOTE["vpot"] + 2   # the press that confirms


def test_send_level_reads_back_the_db():
    from hiremarco.studio.tracks import Tracks

    tracks = Tracks(run=lambda args: "send\tBus 1\t-15.0", conn=__import__("sqlite3").connect(":memory:"))
    tracks._gated = lambda run, capability, message: run()
    assert tracks.send_level("Lead", "Bus 1", -15) == "Lead send to Bus 1 -15 dB"

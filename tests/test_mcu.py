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

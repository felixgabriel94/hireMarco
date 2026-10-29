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

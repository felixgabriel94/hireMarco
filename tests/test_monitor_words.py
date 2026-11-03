"""The Owner's word on the speakers reaches the monitor before the brain, and nothing of it reaches Marco Live."""

from hiremarco import events, server
from hiremarco.studio import monitor


class FakeWA:
    def __init__(self):
        self.sent, self.conn = [], None

    def send_text(self, to, body, **kw):
        events.emit("message_sent", source="marco", status="ok", via="WhatsApp", text=body)   # as the real one does
        self.sent.append((to, body, kw.get("idempotency_key")))
        return "wamid"


class Hand:
    def __init__(self):
        self.fading, self.asked = False, []

    def answer(self, request, reply):
        self.asked.append(request)
        reply("Down to -58.")
        return "fading -55 to -58"


def test_other_words_are_not_taken(monkeypatch):
    monkeypatch.setattr(server, "remember", lambda *a, **k: None)
    assert server.monitor_words("set up my session", "1555", "m1", FakeWA(), hand=Hand()) is None


def test_lower_it_moves_the_monitor_replies_and_stays_off_the_stream(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "path", lambda: tmp_path / "events.jsonl")
    monkeypatch.setattr(server, "remember", lambda *a, **k: None)
    server._MONITOR_SEEN.clear()
    wa, hand = FakeWA(), Hand()
    assert server.monitor_words("lower it", "1555", "m2", wa, hand=hand) == "monitor: fading -55 to -58"
    assert hand.asked == [monitor.Request("step", -3.0)]
    assert wa.sent == [("1555", "Down to -58.", "monitor:m2")]
    assert not (tmp_path / "events.jsonl").exists()                      # nothing on Marco Live
    assert server.monitor_words("lower it", "1555", "m2", wa, hand=hand).endswith("(already handled)")
    assert len(hand.asked) == 1


def test_an_aside_keeps_an_event_off_the_stream_and_ends_with_the_block(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "path", lambda: tmp_path / "events.jsonl")
    with events.aside():
        assert events.in_aside()
        events.emit("message_sent", source="marco", status="ok", via="WhatsApp", text="Down to -58.")
    assert not events.in_aside()
    assert not (tmp_path / "events.jsonl").exists()
    events.emit("message_sent", source="marco", status="ok", via="WhatsApp", text="Calling now.")
    assert (tmp_path / "events.jsonl").read_text().count("\n") == 1

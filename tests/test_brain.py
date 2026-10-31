"""Marco's judgment on WhatsApp (Owner 2026-10-30): every text goes to his brain with the studio's state and the
conversation, he picks the action, the code carries it out and tells the truth."""

import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest

from hiremarco.meta.client import Reply
from hiremarco.studio.beat_in import (BeatLoader, LoadError, keep_received, last_setup, pending, record_setup,
                                      requested_name, sidecar)
from hiremarco.whatsapp.memory import recall, remember
from tests.test_beat_in import FakeLogic, inbound, loader, whatsapp_line


class Brain:
    """A brain that answers with one fixed decision and keeps what it was shown."""

    def __init__(self, action="reply", title="", reply="ok."):
        self.decision = {"action": action, "title": title, "reply": reply}
        self.seen = []

    def converse(self, history, text, **kw):
        self.seen.append({"history": history, "text": json.loads(text), **kw})
        return Reply(text=json.dumps(self.decision), model="m", prompt_tokens=0, completion_tokens=0,
                     cached_tokens=0, cost_usd=0.0, duration_ms=0)


def failed_beat(inbox):
    """The live state at 10:17 pm on 2026-10-30: the beat started, its setup failed, it waits in the inbox."""
    inbox.mkdir(parents=True, exist_ok=True)
    beat = inbox / "aguacero [INST] 99 bpm.wav"
    beat.write_bytes(b"RIFF")
    os.utime(beat, (1_000_000, 1_000_000))
    record_setup(beat.stem, "beat not loaded: LoadError: Logic did not show the session within 180 s", inbox)
    return beat


def test_live_2026_10_30_try_again_retries_and_is_never_a_title(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    inbox = tmp_path / "inbox"
    beat = failed_beat(inbox)
    brain = Brain("retry", reply="on it, trying again.")
    line = handle(inbound(wa, "w1", kind="text", text="Try again"), wa=wa, inbox=inbox, marco=brain)
    assert "brain: retry; retrying aguacero [INST] 99 bpm.wav" in line
    assert requested_name(beat) is None                                   # not named "try again"
    assert beat.stat().st_mtime > 1_000_000                               # touched: the booth takes it again
    assert b"on it, trying again." in sent[-1]
    shown = brain.seen[-1]["text"]
    assert shown["felix_says"] == "Try again"
    assert shown["studio"]["beat_waiting_for_the_booth"]["file"] == beat.name
    assert "did not show the session" in shown["studio"]["last_setup_attempt"]["result"]


def test_live_2026_10_30_a_no_is_answered_with_what_he_said_before(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    inbox = tmp_path / "inbox"
    beat = failed_beat(inbox)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    remember(wa.conn, "felix", "the hook needs more space", ts=yesterday)
    remember(wa.conn, "marco", "noted, I'll leave room after the chorus.", ts=yesterday)
    brain = Brain("reply", reply="okay, I won't rename it. want me to try the setup again?")
    line = handle(inbound(wa, "w1", kind="text", text="No"), wa=wa, inbox=inbox, marco=brain)
    assert "brain: reply; replied" in line and requested_name(beat) is None
    history = brain.seen[-1]["history"]
    assert history[0]["role"] == "user" and history[0]["content"].endswith("the hook needs more space")
    assert history[1]["role"] == "assistant" and "leave room after the chorus" in history[1]["content"]
    # both sides of today are kept for tomorrow
    said = [(who, text) for _, who, text in recall(wa.conn)]
    assert said[-2:] == [("felix", "No"), ("marco", "okay, i won't rename it. want me to try the setup again?")]


def test_the_brain_cannot_claim_a_start_with_no_beat(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    line = handle(inbound(wa, "w1", kind="text", text="set it up"), wa=wa, inbox=tmp_path / "inbox",
                  marco=Brain("start", reply="on it."))
    assert "no beat to start" in line and b"i don't have a beat waiting" in sent[-1]


def test_a_title_before_start_is_kept_for_the_session(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    inbox = tmp_path / "inbox"
    keep_received(b"x", "beat.wav", inbox)
    handle(inbound(wa, "w1", kind="text", text="call it Night Shift"), wa=wa, inbox=inbox,
           marco=Brain("rename", title="Night Shift", reply="got it, night shift."))
    line = handle(inbound(wa, "w2", kind="text", text="go"), wa=wa, inbox=inbox, marco=Brain("start", reply="on it."))
    assert "session started for beat.wav as 'night shift'" in line
    assert requested_name(inbox / "beat.wav") == "night shift"
    assert not sidecar(inbox / "received" / "beat.wav").exists()


def test_cancel_puts_the_beat_back_never_deletes_it(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    inbox = tmp_path / "inbox"
    beat = failed_beat(inbox)
    line = handle(inbound(wa, "w1", kind="text", text="forget that beat"), wa=wa, inbox=inbox,
                  marco=Brain("cancel", reply="okay, holding it."))
    assert "back in received" in line and pending(inbox) == []
    assert (inbox / "received" / beat.name).read_bytes() == b"RIFF"


def test_an_off_schema_brain_falls_back_to_the_patterns(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    brain = Brain()
    brain.decision = {"action": "dance", "title": "", "reply": "x"}
    line = handle(inbound(wa, "w1", kind="text", text="set it up"), wa=wa, inbox=tmp_path / "inbox", marco=brain)
    assert "brain unavailable: ValueError" in line and "none is waiting" in line


def test_the_booth_tries_a_failed_beat_again_once_it_is_touched(tmp_path):
    from hiremarco.studio.beat_in import Inbox
    from hiremarco.studio.booth import watch_inbox

    beat = failed_beat(tmp_path)
    tries = []

    class FakeBooth:
        def log(self, line):
            pass

        def beat_arrived(self, path, name=None):
            tries.append(path.name)
            return "beat not loaded: LoadError" if len(tries) == 1 else "loaded"

    box = Inbox(tmp_path)
    watch_inbox(FakeBooth(), box, rounds=4, sleep=lambda s: None)
    assert tries == [beat.name] and last_setup(tmp_path)["result"] == "beat not loaded: LoadError"
    os.utime(beat)
    watch_inbox(FakeBooth(), box, rounds=3, sleep=lambda s: None)
    assert tries == [beat.name, beat.name] and last_setup(tmp_path)["result"] == "loaded"


def test_an_unnamed_song_asking_to_be_saved_stops_the_setup_at_once(tmp_path):
    beat = tmp_path / "beat.wav"
    beat.write_bytes(b"RIFF")
    logic = FakeLogic("beat")
    logic.asking = lambda answer="": "Untitled 3"
    box = loader(tmp_path, logic)
    box.open_app = lambda p: None                                         # Logic never shows the session
    with pytest.raises(LoadError, match="Untitled 3"):
        box.open_session(beat)


def test_a_named_song_asking_to_be_saved_is_saved_and_the_setup_goes_on(tmp_path):
    beat = tmp_path / "beat.wav"
    beat.write_bytes(b"RIFF")
    logic = FakeLogic("beat")
    pressed = []

    def asking(answer=""):
        if answer:
            pressed.append(answer)
            logic.opened = target_holder[0]
            return "old song"
        return "" if pressed else "old song"

    target_holder = []
    logic.asking = asking
    box = loader(tmp_path, logic)
    box.open_app = lambda p: target_holder.append(p)
    assert box.open_session(beat).name.startswith("beat") and pressed == ["Save"]


def test_facts_are_his_words_dated_listable_and_forgettable_never_deleted(tmp_path):
    from hiremarco import gate
    from hiremarco.whatsapp.facts import block, forget, keep, known

    conn = gate.connect(":memory:")
    monday = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)
    assert keep(conn, "the hook needs more space", ts=monday) and not keep(conn, "The hook needs more space.")
    keep(conn, "my cousin Dani plays bass", ts=monday + timedelta(days=1))
    assert [t for _, t in known(conn)] == ["the hook needs more space", "my cousin Dani plays bass"]
    lines = block(conn, "who plays bass on this?")
    assert lines[0].endswith("my cousin Dani plays bass") and lines[0].startswith("Mon Oct 27") or \
        lines[0].startswith("Tue Oct 27")
    assert forget(conn, "the thing about the hook needing space") == ["the hook needs more space"]
    assert [t for _, t in known(conn)] == ["my cousin Dani plays bass"]
    assert conn.execute("select count(*) from facts").fetchone()[0] == 2          # marked, still on record


def test_the_facts_block_stays_inside_its_budget():
    from hiremarco import gate
    from hiremarco.whatsapp.facts import block, keep

    conn = gate.connect(":memory:")
    for i in range(60):
        keep(conn, f"fact number {i} about a long and winding thing he said one night in the studio")
    lines = block(conn, "")
    assert 0 < len(lines) < 60 and sum(len(line.split()) * 1.3 for line in lines) <= 400 + 20


def test_the_brain_keeps_and_forgets_in_the_same_breath_and_reads_who_he_is(tmp_path, monkeypatch):
    from hiremarco.server import handle
    from hiremarco.whatsapp.facts import known

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    profile = tmp_path / "felix.md"
    profile.write_text("# Felix\n\nFelix sings and produces in Miami.")
    monkeypatch.setenv("HIREMARCO_PROFILE", str(profile))
    brain = Brain("reply", reply="noted.")
    brain.decision["remember"] = ["the hook needs more space", "Dani plays bass on everything"]
    brain.decision["forget"] = []
    line = handle(inbound(wa, "w1", kind="text", text="the hook needs more space, and Dani plays bass on everything"),
                  wa=wa, inbox=tmp_path / "inbox", marco=brain)
    assert line.endswith("kept 2 > " + line.rsplit("> ", 1)[1]) or "kept 2" in line
    assert [t for _, t in known(wa.conn)] == ["the hook needs more space", "Dani plays bass on everything"]
    brain = Brain("reply", reply="forgotten.")
    brain.decision["remember"], brain.decision["forget"] = [], ["Dani plays bass"]
    line = handle(inbound(wa, "w2", kind="text", text="forget what I said about Dani"), wa=wa, inbox=tmp_path / "inbox",
                  marco=brain)
    assert "forgot 1" in line and [t for _, t in known(wa.conn)] == ["the hook needs more space"]
    shown = brain.seen[-1]["text"]
    assert shown["about_felix"] == "# Felix\n\nFelix sings and produces in Miami."
    assert shown["facts"] and shown["facts"][0].endswith("Dani plays bass on everything") or \
        any(f.endswith("the hook needs more space") for f in shown["facts"])


def test_the_persona_drops_its_comment_blocks_and_reads_the_env_file(tmp_path, monkeypatch):
    from hiremarco import marco

    (tmp_path / "SOUL.md").write_text("<!--\nnotes for editors\n-->\n# Marco\n\nHe wants people to win.")
    (tmp_path / "voice.md").write_text("Short sentences.")
    env = tmp_path / "sealed.env"
    env.write_text(f"HIREMARCO_PERSONA_DIR={tmp_path}\n")
    text = marco.persona()
    assert text == "# Marco\n\nHe wants people to win.\n\nShort sentences." and marco.private_persona_on()

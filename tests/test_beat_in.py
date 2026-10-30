from datetime import date
from pathlib import Path

import httpx
import pytest

from hiremarco import gate
from hiremarco.studio.beat_in import (BeatLoader, Inbox, LoadError, beat_file_name, parse_header, requested_name,
                                      session_name, session_path, sidecar)
from hiremarco.studio.booth import Booth, Tape, watch_inbox

OWNER = "13055550100"


def rules(tmp_path):
    p = tmp_path / "RULES.md"
    p.write_text("send: logic -> * ; Logic ; until 2099-01-01\n")
    return p


def test_a_sent_file_keeps_its_name_and_a_voice_note_is_not_a_beat():
    assert beat_file_name("Kai beat 140.wav", "audio/wav", "x") == "Kai beat 140.wav"
    assert beat_file_name("", "audio/mpeg", "beat 1a2b3c") == "beat 1a2b3c.mp3"
    assert beat_file_name("instrumental", "audio/x-wav; codecs=1", "x") == "instrumental.wav"
    assert beat_file_name("note.ogg", "audio/ogg; codecs=opus", "x") is None
    assert beat_file_name("../a:b.wav", "", "x") == "a-b.wav"


def test_a_session_is_named_after_the_beat_and_the_day_and_never_overwritten(tmp_path):
    day = date(2026, 10, 29)
    first = session_path(Path("Kai 140 Em.wav"), tmp_path, day)
    assert first.name == "Kai 140 Em 2026-10-29.logicx"
    first.mkdir()
    assert session_path(Path("Kai 140 Em.wav"), tmp_path, day).name == "Kai 140 Em 2026-10-29 2.logicx"


def test_the_inbox_takes_a_beat_once_its_size_holds_and_moves_it_after(tmp_path):
    inbox = Inbox(tmp_path)
    (tmp_path / "beat.wav").write_bytes(b"1234")
    (tmp_path / "notes.txt").write_text("not audio")
    (tmp_path / ".beat.wav.part").write_bytes(b"12")
    assert inbox.ready() == []                     # first sight: size not yet known to hold
    assert inbox.ready() == [tmp_path / "beat.wav"]
    moved = inbox.done(tmp_path / "beat.wav")
    assert moved == tmp_path / "loaded" / "beat.wav" and moved.read_bytes() == b"1234"
    (tmp_path / "beat.wav").write_bytes(b"5678")
    inbox.ready(), inbox.ready()
    assert inbox.done(tmp_path / "beat.wav").name == "beat 2.wav"


def test_a_header_line_reads_position_focus_and_triangle():
    h = parse_header("237\t195\t325\t44\t1\t-")
    assert (h.x, h.middle, h.focus, h.open) == (237, 217, True, None)
    assert parse_header("missing") is None


class FakeLogic:
    """Logic as tracks_io shows it: PROD closed until its triangle is clicked, Beat selected by a click."""

    def __init__(self, beat_stem, region=None, prod_open=False):
        self.calls, self.clicks = [], []
        self.opened = None
        self.prod_open, self.beat_focus = prod_open, False
        self.region = beat_stem if region is None else region

    def run(self, args):
        self.calls.append(args)
        if args[0] == "window":
            return f"{self.opened.stem} - Tracks" if self.opened else ""
        if args[0] == "header":
            if args[1] == "PROD":
                return f"237\t239\t325\t44\t0\t{1 if self.prod_open else 0}"
            if args[1] == "Beat":
                return f"237\t283\t325\t44\t{1 if self.beat_focus else 0}\t-" if self.prod_open else "missing"
        if args[0] == "import":
            return "imported"
        if args[0] == "regions":
            return self.region if self.beat_focus else ""
        return ""

    def click(self, x, y):
        self.clicks.append((x, y))
        if y == 239 + 22:
            self.prod_open = True
        if y == 283 + 22:
            self.beat_focus = True


def loader(tmp_path, logic, front="Logic Pro", started=None):
    template = tmp_path / "template.logicx"
    (template / "Alternatives" / "000").mkdir(parents=True)
    (template / "Alternatives" / "000" / "ProjectData").write_bytes(b"pd")
    started = started if started is not None else []
    return BeatLoader(run=logic.run, open_app=lambda p: setattr(logic, "opened", p), front=lambda: front,
                      click=logic.click, scroll=lambda n: None, go_to_start=lambda: started.append("start") or "ok",
                      sleep=lambda s: None, template=template, sessions=tmp_path / "sessions",
                      conn=gate.connect(":memory:"), rules_path=rules(tmp_path), today=lambda: date(2026, 10, 29),
                      wait_s=3)


def test_a_beat_lands_on_the_beat_track_of_a_new_session_from_the_template(tmp_path):
    beat = tmp_path / "Kai 140 Em.wav"
    beat.write_bytes(b"RIFF")
    logic, started = FakeLogic("Kai 140 Em"), []
    result = loader(tmp_path, logic, started=started).load(beat)
    session = tmp_path / "sessions" / "Kai 140 Em 2026-10-29.logicx"
    assert result == "Kai 140 Em.wav on the Beat track at bar 1 in Kai 140 Em 2026-10-29.logicx"
    assert (session / "Alternatives" / "000" / "ProjectData").read_bytes() == b"pd"   # a copy; the template untouched
    assert logic.opened == session
    assert logic.clicks[0] == (237 + 43, 239 + 22)          # PROD opened first, by its triangle
    assert logic.clicks[1][1] == 283 + 22                  # then the Beat header clicked
    assert started == ["start"]
    assert ["import", str(beat.resolve())] in logic.calls
    assert logic.calls.index(["import", str(beat.resolve())]) < logic.calls.index(["regions"])


def test_nothing_is_clicked_when_logic_is_not_in_front(tmp_path):
    beat = tmp_path / "beat.wav"
    beat.write_bytes(b"RIFF")
    logic = FakeLogic("beat")
    with pytest.raises(LoadError, match="not the app in front"):
        loader(tmp_path, logic, front="Claude").load(beat)
    assert logic.clicks == [] and not any(c[0] == "import" for c in logic.calls)


def test_a_beat_that_does_not_show_on_the_beat_track_is_not_called_loaded(tmp_path):
    beat = tmp_path / "beat.wav"
    beat.write_bytes(b"RIFF")
    with pytest.raises(LoadError, match="Beat track shows"):
        loader(tmp_path, FakeLogic("beat", region="Audio 1#01", prod_open=True)).load(beat)


def test_a_file_that_is_not_audio_is_refused(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("x")
    with pytest.raises(LoadError, match="not an audio file"):
        loader(tmp_path, FakeLogic("notes")).load(notes)


def booth_with(load_beat, texts=None):
    said = []
    b = Booth(understand=lambda line: None, logic=lambda c: c.describe(), say=said.append, feedback=None,
              tape=Tape(1000, seconds=1), log=lambda line: None, fillers=False, load_beat=load_beat,
              text_owner=None if texts is None else (lambda body: texts.append(body) or "wamid.x"))

    def read(ask=True):
        def apply():
            b.last_setup = {"key": "E minor", "bpm": 105.0, "gain": -9.7}
            return "tempo set to 105"
        b.offer = apply
        return "read: E minor, 105"

    b._read_beat = read
    return b, said


def test_a_sent_beat_is_loaded_read_set_without_a_yes_and_confirmed_by_text(tmp_path):
    # Owner 2026-10-30: a beat he sends means set the session up, and tell him when it is done
    texts = []
    b, said = booth_with(lambda p: f"{p.name} on the Beat track", texts)
    result = b.beat_arrived(tmp_path / "fairyrnb.mp3")
    assert result.startswith("fairyrnb.mp3 on the Beat track; read: E minor, 105; set: tempo set to 105; texted")
    assert said == ["Got the beat. Setting up the session."] and b.offer is None
    assert texts == ["Session's ready: fairyrnb. E minor, 105 BPM, beat at -20 LUFS."]


def test_the_song_he_named_reaches_the_loader_and_the_text(tmp_path):
    texts, asked = [], []
    b, _ = booth_with(lambda p, name=None: asked.append(name) or "loaded", texts)
    b.beat_arrived(tmp_path / "beat.wav", "Midnight Drive")
    assert asked == ["Midnight Drive"] and texts[0].startswith("Session's ready: Midnight Drive.")


def test_a_caption_names_the_session_and_one_that_names_nothing_does_not():
    assert session_name("Start a session for me for Midnight Drive. Here's the beat") == "Midnight Drive"
    assert session_name("start a session for me for Midnight Drive here's the beat") == "Midnight Drive"
    assert session_name("call it Midnight Drive") == "Midnight Drive"
    assert session_name('session called "Kai Night" please') == "Kai Night"
    assert session_name("here you go") is None and session_name("for me") is None and session_name("") is None
    assert session_name("call it AC/DC tribute") == "AC-DC tribute"


def test_a_named_session_takes_the_song_name_and_the_name_travels_with_the_beat(tmp_path):
    assert session_path(Path("x.mp3"), tmp_path, date(2026, 10, 30), "Midnight Drive").name == \
        "Midnight Drive 2026-10-30.logicx"
    inbox = Inbox(tmp_path)
    beat = tmp_path / "x.mp3"
    beat.write_bytes(b"1")
    sidecar(beat).write_text("Midnight Drive")
    inbox.ready()
    assert inbox.ready() == [beat] and requested_name(beat) == "Midnight Drive"
    moved = inbox.done(beat)
    assert requested_name(moved) == "Midnight Drive" and not sidecar(beat).exists()


def test_a_beat_waits_for_a_rolling_take_and_a_failed_load_is_said(tmp_path):
    b, said = booth_with(lambda p: "loaded")
    b.rolling = True
    assert b.beat_arrived(tmp_path / "beat.wav").startswith("holding")
    b.rolling = False

    def broken(p):
        raise LoadError("Logic is not the app in front (Claude); nothing was clicked")

    b2, said2 = booth_with(broken)
    assert b2.beat_arrived(tmp_path / "beat.wav").startswith("beat not loaded: LoadError")
    assert said2[-1] == "I couldn't put the beat in the session. It's still in the inbox."


def test_the_watcher_moves_a_loaded_beat_and_leaves_a_failed_one_tried_once(tmp_path):
    inbox = Inbox(tmp_path)
    (tmp_path / "good.wav").write_bytes(b"1")
    (tmp_path / "bad.wav").write_bytes(b"2")
    seen = []

    sidecar(tmp_path / "good.wav").write_text("Good Song")
    named = []

    class FakeBooth:
        log = staticmethod(lambda line: None)

        def beat_arrived(self, path, name=None):
            seen.append(path.name)
            named.append(name)
            return "beat not loaded: LoadError" if path.name == "bad.wav" else "loaded"

    watch_inbox(FakeBooth(), inbox, rounds=4, sleep=lambda s: None)
    assert sorted(seen) == ["bad.wav", "good.wav"]          # each once
    assert sorted(n or "" for n in named) == ["", "Good Song"]
    assert (tmp_path / "loaded" / "good.wav").exists() and (tmp_path / "bad.wav").exists()


def test_a_beat_sent_on_whatsapp_lands_in_the_inbox_and_a_voice_note_does_not(tmp_path, monkeypatch):
    from hiremarco.server import handle
    from hiremarco.whatsapp import Inbound, WhatsApp
    from hiremarco.whatsapp.client import record_inbound

    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    rules_path = tmp_path / "RULES.md"
    rules_path.write_text(f"send: whatsapp -> {OWNER} ; the Owner's own chat ; until 2099-01-01\n")
    sent = []

    def respond(request):
        if request.url.host == "lookaside.example":
            return httpx.Response(200, content=b"RIFF-beat")
        if request.url.path.endswith("/media-1"):
            return httpx.Response(200, json={"url": "https://lookaside.example/media-1", "mime_type": "audio/wav"})
        sent.append(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.o"}]})

    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"), transport=httpx.MockTransport(respond),
                  rules_path=rules_path)
    record_inbound(wa.conn, "wamid.beat", OWNER, "document")
    inbox = tmp_path / "inbox"
    line = handle(Inbound(id="wamid.beat", sender=OWNER, kind="document", media_id="media-1",
                          filename="Kai 140 Em.wav", mime_type="audio/wav",
                          caption="Start a session for me for Midnight Drive. Here's the beat"), wa=wa, inbox=inbox)
    assert "beat saved to the inbox as Kai 140 Em.wav" in line
    assert (inbox / "Kai 140 Em.wav").read_bytes() == b"RIFF-beat"
    assert requested_name(inbox / "Kai 140 Em.wav") == "Midnight Drive"
    assert b"Beat track" in sent[-1]
    voice = handle(Inbound(id="wamid.v", sender=OWNER, kind="audio", media_id="media-1", mime_type="audio/ogg",
                           voice=True), wa=wa, inbox=inbox)
    assert "audio noted" in voice and sorted(p.name for p in inbox.iterdir()) == ["Kai 140 Em.wav",
                                                                                   "Kai 140 Em.wav.session"]

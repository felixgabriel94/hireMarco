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
                      tempo=lambda beat: 105.0, align=lambda beat, folder, bpm: (beat, 0.3275, 2, None),
                      click=logic.click, scroll=lambda n: None, go_to_start=lambda: started.append("start") or "ok",
                      sleep=lambda s: None, template=template, sessions=tmp_path / "sessions",
                      conn=gate.connect(":memory:"), rules_path=rules(tmp_path), today=lambda: date(2026, 10, 29),
                      wait_s=3, wake=lambda: logic.calls.append(["wake"]), notices=lambda: "",
                      asking=getattr(logic, "asking", lambda answer="": ""))


def test_a_beat_lands_on_the_beat_track_of_a_new_session_from_the_template(tmp_path):
    beat = tmp_path / "Kai 140 Em.wav"
    beat.write_bytes(b"RIFF")
    logic, started = FakeLogic("Kai 140 Em"), []
    result = loader(tmp_path, logic, started=started).load(beat)
    session = tmp_path / "sessions" / "Kai 140 Em 2026-10-29.logicx"
    assert result == ("Kai 140 Em.wav on the Beat track in Kai 140 Em 2026-10-29.logicx, its 1 (0.328 s in, first sound) "
                      "on bar 2 at 105 BPM")
    assert (session / "Alternatives" / "000" / "ProjectData").read_bytes() == b"pd"   # a copy; the template untouched
    assert logic.opened == session and logic.calls[0] == ["wake"]   # the screen lit before Logic opens
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
    assert texts == ["session's ready."]


def test_the_song_he_named_reaches_the_loader_and_the_text(tmp_path):
    texts, asked = [], []
    b, _ = booth_with(lambda p, name=None: asked.append(name) or "loaded", texts)
    b.beat_arrived(tmp_path / "beat.wav", "Midnight Drive")
    assert asked == ["Midnight Drive"] and texts == ["session's ready."]


def test_a_caption_names_the_session_and_one_that_names_nothing_does_not():
    assert session_name("Start a session for me for Midnight Drive. Here's the beat") == "midnight drive"
    assert session_name("start a session for me for Midnight Drive here's the beat") == "midnight drive"
    assert session_name("call it Midnight Drive") == "midnight drive"
    assert session_name('session called "Kai Night" please') == "kai night"
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


def whatsapp_line(tmp_path, monkeypatch):
    from hiremarco.whatsapp import WhatsApp

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
    return wa, sent


def inbound(wa, mid, **kw):
    from hiremarco.whatsapp import Inbound
    from hiremarco.whatsapp.client import record_inbound

    record_inbound(wa.conn, mid, OWNER, kw.get("kind", "text"))
    return Inbound(id=mid, sender=OWNER, **kw)


def test_a_sent_beat_waits_for_his_word_then_his_text_starts_it(tmp_path, monkeypatch):
    # Owner 2026-10-30: his instruction starts it; the beat alone is only received
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    inbox = tmp_path / "inbox"
    line = handle(inbound(wa, "w1", kind="document", media_id="media-1", filename="fairyrnb.mp3",
                          mime_type="audio/mpeg"), wa=wa, inbox=inbox)
    assert "waiting for his word" in line
    assert [p.name for p in inbox.iterdir() if p.is_file()] == []               # nothing for the booth yet
    assert (inbox / "received" / "fairyrnb.mp3").read_bytes() == b"RIFF-beat"
    assert b"want me to start a session with it?" in sent[-1]
    line = handle(inbound(wa, "w2", kind="text", text="Start a session for Midnight Drive"), wa=wa, inbox=inbox)
    assert "session started for fairyrnb.mp3 as 'midnight drive'" in line
    assert (inbox / "fairyrnb.mp3").exists() and requested_name(inbox / "fairyrnb.mp3") == "midnight drive"
    assert b"on it. setting up midnight drive." in sent[-1]


def test_a_caption_that_is_the_instruction_starts_at_once(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    inbox = tmp_path / "inbox"
    line = handle(inbound(wa, "w1", kind="document", media_id="media-1", filename="Kai 140 Em.wav",
                          mime_type="audio/wav", caption="Start a session for me for Midnight Drive. Here's the beat"),
                  wa=wa, inbox=inbox)
    assert "received with its instruction; session started" in line
    assert (inbox / "Kai 140 Em.wav").read_bytes() == b"RIFF-beat"
    assert requested_name(inbox / "Kai 140 Em.wav") == "midnight drive"
    assert b"setting up the session" in sent[-1]


def test_an_instruction_with_no_beat_waiting_asks_for_the_beat(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    line = handle(inbound(wa, "w1", kind="text", text="set it up"), wa=wa, inbox=tmp_path / "inbox")
    assert "none is waiting" in line and b"send me the beat first" in sent[-1]


def test_live_2026_10_30_a_started_beat_is_not_asked_for_again_takes_its_title_and_answers_status(tmp_path,
                                                                                                    monkeypatch):
    # the live test: voice note started it (heard "Anhil de Cristal"), he corrected the title, asked again to start,
    # then asked whether it started; Marco asked for the beat, answered in Spanish, then went silent
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    inbox = tmp_path / "inbox"
    handle(inbound(wa, "w1", kind="document", media_id="media-1", filename="fairyrnb.mp3", mime_type="audio/mpeg"),
           wa=wa, inbox=inbox)
    handle(inbound(wa, "w2", kind="text", text="Yes, start a session and name it Anhil de Cristal"), wa=wa, inbox=inbox)
    line = handle(inbound(wa, "w3", kind="text", text="ángel de cristal"), wa=wa, inbox=inbox)
    assert "renamed the waiting session to 'ángel de cristal'" in line
    assert requested_name(inbox / "fairyrnb.mp3") == "ángel de cristal" and b"naming it" in sent[-1]
    line = handle(inbound(wa, "w4", kind="text", text="No I want you to set up the session for me and give it that "
                                                      "title. Go start the session on Logic"), wa=wa, inbox=inbox)
    assert " > already started" in line and b"already on it" in sent[-1]  # the patterns: no brain here
    line = handle(inbound(wa, "w5", kind="text", text="Did you start the session?"), wa=wa, inbox=inbox)
    assert "status: Setting up ángel de cristal now." in line


def test_a_yes_to_his_question_starts_the_waiting_beat(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    inbox = tmp_path / "inbox"
    handle(inbound(wa, "w1", kind="document", media_id="media-1", filename="beat.wav", mime_type="audio/wav"),
           wa=wa, inbox=inbox)
    line = handle(inbound(wa, "w2", kind="text", text="yes"), wa=wa, inbox=inbox)
    assert "session started for beat.wav" in line and (inbox / "beat.wav").exists()


def test_status_says_where_the_beat_is(tmp_path):
    import os

    from hiremarco.server import status
    from hiremarco.studio.beat_in import keep_received

    inbox = tmp_path / "inbox"
    assert status(inbox, lambda: True) == "No beat yet. Send me one and tell me when to start."
    keep_received(b"x", "beat.wav", inbox)
    assert status(inbox, lambda: True).startswith("Not yet. I have your beat (beat)")
    (inbox / "loaded").mkdir()
    (inbox / "received" / "beat.wav").rename(inbox / "loaded" / "beat.wav")
    sidecar(inbox / "loaded" / "beat.wav").write_text("Night Shift")
    assert status(inbox, lambda: True) == "Yes. Night Shift is set up in Logic."
    (inbox / "next.wav").write_bytes(b"y")
    assert status(inbox, lambda: False) == "Starting it now: next. My booth was off, so I'm opening it."


def test_a_title_is_kept_lowercase_and_an_acronym_stays():
    from hiremarco.studio.beat_in import title

    assert title("ángel de cristal") == "ángel de cristal" and title("Midnight Drive") == "midnight drive"
    assert title("SZA type beat") == "SZA type beat"


def test_chat_replies_stay_in_english(tmp_path, monkeypatch):
    from hiremarco import marco
    from hiremarco.server import ENGLISH, handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    asked = {}

    class Fake:
        def answer(self, text, **kw):
            asked.update(kw)
            return marco.Reply(text="Nice title.") if hasattr(marco, "Reply") else type("R", (), {"text": "Nice title."})()

    handle(inbound(wa, "w1", kind="text", text="¿qué tal?"), wa=wa, inbox=tmp_path / "inbox", marco=Fake())
    assert asked.get("instructions") == ENGLISH and "English" in ENGLISH


def test_a_voice_note_is_heard_and_can_start_the_session(tmp_path, monkeypatch):
    import io

    import numpy as np
    import soundfile as sf

    from hiremarco.hearing import Turn
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    inbox = tmp_path / "inbox"
    handle(inbound(wa, "w1", kind="document", media_id="media-1", filename="beat.wav", mime_type="audio/wav"),
           wa=wa, inbox=inbox)
    ogg = io.BytesIO()
    sf.write(ogg, np.zeros(4800, dtype="float32"), 48000, format="OGG", subtype="OPUS")
    monkeypatch.setattr(wa, "download_media", lambda media_id: (ogg.getvalue(), "audio/ogg"))
    heard = []
    line = handle(inbound(wa, "w2", kind="audio", media_id="v-1", mime_type="audio/ogg; codecs=opus", voice=True),
                  wa=wa, inbox=inbox, listen=lambda audio, rate: heard.append(rate) or [Turn(0, 900, "Set it up, call it Night Shift")])
    assert heard == [48000] and "voice note: Set it up, call it Night Shift" in line
    assert requested_name(inbox / "beat.wav") == "night shift" and b"setting up night shift" in sent[-1]


def test_marco_texts_in_lowercase_but_links_and_acronyms_keep_their_letters():
    from hiremarco.style import casual

    assert casual("Session's ready. Open http://192.168.5.196:8788/?t=QWB3IDqb2k0Q") == \
        "session's ready. open http://192.168.5.196:8788/?t=QWB3IDqb2k0Q"
    assert casual("SZA vibes at 105 BPM, Ángel") == "SZA vibes at 105 BPM, ángel"


def test_the_first_hit_is_found_where_its_attack_begins():
    import numpy as np

    from hiremarco.studio.beat_in import first_hit

    rate = 48000
    audio = np.zeros(rate, dtype=np.float32)
    start = int(0.3275 * rate)
    audio[start:start + 2000] = np.linspace(0.05, 0.9, 2000)        # an attack ramping in from 0.3275 s
    audio[start + 2000:start + 6000] = 0.4
    assert abs(first_hit(audio, rate) - 0.3275) < 0.004
    assert first_hit(np.zeros(100, dtype=np.float32), rate) == 0.0


def test_the_aligned_copy_puts_the_first_hit_on_a_bar_line_and_keeps_the_whole_file(tmp_path):
    import numpy as np

    from hiremarco.studio.beat_in import aligned_copy, first_hit

    rate, written = 48000, {}
    audio = np.zeros((rate * 3, 2), dtype=np.float32)
    audio[int(0.3275 * rate):int(0.3275 * rate) + 4000] = 0.8
    path, hit, bar, one = aligned_copy(Path("fairyrnb.mp3"), tmp_path, 105.0, read=lambda p: (audio, rate),
                                  write=lambda p, d, r: written.update(path=p, data=d, rate=r))
    assert path == tmp_path / "fairyrnb.wav" and bar == 2 and abs(hit - 0.3275) < 0.004
    landed = first_hit(written["data"].mean(axis=1), rate)
    assert abs(landed - 240 / 105.0) < 0.001                       # on bar 2: one bar at 105 BPM
    assert len(written["data"]) - len(audio) == round((240 / 105.0 - hit) * rate)   # nothing cut, only silence added
    long_intro = np.zeros((rate * 6, 2), dtype=np.float32)
    long_intro[int(3.0 * rate):int(3.0 * rate) + 4000] = 0.8
    _, _, bar, _ = aligned_copy(Path("x.wav"), tmp_path, 105.0, read=lambda p: (long_intro, rate),
                             write=lambda p, d, r: None)
    assert bar == 3                                                # a lead-in longer than a bar lands on the next bar


def test_the_grid_is_found_on_the_kicks_behind_an_intro():
    import numpy as np

    from hiremarco.studio.downbeat import find

    rate, bpm = 22050, 120.0
    beat = 60.0 / bpm
    intro = 0.73
    audio = np.random.default_rng(1).standard_normal(int(rate * (intro + 34 * 4 * beat))).astype(np.float32) * 0.002
    t = np.arange(int(0.08 * rate)) / rate
    kick = (np.sin(2 * np.pi * 55 * t) * np.exp(-t * 30)).astype(np.float32)
    for k in range(34 * 4):
        at = int((intro + k * beat) * rate)
        audio[at:at + kick.size] += kick * (1.0 if k % 4 == 0 else 0.6)
    got = find(audio, rate, bpm, intro)
    assert abs(((got.grid - intro) / beat + 0.5) % 1 - 0.5) * beat < 0.01
    assert got.on_grid > 0.9


def test_only_a_one_button_notice_is_pressed(monkeypatch):
    import subprocess

    from hiremarco.studio import beat_in

    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: seen.setdefault("script", args[-1]) and
                        type("R", (), {"stdout": "Plug-ins load as needed;"})())
    assert beat_in.dismiss_notices() == "Plug-ins load as needed;"
    assert 'does not contain "Cancel"' in seen["script"] and 'does not contain "Save"' in seen["script"]


def test_live_2026_10_31_a_beat_that_sounds_from_its_first_sample_starts_on_bar_2(tmp_path):
    import numpy as np

    from hiremarco.studio.beat_in import aligned_copy, first_sound

    rate = 48000
    audio = np.zeros(rate, dtype=np.float32)
    audio[:int(0.156 * rate)] = 0.03                                  # a quiet opening from the very start
    audio[int(0.156 * rate):int(0.156 * rate) + 4000] = 0.9           # the first loud hit
    assert first_sound(audio, rate) == 0.0
    written = {}
    _, hit, bar, _ = aligned_copy(Path("x.wav"), tmp_path, 99.0, read=lambda p: (audio[:, None], rate),
                               write=lambda p, d, r: written.update(data=d))
    assert hit == 0.0 and bar == 2 and len(written["data"]) - rate == round(240 / 99.0 * rate)   # a whole bar


def test_the_1_comes_from_the_model_on_a_hit_and_a_riser_before_it_sits_in_the_bars_before():
    import numpy as np

    from hiremarco.studio import the_one

    rate = 22050
    audio = np.zeros(rate * 6, dtype=np.float32)
    audio[:int(1.5 * rate)] = np.linspace(0.0, 0.2, int(1.5 * rate))      # a riser from the first sample
    hit = int(1.5 * rate)
    audio[hit:hit + 2000] = 0.9                                            # the 1, after the riser
    sure = the_one.find(audio, rate, [1.52, 3.9])
    assert sure.sure and abs(sure.seconds - 1.5) < 0.01                    # moved onto the hit's attack
    unsure = the_one.find(audio, rate, [4.5])                              # no hit near the model's 1
    assert not unsure.sure
    fallback = the_one.find(audio, rate, None)
    assert not fallback.sure and fallback.seconds < 0.05                   # the first sound, never called sure


def test_an_unsure_1_is_said_in_the_ready_text():
    from hiremarco.studio.booth import Booth, Tape

    texts = []
    b = Booth(understand=lambda line: None, logic=lambda c: c.describe(), say=lambda t: None,
              feedback=lambda take, r: None, tape=Tape(48000, seconds=1), log=lambda line: None,
              load_beat=lambda path, name=None: "beat on the Beat track; CHECK BAR 3: not sure where the 1 is",
              text_owner=lambda body: texts.append(body) or "ok")
    b._read_beat = lambda ask=False: "read"
    b.offer = lambda: b.last_setup.update(key="A") or "set"
    b.beat_arrived(Path("beat.wav"))
    assert texts[-1] == "session's ready. check bar 3: I'm not sure that's where the 1 is."

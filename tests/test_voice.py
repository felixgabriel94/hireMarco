import json

import httpx
import numpy as np
import pytest
import soundfile as sf

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.voice import RATE, Speech, Talkback, TakeRolling, VoiceNote, prepare_voice_note, synthesize
from hiremarco.voice.talkback import channel_pair
from hiremarco.whatsapp import WhatsApp
from hiremarco.whatsapp.client import record_inbound

OWNER = "13055550100"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("HIREMARCO_ENV", str(tmp_path / "env"))
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)


def tone(seconds=0.5):
    t = np.arange(int(RATE * seconds)) / RATE
    return (np.sin(2 * np.pi * 220 * t) * 8000).astype("<i2")


def stand_in(text):
    return Speech(text, tone())


def rules_file(tmp_path, *lines):
    p = tmp_path / "RULES.md"
    p.write_text("".join(line + "\n" for line in lines))
    return p


# Text to speech

def test_synthesize_asks_for_24k_pcm_and_logs_cost(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=tone(0.25).tobytes())

    log = JobLog(tmp_path / "j.jsonl")
    speech = synthesize("Rolling", voice_id="v1", api_key="k", joblog=log, transport=httpx.MockTransport(handler))
    assert speech.seconds == pytest.approx(0.25)
    req = seen[0]
    assert req.url.path == "/v1/text-to-speech/v1"
    assert req.url.params["output_format"] == "pcm_24000"
    assert req.headers["xi-api-key"] == "k"
    body = json.loads(req.content)
    assert (body["text"], body["model_id"]) == ("Rolling", "eleven_flash_v2_5")
    assert body["voice_settings"] == {"stability": 0.65, "similarity_boost": 0.75, "style": 0.0, "speed": 0.95}
    (row,) = log.rows()
    assert row["job"] == "speech" and row["ok"] and row["cost_usd"] > 0


def test_synthesize_http_error_is_logged_and_raised(tmp_path):
    log = JobLog(tmp_path / "j.jsonl")
    with pytest.raises(RuntimeError, match="HTTP 401"):
        synthesize("Rolling", voice_id="v", api_key="k", joblog=log,
                   transport=httpx.MockTransport(lambda r: httpx.Response(401, text="Rolling")))
    assert log.rows()[0]["ok"] is False


def test_synthesize_respects_the_kill_switch(tmp_path):
    gate.set_kill_switch(True)
    try:
        with pytest.raises(gate.Refused, match="kill switch"):
            synthesize("Rolling", voice_id="v", api_key="k", joblog=JobLog(tmp_path / "j.jsonl"),
                       transport=httpx.MockTransport(lambda r: pytest.fail("no request")))
    finally:
        gate.set_kill_switch(False)


# Talkback

def make_talkback(tmp_path, rolling, played, switch=True):
    lines = ["send: talkback -> * ; booth talkback ; until 2099-01-01"] if switch else []
    return Talkback(lambda: rolling[0], speak=stand_in, play=lambda pcm, rate: played.append((pcm, rate)),
                    folder=tmp_path / "capture", conn=gate.connect(":memory:"),
                    rules_path=rules_file(tmp_path, *lines), cache_dir=tmp_path / "cache")


def test_talkback_speaks_between_takes_and_keeps_the_line(tmp_path):
    played = []
    talk = make_talkback(tmp_path, [False], played)
    path = talk.say("Morning. Your session's up. Where do you want to start?")
    assert len(played) == 1 and played[0][1] == RATE
    data, rate = sf.read(path, dtype="int16")
    assert rate == RATE and np.array_equal(data, played[0][0])
    (entry,) = [json.loads(line) for line in (tmp_path / "capture" / "talkback.jsonl").read_text().splitlines()]
    assert entry["file"] == path.name and entry["text"].startswith("Morning.")


def test_talkback_never_speaks_over_a_take(tmp_path):
    played = []
    talk = make_talkback(tmp_path, [True], played)
    with pytest.raises(TakeRolling):
        talk.say("Rolling")
    assert played == []


def test_talkback_holds_when_a_take_starts_during_synthesis(tmp_path):
    played, rolling = [], [False]

    def slow_speak(text):
        rolling[0] = True  # Felix hit record while the line was being made
        return stand_in(text)

    talk = make_talkback(tmp_path, rolling, played)
    talk.speak = slow_speak
    with pytest.raises(TakeRolling, match="take started"):
        talk.say("That's in the mix notes")
    assert played == []


def test_talkback_is_off_without_its_switch(tmp_path):
    played = []
    talk = make_talkback(tmp_path, [False], played, switch=False)
    with pytest.raises(gate.Refused, match="no send switch for talkback"):
        talk.say("Rolling")
    assert played == []


def test_channel_pair():
    assert channel_pair("3,4") == [3, 4]
    assert channel_pair(None) is None
    with pytest.raises(ValueError):
        channel_pair("0,1")
    with pytest.raises(ValueError):
        channel_pair("3")


# The voice note

def test_prepare_voice_note_is_mono_opus_with_its_words(tmp_path):
    note = prepare_voice_note("That's a wrap, Felix.", speak=stand_in, folder=tmp_path)
    info = sf.info(note.ogg)
    assert (info.format, info.subtype, info.channels) == ("OGG", "OPUS", 1)
    assert note.text == "That's a wrap, Felix." and note.seconds == pytest.approx(0.5, abs=0.05)
    assert note.ogg.with_suffix(".wav").exists()
    assert VoiceNote.load(note.ogg) == note


def test_voice_note_refuses_a_file_that_is_not_opus(tmp_path):
    bad = tmp_path / "x.ogg"
    sf.write(bad, tone(), RATE, format="OGG", subtype="VORBIS")
    bad.with_suffix(".txt").write_text("hi\n")
    with pytest.raises(ValueError, match="mono OGG/OPUS"):
        VoiceNote.load(bad)


def fake_graph():
    calls = []

    def handler(request):
        calls.append((request.url.path, request.headers.get("content-type", ""), request.content))
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "media-42"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.voice"}]})

    return httpx.MockTransport(handler), calls


def test_send_voice_uploads_then_sends_a_voice_message(tmp_path):
    transport, calls = fake_graph()
    wa = WhatsApp(token="t", phone_number_id="111", conn=gate.connect(":memory:"), transport=transport,
                  rules_path=rules_file(tmp_path, "send: whatsapp -> owner ; the Owner's chat ; until 2099-01-01"))
    record_inbound(wa.conn, "wamid.in", OWNER, "text")
    note = prepare_voice_note("That's a wrap.", speak=stand_in, folder=tmp_path)
    judged = []
    assert wa.send_voice(OWNER, note.ogg.read_bytes(), note.text, idempotency_key="vn",
                         critic=lambda d: (judged.append(d) or True, "ok")) == "wamid.voice"
    assert judged == [f"send_voice_note via whatsapp to {OWNER}: voice note: That's a wrap."]
    (upload_path, upload_type, upload_body), (send_path, _, send_body) = calls
    assert upload_path == "/v25.0/111/media" and upload_type.startswith("multipart/form-data")
    assert b"audio/ogg" in upload_body
    assert send_path == "/v25.0/111/messages"
    assert json.loads(send_body) == {"messaging_product": "whatsapp", "to": OWNER, "type": "audio",
                                     "audio": {"id": "media-42", "voice": True}}


def test_send_voice_held_by_the_critic_uploads_nothing(tmp_path):
    transport, calls = fake_graph()
    wa = WhatsApp(token="t", phone_number_id="111", conn=gate.connect(":memory:"), transport=transport,
                  rules_path=rules_file(tmp_path, "send: whatsapp -> owner ; the Owner's chat ; until 2099-01-01"))
    record_inbound(wa.conn, "wamid.in", OWNER, "text")
    with pytest.raises(gate.Refused, match="critic held it"):
        wa.send_voice(OWNER, b"OggS", "hi", idempotency_key="vn", critic=lambda d: (False, "not now"))
    assert calls == []


def test_stock_lines_are_made_once_and_play_from_the_cache(tmp_path):
    made, played = [], []
    talk = make_talkback(tmp_path, [False], played)
    talk.speak = lambda text: made.append(text) or stand_in(text)
    assert talk.warm(["Rolling", "That's in the mix notes."]) == 2
    assert talk.warm(["Rolling"]) == 0
    talk.say("Rolling")
    talk.say("Rolling")
    assert made == ["Rolling", "That's in the mix notes."] and len(played) == 2
    entries = [json.loads(line) for line in (tmp_path / "capture" / "talkback.jsonl").read_text().splitlines()]
    assert all("ready_ms" in e for e in entries)


def test_voice_settings_come_from_the_env_and_stay_in_range(monkeypatch):
    from hiremarco.voice.tts import voice_settings

    monkeypatch.setenv("HIREMARCO_VOICE_STABILITY", "0.9")
    monkeypatch.setenv("HIREMARCO_VOICE_SPEED", "3")
    s = voice_settings()
    assert s["stability"] == 0.9 and s["speed"] == 1.2


def test_lines_are_leveled_to_one_loudness_under_the_ceiling():
    from hiremarco.voice.talkback import leveled

    loud = (np.sin(np.arange(24000) / 4) * 32000).astype("<i2")   # about -3 dBFS RMS
    quiet = (np.sin(np.arange(24000) / 4) * 800).astype("<i2")
    for pcm in (loud, quiet):
        out = leveled(pcm, target_db=-24).astype(np.float64) / 32768
        assert 20 * np.log10(np.sqrt(np.mean(out ** 2))) == pytest.approx(-24, abs=0.3)
        assert np.max(np.abs(out)) <= 10 ** (-6 / 20) + 1e-3
    assert np.array_equal(leveled(np.zeros(10, dtype="<i2")), np.zeros(10, dtype="<i2"))


def test_say_stock_plays_only_what_is_cached_with_no_gate(tmp_path):
    played = []
    talk = make_talkback(tmp_path, [False], played, switch=False)  # no talkback switch at all
    assert talk.say_stock("Stopped.") is False and played == []
    talk.warm(["Stopped."])  # warming goes through synthesis, not the gate
    assert talk.say_stock("Stopped.") is True and len(played) == 1

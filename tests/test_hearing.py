import asyncio
import json

import httpx
import numpy as np
import pytest

from hiremarco import gate
from hiremarco.hearing import RATE, Listener, to_pcm24k, transcribe
from hiremarco.joblog import JobLog


def test_resample_to_24k_mono_int16():
    stereo = np.zeros((48000, 2), dtype="float32")
    stereo[:, 0] = 0.5
    pcm = to_pcm24k(stereo, 48000)
    assert pcm.dtype == np.dtype("<i2") and len(pcm) == RATE
    assert abs(int(pcm[100]) - int(0.25 * 32767)) < 2
    assert len(to_pcm24k(np.zeros(8000, dtype="float32"), 8000)) == RATE
    quiet_ints = np.ones(24000, dtype="int16")  # 1 LSB, not full scale
    assert int(to_pcm24k(quiet_ints, 24000)[0]) == 0 or int(to_pcm24k(quiet_ints, 24000)[0]) == 1


def test_transcribe_diarized_call(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "k")
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content
        return httpx.Response(200, json={"sessionId": "s", "transcript": "x", "audioDurationMs": 60000, "turns": [
            {"turnId": 0, "startMs": 0, "endMs": 4000, "transcript": "Hi, this call is recorded.", "speaker": "A"},
            {"turnId": 1, "startMs": 4100, "endMs": 7000, "transcript": "Sure, Thursday at eight.", "speaker": "B"},
        ]})

    log = JobLog(tmp_path / "j.jsonl")
    turns = transcribe(np.zeros(8000 * 60, dtype="float32"), 8000, joblog=log, transport=httpx.MockTransport(handler))
    assert [(t.speaker, t.text) for t in turns] == [("A", "Hi, this call is recorded."), ("B", "Sure, Thursday at eight.")]
    assert seen["path"] == "/v1/asr/transcribe" and seen["auth"] == "Bearer k"
    assert b'"mode": "DIARIZATION"' in seen["body"] and b'"audioEncoding": "WAV"' in seen["body"]
    assert log.rows()[-1]["cost_usd"] == pytest.approx(0.18 / 60)


class FakeSocket:
    def __init__(self, events):
        self.sent, self.events = [], events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        return json.dumps({"sessionId": "abc"})

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        await asyncio.sleep(0.01)
        for e in self.events:
            yield json.dumps(e)


def test_listener_yields_finished_sentences(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "k")
    sock = FakeSocket([
        {"type": "speechStart", "turnId": 0, "audioProcessedMs": 100},
        {"type": "transcript", "transcript": "Marco, take me", "final": False, "audioProcessedMs": 900},
        {"type": "speechComplete", "turnId": 0, "transcript": "Marco, take me to the chorus.", "audioProcessedMs": 1500},
        {"type": "speechComplete", "turnId": 1, "transcript": "  ", "audioProcessedMs": 1600},
    ])

    async def chunks():
        yield b"\x00\x00" * 2400

    async def run():
        listener = Listener(joblog=JobLog(tmp_path / "j.jsonl"), connect=lambda url: sock)
        return [s async for s in listener.sentences(chunks())]

    assert asyncio.run(run()) == ["Marco, take me to the chorus."]
    handshake = json.loads(sock.sent[0])
    assert handshake["mode"] == "ENDPOINTING" and handshake["audioEncoding"] == "PCM_24KHZ"
    assert "punch" in handshake["keywords"] and handshake["authorization"]["accessToken"] == "Bearer k"


def test_listener_respects_the_kill_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    gate.set_kill_switch(True)

    async def chunks():
        yield b""

    async def run():
        listener = Listener(joblog=JobLog(tmp_path / "j.jsonl"), connect=lambda url: pytest.fail("no connect"))
        return [s async for s in listener.sentences(chunks())]

    with pytest.raises(gate.Refused):
        asyncio.run(run())
    gate.set_kill_switch(False)


def test_an_error_event_carries_the_servers_message_and_empty_frames_are_never_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "k")
    sock = FakeSocket([{"type": "speechComplete", "turnId": 0, "transcript": "Marco, record."},
                       {"type": "error", "errorType": "invalid_request_error", "message": "audio frame was empty"}])

    async def chunks():
        for chunk in (b"\x00\x01" * 100, b"", b"\x00\x01" * 100):
            yield chunk

    async def run():
        listener = Listener(joblog=JobLog(tmp_path / "j.jsonl"), connect=lambda url: sock)
        heard = []
        async for line in listener.sentences(chunks()):
            heard.append(line)
        return heard

    with pytest.raises(RuntimeError, match="invalid_request_error: audio frame was empty"):
        asyncio.run(run())
    assert b"" not in sock.sent and sum(1 for s in sock.sent if isinstance(s, bytes)) == 2


def test_only_a_line_for_marco_reaches_the_screen(tmp_path, monkeypatch):
    # Owner 2026-11-03: Marco Live showed the room's whole conversation; it shows what is said to Marco, nothing else
    from hiremarco import config, events

    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")

    async def chunks():
        yield b"\x00\x00" * 2400

    def rows():
        return [(r["kind"], r["summary"], r["call_id"]) for r in
                (json.loads(l) for l in (tmp_path / "state" / events.NAME).read_text().splitlines())]

    sock = FakeSocket([
        {"type": "transcript", "transcript": "so Lucie, the chorus", "final": False},
        {"type": "speechComplete", "turnId": 0, "transcript": "so Lucie, the chorus needs another take."},
        {"type": "transcript", "transcript": "Marco, take", "final": False},
        {"type": "speechComplete", "turnId": 1, "transcript": "Marco, take me to the chorus."},
    ])

    async def run():
        listener = Listener(joblog=JobLog(tmp_path / "j.jsonl"), connect=lambda url: sock)
        return [s async for s in listener.sentences(chunks())]

    assert asyncio.run(run()) == ["so Lucie, the chorus needs another take.", "Marco, take me to the chorus."]
    seen = rows()
    assert [(k, s) for k, s, _ in seen] == [("model_call_started", "listening"),
                                            ("model_call_completed", "“Marco, take me to the chorus.”")]
    assert seen[0][2] == seen[1][2]

    # the booth's own judgement wins when it is given: a line that opened as his and turned out not to be closes without
    # the room's words, and a line without his name while he is still listening shows
    sock2 = FakeSocket([{"type": "transcript", "transcript": "Marco's", "final": False},
                        {"type": "speechComplete", "turnId": 0, "transcript": "Marco's line was great there."},
                        {"type": "speechComplete", "turnId": 1, "transcript": "take me to the chorus."}])

    async def run2():
        listener = Listener(joblog=JobLog(tmp_path / "j.jsonl"), connect=lambda url: sock2,
                            addressed=lambda text: not text.endswith("there."))
        return [s async for s in listener.sentences(chunks())]

    asyncio.run(run2())
    assert [(k, s) for k, s, _ in rows()[2:]] == [
        ("model_call_started", "listening"), ("model_call_completed", "Talk in the room, not for Marco."),
        ("model_call_started", "listening"), ("model_call_completed", "“take me to the chorus.”")]

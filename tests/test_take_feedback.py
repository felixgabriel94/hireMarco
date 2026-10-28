import base64
import io
import json

import httpx
import numpy as np
import pytest
import soundfile as sf

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.studio.feedback import MAX_SECONDS, RATE, TakeNote, how_was_that_take, take_wav


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))


def spark(tmp_path, content, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "muse-spark-1.2",
            "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 60},
        })

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def take(seconds=2.0, rate=48000):
    t = np.arange(int(rate * seconds)) / rate
    left = np.sin(2 * np.pi * 220 * t) * 0.3
    return np.column_stack([left, left]).astype("float32")


def test_note_with_a_punch_ends_on_the_question(tmp_path):
    seen = []
    client = spark(tmp_path, json.dumps({"note": "Pitch dips on the last line of the chorus.", "punch": True,
                                         "punch_where": "chorus, last line"}), seen)
    note = how_was_that_take(take(), 48000, client=client)
    assert note == TakeNote("Pitch dips on the last line of the chorus.", True, "chorus, last line")
    assert note.spoken == "Pitch dips on the last line of the chorus. Want to punch it?"
    body = seen[0]
    assert body["model"] == "muse-spark-1.2" and body["max_completion_tokens"] == 4000
    assert body["response_format"]["json_schema"]["strict"] is True
    audio_part = body["messages"][1]["content"][1]
    assert audio_part["type"] == "input_audio" and audio_part["input_audio"]["format"] == "wav"
    data, rate = sf.read(io.BytesIO(base64.b64decode(audio_part["input_audio"]["data"])))
    assert rate == RATE and data.ndim == 1 and len(data) == 2 * RATE
    assert JobLog(tmp_path / "j.jsonl").rows()[0]["job"] == "take_feedback"


def test_a_keeper_asks_nothing(tmp_path):
    client = spark(tmp_path, json.dumps({"note": "That's the one. Keep it.", "punch": False, "punch_where": ""}), [])
    assert how_was_that_take(take(), 48000, client=client).spoken == "That's the one. Keep it."


def test_unreadable_reply_is_an_error_not_a_note(tmp_path):
    client = spark(tmp_path, "sounds great!", [])
    with pytest.raises(ValueError, match="unreadable"):
        how_was_that_take(take(), 48000, client=client)


def test_kill_switch_stops_it_before_any_request(tmp_path):
    gate.set_kill_switch(True)
    try:
        client = spark(tmp_path, "{}", seen := [])
        with pytest.raises(gate.Refused, match="kill switch"):
            how_was_that_take(take(), 48000, client=client)
        assert seen == []
    finally:
        gate.set_kill_switch(False)


def test_long_take_keeps_only_the_last_minutes():
    wav = take_wav(np.zeros(RATE * (MAX_SECONDS + 30), dtype="int16"), RATE)
    assert sf.info(io.BytesIO(wav)).frames == MAX_SECONDS * RATE


def test_empty_take_is_refused(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        how_was_that_take(np.zeros((0, 2), dtype="float32"), 48000, client=spark(tmp_path, "{}", []))

import json

import httpx
import pytest

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.sam import Box, parse_boxes, segment
from hiremarco.studio.six176 import NoKnobsFound, as_note, read_6176, reading_order

SAM_TEXT = ("<0f>0<|box;x1=400;y1=100;x2=480;y2=180;w=1600;h=900;c=0.93|><|mask;x=0;y=0;data=!12|>,"
            "1<|box;x1=100;y1=110;x2=180;y2=190;w=1600;h=900;c=0.88|><|mask;x=0;y=0;data=!3|>,"
            "2<|box;x1=120;y1=500;x2=200;y2=580;w=1600;h=900;c=0.31|><|mask;x=0;y=0;data=!3|>")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))


def test_parse_boxes_reads_coordinates_and_confidence():
    boxes = parse_boxes(SAM_TEXT)
    assert boxes[0] == Box(400, 100, 480, 180, 1600, 900, 0.93)
    assert len(boxes) == 3 and boxes[2].confidence == pytest.approx(0.31)
    assert parse_boxes("") == []


def test_segment_sends_the_phrase_and_image_and_drops_low_confidence(tmp_path):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"output": [{"type": "message", "content": [
            {"type": "output_text", "text": SAM_TEXT}]}]})

    log = JobLog(tmp_path / "j.jsonl")
    boxes = segment(b"\xff\xd8jpeg", "knob", joblog=log, api_key="k", transport=httpx.MockTransport(handler))
    assert len(boxes) == 2
    content = seen[0]["input"][0]["content"]
    assert seen[0]["model"] == "sam-3.1"
    assert content[0] == {"type": "input_text", "text": "knob"}
    assert content[1]["image_url"].startswith("data:image/jpeg;base64,")
    assert log.rows()[0]["cost_usd"] == pytest.approx(0.0025)


def test_reading_order_is_rows_then_left_to_right():
    boxes = parse_boxes(SAM_TEXT)
    assert [b.x1 for b in reading_order(boxes)] == [100, 400, 120]


def spark(tmp_path, readings, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-spark-1.3", "choices": [{"message": {
            "content": json.dumps({"readings": readings})}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 80}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def test_read_6176_keeps_only_real_knobs_once(tmp_path):
    seen = []
    client = spark(tmp_path, [
        {"knob": 1, "label": "GAIN", "setting": "40"},
        {"knob": 2, "label": "INPUT", "setting": "2 o'clock"},
        {"knob": 2, "label": "INPUT", "setting": "3 o'clock"},  # a second answer for the same knob
        {"knob": 9, "label": "RATIO", "setting": "4"},           # no such box
    ], seen)
    boxes = parse_boxes(SAM_TEXT)[:2]
    readings = read_6176(b"jpeg", client=client, find=lambda *a, **k: boxes)
    assert [(r.knob, r.label, r.setting) for r in readings] == [(1, "GAIN", "40"), (2, "INPUT", "2 o'clock")]
    assert as_note(readings) == "6176: GAIN 40; INPUT 2 o'clock"
    user = seen[0]["messages"][1]["content"]
    assert "1: x1=100 y1=110" in user[0]["text"] and user[1]["type"] == "image_url"


def test_no_knobs_is_an_error_not_an_empty_note(tmp_path):
    with pytest.raises(NoKnobsFound):
        read_6176(b"jpeg", client=spark(tmp_path, [], []), find=lambda *a, **k: [])


def test_segment_respects_the_kill_switch(tmp_path):
    gate.set_kill_switch(True)
    try:
        with pytest.raises(gate.Refused):
            segment(b"x", "knob", joblog=JobLog(tmp_path / "j.jsonl"), api_key="k",
                    transport=httpx.MockTransport(lambda r: pytest.fail("no request")))
    finally:
        gate.set_kill_switch(False)

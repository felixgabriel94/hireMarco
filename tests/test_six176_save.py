""""Marco, save my 6176" on WhatsApp: what SAM sees, the reading in one line, kept as the recall (Owner 2026-11-04)."""

import io
import json

import httpx
import pytest
from PIL import Image

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.marco import Marco
from hiremarco.meta.client import MuseSpark
from hiremarco.sam import Box
from hiremarco.server import handle
from hiremarco.studio import six176
from hiremarco.whatsapp import Inbound, WhatsApp
from hiremarco.whatsapp.client import record_inbound

OWNER = "13055550100"
BOXES = [Box(100, 110, 180, 190, 1600, 900, 0.9), Box(400, 100, 480, 180, 1600, 900, 0.9),
         Box(700, 105, 780, 185, 1600, 900, 0.9)]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1600, 900), (40, 40, 44)).save(out, "JPEG", quality=90)
    return out.getvalue()


def spark(tmp_path, readings, seen=None):
    def handler(request):
        (seen if seen is not None else []).append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-spark-1.3", "choices": [{"message": {
            "content": json.dumps({"readings": readings})}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 80}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


TWO_READ = [{"knob": 1, "label": "GAIN", "setting": "40"}, {"knob": 2, "label": "INPUT", "setting": "2 o'clock"}]


@pytest.mark.parametrize("said, wanted", [
    ("Marco, save my 6176", True), ("save my 61 76", True), ("Marco, read the 6176 for me", True),
    ("keep my 6176 settings", True), ("6176 recall", True), ("Marco, dress me", False), ("save the session", False),
])
def test_wants(said, wanted):
    assert six176.wants(said) is wanted


def test_save_sends_what_sam_sees_reads_and_keeps_the_recall(tmp_path):
    photo = tmp_path / "unit.jpg"
    photo.write_bytes(jpeg())
    sent = []
    saved = six176.save(photo, send=lambda pic, caption, step: sent.append((caption, step, pic[:2])),
                        client=spark(tmp_path, TWO_READ), find=lambda *a, **k: BOXES)
    assert sent == [("I see 3 knobs. Reading them now.", "sees", b"\xff\xd8")]
    assert saved.note == "6176: GAIN 40; INPUT 2 o'clock" and saved.found == 3 and saved.picture.exists()
    kept = six176.latest_recall()
    assert kept["note"] == saved.note and kept["found"] == 3 and len(kept["readings"]) == 2


def test_nothing_read_is_not_a_recall(tmp_path):
    photo = tmp_path / "unit.jpg"
    photo.write_bytes(jpeg())
    saved = six176.save(photo, send=None, client=spark(tmp_path, []), find=lambda *a, **k: BOXES)
    assert saved.readings == [] and six176.latest_recall() is None


def line(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    rules = tmp_path / "RULES.md"
    rules.write_text(f"send: whatsapp -> {OWNER} ; the Owner's own chat ; until 2099-01-01\n")
    sent, picture = [], jpeg()

    def respond(request):
        if request.url.host == "lookaside.example":
            return httpx.Response(200, content=picture)
        if request.url.path.endswith("/photo-1"):
            return httpx.Response(200, json={"url": "https://lookaside.example/photo-1", "mime_type": "image/jpeg"})
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "up-1"})
        body = json.loads(request.content)
        if body.get("type") in ("text", "image"):
            sent.append(body)
        return httpx.Response(200, json={"messages": [{"id": "wamid.o"}]})

    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"),
                  transport=httpx.MockTransport(respond), rules_path=rules)
    monkeypatch.setattr(six176, "segment", lambda *a, **k: BOXES)
    return wa, sent


def arrive(wa, mid, **kw):
    record_inbound(wa.conn, mid, OWNER, kw.get("kind", "text"))
    return Inbound(id=mid, sender=OWNER, **kw)


def test_the_photo_with_his_words_gets_the_picture_then_the_line(tmp_path, monkeypatch):
    wa, sent = line(tmp_path, monkeypatch)
    out = handle(arrive(wa, "w1", kind="image", media_id="photo-1", caption="Marco, save my 6176"), wa=wa,
                 marco=Marco(spark(tmp_path, TWO_READ)))
    assert "6176 saved: 6176: GAIN 40; INPUT 2 o'clock (2 of 3 knobs read)" in out
    assert [m["type"] for m in sent] == ["image", "text"]
    assert sent[0]["image"]["caption"] == "I see 3 knobs. Reading them now."
    assert sent[1]["text"]["body"] == ("6176: GAIN 40; INPUT 2 o'clock. 1 I couldn't read for sure, so I left it out. "
                                       "Saved as your recall.")


def test_his_words_first_wait_for_the_photo(tmp_path, monkeypatch):
    wa, sent = line(tmp_path, monkeypatch)
    marco = Marco(spark(tmp_path, TWO_READ[:1]))
    out = handle(arrive(wa, "w1", kind="text", text="Marco, save my 6176"), wa=wa, marco=marco)
    assert "6176: waiting for the photo" in out and sent[-1]["text"]["body"].startswith("Send me a photo of the 6176")
    out = handle(arrive(wa, "w2", kind="image", media_id="photo-1"), wa=wa, marco=marco,
                 settle=lambda s: pytest.fail("the waiting words take the photo at once"))
    assert "6176 saved: 6176: GAIN 40 (1 of 3 knobs read)" in out and six176.waiting() is None


def test_no_knobs_is_said_and_nothing_is_kept(tmp_path, monkeypatch):
    wa, sent = line(tmp_path, monkeypatch)
    monkeypatch.setattr(six176, "segment", lambda *a, **k: [])
    out = handle(arrive(wa, "w1", kind="image", media_id="photo-1", caption="Marco, save my 6176"), wa=wa,
                 marco=Marco(spark(tmp_path, TWO_READ)))
    assert "6176: no knob found" in out and sent[-1]["text"]["body"].startswith("I couldn't find the knobs")
    assert six176.latest_recall() is None

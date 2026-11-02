"""Photos in (Owner 2026-11-01): any photo he sends is kept in a dated folder, remembered in the conversation, and
seen with his words, whether they come with it, just before it or just after it, typed or spoken."""

import io
import json
from datetime import datetime, timedelta, timezone

import httpx
from PIL import Image

from hiremarco import config, gate
from hiremarco.meta.client import MuseSpark, Reply
from hiremarco.joblog import JobLog
from hiremarco.server import handle
from hiremarco.whatsapp import Inbound, WhatsApp, photos
from hiremarco.whatsapp.client import record_inbound
from hiremarco.whatsapp.memory import recall

OWNER = "13055550100"


def jpeg(size=(60, 40), color=(200, 30, 30), orientation=None) -> bytes:
    image = Image.new("RGB", size, color)
    out = io.BytesIO()
    if orientation:
        exif = image.getexif()
        exif[0x0112] = orientation
        image.save(out, "JPEG", exif=exif)
    else:
        image.save(out, "JPEG")
    return out.getvalue()


def line(tmp_path, monkeypatch, picture: bytes | None = None):
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    rules = tmp_path / "RULES.md"
    rules.write_text(f"send: whatsapp -> {OWNER} ; the Owner's own chat ; until 2099-01-01\n")
    sent = []

    def respond(request):
        if request.url.host == "lookaside.example":
            return httpx.Response(200, content=picture or jpeg())
        if request.url.path.endswith("/photo-1"):
            return httpx.Response(200, json={"url": "https://lookaside.example/photo-1", "mime_type": "image/jpeg"})
        sent.append(json.loads(request.content) if request.content.startswith(b"{") else request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.o"}], "id": "m1"})

    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"),
                  transport=httpx.MockTransport(respond), rules_path=rules)
    return wa, sent


def arrive(wa, mid, ts=None, **kw):
    record_inbound(wa.conn, mid, OWNER, kw.get("kind", "text"), ts=ts)
    return Inbound(id=mid, sender=OWNER, **kw)


class Brain:
    def __init__(self, reply="nice."):
        self.reply, self.seen = reply, []

    def converse(self, history, text, **kw):
        self.seen.append({"text": json.loads(text), **kw})
        return Reply(text=json.dumps({"action": "reply", "title": "", "reply": self.reply, "remember": [],
                                      "forget": []}), model="m", prompt_tokens=0, completion_tokens=0,
                     cached_tokens=0, cost_usd=0.0, duration_ms=0)


def texts(sent):
    return [m["text"]["body"] for m in sent if isinstance(m, dict) and m.get("type") == "text"]


def test_a_photo_is_kept_upright_in_a_dated_folder_and_remembered(tmp_path):
    conn = gate.connect(":memory:")
    now = datetime(2026, 11, 2, 14, 5, tzinfo=timezone.utc)
    photo = photos.keep(conn, jpeg((60, 40), orientation=6), "wamid.abcdef123456", "my clothes", now=now)
    assert photo.path.parent == config.STATE_DIR / "photos" / now.astimezone().strftime("%Y-%m-%d")
    assert Image.open(photo.path).size == (40, 60)                     # turned the way the phone held it
    assert recall(conn)[-1][1:] == ("felix", f"[sent a photo: {photo.path.name}] my clothes")
    assert photos.latest(conn, now + timedelta(minutes=9)).id == photo.id
    assert photos.latest(conn, now + timedelta(minutes=11)) is None    # a photo counts as his latest for ten minutes


def test_a_photo_with_words_goes_to_the_brain_with_the_words_and_the_picture(tmp_path, monkeypatch):
    wa, sent = line(tmp_path, monkeypatch)
    brain = Brain("that's a red shirt.")
    out = handle(arrive(wa, "w1", kind="image", media_id="photo-1", caption="what color is this?"), wa=wa,
                 marco=brain, settle=lambda s: (_ for _ in ()).throw(AssertionError("no wait with words")))
    assert "photo kept" in out and "brain: reply" in out
    seen = brain.seen[-1]
    assert seen["text"]["felix_says"] == "what color is this?"
    assert seen["text"]["photo_attached"].endswith("saying: what color is this?")
    assert seen["image_url"].startswith("data:image/jpeg;base64,")
    assert texts(sent) == ["that's a red shirt."]


def test_a_photo_alone_waits_for_his_words_and_lets_them_take_it(tmp_path, monkeypatch):
    wa, sent = line(tmp_path, monkeypatch)
    brain = Brain()
    t0 = datetime.now(timezone.utc)
    msg = arrive(wa, "w1", ts=t0, kind="image", media_id="photo-1")
    out = handle(msg, wa=wa, marco=brain,
                 settle=lambda s: record_inbound(wa.conn, "w2", OWNER, "text", ts=t0 + timedelta(seconds=4)))
    assert "his next message says what it is for" in out
    assert brain.seen == [] and texts(sent) == []
    # his words a moment later: the brain sees the photo with them
    handle(Inbound(id="w2", sender=OWNER, kind="text", text="is this too much for dinner?"), wa=wa, marco=brain)
    assert brain.seen[-1]["image_url"].startswith("data:image/jpeg")
    assert "photo_attached" in brain.seen[-1]["text"]


def test_a_photo_alone_with_no_words_after_it_is_answered(tmp_path, monkeypatch):
    wa, sent = line(tmp_path, monkeypatch)
    waited = []
    brain = Brain("a red shirt on the bed. want me to do something with it?")
    out = handle(arrive(wa, "w1", kind="image", media_id="photo-1"), wa=wa, marco=brain, settle=waited.append)
    assert waited == [20.0] and "brain: reply" in out
    assert brain.seen[-1]["text"]["felix_says"] == "(he sent this photo without a word)"
    assert texts(sent) == ["a red shirt on the bed. want me to do something with it?"]


def test_words_before_the_photo_count_too_and_an_old_photo_does_not(tmp_path, monkeypatch):
    wa, sent = line(tmp_path, monkeypatch)
    brain = Brain()
    photo = photos.keep(wa.conn, jpeg(), "w0", now=datetime.now(timezone.utc) - timedelta(minutes=30))
    handle(arrive(wa, "w1", kind="text", text="what do you think?"), wa=wa, marco=brain)
    assert "photo_attached" not in brain.seen[-1]["text"] and brain.seen[-1]["image_url"] is None
    assert photo.path.exists()  # kept, only too old to be the one he means


def test_a_voice_note_after_a_photo_carries_it(tmp_path, monkeypatch):
    from hiremarco import server

    wa, sent = line(tmp_path, monkeypatch)
    photos.keep(wa.conn, jpeg(), "w0")
    monkeypatch.setattr(server, "voice_text", lambda message, wa, listen=None: "what goes with this?")
    brain = Brain()
    handle(arrive(wa, "w1", kind="audio", media_id="v-1", voice=True), wa=wa, marco=brain)
    assert brain.seen[-1]["text"]["felix_says"] == "what goes with this?"
    assert brain.seen[-1]["image_url"].startswith("data:image/jpeg")


def test_a_photo_still_downloading_is_waited_for(tmp_path):
    conn = gate.connect(":memory:")
    record_inbound(conn, "w1", OWNER, "image")
    assert photos.on_its_way(conn, OWNER)
    naps = []

    def nap(s):
        naps.append(s)
        photos.keep(conn, jpeg(), "w1")

    assert photos.wait_for(conn, OWNER, sleep=nap).message_id == "w1"
    assert naps == [2.0] and not photos.on_its_way(conn, OWNER)
    assert photos.wait_for(gate.connect(":memory:"), OWNER, sleep=lambda s: 1 / 0) is None  # nothing coming


def test_when_the_brain_is_down_marco_still_looks_at_the_photo(tmp_path, monkeypatch):
    wa, sent = line(tmp_path, monkeypatch)
    asked = []

    def muse(request):
        body = json.loads(request.content)
        asked.append(body)
        if body.get("response_format"):
            return httpx.Response(500, json={})
        return httpx.Response(200, json={"model": "muse-spark-1.3", "choices": [{"message": {
            "content": "That's a red shirt."}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 900,
                                                                                  "completion_tokens": 9}})

    from hiremarco.marco import Marco

    client = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(muse))
    out = handle(arrive(wa, "w1", kind="image", media_id="photo-1", caption="what is it?"), wa=wa,
                 marco=Marco(client))
    assert "brain unavailable: MuseSparkError > answered the photo" in out
    content = asked[-1]["messages"][1]["content"]
    assert content[0]["text"] == "what is it?" and content[1]["type"] == "image_url"
    assert texts(sent) == ["That's a red shirt."]

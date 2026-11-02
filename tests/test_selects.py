"""The selects (Owner 2026-11-01): a burst of frames is one shoot, SAM finds him in each, the contact sheet goes first,
then his three, one picture at a time, each with one honest line. His frames are never edited."""

import io
import json
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from hiremarco import config, dress, gate, selects
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark, Reply
from hiremarco.sam import Box, Found, SamError
from hiremarco.server import handle
from hiremarco.whatsapp import Inbound, WhatsApp, photos
from hiremarco.whatsapp.client import record_inbound
from hiremarco.whatsapp.facts import keep as keep_fact
from hiremarco.whatsapp.webhook import parse_payload

OWNER = "13055550100"
W, H = 900, 1200
# where he stands in the frame, on the same pixels SAM is told about: the frames are drawn at W x H
BODY = (250, 200, 650, 1100)


def frame_image(shade=120, sharp=True, body=BODY) -> Image.Image:
    rng = np.random.default_rng(shade)
    image = Image.fromarray(np.full((H, W, 3), shade, dtype=np.uint8))
    person = Image.fromarray(rng.integers(0, 255, (H, W, 3), dtype=np.uint8))
    if not sharp:
        person = person.filter(ImageFilter.GaussianBlur(8))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse(body, fill=255)
    image.paste(person, mask=mask)
    return image


def jpeg(image: Image.Image, **kw) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", quality=95, **kw)
    return out.getvalue()


def found(body=BODY, confidence=0.9, size=(W, H)) -> Found:
    x1, y1, x2, y2 = body
    w, h = x2 - x1 + 1, y2 - y1 + 1
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse((0, 0, w - 1, h - 1), fill=1)
    return Found(Box(x1, y1, x2, y2, size[0], size[1], confidence), bytes(np.asarray(m).astype(np.uint8).ravel()), (w, h))


def fake_find(answers=None):
    """SAM: finds him in every frame unless ``answers`` says otherwise, by call order."""
    calls = []

    def find(data, phrase, **kw):
        calls.append(phrase)
        got = (answers or {}).get(len(calls))
        if isinstance(got, Exception):
            raise got
        return [found()] if got is None else got

    find.calls = calls
    return find


def spark(tmp_path, seen, answers=None) -> MuseSpark:
    answers = list(answers or [])

    def respond(request):
        body = json.loads(request.content)
        seen.append(body)
        answer = answers.pop(0) if answers else {
            "picks": [{"frame": 2, "line": "Your eyes are on it and the light holds your face."},
                      {"frame": 1, "line": "Good stance, though your feet are tight to the edge."},
                      {"frame": 3, "line": "The jacket reads clean here."}],
            "others": "The rest were soft or you were looking away."}
        return httpx.Response(200, json={
            "choices": [{"message": {"content": answer if isinstance(answer, str) else json.dumps(answer)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10}})

    return MuseSpark(api_key="k", transport=httpx.MockTransport(respond), joblog=JobLog(tmp_path / "jobs.jsonl"))


class Marco:
    """The brain a text falls through to; ``client`` is what the selects call."""

    def __init__(self, client=None, reply="on it."):
        self.client, self.reply, self.seen = client, reply, []

    def converse(self, history, text, **kw):
        self.seen.append({"text": json.loads(text), **kw})
        return Reply(text=json.dumps({"action": "reply", "title": "", "reply": self.reply, "remember": [],
                                      "forget": []}), model="m", prompt_tokens=0, completion_tokens=0,
                     cached_tokens=0, cost_usd=0.0, duration_ms=0)


class Line:
    def __init__(self, tmp_path, monkeypatch, picture: bytes | None = None, find=None):
        monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
        monkeypatch.setenv("HIREMARCO_DRESS_FILM_DIR", str(tmp_path / "film"))
        (tmp_path / "film").mkdir(exist_ok=True)
        rules = tmp_path / "RULES.md"
        rules.write_text(f"send: whatsapp -> {OWNER} ; the Owner's own chat ; until 2099-01-01\n")
        self.sent, self.uploads = [], []
        self.picture = picture or jpeg(frame_image())

        def respond(request):
            if request.url.host == "lookaside.example":
                return httpx.Response(200, content=self.picture)
            if "/photo-" in request.url.path:
                return httpx.Response(200, json={"url": "https://lookaside.example/p", "mime_type": "image/jpeg"})
            if request.url.path.endswith("/media"):
                self.uploads.append(request.content)
                return httpx.Response(200, json={"id": f"up-{len(self.uploads)}"})
            body = json.loads(request.content)
            if body.get("type") in ("text", "image", "reaction"):
                self.sent.append(body)
            return httpx.Response(200, json={"messages": [{"id": "wamid.o"}]})

        self.wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"),
                           transport=httpx.MockTransport(respond), rules_path=rules)
        self.find = find or fake_find()
        monkeypatch.setattr(selects, "segment_masks", self.find)

    def arrive(self, mid, ts=None, **kw) -> Inbound:
        record_inbound(self.wa.conn, mid, OWNER, kw.get("kind", "text"), ts=ts)
        return Inbound(id=mid, sender=OWNER, **kw)

    def frames(self, n, start=0):
        """``n`` frames with no words, all reaching the webhook while the first still waits, the way a burst does."""
        return [self.arrive(f"f{i}", kind="image", media_id=f"photo-{i}") for i in range(start, start + n)]

    def texts(self):
        return [m["text"]["body"] for m in self.sent if m["type"] == "text"]

    def captions(self):
        return [m["image"]["caption"] for m in self.sent if m["type"] == "image"]


def burst(line: Line, n=14, marco=None, start=0) -> list[str]:
    """All the frames arrive first, then each handler runs and waits: every one but the last sees a newer message."""
    return [handle(m, wa=line.wa, marco=marco or Marco(), settle=lambda s: None) for m in line.frames(n, start)]


# --- bursts -------------------------------------------------------------------------------------------------------

def test_a_burst_gets_one_short_line_and_no_reply_per_frame(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    marco = Marco()
    out = burst(line, 14, marco)
    assert line.texts() == ["Got 14 frames."]
    assert marco.seen == []  # no frame went to the brain
    assert "burst: 14 frames" in out[-1]
    assert sum("his next message says what it is for" in o for o in out) == 13
    assert len(selects.shoot(line.wa.conn)[0]) == 14


def test_the_line_waits_out_a_slow_frame_and_a_frame_landing_in_the_wait_takes_over(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    first = burst(line, 3, Marco())  # the first three settle here, and the last one spoke
    assert line.texts() == ["Got 3 frames."]
    waits = []

    def slow(seconds):
        waits.append(seconds)
        if len(waits) == 2:  # the next frame lands during the long wait
            record_inbound(line.wa.conn, "f9", OWNER, "image",
                           ts=datetime.now(timezone.utc) + timedelta(seconds=1))

    out = handle(line.arrive("f8", kind="image", media_id="photo-8"), wa=line.wa, marco=Marco(), settle=slow)
    assert waits == [20.0, 25.0] and line.texts() == ["Got 3 frames."]
    assert "next message" in out and first


def test_a_photo_on_its_own_is_still_answered_by_the_brain(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    marco = Marco(reply="a hallway. what do you want me to do with it?")
    out = handle(line.arrive("p1", kind="image", media_id="photo-1"), wa=line.wa, marco=marco, settle=lambda s: None)
    assert "brain: reply" in out and line.texts() == ["a hallway. what do you want me to do with it?"]


def test_photos_an_hour_apart_are_not_a_burst(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    t0 = datetime.now(timezone.utc) - timedelta(minutes=80)
    for i in range(4):
        photos.keep(line.wa.conn, line.picture, f"old{i}", now=t0 + timedelta(minutes=20 * i))
    assert selects.burst(line.wa.conn) == 1
    marco = Marco()
    assert "brain: reply" in handle(line.arrive("p9", kind="image", media_id="photo-9"), wa=line.wa, marco=marco,
                                    settle=lambda s: None)


def test_a_text_in_the_middle_of_a_burst_is_handled_at_once_and_not_swallowed(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    marco = Marco(reply="setting it up.")
    burst(line, 5, marco)
    line.sent.clear()
    never = lambda s: pytest.fail("a text waits for nothing")  # noqa: E731
    out = handle(line.arrive("t1", kind="text", text="set up my session"), wa=line.wa, marco=marco, settle=never)
    assert "brain: reply" in out and line.texts() == ["setting it up."]
    assert marco.seen[-1]["text"]["felix_says"] == "set up my session"
    assert marco.seen[-1].get("image_url") is None  # the last frame is not what he is talking about
    # the rest of the burst goes on, one line at the end for all of it
    burst(line, 6, marco, start=20)
    assert line.texts() == ["setting it up.", "Got 11 frames."]


def test_a_voice_note_in_the_middle_of_a_burst_is_handled_at_once_too(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    marco = Marco(reply="setting it up.")
    burst(line, 5, marco)
    line.sent.clear()
    from hiremarco import server
    monkeypatch.setattr(server, "voice_text", lambda m, wa, listen=None: "set up my session")
    out = handle(line.arrive("v2", kind="audio", media_id="photo-v", voice=True), wa=line.wa, marco=marco,
                 settle=lambda s: pytest.fail("a voice note waits for nothing"))
    assert "brain: reply" in out and line.texts() == ["setting it up."]
    assert marco.seen[-1].get("image_url") is None


def test_words_about_the_frame_mid_burst_still_see_it(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    marco = Marco()
    burst(line, 4, marco)
    handle(line.arrive("t1", kind="text", text="is this one too dark?"), wa=line.wa, marco=marco)
    assert marco.seen[-1]["image_url"].startswith("data:image/jpeg")


# --- documents and formats ----------------------------------------------------------------------------------------

def document(mime, name, mid="d1"):
    return {"entry": [{"changes": [{"value": {"messages": [{
        "id": mid, "from": OWNER, "type": "document", "timestamp": "1",
        "document": {"id": "photo-doc", "mime_type": mime, "filename": name}}]}}]}]}


@pytest.mark.parametrize("mime, name, kind", [
    ("image/jpeg", "DSC01.JPG", "image"),
    ("image/heic", "IMG_1.HEIC", "image"),
    ("application/octet-stream", "DSC02.ARW", "image"),
    ("image/x-sony-arw", "DSC03.arw", "image"),
    ("audio/mpeg", "beat.mp3", "document"),
    ("audio/wav", "beat.wav", "document"),
    ("application/pdf", "contract.pdf", "document"),
])
def test_a_document_that_is_a_photo_arrives_as_a_photo(mime, name, kind):
    message = parse_payload(document(mime, name))[0]
    assert message.kind == kind and message.media_id == "photo-doc" and message.filename == name


def test_a_jpeg_sent_as_a_document_is_kept_as_a_photo_full_size_and_never_taken_for_a_beat(tmp_path, monkeypatch):
    big = jpeg(frame_image().resize((3600, 4800)))
    line = Line(tmp_path, monkeypatch, big)
    message = parse_payload(document("image/jpeg", "DSC01.JPG"))[0]
    record_inbound(line.wa.conn, message.id, OWNER, message.kind)
    waits = []
    out = handle(message, wa=line.wa, marco=Marco(), settle=waits.append)
    assert "photo kept" in out and "beat" not in out
    assert not list((config.STATE_DIR).glob("**/received/*"))
    frame = selects.shoot(line.wa.conn)[0][0]
    assert max(Image.open(frame.path).size) == 2048      # what the models see
    assert frame.original.read_bytes() == big            # what he sent, whole
    assert frame.original.suffix == ".jpg"
    assert waits == [45.0]                               # a document gets the long wait: the next one is slow to come


@pytest.mark.skipif(not shutil.which("sips"), reason="macOS sips turns HEIC into JPEG")
def test_a_heic_sent_as_a_document_is_kept_as_a_photo(tmp_path, monkeypatch):
    import subprocess

    src = tmp_path / "f.jpg"
    src.write_bytes(jpeg(frame_image()))
    subprocess.run(["sips", "-s", "format", "heic", str(src), "--out", str(tmp_path / "f.heic")], check=True,
                   capture_output=True)
    heic = (tmp_path / "f.heic").read_bytes()
    line = Line(tmp_path, monkeypatch, heic)
    message = parse_payload(document("image/heic", "IMG_1.HEIC"))[0]
    record_inbound(line.wa.conn, message.id, OWNER, message.kind)
    handle(message, wa=line.wa, marco=Marco(), settle=lambda s: None)
    frame = selects.shoot(line.wa.conn)[0][0]
    assert Image.open(frame.path).size == (W, H) and frame.original.read_bytes() == heic


@pytest.mark.parametrize("fmt, name", [("PNG", "f.png"), ("WEBP", "f.webp"), ("TIFF", "f.tif")])
def test_other_photo_files_are_read_too(fmt, name):
    out = io.BytesIO()
    frame_image().save(out, fmt)
    made = photos.upright(out.getvalue(), suffix=photos.suffix_of(name, ""))
    assert Image.open(io.BytesIO(made)).size == (W, H) and photos.is_photo_file("", name)


def test_a_very_large_frame_is_cut_down_for_the_models(tmp_path):
    conn = gate.connect(":memory:")
    big = jpeg(frame_image().resize((6336, 9504), Image.NEAREST))
    photo = photos.keep(conn, big, "huge", suffix=".jpg")
    assert max(Image.open(photo.path).size) == 2048 and photo.original.read_bytes() == big


def test_a_raw_goes_to_sips_and_never_to_pillow(monkeypatch):
    # an ARW is built on TIFF: Pillow would read its tiny thumbnail as the photo
    called = []
    monkeypatch.setattr(photos, "through_sips", lambda data, suffix: called.append(suffix) or jpeg(frame_image()))
    thumbnail_shaped_like_tiff = io.BytesIO()
    Image.new("RGB", (160, 120)).save(thumbnail_shaped_like_tiff, "TIFF")
    made = photos.upright(thumbnail_shaped_like_tiff.getvalue(), suffix=".arw")
    assert called == [".arw"] and Image.open(io.BytesIO(made)).size == (W, H)


def test_a_file_that_cannot_be_read_gets_one_plain_line_for_the_whole_burst(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch, b"not a photo at all")

    def no_sips(data, suffix):
        raise photos.Unreadable("sips could not read it")

    monkeypatch.setattr(photos, "through_sips", no_sips)
    marco = Marco()
    out = [handle(line.arrive(f"r{i}", kind="image", media_id=f"photo-{i}", filename=f"D{i}.ARW"), wa=line.wa,
                  marco=marco, settle=lambda s: None) for i in range(4)]
    assert line.texts() == ["I can't open that one. Send your frames as JPEG?"]
    assert "photo not kept" in out[0] and "held" in out[1] and marco.seen == []
    assert not photos.on_its_way(line.wa.conn, OWNER)    # nothing waits for a frame that will not come
    assert selects.shoot(line.wa.conn) == ([], 0)


def test_twenty_frames_at_once_are_all_kept_even_when_the_ends_of_their_ids_match(tmp_path):
    """The webhook runs each message on its own thread, each with its own handle on the database; a real WhatsApp id
    ends in the same few letters for many messages and can hold a slash."""
    path = tmp_path / "gate.sqlite"
    picture = jpeg(frame_image().resize((300, 400)))
    moment = datetime.now(timezone.utc)
    errors = []

    def one(i):
        try:
            conn = gate.connect(path)
            record_inbound(conn, f"wamid.{i}/SAME=", OWNER, "image")
            photos.keep(conn, picture, f"wamid.{i}/SAME=", now=moment)
            conn.close()
        except Exception as exc:  # any lost frame fails the test
            errors.append(exc)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    conn = gate.connect(path)
    frames, total = selects.shoot(conn)
    assert total == 20 and len({f.path for f in frames}) == 20 and all(f.path.exists() for f in frames)


# --- the set ------------------------------------------------------------------------------------------------------

def test_the_shoot_starts_after_the_last_dress_me_and_leaves_out_its_clothes(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    conn = line.wa.conn
    clothes = photos.keep(conn, line.picture, "clothes")
    dress._state(conn).execute("insert into dress (ts, status, photo) values (?, 'picked', ?)",
                               (datetime.now(timezone.utc).isoformat(), str(clothes.path)))
    a = photos.keep(conn, line.picture, "a")
    b = photos.keep(conn, line.picture, "b")
    assert [f.id for f in selects.shoot(conn)[0]] == [a.id, b.id]


def test_the_shoot_starts_after_the_last_selects_unless_that_run_failed(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    conn = line.wa.conn
    a = photos.keep(conn, line.picture, "a")
    row = selects.begin(conn, a.id, 1)
    assert selects.shoot(conn) == ([], 0) and selects.running(conn) and selects.taken(conn, a)
    selects.finish(conn, row, "failed")
    assert [f.id for f in selects.shoot(conn)[0]] == [a.id] and not selects.running(conn)
    row = selects.begin(conn, a.id, 1)
    selects.finish(conn, row, "done", [1])
    b = photos.keep(conn, line.picture, "b")
    assert [f.id for f in selects.shoot(conn)[0]] == [b.id]


def test_a_run_that_died_gives_its_frames_back(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    conn = line.wa.conn
    a = photos.keep(conn, line.picture, "a")
    selects.begin(conn, a.id, 1, now=datetime.now(timezone.utc) - timedelta(minutes=6))
    assert not selects.running(conn) and [f.id for f in selects.shoot(conn)[0]] == [a.id]


def test_the_shoot_has_a_window_and_a_cap(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    conn = line.wa.conn
    now = datetime.now(timezone.utc)
    picture = jpeg(frame_image().resize((90, 120)))
    photos.keep(conn, picture, "old", now=now - timedelta(minutes=91))
    kept = [photos.keep(conn, picture, f"n{i}", now=now - timedelta(minutes=60)) for i in range(32)]
    frames, total = selects.shoot(conn, now)
    assert total == 32 and [f.id for f in frames] == [k.id for k in kept[-30:]]


@pytest.mark.parametrize("said, asked", [
    ("Marco, pick my selects", True), ("my selects?", True), ("show me the selects", True), ("selects please", True),
    ("which are the best three?", True), ("Which are the best three, Marco?", True), ("best 3 shots", True),
    ("pick the best ones", True), ("which frames should I keep?", True), ("what are the best photos", True),
    ("which are the best three restaurants?", False), ("set up my session", False),
    ("select the second take", False), ("best three plugins for vocals", False), ("Marco, dress me", False),
])
def test_how_he_asks(said, asked):
    assert selects.wants(said) is asked


# --- SAM and the measures -----------------------------------------------------------------------------------------

def framed(tmp_path, image, number=1) -> selects.Frame:
    path = tmp_path / f"frame{number}.jpg"
    path.write_bytes(jpeg(image))
    return selects.Frame(number, path, path)


def test_one_call_per_frame_for_him_and_what_the_mask_measures(tmp_path):
    frame = framed(tmp_path, frame_image())
    find = fake_find()
    assert selects.find_him(frame, find=find) is None
    assert find.calls == ["person"]
    area = np.pi * 200 * 450  # the ellipse in BODY
    assert frame.fill == pytest.approx(area / (W * H), rel=0.02)
    assert frame.cut == [] and frame.people == 1 and frame.usable


def test_the_sharp_frame_measures_sharper_than_the_soft_one(tmp_path):
    sharp, soft = framed(tmp_path, frame_image(), 1), framed(tmp_path, frame_image(sharp=False), 2)
    selects.find_him(sharp, find=fake_find())
    selects.find_him(soft, find=fake_find())
    assert sharp.sharp > 10 * soft.sharp > 0


def test_a_clean_edge_around_him_does_not_read_as_focus(tmp_path):
    """A soft body against a flat wall: its outline is a hard edge, and sharpness is read inside it."""
    body = Image.new("L", (W, H), 0)
    ImageDraw.Draw(body).ellipse(BODY, fill=255)
    image = Image.new("RGB", (W, H), (20, 20, 20))
    image.paste((220, 220, 220), mask=body)
    frame = framed(tmp_path, image)
    selects.find_him(frame, find=fake_find())
    assert frame.sharp < 5


def test_the_light_on_him_is_read_on_him(tmp_path):
    body = Image.new("L", (W, H), 0)
    ImageDraw.Draw(body).ellipse(BODY, fill=255)
    image = Image.new("RGB", (W, H), (5, 5, 5))
    image.paste((255, 255, 255), mask=body)
    frame = framed(tmp_path, image)
    selects.find_him(frame, find=fake_find())
    assert frame.light > 0.9 and frame.blown > 0.8 and frame.crushed < 0.1


@pytest.mark.parametrize("body, cut", [
    ((250, 200, 650, 1199), ["bottom"]), ((0, 200, 400, 1000), ["left"]), ((500, 0, 899, 1199), ["top", "bottom", "right"]),
])
def test_cut_off_at_an_edge(tmp_path, body, cut):
    frame = framed(tmp_path, frame_image(body=body))
    selects.find_him(frame, find=lambda *a, **k: [found(body)])
    assert frame.cut == cut


def test_several_people_keep_the_largest_and_the_log_says_so(tmp_path):
    frame = framed(tmp_path, frame_image())
    small = (10, 10, 120, 200)
    line = selects.find_him(frame, find=lambda *a, **k: [found(small), found(), found((700, 10, 800, 90), 0.3)])
    assert frame.person.box[:2] == (250, 200) and frame.people == 2
    assert line == "frame 1: 2 people, kept the largest"


def test_a_frame_with_nobody_is_not_usable_nor_one_where_he_is_a_speck(tmp_path):
    empty, speck = framed(tmp_path, frame_image(), 1), framed(tmp_path, frame_image(), 2)
    selects.find_him(empty, find=lambda *a, **k: [])
    selects.find_him(speck, find=lambda *a, **k: [found((10, 10, 30, 50))])
    assert not empty.usable and not speck.usable and speck.person is not None


def test_sam_gets_a_smaller_copy_and_the_mask_lands_back_on_the_full_frame(tmp_path):
    big = frame_image().resize((1536, 2048))
    frame = framed(tmp_path, big)
    seen = []

    def find(data, phrase, **kw):
        seen.append(Image.open(io.BytesIO(data)).size)
        return [found((200, 150, 760, 1200), size=(960, 1280))]

    selects.find_him(frame, find=find)
    assert seen == [(960, 1280)] and frame.size == (1536, 2048)
    assert frame.person.box[0] == 320 and frame.person.box[3] == 1920


def test_a_failed_call_is_tried_again_and_a_frame_that_keeps_failing_is_left_out(tmp_path):
    frames = [framed(tmp_path, frame_image(), i) for i in (1, 2)]
    tries = {}

    def flaky(data, phrase, **kw):
        tries["n"] = tries.get("n", 0) + 1
        if tries["n"] == 1:
            raise SamError("http 500")
        return [found()]

    assert selects.find_him(frames[0], find=flaky, wait=lambda s: None) is None and frames[0].usable

    def down(*a, **k):
        raise SamError("http 500")

    assert "http 500" in selects.find_him(frames[1], find=down, wait=lambda s: None) and frames[1].failed
    with pytest.raises(SamError):
        selects.find_all([framed(tmp_path, frame_image(), 3)], find=down, wait=lambda s: None)


def test_sam_runs_in_parallel_with_a_limit(tmp_path):
    frames = [framed(tmp_path, frame_image().resize((90, 120)), i) for i in range(1, 21)]
    lock, now_running, most = threading.Lock(), [0], [0]

    def find(data, phrase, **kw):
        with lock:
            now_running[0] += 1
            most[0] = max(most[0], now_running[0])
        time.sleep(0.05)
        with lock:
            now_running[0] -= 1
        return [found(size=(90, 120), body=(20, 20, 70, 110))]

    started = time.monotonic()
    selects.find_all(frames, find=find)
    assert 1 < most[0] <= selects.SAM_WORKERS and time.monotonic() - started < 20 * 0.05 / 2


# --- the contact sheet --------------------------------------------------------------------------------------------

def sheet_of(tmp_path, n, size=(W, H)):
    frames = []
    for i in range(1, n + 1):
        f = framed(tmp_path, frame_image(100 + i).resize(size), i)
        selects.find_him(f, find=lambda *a, **k: [found(size=(W, H))])
        frames.append(f)
    return frames


@pytest.mark.parametrize("n", [12, 14, 20, 30])
def test_the_contact_sheet_fits_every_frame_big_enough_for_a_phone(tmp_path, n):
    frames = sheet_of(tmp_path, n, (225, 300))
    sheet = selects.contact_sheet(frames)
    assert sheet.width <= 1800 and sheet.height <= 2400
    cols, rows, cell_w, cell_h = selects._grid(n, 0.75, selects.SHEET, 14)
    assert cols * rows >= n
    # a phone shows the sheet about 1100 px wide: each number's badge stays over 25 px across even at 30 frames
    assert 2 * max(26, round(min(cell_w, cell_h) * 0.15)) * 1100 / sheet.width >= 25
    if n <= 20:
        assert cell_w >= 300


def test_the_contact_sheet_tints_him_and_dims_a_frame_with_nobody(tmp_path):
    frames = sheet_of(tmp_path, 2)
    frames[1].person = None
    sheet = np.asarray(selects.contact_sheet(frames)).astype(int)
    plain = np.asarray(selects.contact_sheet(frames, tinted=False)).astype(int)
    half = sheet.shape[1] // 2
    assert (sheet[..., 2] - sheet[..., 0])[:, :half].mean() > (plain[..., 2] - plain[..., 0])[:, :half].mean() + 10
    assert sheet[:, half:].mean() < plain[:, half:].mean() - 10


def test_the_contact_sheet_handles_wide_and_tall_frames_together(tmp_path):
    frames = sheet_of(tmp_path, 3) + [framed(tmp_path, frame_image().resize((1200, 900)), 4)]
    selects.find_him(frames[3], find=lambda *a, **k: [found(size=(1200, 900), body=(100, 100, 800, 800))])
    assert selects.contact_sheet(frames).width <= 1800


def test_the_film_image_of_the_three_is_his_own_pixels_under_their_numbers(tmp_path):
    frames = sheet_of(tmp_path, 3, (450, 600))
    together = np.asarray(selects.combined(frames)).astype(int)
    first = np.asarray(Image.open(frames[0].path).convert("RGB")).astype(int)
    assert np.abs(together[130:130 + 600, 20:20 + 450] - first).mean() < 1  # the frame untouched below the number's band


# --- the pick -----------------------------------------------------------------------------------------------------

def answer(*numbers, others="The rest were soft."):
    return {"picks": [{"frame": n, "line": f"line for {n}."} for n in numbers], "others": others}


def test_a_number_that_is_not_a_frame_he_is_in_is_thrown_out():
    got = selects.checked(answer(40, 2, 3, 1), {1, 2, 3, 4}, 3)
    assert [n for n, _ in got.picks] == [2, 3, 1] and got.thrown == [40]


def test_a_frame_named_twice_counts_once_and_too_few_fails():
    with pytest.raises(selects.PickError):
        selects.checked(answer(2, 2, 3), {1, 2, 3}, 3)
    with pytest.raises(selects.PickError):
        selects.checked(answer(9, 8), {1, 2, 3}, 3)


def test_only_as_many_as_asked_are_kept():
    assert [n for n, _ in selects.checked(answer(1, 2, 3, 4), {1, 2, 3, 4}, 3).picks] == [1, 2, 3]


def test_a_pick_with_no_line_fails():
    with pytest.raises(selects.PickError):
        selects.checked({"picks": [{"frame": 1, "line": " "}], "others": ""}, {1}, 1)


@pytest.mark.parametrize("line", [
    "Sharpness 0.92 and you fill 38% of it.", "Scores best of the set.", "The mask is clean here.",
    "This is the one to post it with the release.", "Great for the album cover art.", "I'd retouch your jacket.",
    "An 8/10 for me.",
])
def test_a_line_with_a_score_or_the_wrong_subject_never_reaches_him(line):
    with pytest.raises(selects.PickError):
        selects.checked({"picks": [{"frame": 1, "line": line}], "others": ""}, {1}, 1)


def test_an_honest_line_about_a_flaw_gets_through_and_a_bad_closing_line_is_just_dropped():
    got = selects.checked({"picks": [{"frame": 1, "line": "Soft on the left, but your face is right there."}],
                           "others": "Those were sharper by a score of two."}, {1, 2}, 1)
    assert got.picks[0][1].startswith("Soft") and got.others == ""


def test_the_model_sees_the_frames_the_measures_the_mood_board_and_his_words(tmp_path):
    frames = sheet_of(tmp_path, 4)
    frames[3].person = None
    seen = []
    got = selects.pick(frames, b"plain", b"seen", "Marco, pick my selects", mood=["From your mood board: washed black"],
                       facts=["Wearing look B"], client=spark(tmp_path, seen))
    content = seen[0]["messages"][1]["content"]
    asked = json.loads(content[0]["text"])
    assert asked["pick_exactly"] == 3 and asked["can_pick"] == [1, 2, 3]
    assert asked["mood_board"] == ["From your mood board: washed black"] and asked["facts"] == ["Wearing look B"]
    assert asked["felix_says"] == "Marco, pick my selects"
    assert {"frame", "he_fills_of_the_frame", "cut_off_at", "sharpness_against_the_sharpest_frame",
            "light_on_him_0_dark_1_bright"} <= set(asked["frames"][0])
    assert [c["type"] for c in content[1:]] == ["image_url", "image_url"]
    assert seen[0]["response_format"]["json_schema"]["strict"] is True
    assert [n for n, _ in got.picks] == [2, 1, 3]


def test_a_wrong_answer_gets_one_more_try(tmp_path):
    frames = sheet_of(tmp_path, 3)
    seen = []
    got = selects.pick(frames, b"p", b"s", "x", mood=[], facts=[], client=spark(tmp_path, seen, [answer(8, 9), answer(1, 2, 3)]))
    assert len(seen) == 2 and [n for n, _ in got.picks] == [1, 2, 3]
    with pytest.raises(selects.PickError):
        selects.pick(frames, b"p", b"s", "x", mood=[], facts=[], client=spark(tmp_path, [], ["not json", answer(9)]))


# --- WhatsApp, end to end -----------------------------------------------------------------------------------------

def different_frames(line, n, base=60):
    """Frames with their own pixels, in the order they were kept, so a picture sent can be traced to its frame."""
    out, tag = [], time.monotonic_ns()
    arrived = [line.arrive(f"f{tag}-{i}", kind="image", media_id=f"photo-{i}") for i in range(n)]
    for i, message in enumerate(arrived):
        line.picture = jpeg(frame_image(base + 10 * i))
        handle(message, wa=line.wa, marco=Marco(), settle=lambda s: None)
        out.append(selects.shoot(line.wa.conn)[0][-1])
    line.sent.clear()
    return out


def test_he_asks_and_gets_the_sheet_then_three_pictures_one_at_a_time_then_the_line_on_the_rest(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    frames = different_frames(line, 5)
    keep_fact(line.wa.conn, "From your mood board: washed black and cream")
    seen = []
    marco = Marco(spark(tmp_path, seen))
    out = handle(line.arrive("ask", kind="text", text="Marco, pick my selects"), wa=line.wa, marco=marco,
                 settle=lambda s: None)
    assert "selects: 5 frames, picked [2, 1, 3]" in out
    assert [m["type"] for m in line.sent if m["type"] != "reaction"] == ["image", "image", "image", "image", "text"]
    assert line.captions() == ["I've got you in all 5 frames. Going through them now.",
                               "2. Your eyes are on it and the light holds your face.",
                               "1. Good stance, though your feet are tight to the edge.",
                               "3. The jacket reads clean here."]
    assert line.texts() == ["The rest were soft or you were looking away."]
    assert line.find.calls == ["person"] * 5
    assert "washed black and cream" in seen[0]["messages"][1]["content"][0]["text"]
    # each pick is his frame's own bytes, not a redraw
    bytes_of = [next(p[p.index(b"\xff\xd8"):] for p in [u]) for u in line.uploads]
    for upload, number in zip(bytes_of[1:], (2, 1, 3)):
        assert upload.startswith(frames[number - 1].path.read_bytes())
    # the originals together in a dated folder, and everything in the film folder
    folder = next((config.STATE_DIR / "selects").iterdir())
    assert sorted(p.name for p in folder.iterdir()) == ["contact-sheet.png", "select-01.jpg", "select-02.jpg",
                                                        "select-03.jpg", "selects.png"]
    assert (folder / "select-02.jpg").read_bytes() == frames[1].original.read_bytes()
    film = sorted(p.name.split("-", 4)[-1] for p in (tmp_path / "film").iterdir())
    assert film == ["select-01.jpg", "select-02.jpg", "select-03.jpg", "selects-contact-sheet.png", "selects.png"]
    # the combined picture is kept, never sent: the sheet and three frames are all that went out
    assert len(line.uploads) == 4
    # the next ask has nothing new to pick from
    line.sent.clear()
    out = handle(line.arrive("ask2", kind="text", text="which are the best three?"), wa=line.wa, marco=marco,
                 settle=lambda s: None)
    assert "no frames" in out and line.texts() == ["I don't have any new frames from you. Send them over and ask me again."]


def test_his_words_can_be_a_voice_note_or_a_caption_on_a_frame(tmp_path, monkeypatch):
    from hiremarco import server

    line = Line(tmp_path, monkeypatch)
    different_frames(line, 3)
    monkeypatch.setattr(server, "voice_text", lambda m, wa, listen=None: "Marco, which are the best three?")
    out = handle(line.arrive("v", kind="audio", media_id="photo-v", voice=True), wa=line.wa,
                 marco=Marco(spark(tmp_path, [])), settle=lambda s: None)
    assert "picked [2, 1, 3]" in out
    line.sent.clear()
    different_frames(line, 2, base=150)
    out = handle(line.arrive("c", kind="image", media_id="photo-c", caption="pick my selects"), wa=line.wa,
                 marco=Marco(spark(tmp_path, [])), settle=lambda s: None)
    assert "selects: 3 frames, picked [2, 1, 3]" in out


def test_the_ask_waits_for_frames_his_words_overtook(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    different_frames(line, 3)
    conn = line.wa.conn
    # one more frame reached the webhook just now and is still downloading when he asks
    record_inbound(conn, "late", OWNER, "image")
    landed = []

    def wait(seconds):
        if not landed:
            landed.append(photos.keep(conn, line.picture, "late"))
            conn.execute("update inbound set ts = ? where wa_message_id = 'late'",
                         ((datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),))

    out = handle(line.arrive("ask", kind="text", text="pick my selects"), wa=line.wa, marco=Marco(spark(tmp_path, [])),
                 settle=wait)
    assert landed and "selects: 4 frames" in out


def test_a_frame_whose_wait_ends_while_the_selects_have_it_stays_quiet(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    different_frames(line, 3, base=100)
    conn = line.wa.conn
    marco = Marco()
    waits = []

    def the_ask_came_as_a_caption_on_another_frame(seconds):
        waits.append(seconds)
        selects.begin(conn, selects.shoot(conn)[0][-1].id, 4)

    out = handle(line.arrive("f9", kind="image", media_id="photo-9"), wa=line.wa, marco=marco,
                 settle=the_ask_came_as_a_caption_on_another_frame)
    assert "the selects have it" in out and waits == [20.0] and line.texts() == [] and marco.seen == []
    # his second ask while the first is still running is not answered twice
    assert "already going through them" in handle(line.arrive("a", kind="text", text="pick my selects"), wa=line.wa,
                                                  marco=marco, settle=lambda s: None)


def test_asking_with_no_frames_says_so_plainly(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    out = handle(line.arrive("ask", kind="text", text="Marco, pick my selects"), wa=line.wa, marco=Marco(),
                 settle=lambda s: None)
    assert "no frames" in out and line.texts() == ["I don't have any new frames from you. Send them over and ask me again."]
    assert line.find.calls == []


def test_fewer_than_three_usable_frames_are_picked_and_said(tmp_path, monkeypatch):
    find = fake_find({1: [], 3: []})
    line = Line(tmp_path, monkeypatch, find=find)
    monkeypatch.setattr(selects, "SAM_WORKERS", 1)  # call order is frame order
    different_frames(line, 4)
    marco = Marco(spark(tmp_path, [], [answer(2, 4)]))
    out = handle(line.arrive("ask", kind="text", text="pick my selects"), wa=line.wa, marco=marco, settle=lambda s: None)
    assert "picked [2, 4]" in out
    assert line.captions()[0] == "I can see you in 2 of 4 frames. Going through them now."
    assert line.captions()[1:] == ["2. line for 2.", "4. line for 4."]
    assert line.texts() == ["Only 2 frames had you in them, so that's all I could pick."]


def test_nobody_in_any_frame_says_so_and_the_frames_stay_for_another_try(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch, find=lambda *a, **k: [])
    different_frames(line, 3)
    seen = []
    out = handle(line.arrive("ask", kind="text", text="pick my selects"), wa=line.wa, marco=Marco(spark(tmp_path, seen)),
                 settle=lambda s: None)
    assert "nobody found in 3 frames" in out and seen == []
    assert line.texts() == ["I couldn't find you in any of those frames. Send me a few more?"]
    assert len(selects.shoot(line.wa.conn)[0]) == 3


def test_a_wrong_answer_from_the_model_never_reaches_him(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    different_frames(line, 3)
    marco = Marco(spark(tmp_path, [], [answer(40, 41), answer(40, 41)]))
    out = handle(line.arrive("ask", kind="text", text="pick my selects"), wa=line.wa, marco=marco, settle=lambda s: None)
    assert "picks rejected" in out
    assert line.captions() == ["I've got you in all 3 frames. Going through them now."]  # the sheet, and no picks
    assert line.texts() == ["I couldn't settle on my three just now. Ask me again?"]
    assert len(selects.shoot(line.wa.conn)[0]) == 3


def test_more_than_thirty_frames_says_so(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    small = jpeg(frame_image().resize((90, 120)))
    for i in range(32):
        photos.keep(line.wa.conn, small, f"n{i}", now=now)
    monkeypatch.setattr(selects, "segment_masks", lambda *a, **k: [found(size=(90, 120), body=(20, 20, 70, 110))])
    out = handle(line.arrive("ask", kind="text", text="pick my selects"), wa=line.wa, marco=Marco(spark(tmp_path, [])),
                 settle=lambda s: None)
    assert "selects: 30 frames" in out
    assert "You sent 32, so I'm working from the last 30." in line.captions()[0]


def test_a_retake_of_the_same_size_shoot_is_not_held_as_a_duplicate(tmp_path, monkeypatch):
    """The gate refuses the same message twice in ten minutes; the same caption on new frames is a new message."""
    line = Line(tmp_path, monkeypatch)
    marco = Marco(spark(tmp_path, []))
    different_frames(line, 3)
    assert "picked" in handle(line.arrive("a1", kind="text", text="pick my selects"), wa=line.wa, marco=marco,
                              settle=lambda s: None)
    line.sent.clear()
    for frame in selects.shoot(line.wa.conn)[0]:
        pytest.fail(f"nothing should be left: {frame}")
    arrived = [line.arrive(f"r{i}", kind="image", media_id=f"photo-{i}") for i in range(3)]
    for i, message in enumerate(arrived):
        line.picture = jpeg(frame_image(150 + 5 * i))  # new frames, the same count
        handle(message, wa=line.wa, marco=Marco(), settle=lambda s: None)
    line.sent.clear()
    out = handle(line.arrive("a2", kind="text", text="pick my selects"), wa=line.wa, marco=marco, settle=lambda s: None)
    assert "picked" in out and "held" not in out and len(line.captions()) == 4


def test_each_step_of_a_run_is_timed(tmp_path, monkeypatch):
    line = Line(tmp_path, monkeypatch)
    frames = different_frames(line, 3)
    got = selects.run([(f.path, f.original) for f in frames], "x", conn=line.wa.conn, send=lambda *a: None,
                      client=spark(tmp_path, []), find=fake_find(), pause=lambda s: None)
    assert {"sam", "sheet", "send_sheet", "pick", "send_picks", "total"} <= set(got.seconds)


# --- the command --------------------------------------------------------------------------------------------------

def command(tmp_path, monkeypatch, *argv, frames=4):
    import argparse

    from hiremarco import cli
    from hiremarco.meta import client as meta_client

    seen = []
    monkeypatch.setattr(meta_client, "MuseSpark", lambda *a, **k: spark(tmp_path, seen))
    monkeypatch.setattr(selects, "segment_masks", fake_find())
    monkeypatch.setenv("HIREMARCO_DRESS_FILM_DIR", str(tmp_path / "film"))
    (tmp_path / "film").mkdir(exist_ok=True)
    shoot = tmp_path / "shoot"
    shoot.mkdir(exist_ok=True)
    for i in range(frames):
        (shoot / f"DSC{i:02d}.JPG").write_bytes(jpeg(frame_image(60 + 10 * i)))
    (shoot / "notes.txt").write_text("not a frame")
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    se = sub.add_parser("selects")
    se.add_argument("folder")
    se.add_argument("--say", default="")
    se.add_argument("--dry-run", action="store_true")
    return cli.cmd_selects(parser.parse_args(["selects", str(shoot), *argv])), seen


def test_the_command_dry_run_writes_the_files_and_sends_nothing(tmp_path, monkeypatch, capsys):
    from hiremarco import whatsapp

    monkeypatch.setattr(whatsapp, "WhatsApp", lambda *a, **k: pytest.fail("a dry run sends nothing"))
    code, seen = command(tmp_path, monkeypatch, "--dry-run", "--say", "which are the best three?")
    out = capsys.readouterr().out
    assert code == 0 and "dry run, nothing sent" in out and "pick 2:" in out and "seconds: sam" in out
    assert json.loads(seen[0]["messages"][1]["content"][0]["text"])["felix_says"] == "which are the best three?"
    names = sorted(p.name for p in (tmp_path / "film").iterdir())
    assert len(names) == 5 and any(n.endswith("select-02.jpg") for n in names)
    original = (tmp_path / "shoot" / "DSC01.JPG").read_bytes()
    assert (next((config.STATE_DIR / "selects").iterdir()) / "select-02.jpg").read_bytes() == original


def test_the_command_sends_the_sheet_and_three_pictures_to_the_owner(tmp_path, monkeypatch):
    from hiremarco import whatsapp

    sent = []

    class Wire:
        def __init__(self, conn=None, **k):
            self.conn = conn

        def send_image(self, to, picture, caption, *, idempotency_key, mime):
            sent.append((to, idempotency_key.split(":")[0], picture[:2]))

        def send_text(self, to, text, *, idempotency_key):
            sent.append((to, idempotency_key.split(":")[0], None))

    monkeypatch.setattr(whatsapp, "WhatsApp", Wire)
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    monkeypatch.setattr(selects.time, "sleep", lambda s: None)
    code, _ = command(tmp_path, monkeypatch)
    assert code == 0 and {s[0] for s in sent} == {OWNER}
    assert [s[1] for s in sent] == ["selects-sees", "selects-pick-2", "selects-pick-1", "selects-pick-3",
                                    "selects-others"]


def test_the_command_says_when_there_is_nothing_to_read(tmp_path, capsys):
    import argparse

    from hiremarco import cli

    (tmp_path / "empty").mkdir()
    code = cli.cmd_selects(argparse.Namespace(folder=str(tmp_path / "empty"), say="", dry_run=True))
    assert code == 2 and "no frames" in capsys.readouterr().out

"""Dress me (Owner 2026-11-01): the clothes on the bed, what SAM sees, three looks of real pieces, his pick."""

import base64
import io
import json
from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pytest
from meta_sam_parser._mask_codec import _encode_raster
from PIL import Image, ImageDraw

from hiremarco import config, dress, gate
from hiremarco.joblog import JobLog
from hiremarco.marco import Marco
from hiremarco.meta import image as muse_image
from hiremarco.meta.client import MuseSpark
from hiremarco.sam import Box, Found, SamError, parse_found, segment_masks
from hiremarco.server import handle
from hiremarco.whatsapp import Inbound, WhatsApp, photos
from hiremarco.whatsapp.client import record_inbound
from hiremarco.whatsapp.facts import keep, known

OWNER = "13055550100"
W, H = 1200, 900
# the bed: a black tee, blue jeans, a pair of white sneakers, a red cap
CLOTHES = {
    "t-shirt": [((100, 80, 460, 420), (20, 20, 20))],
    "jeans": [((560, 60, 760, 760), (40, 70, 160))],
    "sneakers": [((120, 640, 260, 760), (245, 245, 245)), ((300, 650, 440, 770), (245, 245, 245))],
    "cap": [((860, 600, 1100, 780), (200, 20, 20))],
}


def bed() -> Image.Image:
    image = Image.new("RGB", (W, H), (210, 200, 188))
    draw = ImageDraw.Draw(image)
    for items in CLOTHES.values():
        for box, color in items:
            draw.ellipse(box, fill=color)
    return image


def jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", quality=95)
    return out.getvalue()


def ellipse_mask(box) -> tuple[bytes, tuple[int, int]]:
    x1, y1, x2, y2 = box
    w, h = x2 - x1 + 1, y2 - y1 + 1
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse((0, 0, w - 1, h - 1), fill=1)
    return bytes(np.asarray(m).astype(np.uint8).ravel()), (w, h)


def found(box, confidence=0.9, with_mask=True) -> Found:
    if not with_mask:
        return Found(Box(*box, W, H, confidence))
    raster, size = ellipse_mask(box)
    return Found(Box(*box, W, H, confidence), raster, size)


def fake_find(extra=None, fail=()):
    calls = []

    def find(photo, phrase, **kw):
        calls.append(phrase)
        if phrase in fail:
            raise SamError("http 500")
        out = [found(box) for box, _ in CLOTHES.get(phrase, [])]
        if phrase == "shirt":  # the tee again, under another phrase, weaker and box only
            out.append(found(CLOTHES["t-shirt"][0][0], 0.7, with_mask=False))
        if phrase == "hat":
            out.append(found((900, 100, 950, 150), 0.3))  # low confidence: dropped
        return out + (extra or {}).get(phrase, [])

    find.calls = calls
    return find


# --- SAM masks ---------------------------------------------------------------------------------------------------

def sam_text(box, raster, size, c=0.91):
    payload = _encode_raster(list(raster), *size)
    x1, y1, x2, y2 = box
    return (f"<0f>0<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={W};h={H};c={c}|>"
            f"<|mask;x=0;y=0;c={c};data={size[1]},{size[0]},{payload}|>")


def test_segment_masks_asks_for_one_bit_masks_and_decodes_them(tmp_path):
    box = (10, 20, 49, 39)
    raster, size = ellipse_mask(box)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"output_text": sam_text(box, raster, size)})

    got = segment_masks(b"jpeg", "jeans", joblog=JobLog(tmp_path / "j.jsonl"), api_key="k",
                        transport=httpx.MockTransport(handler))
    assert seen[0]["metadata"] == {"include_confidence": "true", "mask_encoding": "one_bit"}
    assert got[0].box == Box(10, 20, 49, 39, W, H, 0.91)
    assert got[0].mask == raster and got[0].mask_size == size


def test_a_mask_the_parser_cannot_read_falls_back_to_the_box():
    text = f"<0f>0<|box;x1=1;y1=1;x2=5;y2=5;w={W};h={H};c=0.8|><|mask;x=0;y=0;data=5,5,!garbage|>"
    assert parse_found(text) == [Found(Box(1, 1, 5, 5, W, H, 0.8))]


# --- finding the pieces -------------------------------------------------------------------------------------------

def test_pieces_are_found_once_each_paired_and_numbered_like_a_page():
    find = fake_find()
    pieces = dress.find_pieces(jpeg(bed()), (W, H), find=find)
    assert sorted(find.calls) == sorted(dress.PHRASES)                  # one call per noun phrase
    assert [(p.number, p.label) for p in pieces] == [(1, "t-shirt"), (2, "jeans"), (3, "sneakers"), (4, "cap")]
    tee = pieces[0]
    assert tee.mask is not None and tee.confidence == 0.9                # the stronger find of the tee is kept
    shoes = pieces[2]
    assert shoes.box == (120, 640, 440, 770)                             # the two sneakers are one pair


def test_a_failing_phrase_is_skipped_and_all_failing_is_an_error():
    pieces = dress.find_pieces(jpeg(bed()), (W, H), find=fake_find(fail={"jeans"}))
    assert "jeans" not in [p.label for p in pieces] and len(pieces) == 3
    with pytest.raises(SamError):
        dress.find_pieces(jpeg(bed()), (W, H), find=fake_find(fail=set(dress.PHRASES)))


def test_a_piece_is_cut_out_on_its_mask_or_on_its_box():
    pieces = dress.find_pieces(jpeg(bed()), (W, H), find=fake_find())
    cut = dress.cutout(bed(), pieces[0])
    assert cut.mode == "RGBA" and cut.getpixel((0, 0))[3] == 0          # outside the tee is transparent
    assert cut.getpixel((cut.width // 2, cut.height // 2))[3] == 255
    boxed = dress.Piece(9, "bag", (10, 10, 59, 39), None, 0.8)
    plain = dress.cutout(bed(), boxed)
    assert plain.size == (50, 30) and plain.getpixel((0, 0))[3] == 255


def test_what_sam_sees_tints_outlines_and_numbers_each_piece_big():
    pieces = dress.find_pieces(jpeg(bed()), (W, H), find=fake_find())
    seen = dress.what_sam_sees(bed(), pieces)
    assert max(seen.size) == 1600
    scale = 1600 / W
    jeans_color = dress.COLORS[1]
    left_edge = seen.getpixel((round(562 * scale), round(410 * scale)))  # on the jeans' outline
    assert all(abs(a - b) < 40 for a, b in zip(left_edge, jeans_color))
    cx, cy = (v * scale for v in pieces[1].center())
    badge = seen.getpixel((round(cx) - 30, round(cy)))                   # inside the number's circle
    assert all(abs(a - b) < 40 for a, b in zip(badge, jeans_color))


# --- the looks ---------------------------------------------------------------------------------------------------

LOOKS = {"looks": [
    {"letter": "A", "name": "Clean studio", "pieces": [1, 2, 3], "line": "Easy to move in all day."},
    {"letter": "B", "name": "Studio to dinner", "pieces": [1, 2, 3, 4, 7], "line": "The cap keeps it yours."},
    {"letter": "C", "name": "Low key", "pieces": [2, 3, 4], "line": "Quiet and sharp."}],
    "recommend": "B", "caption": "B for me: it goes from the booth to dinner without a change. A, B or C?"}


def test_a_piece_not_in_the_photo_is_thrown_out():
    looks = dress.checked(LOOKS, {1, 2, 3, 4})
    assert looks.get("B").pieces == [1, 2, 3, 4] and looks.dropped == [7]
    assert looks.recommend == "B"


@pytest.mark.parametrize("broken, why", [
    ({**LOOKS, "looks": [{**LOOKS["looks"][0], "pieces": [8, 9]}, *LOOKS["looks"][1:]]}, "no piece from the photo"),
    ({**LOOKS, "looks": LOOKS["looks"][:2]}, "not A, B and C"),
    ({**LOOKS, "looks": [LOOKS["looks"][0], LOOKS["looks"][0], LOOKS["looks"][2]]}, "once each"),
    ({**LOOKS, "recommend": "D"}, "not A, B or C"),
])
def test_looks_that_are_not_three_real_looks_fail(broken, why):
    with pytest.raises(dress.LooksError, match=why):
        dress.checked(broken, {1, 2, 3, 4})


def spark(tmp_path, seen, looks=LOOKS, warm="b it is. you're going to feel good in that all day."):
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if body.get("response_format", {}).get("json_schema", {}).get("name") == "looks":
            text = json.dumps(looks)
        else:
            text = warm
        return httpx.Response(200, json={"model": "muse-spark-1.3", "choices": [{"message": {"content": text},
                                                                                "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 3000, "completion_tokens": 300}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def test_three_looks_sees_both_pictures_his_words_and_the_mood_board(tmp_path):
    seen = []
    pieces = dress.find_pieces(jpeg(bed()), (W, H), find=fake_find())
    looks = dress.three_looks(jpeg(bed()), b"png", pieces, "Studio today, dinner tonight.",
                              mood=["From your mood board: The vibe's palette is washed black and cream"], facts=[],
                              client=spark(tmp_path, seen))
    content = seen[0]["messages"][1]["content"]
    asked = json.loads(content[0]["text"])
    assert asked["felix_says"] == "Studio today, dinner tonight."
    assert asked["pieces"] == "1: t-shirt\n2: jeans\n3: sneakers\n4: cap"
    assert asked["mood_board"][0].startswith("From your mood board")
    assert [c["type"] for c in content[1:]] == ["image_url", "image_url"]
    assert seen[0]["response_format"]["json_schema"]["strict"] is True
    assert looks.recommend == "B"


def test_the_board_is_made_only_of_the_pieces_in_the_looks():
    pieces = dress.find_pieces(jpeg(bed()), (W, H), find=fake_find())
    only_tee = dress.checked({"looks": [{"letter": x, "name": "Tee", "pieces": [1], "line": ""} for x in "ABC"],
                              "recommend": "A", "caption": "a?"}, {1, 2, 3, 4})
    made = dress.board(bed(), pieces, only_tee)
    assert made.size == (1800, 1200)
    pixels = np.asarray(made).reshape(-1, 3).astype(int)
    blue = (abs(pixels - (40, 70, 160)).sum(axis=1) < 30).sum()         # the jeans are on no look
    black = (abs(pixels - (20, 20, 20)).sum(axis=1) < 20).sum()         # the tee is on all three
    assert blue == 0 and black > 10_000


def test_the_backdrop_is_painted_once_and_only_read_after(tmp_path):
    painted = []

    def paint(prompt, size, job):
        painted.append((prompt, size, job))
        return dress.png(Image.new("RGB", (30, 20), (240, 236, 228)))

    assert dress.backdrop() is None
    assert dress.backdrop(paint).size == (30, 20)
    assert dress.backdrop(paint).size == (30, 20) and len(painted) == 1
    assert "No people, no clothes" in painted[0][0]


# --- WhatsApp, end to end ----------------------------------------------------------------------------------------

def line(tmp_path, monkeypatch, picture: bytes):
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    monkeypatch.setenv("HIREMARCO_DRESS_FILM_DIR", str(tmp_path / "film"))
    (tmp_path / "film").mkdir()
    rules = tmp_path / "RULES.md"
    rules.write_text(f"send: whatsapp -> {OWNER} ; the Owner's own chat ; until 2099-01-01\n")
    sent, uploads = [], []

    def respond(request):
        if request.url.host == "lookaside.example":
            return httpx.Response(200, content=picture)
        if request.url.path.endswith("/photo-1"):
            return httpx.Response(200, json={"url": "https://lookaside.example/photo-1", "mime_type": "image/jpeg"})
        if request.url.path.endswith("/media"):
            uploads.append(request.content)
            return httpx.Response(200, json={"id": f"up-{len(uploads)}"})
        body = json.loads(request.content)
        if body.get("type") in ("text", "image"):
            sent.append(body)
        return httpx.Response(200, json={"messages": [{"id": "wamid.o"}]})

    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"),
                  transport=httpx.MockTransport(respond), rules_path=rules)
    monkeypatch.setattr(dress, "segment_masks", fake_find())
    return wa, sent, uploads


def arrive(wa, mid, ts=None, **kw):
    record_inbound(wa.conn, mid, OWNER, kw.get("kind", "text"), ts=ts)
    return Inbound(id=mid, sender=OWNER, **kw)


def test_dress_me_with_the_photo_sends_what_sam_sees_then_the_board_then_locks_in_his_pick(tmp_path, monkeypatch):
    wa, sent, uploads = line(tmp_path, monkeypatch, jpeg(bed()))
    keep(wa.conn, "From your mood board: The vibe's palette is washed black and cream")
    seen = []
    marco = Marco(spark(tmp_path, seen))
    out = handle(arrive(wa, "w1", kind="image", media_id="photo-1",
                        caption="Marco, dress me. Studio today, dinner tonight."), wa=wa, marco=marco)
    assert "dress me: 4 pieces, what SAM sees and the board sent, B recommended; threw out pieces [7]" in out
    assert [m["type"] for m in sent] == ["image", "image"]
    assert sent[0]["image"]["caption"] == "i see 4 pieces. give me a sec to put three looks together."
    assert sent[1]["image"]["caption"].startswith("b for me")
    assert len(uploads) == 2 and all(b"image/jpeg" in u and b"marco.jpg" in u for u in uploads)
    film = sorted(p.name for p in (tmp_path / "film").iterdir())
    assert len(film) == 2 and film[0].endswith("-board.png") and film[1].endswith("-what-sam-sees.png")
    for name in film:
        assert (config.STATE_DIR / "dress" / name).read_bytes() == (tmp_path / "film" / name).read_bytes()
    asked = json.loads(seen[0]["messages"][1]["content"][0]["text"])
    assert asked["mood_board"] == ["From your mood board: The vibe's palette is washed black and cream"]
    # his pick
    out = handle(arrive(wa, "w2", kind="text", text="B"), wa=wa, marco=marco)
    assert "dress me: look B locked in (t-shirt, jeans, sneakers, cap)" in out
    assert sent[-1]["text"]["body"] == "b it is. you're going to feel good in that all day."
    wearing = [t for _, t in known(wa.conn) if t.startswith("Wearing look B on ")]
    assert len(wearing) == 1 and wearing[0].endswith("Studio to dinner (t-shirt, jeans, sneakers, cap)")
    assert dress.open_board(wa.conn) is None
    # once picked, a lone "b" is just words again
    assert dress.picked("b") == "B" and "locked in" not in handle(arrive(wa, "w3", kind="text", text="b"), wa=wa,
                                                                   marco=Brainless())


class Brainless:
    """A brain that cannot be reached: the fixed patterns answer, which say nothing about looks."""

    def converse(self, *a, **k):
        raise RuntimeError("down")

    def answer(self, text, **k):
        from hiremarco.meta.client import Reply

        return Reply(text="ok.", model="m", prompt_tokens=0, completion_tokens=0, cached_tokens=0, cost_usd=0,
                     duration_ms=0)


def test_dress_me_before_the_photo_waits_for_it(tmp_path, monkeypatch):
    wa, sent, _ = line(tmp_path, monkeypatch, jpeg(bed()))
    marco = Marco(spark(tmp_path, []))
    out = handle(arrive(wa, "w1", kind="text", text="Marco, dress me. Studio today, dinner tonight."), wa=wa,
                 marco=marco)
    assert out.split(" > ")[1] == "dress me: waiting for the photo"
    assert sent[-1]["text"]["body"].startswith("send me a photo of the clothes")
    out = handle(arrive(wa, "w2", kind="image", media_id="photo-1"), wa=wa, marco=marco,
                 settle=lambda s: pytest.fail("the waiting instruction takes the photo at once"))
    assert "B recommended" in out and [m["type"] for m in sent[-2:]] == ["image", "image"]
    row = wa.conn.execute("select status, said from dress").fetchall()
    assert row == [("open", "Marco, dress me. Studio today, dinner tonight.")]


def test_dress_me_by_voice_just_after_the_photo_takes_that_photo(tmp_path, monkeypatch):
    from hiremarco import server

    wa, sent, _ = line(tmp_path, monkeypatch, jpeg(bed()))
    marco = Marco(spark(tmp_path, []))
    t0 = datetime.now(timezone.utc)
    out = handle(arrive(wa, "w1", ts=t0, kind="image", media_id="photo-1"), wa=wa, marco=marco,
                 settle=lambda s: record_inbound(wa.conn, "w2", OWNER, "audio", ts=t0 + timedelta(seconds=3)))
    assert "his next message says what it is for" in out and sent == []
    monkeypatch.setattr(server, "voice_text", lambda m, wa, listen=None: "Marco, dress me. Studio today.")
    out = handle(Inbound(id="w2", sender=OWNER, kind="audio", media_id="v-1", voice=True), wa=wa, marco=marco)
    assert "B recommended" in out
    # and his pick by voice
    monkeypatch.setattr(server, "voice_text", lambda m, wa, listen=None: "Bee.")
    out = handle(arrive(wa, "w3", kind="audio", media_id="v-2", voice=True), wa=wa, marco=marco)
    assert "look B locked in" in out


@pytest.mark.parametrize("said, letter", [("B", "B"), ("b", "B"), ("look B", "B"), ("Look b.", "B"),
                                          ("I'll go with A", "A"), ("let's do C", "C"), ("Bee.", "B"),
                                          ("option c please", "C"), ("see", "C"),
                                          ("be careful", None), ("A lot of people", None), ("look at this", None)])
def test_his_pick_is_read_from_the_ways_he_says_it(said, letter):
    assert dress.picked(said) == letter


def test_a_wrong_answer_from_the_model_never_reaches_him(tmp_path, monkeypatch):
    wa, sent, _ = line(tmp_path, monkeypatch, jpeg(bed()))
    bad = {**LOOKS, "looks": LOOKS["looks"][:2]}
    out = handle(arrive(wa, "w1", kind="image", media_id="photo-1", caption="dress me"), wa=wa,
                 marco=Marco(spark(tmp_path, [], looks=bad)))
    assert "looks rejected" in out
    assert [m["type"] for m in sent] == ["image", "text"]                # what SAM sees, then a plain line; no board
    assert dress.open_board(wa.conn) is None


def test_a_photo_with_no_clothes_says_so(tmp_path, monkeypatch):
    wa, sent, _ = line(tmp_path, monkeypatch, jpeg(bed()))
    monkeypatch.setattr(dress, "segment_masks", lambda *a, **k: [])
    out = handle(arrive(wa, "w1", kind="image", media_id="photo-1", caption="dress me"), wa=wa,
                 marco=Marco(spark(tmp_path, [])))
    assert "no clothing found" in out and sent[-1]["text"]["body"].startswith("i couldn't make out any clothes")


def test_a_dry_run_writes_both_pictures_and_sends_nothing(tmp_path):
    path = tmp_path / "bed.jpg"
    path.write_bytes(jpeg(bed()))
    conn = gate.connect(":memory:")
    done = dress.dress(path, "dress me", conn=conn, send=None, client=spark(tmp_path, []), find=fake_find(),
                       film=None)
    assert done.seen.exists() and done.board.exists() and done.copies == [] and done.row is None
    assert Image.open(done.board).size == (1800, 1200)


# --- Muse Image --------------------------------------------------------------------------------------------------

def test_muse_image_sends_one_low_pass_png_request_and_logs_its_price(tmp_path):
    seen = []
    picture = dress.png(Image.new("RGB", (4, 4)))

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(picture).decode()}]})

    log = JobLog(tmp_path / "j.jsonl")
    assert muse_image.generate("paper", joblog=log, api_key="k", transport=httpx.MockTransport(handler)) == picture
    path, body = seen[0]
    assert path == "/v1/images/generations"
    assert body["model"] == "muse-image-1.0" and body["output_format"] == "png" and body["reasoning_strength"] == "low"
    assert log.rows()[0]["cost_usd"] == pytest.approx(0.01)


def test_muse_image_refusal_carries_the_status_and_code_only(tmp_path):
    def handler(request):
        return httpx.Response(403, json={"error": {"code": "model_not_available", "message": "echo paper"}})

    log = JobLog(tmp_path / "j.jsonl")
    with pytest.raises(muse_image.MuseImageError) as raised:
        muse_image.generate("paper", joblog=log, api_key="k", transport=httpx.MockTransport(handler))
    assert str(raised.value) == "Meta Model API returned HTTP 403 (model_not_available)"
    assert log.rows()[0]["ok"] is False and "echo" not in log.rows()[0]["note"]


def test_muse_image_respects_the_kill_switch(tmp_path):
    gate.set_kill_switch(True)
    try:
        with pytest.raises(gate.Refused):
            muse_image.generate("paper", joblog=JobLog(tmp_path / "j.jsonl"), api_key="k",
                                transport=httpx.MockTransport(lambda r: pytest.fail("no request")))
    finally:
        gate.set_kill_switch(False)


# --- the command -------------------------------------------------------------------------------------------------

def command(tmp_path, monkeypatch, *argv):
    import argparse

    from hiremarco import cli
    from hiremarco.meta import client as meta_client

    seen = []
    monkeypatch.setattr(meta_client, "MuseSpark", lambda *a, **k: spark(tmp_path, seen))
    monkeypatch.setattr(dress, "segment_masks", fake_find())
    monkeypatch.setenv("HIREMARCO_DRESS_FILM_DIR", str(tmp_path / "film"))
    (tmp_path / "film").mkdir(exist_ok=True)
    photo = tmp_path / "bed.jpg"
    photo.write_bytes(jpeg(bed()))
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    dm = sub.add_parser("dress")
    dm.add_argument("photo", nargs="?")
    dm.add_argument("--say", default="")
    dm.add_argument("--dry-run", action="store_true")
    dm.add_argument("--backdrop", action="store_true")
    args = parser.parse_args(["dress", str(photo), *argv])
    return cli.cmd_dress(args), seen


def test_the_command_dry_run_writes_the_pictures_and_sends_nothing(tmp_path, monkeypatch, capsys):
    from hiremarco import whatsapp

    monkeypatch.setattr(whatsapp, "WhatsApp", lambda *a, **k: pytest.fail("a dry run sends nothing"))
    code, seen = command(tmp_path, monkeypatch, "--dry-run", "--say", "Marco, dress me. Studio today, dinner tonight.")
    out = capsys.readouterr().out
    assert code == 0 and "dry run, nothing sent" in out and "<- pick" in out
    assert json.loads(seen[0]["messages"][1]["content"][0]["text"])["felix_says"].startswith("Marco, dress me.")
    assert len(list((tmp_path / "film").iterdir())) == 2
    assert dress.open_board(gate.connect()) is None


def test_the_command_sends_both_pictures_to_the_owner_and_opens_the_board(tmp_path, monkeypatch, capsys):
    from hiremarco import whatsapp

    sent = []

    class Line:
        def __init__(self, conn=None, **k):
            self.conn = conn

        def send_image(self, to, picture, caption, *, idempotency_key, mime):
            sent.append((to, caption, idempotency_key, mime, picture[:2]))

    monkeypatch.setattr(whatsapp, "WhatsApp", Line)
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    code, _ = command(tmp_path, monkeypatch, "--say", "dress me")
    assert code == 0 and [s[0] for s in sent] == [OWNER, OWNER]
    assert sent[0][2].startswith("dress-sees:desk:") and sent[1][2].startswith("dress-board:desk:")
    assert {s[3] for s in sent} == {"image/jpeg"} and {s[4] for s in sent} == {b"\xff\xd8"}
    assert dress.open_board(gate.connect())["recommend"] == "B"


@pytest.mark.skipif(not __import__("shutil").which("sips"), reason="macOS sips turns HEIC into JPEG")
def test_an_iphone_heic_is_read_through_sips(tmp_path):
    import subprocess

    from hiremarco.cli import photo_bytes

    src = tmp_path / "bed.jpg"
    src.write_bytes(jpeg(bed()))
    heic = tmp_path / "bed.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(src), "--out", str(heic)], check=True, capture_output=True)
    assert Image.open(io.BytesIO(photo_bytes(heic))).size == (W, H)

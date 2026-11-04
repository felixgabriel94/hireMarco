"""SAM 3.1 in motion: the reveal clip for the edit, and a video's sharpest frame as the photo (Owner 2026-11-04)."""

import io
import json

import av
import httpx
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from hiremarco import reveal
from hiremarco.marco import Marco
from hiremarco.server import handle
from hiremarco.studio import six176
from tests.test_six176_save import BOXES, OWNER, TWO_READ, arrive, line, spark


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))


def panel(sharp=True) -> Image.Image:
    image = Image.new("RGB", (640, 360), (30, 30, 34))
    draw = ImageDraw.Draw(image)
    for x in range(40, 600, 40):
        draw.line((x, 40, x, 320), fill=(230, 230, 230), width=2)
    return image if sharp else image.filter(ImageFilter.GaussianBlur(6))


def video(frames) -> bytes:
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as clip:
        stream = clip.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = 640, 360, "yuv420p"
        for image in frames:
            for packet in stream.encode(av.VideoFrame.from_image(image)):
                clip.mux(packet)
        for packet in stream.encode():
            clip.mux(packet)
    return out.getvalue()


def test_the_timeline_holds_the_photo_then_brings_each_find_on_then_holds_the_whole():
    states = [Image.new("RGB", (101, 51), (i * 60, 0, 0)) for i in range(4)]
    frames = reveal.timeline(states, fps=10)
    assert frames[0].size == (100, 50)              # even for H.264
    assert len(frames) == 10 + 3 * (2 + 3) + 27     # 1 s first; 3 steps of fade 2 + hold 3; 2.7 s last
    assert frames[-1].getpixel((0, 0)) == (180, 0, 0)


def test_the_clip_is_an_mp4_that_plays_back(tmp_path):
    made = reveal.write_clip([panel(), panel(False), panel()], tmp_path / "seen.mp4", fps=10)
    with av.open(str(made)) as clip:
        frames = list(clip.decode(video=0))
    assert len(frames) == len(reveal.timeline([panel()] * 3, fps=10)) and frames[0].width == 640


def test_a_clip_that_cannot_be_written_is_logged_not_raised(tmp_path):
    said = []
    assert reveal.try_clip([], tmp_path / "x.mp4", log=said.append) is None and "not written" in said[0]


def test_the_sharpest_frame_is_the_one_kept():
    frames = [panel(False)] * 6 + [panel()] + [panel(False)] * 6
    picked = Image.open(io.BytesIO(reveal.sharpest_frame(video(frames))))
    assert reveal.sharpness(picked) > 5 * reveal.sharpness(panel(False))


def test_a_file_that_is_not_a_video_is_unreadable():
    with pytest.raises(ValueError):
        reveal.sharpest_frame(b"not a video")


def test_a_video_with_his_words_reads_the_6176_and_writes_the_clip(tmp_path, monkeypatch):
    wa, sent = line(tmp_path, monkeypatch)
    clip = video([panel(False)] * 4 + [panel()] + [panel(False)] * 4)
    monkeypatch.setattr(wa, "download_media", lambda media_id: (clip, "video/mp4"))
    small = [b.__class__(int(b.x1 / 2.5), int(b.y1 / 2.5), int(b.x2 / 2.5), int(b.y2 / 2.5), 640, 360) for b in BOXES]
    monkeypatch.setattr(six176, "segment", lambda *a, **k: small)
    out = handle(arrive(wa, "w1", kind="video", media_id="video-1", caption="Marco, save my 6176"), wa=wa,
                 marco=Marco(spark(tmp_path, TWO_READ)))
    assert "video: its sharpest frame kept as the photo" in out and "6176 saved:" in out
    assert [m["type"] for m in sent] == ["image", "text"]
    clips = list((tmp_path / "recall").glob("*-6176-what-sam-sees.mp4"))
    assert len(clips) == 1 and clips[0].stat().st_size > 1000

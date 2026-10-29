import pytest
from starlette.testclient import TestClient

from hiremarco import config
from hiremarco.studio import live

JPEG = b"\xff\xd8\xff\xe0fake-frame\xff\xd9"


def app(grab=lambda: JPEG, max_frames=2):
    frames = live.Frames(grab, fps=50)
    return TestClient(live.make_app(frames, "tok-123", max_frames=max_frames)), frames


@pytest.mark.parametrize("path", ["/", "/?t=wrong", "/stream", "/frame.jpg?t=nope"])
def test_without_the_token_nothing_is_there(path):
    client, frames = app()
    assert client.get(path).status_code == 404 and frames.seq == 0


def test_the_page_plays_the_stream_with_its_token():
    client, _ = app()
    page = client.get("/?t=tok-123")
    assert page.status_code == 200 and 'src="stream?t=tok-123"' in page.text


def test_the_stream_sends_jpeg_parts_and_stops_capturing_when_the_viewer_leaves():
    client, frames = app()
    with client.stream("GET", "/stream?t=tok-123") as response:
        assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
        body = b"".join(response.iter_bytes())
    assert body.count(b"--marcoframe\r\nContent-Type: image/jpeg") == 2 and JPEG in body
    assert frames.viewers == 0


def test_a_failed_capture_keeps_the_last_frame_and_says_why():
    calls = []

    def grab():
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("could not create image from window")
        return JPEG

    frames = live.Frames(grab)
    frames.capture_once()
    frames.capture_once()
    assert frames.latest == JPEG and frames.seq == 1 and "could not create image" in frames.error


def test_a_single_frame_and_the_reason_when_there_is_none():
    client, _ = app()
    assert client.get("/frame.jpg?t=tok-123").content == JPEG

    def broken():
        raise PermissionError("screen recording not allowed")

    client, _ = app(grab=broken)
    refused = client.get("/frame.jpg?t=tok-123")
    assert refused.status_code == 503 and "screen recording" in refused.text


def test_the_link_token_is_kept_and_replaced_on_request():
    first = live.link_token()
    assert live.link_token() == first and config.get("HIREMARCO_LIVE_TOKEN") == first
    assert live.link_token(new=True) != first

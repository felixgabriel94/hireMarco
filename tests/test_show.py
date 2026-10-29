import json

import httpx
import pytest

from hiremarco import gate
from hiremarco.studio.booth import Booth, Tape
from hiremarco.studio.commands import Command, understand
from hiremarco.studio.show import show
from hiremarco.whatsapp import WhatsApp
from hiremarco.whatsapp.client import record_inbound

OWNER = "13055550100"
PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture(autouse=True)
def owner(monkeypatch):
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)


def fake_graph():
    calls = []

    def handler(request):
        calls.append((request.url.path, request.headers.get("content-type", ""), request.content))
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "media-7"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.shown"}]})

    return httpx.MockTransport(handler), calls


def client(tmp_path):
    rules = tmp_path / "RULES.md"
    rules.write_text("send: whatsapp -> owner ; the Owner's chat ; until 2099-01-01\n")
    transport, calls = fake_graph()
    wa = WhatsApp(token="t", phone_number_id="111", conn=gate.connect(":memory:"), transport=transport,
                  rules_path=rules)
    record_inbound(wa.conn, "wamid.in", OWNER, "text")
    return wa, calls


def test_send_image_uploads_then_sends_with_a_caption(tmp_path):
    wa, calls = client(tmp_path)
    assert wa.send_image(OWNER, PNG, "Here's the session.", idempotency_key="s1") == "wamid.shown"
    (upload_path, upload_type, _), (send_path, _, send_body) = calls
    assert upload_path == "/v25.0/111/media" and upload_type.startswith("multipart/form-data")
    assert json.loads(send_body) == {"messaging_product": "whatsapp", "to": OWNER, "type": "image",
                                     "image": {"id": "media-7", "caption": "Here's the session."}}


def test_show_captures_then_sends_and_the_booth_hears_it(tmp_path):
    sent = []
    result = show("Here's the session.", grab=lambda: PNG, send=lambda png, cap: sent.append((png, cap)) or "wamid.x")
    assert result == "wamid.x" and sent == [(PNG, "Here's the session.")]
    assert understand("Marco, show me", client=None) == Command("show")
    assert understand("Marco, send me a screenshot", client=None) == Command("show")
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(), say=lambda t: None,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=1), log=lambda line: None,
              show=lambda cap: "wamid.booth1")
    assert "shown on the phone (booth1)" in b.hear("Marco, show me the session")

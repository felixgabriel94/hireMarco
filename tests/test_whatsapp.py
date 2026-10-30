import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from starlette.testclient import TestClient

from hiremarco import gate
from hiremarco.whatsapp import WhatsApp, make_app, parse_payload, verify_signature
from hiremarco.whatsapp.client import last_inbound, record_inbound

OWNER = "13055550100"
SECRET = "app-secret"


def payload(sender=OWNER, mid="wamid.1", text="Marco?"):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "messages": [{"from": sender, "id": mid, "timestamp": "1761600000", "type": "text", "text": {"body": text}}]
    }}]}]}


def signed(body: bytes) -> dict:
    return {"x-hub-signature-256": "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest(),
            "content-type": "application/json"}


@pytest.fixture
def app(tmp_path):
    db = tmp_path / "gate.sqlite"
    seen = []
    application = make_app(seen.append, verify_token="vt", app_secret=SECRET, owner="+" + OWNER,
                           conn_factory=lambda: gate.connect(db))
    return TestClient(application), seen, db


def test_signature():
    body = b'{"a":1}'
    good = signed(body)["x-hub-signature-256"]
    assert verify_signature(SECRET, body, good)
    assert not verify_signature(SECRET, body + b" ", good)
    assert not verify_signature(SECRET, body, None)
    assert not verify_signature("", body, good)


def test_parse_text_and_audio():
    p = payload()
    p["entry"][0]["changes"][0]["value"]["messages"].append(
        {"from": OWNER, "id": "wamid.2", "type": "audio", "audio": {"id": "media-9", "mime_type": "audio/ogg"}})
    found = parse_payload(p)
    assert [m.kind for m in found] == ["text", "audio"]
    assert found[0].text == "Marco?" and found[1].media_id == "media-9"


def test_verify_handshake(app):
    client, _, _ = app
    ok = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "42"})
    assert bad.status_code == 403


def test_post_needs_a_good_signature(app):
    client, seen, _ = app
    body = json.dumps(payload()).encode()
    r = client.post("/webhook", content=body, headers={"x-hub-signature-256": "sha256=00"})
    assert r.status_code == 401 and seen == []


def test_owner_message_handled_once_others_dropped(app):
    client, seen, db = app
    body = json.dumps(payload()).encode()
    assert client.post("/webhook", content=body, headers=signed(body)).status_code == 200
    assert client.post("/webhook", content=body, headers=signed(body)).status_code == 200  # Meta retry
    stranger = json.dumps(payload(sender="17865550111", mid="wamid.9")).encode()
    client.post("/webhook", content=stranger, headers=signed(stranger))
    assert [m.id for m in seen] == ["wamid.1"]
    health = client.get("/health").text
    assert '"dropped_not_owner": 1' in health and '"retries": 1' in health
    assert last_inbound(gate.connect(db), OWNER) is not None


def fake_graph():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        return httpx.Response(200, json={"messages": [{"id": "wamid.out123456"}], "success": True})

    return httpx.MockTransport(handler), calls


@pytest.fixture
def wa(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    rules_path = tmp_path / "RULES.md"
    rules_path.write_text(f"send: whatsapp -> {OWNER} ; the Owner's own chat ; until 2099-01-01\n")
    transport, calls = fake_graph()
    client = WhatsApp(token="t", phone_number_id="111", conn=gate.connect(":memory:"),
                      transport=transport, rules_path=rules_path)
    return client, calls


def test_send_inside_window(wa):
    client, calls = wa
    record_inbound(client.conn, "wamid.in", OWNER, "text")
    assert client.send_text(OWNER, "Morning, Felix", idempotency_key="k") == "wamid.out123456"
    method, path, body = calls[0]
    assert (method, path) == ("POST", "/v25.0/111/messages")
    # sent the way Marco texts: lowercase (Owner 2026-10-30)
    assert body == {"messaging_product": "whatsapp", "to": OWNER, "type": "text", "text": {"body": "morning, felix"}}


def test_send_outside_window_refused(wa):
    client, calls = wa
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    record_inbound(client.conn, "wamid.old", OWNER, "text", ts=old)
    with pytest.raises(gate.Refused, match="24-hour window"):
        client.send_text(OWNER, "hello", idempotency_key="k")
    assert calls == []


def test_send_to_anyone_else_refused(wa):
    client, calls = wa
    record_inbound(client.conn, "wamid.x", "17865550111", "text")
    with pytest.raises(gate.Refused, match="Owner only"):
        client.send_text("17865550111", "hi", idempotency_key="k")
    assert calls == []


def test_mark_read_with_typing(wa):
    client, calls = wa
    client.mark_read("wamid.in", typing=True)
    assert calls[0][2] == {"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.in",
                           "typing_indicator": {"type": "text"}}


def test_http_error_does_not_echo_text(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    transport = httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "Morning, Felix"}))
    client = WhatsApp(token="t", phone_number_id="111", conn=gate.connect(":memory:"), transport=transport)
    with pytest.raises(Exception) as info:
        client.mark_read("x")
    assert "Morning" not in str(info.value) and "400" in str(info.value)

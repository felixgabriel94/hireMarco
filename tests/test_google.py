import base64
import json
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from hiremarco import gate
from hiremarco.google import Calendar, Mail
from hiremarco.google.auth import SCOPES, auth_url, pkce_pair
from hiremarco.google.mail import body_text, query
from hiremarco.rules import read_grants


class FakeAuth:
    def headers(self):
        return {"Authorization": "Bearer test"}


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_pkce_and_auth_url():
    verifier, challenge = pkce_pair()
    assert len(verifier) >= 43 and "=" not in challenge
    url = auth_url("cid", "http://127.0.0.1:8765/", challenge, "st")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert q["scope"] == " ".join(SCOPES) and q["code_challenge_method"] == "S256"
    assert q["access_type"] == "offline" and q["state"] == "st"
    assert "gmail.modify" not in url and "gmail.send" not in url


def test_body_prefers_plain_then_strips_html():
    plain = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/plain", "body": {"data": b64("Dinner with Kai?")}},
        {"mimeType": "text/html", "body": {"data": b64("<p>ignored</p>")}}]}
    assert body_text(plain) == "Dinner with Kai?"
    rich = {"mimeType": "text/html", "body": {"data": b64("<style>x</style><p>Table for <b>4</b></p>")}}
    assert body_text(rich) == "Table for 4"


@pytest.fixture
def rules_path(tmp_path):
    p = tmp_path / "RULES.md"
    p.write_text("read: mail <- lucie@example.com ; the dinner email ; until 2099-01-01\n"
                 "read: mail <- @resy.com ; booking proof ; until 2099-01-01\n")
    return p


def test_query_names_only_granted_senders(rules_path):
    assert query(read_grants(rules_path)) == "from:(lucie@example.com OR resy.com) newer_than:2d"


def test_mail_opens_only_granted_senders(rules_path):
    opened = []
    froms = {"m1": "Lucie <lucie@example.com>", "m2": "Lucie <lucie@example.com.attacker.io>"}

    def handler(request):
        path = request.url.path
        if path.endswith("/messages"):
            assert "lucie@example.com" in request.url.params["q"]
            return httpx.Response(200, json={"messages": [{"id": "m1"}, {"id": "m2"}]})
        mid = path.rsplit("/", 1)[1]
        if request.url.params.get("format") == "metadata":
            return httpx.Response(200, json={"payload": {"headers": [{"name": "From", "value": froms[mid]}]}})
        opened.append(mid)
        return httpx.Response(200, json={"payload": {"mimeType": "text/plain", "body": {"data": b64("Dinner?")},
                                                     "headers": [{"name": "Subject", "value": "Kai"},
                                                                 {"name": "From", "value": froms[mid]}]}})

    items = Mail(auth=FakeAuth(), transport=httpx.MockTransport(handler), rules_path=rules_path).recent()
    assert [i.id for i in items] == ["m1"] and opened == ["m1"]
    assert items[0].subject == "Kai" and items[0].text == "Dinner?" and items[0].sender == "lucie@example.com"


def test_no_grants_reads_nothing(tmp_path):
    empty = tmp_path / "RULES.md"
    empty.write_text("(none)\n")
    transport = httpx.MockTransport(lambda r: pytest.fail("no request should be made"))
    assert Mail(auth=FakeAuth(), transport=transport, rules_path=empty).recent() == []


def test_calendar_add_needs_its_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    posted = []

    def handler(request):
        if request.method == "POST":
            posted.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "evt1"})
        return httpx.Response(200, json={"items": []})

    off = tmp_path / "off.md"
    off.write_text("(none)\n")
    on = tmp_path / "on.md"
    on.write_text("send: calendar -> * ; the booking ; until 2099-01-01\n")
    start = datetime(2026, 11, 5, 20, tzinfo=timezone(timedelta(hours=-5)))
    cal = Calendar(auth=FakeAuth(), conn=gate.connect(":memory:"), transport=httpx.MockTransport(handler), rules_path=off)
    assert cal.is_clear(start, start + timedelta(hours=2))
    with pytest.raises(gate.Refused, match="no send switch for calendar"):
        cal.add("Dinner with Kai", start, start + timedelta(hours=2), idempotency_key="b1")
    cal.rules_path = on
    assert cal.add("Dinner with Kai", start, start + timedelta(hours=2), idempotency_key="b1") == "evt1"
    assert posted[0]["summary"] == "Dinner with Kai" and posted[0]["start"]["dateTime"].endswith("-05:00")

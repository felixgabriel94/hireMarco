"""Quoting one of Felix's messages on WhatsApp (Owner 2026-11-02): only when it isn't plain what a text answers."""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from hiremarco import gate, inbox, offer, server
from hiremarco.calls import offers
from hiremarco.meta.client import Reply
from hiremarco.offer import Place
from hiremarco.server import handle, offer_yes, receive_offer, send_held_offers
from hiremarco.studio.beat_in import asked_file, asked_for, keep_received, start_session
from hiremarco.whatsapp import Inbound, WhatsApp
from hiremarco.whatsapp.client import latest_inbound, record_inbound

OWNER = "15551230000"
T0 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
KITCHEN = Place("kitchen", "Test Kitchen", "15557770000")


class Brain:
    def __init__(self, reply="Sure.", quote="", reaction=""):
        self.decision = {"action": "reply", "title": "", "reply": reply, "reaction": reaction, "quote": quote, "remember": [], "forget": []}
        self.seen = []

    def converse(self, history, text, **kw):
        self.seen.append(json.loads(text))
        return Reply(text=json.dumps(self.decision), model="m", prompt_tokens=0, completion_tokens=0, cached_tokens=0, cost_usd=0.0, duration_ms=0)


@pytest.fixture
def line(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    monkeypatch.setattr("hiremarco.joblog.STATE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(gate.checks, "kill_switch_on", lambda: False)
    rules = tmp_path / "RULES.md"
    rules.write_text(f"send: whatsapp -> {OWNER} ; chat ; until revoked\nsend: email-offers -> {OWNER} ; offers ; until revoked\n")
    sent, refuse = [], {"context": False}

    def handler(request):
        body = json.loads(request.content)
        if refuse["context"] and "context" in body:
            return httpx.Response(400, json={"error": {"message": "too old"}})
        if "type" in body:
            sent.append(body)
        return httpx.Response(200, json={"messages": [{"id": "wamid.o"}]})

    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"), transport=httpx.MockTransport(handler), rules_path=rules)
    return {"wa": wa, "sent": sent, "refuse": refuse, "rules": rules, "tmp": tmp_path}


def arrive(line, mid, minutes=0):
    record_inbound(line["wa"].conn, mid, OWNER, "text", ts=datetime.now(timezone.utc) - timedelta(hours=1) + timedelta(minutes=minutes))
    return Inbound(id=mid, sender=OWNER, kind="text", text=f"message {mid}")


def turn(line, message, brain=None):
    return handle(message, wa=line["wa"], marco=brain or Brain(), inbox=line["tmp"] / "in", booth=lambda: "booth", running=lambda: True)


def quotes(line):
    return [m.get("context", {}).get("message_id") for m in line["sent"] if m["type"] == "text"]


def test_answering_his_latest_never_quotes(line):
    turn(line, arrive(line, "a"))
    assert quotes(line) == [None]


def test_answering_a_message_he_has_written_past_quotes_it(line):
    first = arrive(line, "a")
    second = arrive(line, "b", minutes=1)  # both reached the webhook before the first was answered
    turn(line, first, Brain("One."))
    turn(line, second, Brain("Two."))  # the same words twice in ten minutes would be held as a repeat
    assert quotes(line) == ["a", None]


def test_a_rejected_quote_still_gets_the_message_through(line):
    first = arrive(line, "a")
    arrive(line, "b", minutes=1)
    line["refuse"]["context"] = True
    turn(line, first)
    assert quotes(line) == [None] and line["sent"][0]["text"]["body"] == "Sure."


def test_it_never_fails_when_the_plain_send_fails(line):
    line["wa"]._post_message = lambda payload: (_ for _ in ()).throw(__import__("hiremarco.whatsapp.client", fromlist=["x"]).WhatsAppError("down"))
    record_inbound(line["wa"].conn, "a", OWNER, "text")
    record_inbound(line["wa"].conn, "b", OWNER, "text")
    with pytest.raises(Exception):
        line["wa"].send_text(OWNER, "hello", idempotency_key="k", quote="a")


def test_the_turn_ends_and_the_quote_with_it(line):
    first = arrive(line, "a")
    arrive(line, "b", minutes=1)
    turn(line, first)
    assert line["wa"].answering is None
    line["wa"].send_text(OWNER, "later", idempotency_key="k2")
    assert quotes(line)[-1] is None


def test_his_earlier_question_can_be_pointed_at_only_from_the_list(line):
    first, second, third = arrive(line, "a"), arrive(line, "b", minutes=1), arrive(line, "c", minutes=2)
    turn(line, first, Brain("One."))
    turn(line, second, Brain("Two."))
    brain = Brain("Which one did you mean there?", quote="a")
    turn(line, third, brain)
    assert [m["says"] for m in brain.seen[0]["his_earlier_messages"]] == ["message a", "message b"]
    assert quotes(line)[-1] == "a"


@pytest.mark.parametrize("ref", ["z", "wamid.made.up", "marco"])
def test_a_ref_off_the_list_quotes_nothing(line, ref):
    turn(line, arrive(line, "a"), Brain("One."))
    turn(line, arrive(line, "b", minutes=1), Brain("Hm?", quote=ref))
    assert quotes(line) == [None, None]


def test_the_brain_never_sees_marcos_lines_as_messages_to_quote(line):
    turn(line, arrive(line, "a"), Brain("From Marco."))
    brain = Brain()
    turn(line, arrive(line, "b", minutes=1), brain)
    assert "From Marco." not in json.dumps(brain.seen[0]["his_earlier_messages"])


def test_a_call_result_quotes_the_yes_that_started_it(line, monkeypatch):
    places = line["tmp"] / "places.json"
    places.write_text(json.dumps([KITCHEN.__dict__]))
    monkeypatch.setenv("HIREMARCO_PLACES", str(places))
    conn = offers.connect(":memory:")
    record_inbound(line["wa"].conn, "yes-1", OWNER, "text", ts=T0)
    offers.record_offer(conn, KITCHEN, weekday="thursday", day="2026-11-05", hour=20, party_size=4, now=datetime.now(timezone.utc))
    offer_yes("yes", OWNER, "yes-1", line["wa"], conn=conn, places=[KITCHEN])
    pending = offers.asking(conn)
    assert pending.asked_id == "yes-1"
    offer_yes("whatever works", OWNER, "yes-2", line["wa"], conn=conn, places=[KITCHEN])
    assert offers.get(conn, pending.id).asked_id == "yes-1"  # a later reply doesn't move it


def test_a_spoken_yes_has_no_message_to_quote(line):
    conn = offers.connect(":memory:")
    made = offers.record_offer(conn, KITCHEN, weekday="thursday", day="2026-11-05", hour=20, party_size=4, now=datetime.now(timezone.utc))
    record_inbound(line["wa"].conn, "w", OWNER, "text")
    offer_yes("yes", OWNER, f"booth-yes-{made.id}", line["wa"], conn=conn, places=[KITCHEN], offer=made)
    assert offers.get(conn, made.id).asked_id is None


def test_a_booking_proof_quotes_the_message_that_asked(line):
    conn = inbox.connect(":memory:")
    inbox.open_task(conn, "offer-1", "Test Kitchen booking", {"place": "Test Kitchen"}, asked_id="yes-1")
    inbox.open_task(conn, "offer-2", "Other", {})
    assert inbox.asked_of(conn, "offer-1") == {"quote": "yes-1"} and inbox.asked_of(conn, "offer-2") == {} and inbox.asked_of(conn, "no") == {}
    assert "asked_id" not in json.dumps(inbox.get_task(conn, "offer-1").expect)  # a message id never goes to a model


def test_the_tasks_table_gains_the_column_on_an_old_file(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("create table tasks (id text primary key, name text not null, expect text not null, opened_at text not null,"
                " status text not null, closed_at text, proof text)")
    old.execute("insert into tasks values ('t', 'n', '{}', 'x', 'open', null, null)")
    old.commit()
    old.close()
    assert inbox.asked_of(inbox.connect(path), "t") == {}


def test_session_ready_quotes_the_message_that_asked(tmp_path):
    from hiremarco.studio.booth import Booth, Tape

    folder = tmp_path / "in"
    keep_received(b"RIFF", "beat.wav", folder)
    started = start_session(folder, "Night Shift", asked="ask-1")
    assert asked_file(started).read_text() == "ask-1"
    told = []
    b = Booth(understand=lambda l: None, logic=lambda c: c.describe(), say=lambda t: None, feedback=lambda a, r: None,
              tape=Tape(1000, seconds=1), log=lambda l: None, load_beat=None,
              text_owner=lambda body, quote=None: told.append((body, quote)) or "ok")
    b._asked = asked_for(started)
    assert not asked_file(started).exists()
    b._text("Session's ready.")
    assert told == [("Session's ready.", "ask-1")]


def test_session_ready_with_nothing_kept_goes_plain(tmp_path):
    from hiremarco.studio.booth import Booth, Tape

    told = []
    b = Booth(understand=lambda l: None, logic=lambda c: c.describe(), say=lambda t: None, feedback=lambda a, r: None,
              tape=Tape(1000, seconds=1), log=lambda l: None, text_owner=lambda body: told.append(body) or "ok")
    b._text("Session's ready.")
    assert told == ["Session's ready."]


def test_an_email_offer_and_a_heads_up_never_quote_even_when_held(line, monkeypatch):
    monkeypatch.setenv("HIREMARCO_OFFER_TOKEN", "w")
    record_inbound(line["wa"].conn, "a", OWNER, "text", ts=datetime.now(timezone.utc) - timedelta(hours=1))
    record_inbound(line["wa"].conn, "b", OWNER, "text", ts=datetime.now(timezone.utc) - timedelta(minutes=30))
    now = datetime.now(timezone.utc)
    for key, kind in (("mail-1", "heads_up"), ("mail-2", "reply")):
        raw = json.dumps({"offer_id": key, "message_id": key, "kind": kind, "who": "Dana", "subject": "Hi", "says": "Dana asks."}).encode()
        stamp = str(int(now.timestamp()))
        receive_offer(raw, {offer.HEADER_TIME: stamp, offer.HEADER_OFFER: key, offer.HEADER_SIGNATURE: offer.sign("w", stamp, key, raw)},
                      wa=line["wa"], conn=offers.connect(":memory:"), places=[], now=now, rules_path=line["rules"])
    assert len(line["sent"]) == 2 and quotes(line) == [None, None]


def test_the_latest_is_read_from_what_reached_the_webhook(line):
    arrive(line, "a")
    arrive(line, "b", minutes=1)
    assert latest_inbound(line["wa"].conn, OWNER) == "b" and latest_inbound(line["wa"].conn, "19990000000") is None

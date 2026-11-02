"""When Felix quotes one of Marco's messages, his answer goes to exactly that one, never just the latest (Owner 2026-11-02)."""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from hiremarco import gate, offer as reader
from hiremarco.calls import offers
from hiremarco.inbox import outbox
from hiremarco.meta.client import Reply
from hiremarco.offer import Place
from hiremarco.server import handle, quoted_reply, receive_offer
from hiremarco.whatsapp import Inbound, WhatsApp, parse_payload
from hiremarco.whatsapp.client import record_inbound
from hiremarco.whatsapp.memory import note_sent, quoted_words

OWNER = "15551230000"
KITCHEN = Place("kitchen", "Test Kitchen", "15557770000")
BISTRO = Place("bistro", "Corner Bistro", "15555550123")


class Brain:
    def __init__(self, reply="Sure."):
        self.decision = {"action": "reply", "title": "", "reply": reply, "reaction": "", "quote": "", "remember": [], "forget": []}
        self.seen = []

    def converse(self, history, text, **kw):
        self.seen.append(json.loads(text))
        return Reply(text=json.dumps(self.decision), model="m", prompt_tokens=0, completion_tokens=0, cached_tokens=0, cost_usd=0.0, duration_ms=0)


@pytest.fixture
def line(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    monkeypatch.setenv("HIREMARCO_OFFER_TOKEN", "w")
    monkeypatch.setattr("hiremarco.joblog.STATE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(gate.checks, "kill_switch_on", lambda: False)
    monkeypatch.setattr("hiremarco.gate.kill.kill_switch_on", lambda: False)
    rules = tmp_path / "RULES.md"
    rules.write_text(f"send: whatsapp -> {OWNER} ; chat ; until revoked\nsend: email-offers -> {OWNER} ; o ; until revoked\nsend: mail -> * ; m ; until revoked\n")
    sent, n = [], [0]

    def handler(request):
        body = json.loads(request.content)
        if "type" not in body:
            return httpx.Response(200, json={"success": True})
        n[0] += 1
        sent.append({**body, "id": f"wamid.{n[0]}"})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{n[0]}"}]})

    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"), transport=httpx.MockTransport(handler), rules_path=rules)
    record_inbound(wa.conn, "in.0", OWNER, "text")
    conn = offers.connect(":memory:")
    return {"wa": wa, "sent": sent, "conn": conn, "rules": rules, "tmp": tmp_path}


def deliver(line, key, kind="table", place="kitchen", now=None):
    now = now or datetime.now(timezone.utc)
    data = {"offer_id": key, "message_id": key, "kind": kind, "who": "Dana", "subject": "Hi", "says": f"Dana asks ({key}).", "place_id": place,
            "weekday": "thursday", "day": "2026-11-05", "hour": 20, "party_size": 4}
    raw = json.dumps(data).encode()
    stamp = str(int(now.timestamp()))
    status, _ = receive_offer(raw, {reader.HEADER_TIME: stamp, reader.HEADER_OFFER: key, reader.HEADER_SIGNATURE: reader.sign("w", stamp, key, raw)},
                              wa=line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO], now=now, rules_path=line["rules"])
    assert status == 200
    r = offers._row(line["conn"].execute("select * from offers where offer_key = ?", (key,)).fetchone())
    assert r.message_ids == line["sent"][-1]["id"]
    return r


def said_last(line):
    return line["sent"][-1]["text"]["body"]


def test_the_webhook_keeps_what_he_quoted():
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "m1", "from": OWNER, "type": "text", "text": {"body": "yes"}, "context": {"from": "1", "id": "wamid.older"}},
        {"id": "m2", "from": OWNER, "type": "text", "text": {"body": "yes"}}]}}]}]}
    first, second = parse_payload(payload)
    assert first.quoted == "wamid.older" and second.quoted == ""


def test_two_open_offers_and_a_quoted_yes_goes_to_the_older_one(line, monkeypatch):
    monkeypatch.setattr(offers, "load_places", lambda: [KITCHEN, BISTRO])
    older = deliver(line, "mail-old", place="kitchen")
    newer = deliver(line, "mail-new", place="bistro")
    assert offers.get(line["conn"], older.id).status == "replaced"  # an unquoted yes would go to the newer, as today
    done = quoted_reply("yes", OWNER, "in.1", older.message_ids, line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO])
    assert f"offer {older.id}: asked the fallback questions" in done
    assert offers.get(line["conn"], older.id).status == "questions"
    assert offers.get(line["conn"], newer.id).status == "pending"  # the newer one is untouched, still his to answer
    assert offers.get(line["conn"], older.id).asked_id == "in.1"


def test_an_unquoted_yes_behaves_as_today_and_goes_to_the_latest(line):
    from hiremarco.server import offer_yes

    deliver(line, "mail-old", place="kitchen")
    newer = deliver(line, "mail-new", place="bistro")
    assert f"offer {newer.id}: asked" in offer_yes("yes", OWNER, "in.1", line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO])


def test_his_answer_to_the_what_if_questions_quoting_them_goes_to_that_offer(line, monkeypatch):
    monkeypatch.setattr(offers, "load_places", lambda: [KITCHEN, BISTRO])
    first = deliver(line, "mail-old", place="kitchen")
    quoted_reply("yes", OWNER, "in.1", first.message_ids, line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO])
    questions = line["sent"][-1]["id"]
    assert offers.by_message(line["conn"], questions).id == first.id
    deliver(line, "mail-new", place="bistro")
    from hiremarco.calls import brief

    monkeypatch.setattr(brief, "build", lambda *a, **k: (_ for _ in ()).throw(brief.BriefIncomplete("reservation", ["name"])))
    quoted_reply("9pm works", OWNER, "in.2", questions, line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO])
    assert offers.get(line["conn"], first.id).fallbacks == "9pm works"


def test_a_quoted_no_declines_that_offer_only(line):
    older, newer = deliver(line, "mail-old"), deliver(line, "mail-new", place="bistro")
    assert "declined" in quoted_reply("no", OWNER, "in.1", older.message_ids, line["wa"], conn=line["conn"])
    assert offers.get(line["conn"], older.id).status == "declined" and offers.get(line["conn"], newer.id).status == "pending"


def test_a_quoted_yes_on_an_expired_offer_says_so_and_acts_on_no_other(line):
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=45)
    record_inbound(line["wa"].conn, "in.old", OWNER, "text", ts=long_ago)
    old = deliver(line, "mail-old", now=long_ago)
    newer = deliver(line, "mail-new", place="bistro")
    done = quoted_reply("yes", OWNER, "in.1", old.message_ids, line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO])
    assert "nothing done" in done and said_last(line) == "That was a while back, so I held off. Still want me to book it? Just say the word."
    assert offers.get(line["conn"], old.id).status == "pending" and offers.get(line["conn"], newer.id).status == "replaced"  # no call, and the question is asked again
    assert not [m for m in line["sent"] if "before i call" in str(m).lower()]


def test_saying_the_word_after_that_is_a_yes_to_that_one_with_a_fresh_window(line):
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=45)
    old = deliver(line, "mail-old", now=long_ago)
    quoted_reply("yes", OWNER, "in.1", old.message_ids, line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO])
    again = offers.get(line["conn"], old.id)
    assert again.offered_at > long_ago + timedelta(minutes=40) and line["sent"][-1]["id"] in again.message_ids
    done = quoted_reply("yes", OWNER, "in.2", line["sent"][-1]["id"], line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO])
    assert "asked the fallback questions" in done


def test_a_day_that_has_passed_is_not_offered_again(line):
    long_ago = datetime.now(timezone.utc) - timedelta(days=2)
    record_inbound(line["wa"].conn, "in.old", OWNER, "text", ts=datetime.now(timezone.utc))
    old = deliver(line, "mail-old", now=long_ago)
    line["conn"].execute("update offers set day = '2020-01-02' where id = ?", (old.id,))
    quoted_reply("yes", OWNER, "in.1", old.message_ids, line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO])
    assert "book it" not in said_last(line) and "held off" in said_last(line)
    assert offers.get(line["conn"], old.id).status == "pending" and offers.pending(line["conn"]) is None


def test_old_heads_up_has_nothing_to_ask_again(line):
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=45)
    old = deliver(line, "mail-h", kind="heads_up", now=long_ago)
    quoted_reply("yes", OWNER, "in.1", old.message_ids, line["wa"], conn=line["conn"])
    assert said_last(line) == "That was a while back, so I held off. Let me know if there's something you need on it."
    assert offers.pending(line["conn"]) is None


@pytest.mark.parametrize("line_of_his", ["expired", "offer", "draft id", "wamid"])
def test_no_system_words_in_what_he_reads(line, line_of_his):
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=45)
    old = deliver(line, "mail-old", now=long_ago)
    quoted_reply("yes", OWNER, "in.1", old.message_ids, line["wa"], conn=line["conn"], places=[KITCHEN, BISTRO])
    assert line_of_his not in said_last(line).lower()


def test_a_quoted_yes_on_one_already_taken_says_so(line):
    done = deliver(line, "mail-1")
    offers.set_status(line["conn"], done.id, "called")
    assert "already" in quoted_reply("yes", OWNER, "in.1", done.message_ids, line["wa"], conn=line["conn"])
    assert said_last(line) == "Already took care of that one."


def test_a_quoted_yes_on_a_message_from_before_they_were_kept_acts_on_nothing(line):
    live = deliver(line, "mail-1")
    assert "nothing done" in quoted_reply("yes", OWNER, "in.1", "wamid.ancient", line["wa"], conn=line["conn"])
    assert said_last(line) == "Not sure which one you mean. Can you tell me what you'd like me to do?" and offers.get(line["conn"], live.id).status == "pending"


def test_a_quoted_yes_on_some_other_message_never_reaches_an_open_offer(line):
    line["conn"] = offers.connect()  # the file the handler itself opens, so the offer is really in its reach
    live = deliver(line, "mail-1")
    note_sent(line["wa"].conn, "wamid.chat", "Lead or double?")
    out = handle(Inbound(id="in.1", sender=OWNER, kind="text", text="yes", quoted="wamid.chat"), wa=line["wa"], marco=(brain := Brain("Double it is.")),
                 inbox=line["tmp"] / "in", booth=lambda: "b", running=lambda: True)
    assert "brain: reply" in out
    assert brain.seen[0]["he_is_replying_to"] == {"from": "marco", "says": "Lead or double?"}
    assert offers.get(line["conn"], live.id).status == "pending"


def test_a_reply_offer_quoted_asks_what_to_say_for_that_one(line):
    reply_offer = deliver(line, "mail-reply", kind="reply")
    table = deliver(line, "mail-table", place="bistro")
    class Clear:
        def is_clear(self, a, b):
            return False
    done = quoted_reply("yes", OWNER, "in.1", reply_offer.message_ids, line["wa"], conn=line["conn"], calendar=Clear())
    assert "asked what to say" in done and offers.get(line["conn"], reply_offer.id).status == "what to say"
    assert offers.get(line["conn"], table.id).status == "pending"


def test_quoting_him_back_gives_the_brain_his_own_words(line):
    from hiremarco.whatsapp.memory import note_words

    note_words(line["wa"].conn, "in.old", "the hook needs more space")
    assert quoted_words(line["wa"].conn, "in.old") == ("felix", "the hook needs more space")
    assert quoted_words(line["wa"].conn, "nope") is None


# the email gate

class Drafts:
    def __init__(self):
        self.raws, self.sent, self.deleted = {}, [], []

    def create_draft(self, raw, thread_id=None):
        draft = f"d{len(self.raws) + 1}"
        self.raws[draft] = raw
        return draft

    def draft_raw(self, draft_id):
        return self.raws.get(draft_id)

    def send_draft(self, draft_id):
        self.sent.append(draft_id)
        return f"g-{draft_id}"

    def delete_draft(self, draft_id):
        self.deleted.append(draft_id)
        self.raws.pop(draft_id, None)


@pytest.fixture
def mail(line):
    box, drafts = outbox.connect(":memory:"), Drafts()

    def draft(to, tag):
        raw = outbox.build(to, "", "Hello", f"Body {tag}")
        outbox._make_draft(box, drafts, line["wa"], OWNER, tag, kind="new", to=to, cc="", subject="Hello", body=f"Body {tag}", words="w", raw=raw)
        return line["sent"][-1]["id"]

    def words(said, quoted="", n=[0]):
        n[0] += 1
        return outbox.handle_words(said, OWNER, f"w{n[0]}", line["wa"], conn=box, mail=drafts, gate_conn=gate.connect(":memory:"),
                                   rules_path=line["rules"], quoted=quoted)

    return {"box": box, "drafts": drafts, "draft": draft, "words": words}


def test_a_quoted_send_goes_to_the_preview_he_quoted_not_the_latest(line, mail):
    first, second = mail["draft"]("a@example.com", "one"), mail["draft"]("b@example.com", "two")
    assert second != first
    assert mail["words"]("send", quoted=first) == "mail: sent on his word"
    assert mail["drafts"].sent == ["d1"] and "a@example.com" in said_last(line)


def test_an_unquoted_send_goes_to_the_newest_as_today(line, mail):
    mail["draft"]("a@example.com", "one"), mail["draft"]("b@example.com", "two")
    assert mail["words"]("send") == "mail: sent on his word"
    assert mail["drafts"].sent == ["d2"]


def test_a_quoted_send_on_something_that_is_no_draft_sends_nothing(line, mail):
    mail["draft"]("a@example.com", "one")
    assert "nothing done" in mail["words"]("send", quoted="wamid.chat")
    assert mail["drafts"].sent == [] and "isn't one of the emails I wrote" in said_last(line)


def test_a_quoted_send_on_a_closed_draft_sends_nothing_and_not_the_other_one(line, mail):
    first = mail["draft"]("a@example.com", "one")
    mail["words"]("send", quoted=first)
    mail["draft"]("b@example.com", "two")
    assert "closed draft" in mail["words"]("send", quoted=first)
    assert mail["drafts"].sent == ["d1"] and "already closed" in said_last(line)


def test_a_quoted_cancel_deletes_only_that_draft(line, mail):
    first = mail["draft"]("a@example.com", "one")
    mail["draft"]("b@example.com", "two")
    assert mail["words"]("cancel", quoted=first) == "mail: draft cancelled"
    assert mail["drafts"].deleted == ["d1"] and "d2" in mail["drafts"].raws

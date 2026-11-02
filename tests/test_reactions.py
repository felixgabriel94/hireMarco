"""Marco's reactions on Felix's messages (Owner 2026-11-02): fourteen, plain, and a reaction never stands in for proof."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from hiremarco import gate, server
from hiremarco.calls import CallError
from hiremarco.meta.client import Reply
from hiremarco.server import handle
from hiremarco.whatsapp import Inbound, WhatsApp, reactions
from hiremarco.whatsapp.brain import RULES, SCHEMA
from hiremarco.whatsapp.client import record_inbound

OWNER = "15551230000"
THE_SET = "👍 👨‍💻 📠 🤝 📞 💽 📎 📸 🛒 ✉️ 📆 ✅ 💸 😤 😂".split()


class Brain:
    def __init__(self, reaction="", reply="", action="reply", **rest):
        self.decision = {"action": action, "title": "", "reply": reply, "reaction": reaction, "remember": [], "forget": [], **rest}

    def converse(self, history, text, **kw):
        return Reply(text=json.dumps(self.decision), model="m", prompt_tokens=0, completion_tokens=0, cached_tokens=0,
                     cost_usd=0.0, duration_ms=0)


@pytest.fixture
def line(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    monkeypatch.setattr("hiremarco.joblog.STATE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(gate.checks, "kill_switch_on", lambda: False)
    rules = tmp_path / "RULES.md"
    rules.write_text(f"send: whatsapp -> {OWNER} ; the Owner's own chat ; until revoked\n")
    sent, refuse = [], {"reaction": False}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, content=b"RIFFdata") if request.url.host == "x" \
                else httpx.Response(200, json={"url": "https://x/m", "mime_type": "audio/mpeg"})
        body = json.loads(request.content)
        if body.get("type") == "reaction" and refuse["reaction"]:
            return httpx.Response(400, json={"error": {"message": "no"}})
        if "type" in body:
            sent.append(body)
        return httpx.Response(200, json={"messages": [{"id": "wamid.o"}]})

    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"), transport=httpx.MockTransport(handler), rules_path=rules)
    record_inbound(wa.conn, "wamid.in", OWNER, "text")
    return {"wa": wa, "sent": sent, "refuse": refuse, "inbox": tmp_path / "inbox"}


def message(mid="w1", kind="text", text="", **kw):
    return Inbound(id=mid, sender=OWNER, kind=kind, text=text, **kw)


def run(line, said, brain):
    return handle(message(text=said), wa=line["wa"], marco=brain, inbox=line["inbox"], booth=lambda: "booth faked", running=lambda: True)


def kinds(line):
    return [(m["type"], m["reaction"]["emoji"] if m["type"] == "reaction" else m.get("text", {}).get("body")) for m in line["sent"]]


def test_the_fifteen_are_exactly_these_all_plain():
    assert sorted(reactions.ALLOWED) == sorted(THE_SET) and len(set(reactions.ALLOWED)) == 15
    assert not [e for e in reactions.ALLOWED if any(0x1F3FB <= ord(c) <= 0x1F3FF for c in e)]  # no skin tone anywhere
    assert not set("🎚️ 🎙️ 💪".split()) & set(reactions.ALLOWED)


def test_the_brain_picks_only_from_its_list_and_cant_claim_work_with_one():
    assert SCHEMA["properties"]["reaction"]["enum"] == ["", *reactions.MODEL_PICKS]
    assert not {reactions.ON_IT, reactions.RESULT, reactions.CALLING, reactions.DRAFT, reactions.FILE, reactions.PHOTOS} & set(reactions.MODEL_PICKS.values())
    assert "never type an emoji" in RULES


def test_a_reaction_with_nothing_to_say_is_the_whole_reply(line):
    out = run(line, "fyi I'm out friday", Brain("noted"))
    assert kinds(line) == [("reaction", "👍")] and "brain: reply" in out
    assert line["sent"][0]["reaction"]["message_id"] == "w1" and line["sent"][0]["to"] == OWNER


def test_a_reaction_and_words_both_go_when_there_is_something_to_say(line):
    run(line, "great, the invoice got paid, what's next?", Brain("money", reply="Nice. Next is the mix."))
    assert kinds(line) == [("reaction", "💸"), ("text", "Nice. Next is the mix.")]


def test_when_a_reaction_fails_a_short_line_goes_instead_and_never_silence(line):
    line["refuse"]["reaction"] = True
    run(line, "thanks man", Brain("deal"))
    assert kinds(line) == [("text", "Anytime.")]


def test_a_failed_reaction_beside_words_needs_no_second_line(line):
    line["refuse"]["reaction"] = True
    run(line, "paid!", Brain("money", reply="Good news."))
    assert kinds(line) == [("text", "Good news.")]


def test_anything_off_the_list_does_not_go(line):
    assert reactions.react(line["wa"], OWNER, "w1", "🎚️") is False
    assert reactions.react(line["wa"], OWNER, "w1", "👍🏻") is False
    assert line["sent"] == []
    run(line, "cool", Brain("bomb", reply="Okay."))
    assert kinds(line) == [("text", "Okay.")]


def test_a_reaction_the_brain_invents_with_no_words_is_no_answer(line):
    run(line, "cool", Brain("🎚️"))
    assert not [k for k in kinds(line) if k[0] == "reaction"]


def test_only_a_plain_reply_can_be_silent(line):
    # a start must say so: with no words it is off the schema, whatever reaction it names
    run(line, "set it up", Brain("noted", action="start"))
    assert ("reaction", "👍") not in kinds(line)


def test_the_gate_holds_a_reaction_as_it_would_a_text(line, monkeypatch):
    monkeypatch.setattr(gate.checks, "kill_switch_on", lambda: True)
    assert reactions.react(line["wa"], OWNER, "w1", reactions.NOTED) is False and line["sent"] == []


def test_a_beat_gets_the_disc_and_still_asks_its_question(line):
    handle(message(kind="document", media_id="m/1", filename="beat.mp3", mime_type="audio/mpeg"), wa=line["wa"], inbox=line["inbox"])
    emoji, text = kinds(line)
    assert emoji == ("reaction", "💽") and "Want me to start a session" in text[1]


def test_a_file_gets_the_clip_and_nothing_else_and_a_line_if_that_fails(line):
    handle(message(kind="document", media_id="m/1", filename="contract.xyz", mime_type="application/x-thing"), wa=line["wa"], inbox=line["inbox"])
    assert kinds(line) == [("reaction", "📎")]
    line["sent"].clear()
    line["refuse"]["reaction"] = True
    handle(message("w2", kind="document", media_id="m/1", filename="contract2.xyz", mime_type="application/x-thing"), wa=line["wa"], inbox=line["inbox"])
    assert kinds(line) == [("text", "Got your file.")]


def test_the_questions_before_a_call_get_no_phone(line, monkeypatch):
    monkeypatch.setattr(server, "email_words", lambda *a, **k: None)
    monkeypatch.setattr(server, "offer_yes", lambda *a, **k: "offer 1: asked the fallback questions before dialing")
    run(line, "yes", Brain())
    assert line["sent"] == []


def test_a_draft_shown_gets_the_envelope_and_never_replaces_the_preview(line, monkeypatch):
    def draft(said, sender, message_id, wa):
        wa.send_text(sender, "To: a@example.com ... Say send", idempotency_key="p", exact=True)
        return "mail: reply draft shown"

    monkeypatch.setattr(server, "email_words", draft)
    run(line, "reply to pat", Brain())
    assert kinds(line) == [("text", "To: a@example.com ... Say send"), ("reaction", "✉️")]


def test_starting_a_session_gets_on_it_and_the_brains_own_pick_gives_way(line):
    from hiremarco.studio.beat_in import keep_received

    keep_received(b"RIFF", "beat.wav", line["inbox"])
    run(line, "set it up", Brain("noted", action="start", reply="On it."))
    assert kinds(line) == [("reaction", "👨‍💻"), ("text", "On it.")]


def test_on_it_is_not_claimed_when_nothing_started(line):
    run(line, "set it up", Brain(action="start", reply="On it."))
    assert kinds(line) == [("text", "I don't have a beat waiting. Send me one and I'll set it up.")]


def test_an_email_offer_never_reacts(line, tmp_path):
    from hiremarco import offer
    from hiremarco.calls import offers
    from hiremarco.server import receive_offer

    line["wa"].rules_path.write_text(f"send: whatsapp -> {OWNER} ; chat ; until revoked\nsend: email-offers -> {OWNER} ; o ; until revoked\n")
    raw = json.dumps({"offer_id": "mail-1", "message_id": "m1", "kind": "heads_up", "who": "Dana", "subject": "Hi"}).encode()
    now = datetime.now(timezone.utc)
    stamp = str(int(now.timestamp()))
    import os

    os.environ["HIREMARCO_OFFER_TOKEN"] = "w"
    try:
        receive_offer(raw, {offer.HEADER_TIME: stamp, offer.HEADER_OFFER: "mail-1", offer.HEADER_SIGNATURE: offer.sign("w", stamp, "mail-1", raw)},
                      wa=line["wa"], conn=offers.connect(":memory:"), places=[], now=now, rules_path=line["wa"].rules_path)
    finally:
        del os.environ["HIREMARCO_OFFER_TOKEN"]
    assert [m["type"] for m in line["sent"]] == ["text"]


def test_he_remembers_that_he_reacted_so_his_next_answer_can_see_it(line):
    from hiremarco.whatsapp.memory import recall

    run(line, "thanks man", Brain("deal"))
    assert recall(line["wa"].conn)[-1][2] == "[reacted 🤝]"


def test_a_shoot_gets_the_camera_once_on_its_last_frame(tmp_path, monkeypatch):
    from tests.test_selects import Line, Marco, burst

    line = Line(tmp_path, monkeypatch)
    burst(line, 6, Marco())
    reacted = [m for m in line.sent if m["type"] == "reaction"]
    assert [(m["reaction"]["emoji"], m["reaction"]["message_id"]) for m in reacted] == [("📸", "f5")]
    assert line.texts() == ["Got 6 frames."]


# the result: the page coming out of the fax

KITCHEN = ("kitchen", "Test Kitchen", "15557770000")


class FakeCalls:
    """A dial that sees what had already gone to WhatsApp when it was placed, and can fail or report a result."""

    def __init__(self, line, tmp_path, data=None, fails=None):
        self.line, self.tmp_path, self.data, self.fails, self.seen = line, tmp_path, data or {"status": "failed"}, fails, None

    def place(self, *a, **k):
        self.seen = reacted(self.line)
        if self.fails:
            raise self.fails
        return {"conversation_id": "c"}

    def _json(self, *a, **k):
        return self.data

    def transcript(self, cid):
        path = self.tmp_path / "t.json"
        path.write_text(json.dumps(self.data))
        return path


def reacted(line):
    return [(m["reaction"]["emoji"], m["reaction"]["message_id"]) for m in line["sent"] if m["type"] == "reaction"]


@pytest.fixture
def table(monkeypatch):
    from hiremarco.calls import brief as briefs
    from hiremarco.calls import offers
    from hiremarco.offer import Place

    monkeypatch.setattr(briefs, "build", lambda *a, **k: "brief")
    conn = offers.connect(":memory:")
    place = Place(*KITCHEN)
    return {"conn": conn, "place": place, "made": offers.record_offer(conn, place, weekday="thursday", day="2026-11-05", hour=20,
                                                                     party_size=4, now=datetime.now(timezone.utc))}


def yes_then_answer(line, table, calls):
    server.offer_yes("yes", OWNER, "the-yes", line["wa"], conn=table["conn"], places=[table["place"]])
    assert reacted(line) == []  # the questions before a call get no phone
    return server.offer_yes("whatever works", OWNER, "the-reply", line["wa"], conn=table["conn"], calls=calls,
                            places=[table["place"]], start=lambda f: f())


@pytest.mark.parametrize("data, faxed", [
    ({"status": "done", "transcript": [{"role": "agent", "message": "See you then."}], "analysis": {}}, True),
    ({"status": "done", "transcript": [{"role": "agent", "message": "Okay, bye."}], "analysis": {}}, False),
    ({"status": "done", "transcript": [{"role": "agent", "message": "Thanks for adding us to the waitlist."}], "analysis": {}}, False),
    ({"status": "failed"}, False),
])
def test_the_phone_goes_on_the_message_that_dials_and_the_fax_only_on_a_booking_on_the_one_that_asked(line, table, tmp_path, data, faxed):
    calls = FakeCalls(line, tmp_path, data)
    yes_then_answer(line, table, calls)
    assert calls.seen == [("📞", "the-reply")]  # up before the dial, not after
    assert reacted(line) == [("📞", "the-reply")] + ([("📠", "the-yes")] if faxed else [])
    assert any("Calling Test Kitchen now" in str(m) for m in line["sent"])


@pytest.mark.parametrize("failure", [gate.Refused("no switch"), CallError("did not start")])
def test_the_phone_comes_off_when_the_dial_fails_and_the_text_says_so(line, table, tmp_path, failure):
    calls = FakeCalls(line, tmp_path, fails=failure)
    yes_then_answer(line, table, calls)
    assert calls.seen == [("📞", "the-reply")]
    assert reacted(line) == [("📞", "the-reply"), ("", "the-reply")]
    assert "couldn't get the call to Test Kitchen going" in kinds(line)[-1][1]
    assert not any("📠" in str(m) for m in line["sent"])


def test_the_phone_comes_off_on_an_error_nobody_planned_for_too(line, table, tmp_path):
    with pytest.raises(KeyError):
        yes_then_answer(line, table, FakeCalls(line, tmp_path, fails=KeyError("agent id")))
    assert reacted(line) == [("📞", "the-reply"), ("", "the-reply")]


def test_a_phone_that_never_went_up_is_not_taken_off_and_the_dial_still_goes(line, table, tmp_path):
    line["refuse"]["reaction"] = True
    calls = FakeCalls(line, tmp_path, fails=gate.Refused("no switch"))
    yes_then_answer(line, table, calls)
    assert calls.seen == [] and reacted(line) == []


def test_after_a_spoken_yes_the_phone_and_the_fax_go_on_the_text_that_dials(line, table, tmp_path):
    from hiremarco.calls import offers

    done = {"status": "done", "transcript": [{"role": "agent", "message": "See you then."}], "analysis": {}}
    calls = FakeCalls(line, tmp_path, done)
    server.offer_yes("yes", OWNER, f"booth-yes-{table['made'].id}", line["wa"], conn=table["conn"], places=[table["place"]], offer=table["made"])
    assert reacted(line) == [] and offers.get(table["conn"], table["made"].id).asked_id is None
    server.offer_yes("whatever works", OWNER, "the-reply", line["wa"], conn=table["conn"], calls=calls, places=[table["place"]], start=lambda f: f())
    assert calls.seen == [("📞", "the-reply")]
    assert reacted(line) == [("📞", "the-reply"), ("📠", "the-reply")]


def test_a_dial_set_off_by_voice_alone_reacts_on_no_made_up_message(line, table, tmp_path):
    from hiremarco.calls import offers

    done = {"status": "done", "transcript": [{"role": "agent", "message": "See you then."}], "analysis": {}}
    offers.ask_fallbacks(table["conn"], table["made"])
    asking = offers.get(table["conn"], table["made"].id)
    server.offer_yes("yes", OWNER, f"booth-yes-{asking.id}", line["wa"], conn=table["conn"], calls=FakeCalls(line, tmp_path, done),
                     places=[table["place"]], start=lambda f: f(), offer=asking)
    assert reacted(line) == []


def test_the_brain_cannot_choose_the_phone(line):
    assert reactions.CALLING not in reactions.MODEL_PICKS.values() and "calling" not in reactions.MODEL_PICKS
    run(line, "calling them?", Brain("calling", reply="Not yet."))
    run(line, "calling them now?", Brain("\N{TELEPHONE RECEIVER}", reply="Not yet, no."))
    assert not [m for m in line["sent"] if m["type"] == "reaction"]


def test_a_job_that_fails_keeps_on_it_and_never_gets_the_fax(line, monkeypatch):
    from hiremarco import dress
    from hiremarco.server import dress_me

    def fails(*a, **k):
        raise dress.NoClothesFound()

    monkeypatch.setattr(dress, "dress", fails)
    monkeypatch.setattr(dress, "film_dir", lambda: None)
    dress_me(type("P", (), {"path": "x"})(), "dress me", OWNER, "w1", line["wa"])
    assert [m["reaction"]["emoji"] for m in line["sent"] if m["type"] == "reaction"] == ["👨‍💻"]


def test_a_job_that_finishes_gets_the_fax_after_on_it(line, monkeypatch):
    from hiremarco import dress
    from hiremarco.server import dress_me

    looks = type("L", (), {"dropped": [], "recommend": "B"})()
    monkeypatch.setattr(dress, "dress", lambda *a, **k: type("D", (), {"looks": looks, "pieces": [1]})())
    monkeypatch.setattr(dress, "film_dir", lambda: None)
    dress_me(type("P", (), {"path": "x"})(), "dress me", OWNER, "w1", line["wa"])
    assert [m["reaction"]["emoji"] for m in line["sent"] if m["type"] == "reaction"] == ["👨‍💻", "📠"]


def test_session_ready_changes_on_it_to_the_fax_on_the_message_that_asked():
    from hiremarco.studio.booth import Booth, Tape

    faxed = []
    b = Booth(understand=lambda l: None, logic=lambda c: c.describe(), say=lambda t: None, feedback=lambda a, r: None,
              tape=Tape(1000, seconds=1), log=lambda l: None, result_on=faxed.append)
    b._result()
    assert faxed == []  # nothing kept to put it on
    b._asked = "ask-1"
    b._result()
    assert faxed == ["ask-1"]


def test_a_failed_result_reaction_stops_nothing():
    from hiremarco.studio.booth import Booth, Tape

    logged = []
    b = Booth(understand=lambda l: None, logic=lambda c: c.describe(), say=lambda t: None, feedback=lambda a, r: None,
              tape=Tape(1000, seconds=1), log=logged.append, result_on=lambda m: 1 / 0)
    b._asked = "ask-1"
    b._result()
    assert "no result reaction" in logged[0]


def test_a_booking_proof_puts_the_fax_on_the_message_that_asked(line):
    from hiremarco import inbox as mailbox
    from hiremarco.cli import _proved

    conn = mailbox.connect(":memory:")
    mailbox.open_task(conn, "offer-1", "Test Kitchen booking", {}, asked_id="yes-1")
    mailbox.open_task(conn, "offer-2", "Other", {})
    _proved(line["wa"], OWNER, conn, "offer-1")
    _proved(line["wa"], OWNER, conn, "offer-2")
    assert [(m["reaction"]["emoji"], m["reaction"]["message_id"]) for m in line["sent"]] == [("📠", "yes-1")]


def test_the_brain_cannot_choose_the_fax(line):
    assert reactions.RESULT not in reactions.MODEL_PICKS.values()
    run(line, "done?", Brain("result", reply="Yes."))
    run(line, "done now?", Brain("\N{FAX MACHINE}", reply="Yes, done."))
    assert not [m for m in line["sent"] if m["type"] == "reaction"]

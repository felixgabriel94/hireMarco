"""Calls from the WhatsApp brain, and a reply that never claims a send (Owner 2026-11-03).

Live 2026-11-03, 8:41 to 8:56 am New York time: Felix asked Marco to call Lucie about dinner on Saturday at 8pm.
The brain had no call action and no list of what Marco can do, so it said calls were not live, then that they were,
then that they were not; offered to text her instead, which Marco has no way to do; and said "Sending it now" twice.
Every one of the twelve answers was a plain reply: nothing was dialed and nothing was sent."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from hiremarco import gate
from hiremarco.calls import Calls
from hiremarco.calls import brief as briefs
from hiremarco.joblog import JobLog
from hiremarco.whatsapp import WhatsApp
from hiremarco.whatsapp.brain import Decision, abilities
from hiremarco.whatsapp.memory import remember
from tests.test_brain import Brain

OWNER = "15551230000"
LUCIE = "+1 (908) 555-0142"
PROFILE = {"full_name": "Felix Example", "email": "f@example.com", "seating": "", "special_requests": "",
           "time_window": "", "say_as": ""}
LUCIE_CALL = {"who": "Lucie", "number": "+19085550142", "purpose": "ask if you're free for dinner Saturday at 8pm",
              "ask": "Is she free for dinner with Felix on Saturday at 8pm?",
              "if_unavailable": "ask when she is free this weekend", "voicemail": ""}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.setenv("ELEVENLABS_CALL_AGENT_ID", "agent-1")
    monkeypatch.setenv("ELEVENLABS_PHONE_NUMBER_ID", "pn-1")
    monkeypatch.setattr("hiremarco.critic.Critic.__call__", lambda self, d: (True, "ok"))
    briefs.save_profile(PROFILE)
    rules = tmp_path / "RULES.md"
    rules.write_text(f"send: whatsapp -> {OWNER} ; chat ; until revoked\n"
                     "send: calls -> named ; the number he names ; until revoked\n")
    texts, reacted, dialed = [], [], []
    result = {"status": "done", "transcript": [
        {"role": "agent", "message": "Hi, just so you know, this call is recorded."},
        {"role": "user", "message": "Saturday at eight works, tell him yes."}],
        "analysis": {"data_collection_results": {"agreed": {"value": "Saturday at 8pm works"},
                                                 "next_step": {"value": "Felix picks the place"}}}}

    def wa_handler(request):
        body = json.loads(request.content)
        if body.get("type") == "text":
            texts.append(body["text"]["body"])
        elif body.get("type") == "reaction":
            reacted.append(body["reaction"]["emoji"])
        return httpx.Response(200, json={"messages": [{"id": "wamid.o"}]})

    def el_handler(request):
        if request.method == "POST":
            dialed.append(json.loads(request.content))
            return httpx.Response(200, json={"success": True, "message": "ok", "conversation_id": "conv_x",
                                             "callSid": "CAx"})
        return httpx.Response(200, json=result)

    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"),
                  transport=httpx.MockTransport(wa_handler), rules_path=rules)
    calls = Calls(transport=httpx.MockTransport(el_handler), conn=gate.connect(":memory:"),
                  joblog=JobLog(tmp_path / "j.jsonl"), rules_path=rules)
    return {"wa": wa, "calls": calls, "texts": texts, "reacted": reacted, "dialed": dialed, "rules": rules,
            "result": result, "inbox": tmp_path / "inbox"}


def inbound(wa, mid, **kw):
    from hiremarco.whatsapp import Inbound
    from hiremarco.whatsapp.client import record_inbound

    record_inbound(wa.conn, mid, OWNER, kw.get("kind", "text"))
    return Inbound(id=mid, sender=OWNER, **kw)


def ask(world, mid, said, decision):
    """He says something; the brain's decision is carried out."""
    from hiremarco.server import act
    from hiremarco.whatsapp.client import record_inbound

    record_inbound(world["wa"].conn, mid, OWNER, "text")
    remember(world["wa"].conn, "felix", said)
    return act(decision, OWNER, mid, world["wa"], world["inbox"], calls=world["calls"], start=lambda f: f())


def call(**changes):
    return Decision("call", "", "Calling Lucie now.", call={**LUCIE_CALL, **changes})


def test_the_brain_is_told_what_it_can_and_cannot_do_from_the_live_switches(world, tmp_path):
    told = abilities(world["rules"])
    assert any("phone a person or a place" in line for line in told["can"])
    assert any("anyone but Felix" in line for line in told["cannot_yet"])
    off = tmp_path / "OFF.md"
    off.write_text(f"send: whatsapp -> {OWNER} ; chat ; until revoked\n")
    told = abilities(off)
    assert not any("phone" in line for line in told["can"]) and "phone anyone" in told["cannot_yet"]


def test_the_list_reaches_the_brain_on_every_message(world, monkeypatch):
    from hiremarco.server import handle

    brain = Brain("reply", reply="Sure. What's Lucie's number?")
    handle(inbound(world["wa"], "w1", kind="text", text="Can u call Lucie"), wa=world["wa"], inbox=world["inbox"],
           marco=brain, running=lambda: False)
    shown = brain.seen[-1]["text"]["what_you_can_do"]
    assert any("phone a person or a place" in line for line in shown["can"])


def test_live_2026_11_03_a_promised_text_is_never_sent_as_if_it_went(world):
    from hiremarco.server import NO_SEND, handle

    for said, promised in [("Yes", "Got it. I'll text Lucie about Saturday at 8pm."),
                           ("Did you send it?", "Not yet. Sending it now and I'll let you know what she says."),
                           ("Did you send it?", "You're right to check, I haven't sent it yet. It's going out now.")]:
        brain = Brain("reply", reply=promised)
        line = handle(inbound(world["wa"], f"w-{len(world['texts'])}", kind="text", text=said), wa=world["wa"],
                      inbox=world["inbox"], marco=brain, running=lambda: False)
        assert len(brain.seen) == 2                                  # asked again once, told why
        assert world["texts"][-1] in NO_SEND and "replaced" in line
    assert len(set(world["texts"])) == 3                             # each answered, none held as a repeat
    assert world["dialed"] == []


def test_an_honest_offer_or_a_question_is_not_a_promise():
    from hiremarco.server import promises_send

    assert promises_send("Send it over and I'll get that text out.")
    assert promises_send("I texted her already.")
    assert not promises_send("I can't text Lucie from here. Want me to call her instead?")
    assert not promises_send("I can text Lucie about Saturday at 8pm for you, want me to?")
    assert not promises_send("I'll text you when the session is ready.")
    assert not promises_send("What's Lucie's number?")


def test_a_call_with_his_number_dials_once_and_texts_him_how_it_went(world):
    from hiremarco.whatsapp import reactions

    ask(world, "m1", "Can u call Lucie and ask about her availability for Saturday at 8pm", Decision("reply", "", "x"))
    line = ask(world, "m2", LUCIE, call())
    assert line.startswith("brain: call; calling Lucie, conversation conv_x")
    assert len(world["dialed"]) == 1 and world["dialed"][0]["to_number"] == "+19085550142"
    variables = world["dialed"][0]["conversation_initiation_client_data"]["dynamic_variables"]
    assert variables["opening"].endswith("I'm calling to ask if you're free for dinner Saturday at 8pm for Felix Gabriel.")
    assert "- what to ask or arrange: Is she free for dinner with Felix on Saturday at 8pm?" in variables["brief"]
    assert "- if it cannot be done: ask when she is free this weekend" in variables["brief"]
    assert reactions.CALLING in world["reacted"]                     # the phone goes on his message, before the dial
    assert world["texts"][1:] == ["Calling Lucie now. I'll tell you how it goes.",   # in this order
                                  "Lucie: Saturday at 8pm works. Next: FEGA picks the place."]
    assert reactions.RESULT in world["reacted"]
    assert "0142" not in " ".join(world["texts"])


def test_a_number_he_did_not_send_here_is_asked_for_never_dialed(world):
    long_ago = datetime(2026, 10, 1, tzinfo=timezone.utc)            # memory, not this request
    remember(world["wa"].conn, "felix", "Lucie's number is +1 908 555 0142", ts=long_ago)
    line = ask(world, "m1", "Call Lucie about Saturday", call())
    assert world["dialed"] == [] and "no number of his" in line
    assert world["texts"][-1] == "What's Lucie's number? Send it here and I'll call."


def test_a_number_without_the_country_code_is_asked_for_again_with_it(world):
    line = ask(world, "m1", "her number is 908-555-0142", call())
    assert world["dialed"] == [] and "country code" in line
    assert "+1" in world["texts"][-1]


def test_a_call_without_a_fallback_asks_first_and_does_not_dial(world):
    line = ask(world, "m1", LUCIE, call(if_unavailable=""))
    assert world["dialed"] == [] and "asked for if_unavailable" in line
    assert world["texts"][-1] == "Before I call Lucie: what should I do if they can't?"


def test_a_held_call_takes_the_phone_off_and_says_so_plainly(world):
    world["rules"].write_text(f"send: whatsapp -> {OWNER} ; chat ; until revoked\n")   # no calls switch
    line = ask(world, "m1", LUCIE, call())
    assert world["dialed"] == [] and "held" in line
    assert world["reacted"][-1] == ""                                 # taken back off
    assert world["texts"][-1].startswith("I couldn't get the call to Lucie going at ")
    assert world["texts"][-1].endswith('Say "call again" and I\'ll try right away.')


def test_a_voicemail_or_no_answer_is_said_as_it_is(world):
    from hiremarco.server import call_result

    assert call_result("Lucie", {"status": "done", "transcript": [
        {"role": "agent", "message": "", "tool_calls": [{"tool_name": "voicemail_detection"}]}]}) == \
        "Lucie didn't pick up, so I left a voicemail."
    assert call_result("Lucie", {"status": "done", "transcript": [{"role": "agent", "message": "Hi"}]}) == \
        "Lucie didn't pick up. Want me to try again later?"
    assert call_result("Lucie", {"status": "failed"}).startswith("The call to Lucie didn't go through")

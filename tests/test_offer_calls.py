import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from hiremarco import gate
from hiremarco.calls import Calls
from hiremarco.calls import brief as briefs
from hiremarco.calls import offers
from hiremarco.joblog import JobLog
from hiremarco.offer import Place
from hiremarco.server import offer_yes
from hiremarco.whatsapp import WhatsApp

OWNER = "15551230000"
KITCHEN = Place("test-kitchen", "Test Kitchen", "15557770000")
NOW = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)
PROFILE = {"full_name": "Felix Example", "email": "f@example.com", "seating": "indoor", "special_requests": "none",
           "time_window": "plus or minus 30 minutes", "say_as": ""}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el")
    monkeypatch.setenv("ELEVENLABS_CALL_AGENT_ID", "agent-1")
    monkeypatch.setenv("ELEVENLABS_PHONE_NUMBER_ID", "pn-1")
    places = tmp_path / "places.json"
    places.write_text(json.dumps([KITCHEN.__dict__]))
    monkeypatch.setenv("HIREMARCO_PLACES", str(places))
    briefs.save_profile(PROFILE)
    rules = tmp_path / "RULES.md"
    rules.write_text(f"send: whatsapp -> {OWNER} ; chat ; until revoked\n"
                     "send: calls -> places ; offers ; until revoked\n")
    texts, dialed = [], []

    def wa_handler(request):
        texts.append(json.loads(request.content)["text"]["body"])
        return httpx.Response(200, json={"messages": [{"id": "wamid.o"}]})

    def el_handler(request):
        if request.method == "POST":
            dialed.append(json.loads(request.content))
            return httpx.Response(200, json={"success": True, "message": "ok", "conversation_id": "conv_x",
                                             "callSid": "CAx"})
        return httpx.Response(200, json={"status": "done", "transcript": [
            {"role": "agent", "message": "Those don't work for us, unfortunately. Is there a waitlist?"},
            {"role": "agent", "message": "Thanks for adding us. Bye."}],
            "analysis": {"data_collection_results": {"off_brief": {"value": "Asked for a birthday"}}}})

    wa = WhatsApp(token="t", phone_number_id="1", conn=gate.connect(":memory:"),
                  transport=httpx.MockTransport(wa_handler), rules_path=rules)
    from hiremarco.whatsapp.client import record_inbound
    record_inbound(wa.conn, "wamid.in", OWNER, "text")
    calls = Calls(transport=httpx.MockTransport(el_handler), conn=gate.connect(":memory:"),
                  joblog=JobLog(tmp_path / "j.jsonl"), rules_path=rules)
    return {"wa": wa, "calls": calls, "texts": texts, "dialed": dialed, "conn": offers.connect(":memory:"),
            "rules": rules}


def yes(world, said="yes", now=None, mid="m1"):
    return offer_yes(said, OWNER, mid, world["wa"], conn=world["conn"], calls=world["calls"], places=[KITCHEN],
                     start=lambda f: f(), now=now)


def test_the_offer_names_the_exact_call():
    offer = offers.CallOffer(1, NOW, "test-kitchen", "thursday", "2026-11-05", 20, 4, "", "pending")
    assert offer.text(KITCHEN) == "Want me to call Test Kitchen to book Thursday at eight for four?"


def test_a_yes_places_one_call_and_reports_the_result(world, monkeypatch):
    monkeypatch.setattr("hiremarco.critic.Critic.__call__", lambda self, d: (True, "ok"))
    offer = offers.record_offer(world["conn"], KITCHEN, weekday="thursday", day="2026-11-05", hour=20, party_size=4,
                                now=datetime.now(timezone.utc))
    line = yes(world)
    assert line == f"offer {offer.id}: asked the fallback questions before dialing" and world["dialed"] == []
    assert world["texts"][-1].lower().startswith("before i call, a few quick ones")
    assert "if thursday at eight is gone" in world["texts"][-1].lower()
    line = yes(world, said="Friday at 8 is fine, patio ok, link is fine", mid="m1b")
    assert line.startswith(f"offer {offer.id}: calling Test Kitchen")
    assert len(world["dialed"]) == 1 and world["dialed"][0]["to_number"] == "+15557770000"
    brief = world["dialed"][0]["conversation_initiation_client_data"]["dynamic_variables"]["brief"]
    assert "- party size: 4" in brief and "Thursday (2026-11-05)" in brief and "eight pm" in brief
    assert "- fallbacks: Friday at 8 is fine, patio ok, link is fine" in brief
    assert world["texts"][1].lower().startswith("calling test kitchen now")
    result = world["texts"][-1].lower()
    assert "waitlist" in result and "thanks for adding us. bye." in result and "asked for a birthday" in result
    assert "7770000" not in " ".join(world["texts"])
    # a second yes to the same offer places nothing more
    assert yes(world, mid="m2") is None and len(world["dialed"]) == 1


def test_whatever_works_stands_as_flexible(world, monkeypatch):
    monkeypatch.setattr("hiremarco.critic.Critic.__call__", lambda self, d: (True, "ok"))
    offers.record_offer(world["conn"], KITCHEN, weekday="thursday", day="2026-11-05", hour=20, party_size=4)
    yes(world)
    yes(world, said="whatever works", mid="m3")
    brief = world["dialed"][0]["conversation_initiation_client_data"]["dynamic_variables"]["brief"]
    assert "- fallbacks: flexible (whatever works)" in brief


def test_one_reply_fills_what_the_profile_leaves_open(world, monkeypatch):
    # live 2026-10-31: the profile had no window, seating or requests; the questions now come first and cover them
    monkeypatch.setattr("hiremarco.critic.Critic.__call__", lambda self, d: (True, "ok"))
    briefs.save_profile({**PROFILE, "time_window": "", "seating": "", "special_requests": ""})
    offers.record_offer(world["conn"], KITCHEN, weekday="thursday", day="2026-11-05", hour=20, party_size=4)
    assert yes(world).endswith("asked the fallback questions before dialing")
    assert "4. any allergies, an occasion" in world["texts"][-1].lower()
    line = yes(world, said="1. Friday at 8 or Thursday 7:30 to 8:30. 2. Either. 3. Yes. 4. No allergies.", mid="m5")
    assert "calling Test Kitchen" in line and len(world["dialed"]) == 1
    brief = world["dialed"][0]["conversation_initiation_client_data"]["dynamic_variables"]["brief"]
    assert "- seating (indoor, outdoor, any): see Felix's fallbacks below" in brief
    assert "- fallbacks: 1. Friday at 8 or Thursday 7:30 to 8:30. 2. Either. 3. Yes. 4. No allergies." in brief


def test_no_offer_or_a_stale_one_or_not_a_yes_does_nothing(world):
    assert yes(world) is None
    offers.record_offer(world["conn"], KITCHEN, weekday="thursday", day="2026-11-05", hour=20, party_size=4,
                        now=datetime.now(timezone.utc) - timedelta(minutes=31))
    assert yes(world) is None
    offers.record_offer(world["conn"], KITCHEN, weekday="thursday", day="2026-11-05", hour=20, party_size=4)
    assert yes(world, said="what time is it?") is None
    assert world["dialed"] == []


def test_a_gap_in_the_brief_is_asked_about_before_dialing(world):
    briefs.save_profile({**PROFILE, "email": ""})
    offers.record_offer(world["conn"], KITCHEN, weekday="thursday", day="2026-11-05", hour=20, party_size=4)
    yes(world)
    line = yes(world, said="Friday works", mid="m4")
    assert "asked for email before dialing" in line and world["dialed"] == []
    assert "email for the confirmation" in world["texts"][-1].lower()


def test_the_gate_holds_a_places_call_without_its_offer(world):
    conn = gate.connect(":memory:")
    fields = dict(tenant_id="owner", capability="call", channel="voice", target="15557770000",
                  message=gate.RECORDING_OPENING + " I'm calling to book a table for Felix.", department="assistant",
                  rules_path=world["rules"])
    with pytest.raises(gate.Refused, match="no send switch"):
        gate.check_outbound(conn, idempotency_key="a", **fields)
    now = datetime.now(timezone.utc)
    good = {"offer_id": 1, "place_name": "Test Kitchen", "place_phone": "15557770000", "offered_at": now,
            "accepted_at": now}
    gate.check_outbound(conn, idempotency_key="b", offer=good, **fields)
    for bad in ({**good, "place_phone": "15550000001"},                          # another place's number
                {**good, "accepted_at": None},                                   # never said yes
                {**good, "offered_at": now - timedelta(minutes=45)},             # yes long after the offer
                {**good, "accepted_at": now - timedelta(hours=2), "offered_at": now - timedelta(hours=2)}):  # old yes
        with pytest.raises(gate.Refused, match="no send switch"):
            gate.check_outbound(conn, idempotency_key="c", offer=bad, **fields)
    with pytest.raises(gate.Refused, match="no send switch"):  # a number that is not in the places file
        gate.check_outbound(conn, idempotency_key="d", offer={**good, "place_phone": "15559990000"},
                            **{**fields, "target": "15559990000"})


def test_the_critic_sees_the_place_even_when_its_number_is_the_owners(world):
    now = datetime.now(timezone.utc)
    seen = []
    mine = Place("test-kitchen", "Test Kitchen", OWNER)
    (world["rules"].parent / "places.json").write_text(json.dumps([mine.__dict__]))
    evidence = {"offer_id": 7, "place_name": "Test Kitchen", "place_phone": OWNER, "offered_at": now, "accepted_at": now}
    gate.execute_effect(gate.connect(":memory:"), lambda: None, tenant_id="owner", idempotency_key="k", capability="call",
                        channel="voice", target=OWNER, message=gate.RECORDING_OPENING + " I'm calling to book a table.",
                        department="assistant", critic=lambda d: (seen.append(d) or True, "ok"),
                        rules_path=world["rules"], offer=evidence)
    assert seen[0].startswith("call via voice to Test Kitchen (its number from the Owner's places file, offer 7)")
    assert "the Owner's own number" not in seen[0]


def test_the_client_never_reads_what_is_under_the_hood(world):
    from hiremarco.style import PLAIN, plain

    assert plain("i couldn't place the call to test kitchen: critic held it: recipient wrong")[0] == PLAIN
    assert plain("Booked at Test Kitchen, Thursday at eight.")[0] == "Booked at Test Kitchen, Thursday at eight."
    world["wa"].send_text(OWNER, "held: no send switch for calls -> 15557770000", idempotency_key="leak")
    assert world["texts"][-1] == PLAIN.lower() and "15557770000" not in world["texts"][-1]

"""The Owner's lines for email offers (2026-11-02): the send line is on, and a spoken yes holds for a call only when the
offer was really texted. Made-up numbers."""

from datetime import datetime, timedelta, timezone

from hiremarco import config, gate, rules
from hiremarco.calls import offers
from hiremarco.gate.checks import offer_holds
from hiremarco.offer import Place

NOW = datetime.now(timezone.utc)
PLACE = "15555550123"


def evidence(**changed):
    return {"offer_id": 1, "place_name": "Corner Bistro", "place_phone": PLACE, "offered_at": NOW - timedelta(minutes=5),
            "accepted_at": NOW - timedelta(minutes=1), **changed}


def on_file(monkeypatch):
    monkeypatch.setattr("hiremarco.offer.load_places", lambda: [Place("corner", "Corner Bistro", PLACE)])


def test_the_repo_says_a_spoken_yes_counts_and_the_offers_line_is_on(monkeypatch):
    monkeypatch.setenv("OWNER_WHATSAPP", "15551230000")
    assert offers.voice_yes_on() and rules.allowed("email-offers", "15551230000")
    assert not rules.allowed("email-offers", "15559990000")


def test_a_voice_yes_holds_for_an_offer_he_was_texted(monkeypatch):
    on_file(monkeypatch)
    assert offer_holds(evidence(yes_by="booth", texted_at=NOW - timedelta(minutes=5)), PLACE)


def test_a_voice_yes_with_no_text_behind_it_holds_nothing(monkeypatch):
    on_file(monkeypatch)
    assert not offer_holds(evidence(yes_by="booth"), PLACE)
    assert not offer_holds(evidence(yes_by="booth", texted_at=None), PLACE)


def test_a_yes_by_any_other_way_holds_nothing_and_whatsapp_stands(monkeypatch):
    on_file(monkeypatch)
    assert not offer_holds(evidence(yes_by="email"), PLACE)
    assert offer_holds(evidence(), PLACE) and offer_holds(evidence(yes_by="whatsapp"), PLACE)


def test_past_the_window_a_voice_yes_holds_nothing(monkeypatch):
    on_file(monkeypatch)
    late = evidence(yes_by="booth", texted_at=NOW, offered_at=NOW - timedelta(minutes=40), accepted_at=NOW - timedelta(minutes=1))
    assert not offer_holds(late, PLACE)


def test_the_critic_is_told_how_he_said_yes(tmp_path, monkeypatch):
    on_file(monkeypatch)
    monkeypatch.setattr(gate.checks, "kill_switch_on", lambda: False)
    switch = tmp_path / "RULES.md"
    switch.write_text("send: calls -> places ; offers ; until revoked\n")
    told = []

    def critic(text):
        told.append(text)
        return True, ""

    gate.execute_effect(gate.connect(":memory:"), lambda: "ok", tenant_id="owner", idempotency_key="k", capability="call",
                        channel="voice", target=PLACE, message=gate.RECORDING_NOTICE, department="assistant", critic=critic,
                        rules_path=switch, offer=evidence(yes_by="booth", texted_at=NOW))
    assert "by voice in the booth" in told[0]

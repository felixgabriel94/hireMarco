from datetime import date

import pytest

from hiremarco import rules


def write(tmp_path, text):
    p = tmp_path / "RULES.md"
    p.write_text(text)
    return p


def test_absent_means_off(tmp_path):
    p = write(tmp_path, "# Rules\n\n## Send switches\n\n(none)\n")
    assert rules.allowed("calls", "15551234567", path=p) is False
    with pytest.raises(rules.SendNotAllowed):
        rules.require("calls", "15551234567", path=p)


def test_live_line_allows_exact_tool_and_destination(tmp_path):
    p = write(tmp_path, "send: calls -> 15551234567 ; the Owner's own phone, rehearsal ; until 2026-11-04\n")
    today = date(2026, 10, 27)
    assert rules.allowed("calls", "15551234567", today, p) is True
    assert rules.allowed("calls", "+15551234567", today, p) is True
    assert rules.allowed("whatsapp", "15551234567", today, p) is False
    assert rules.allowed("calls", "15559999999", today, p) is False


def test_expired_line_is_off(tmp_path):
    p = write(tmp_path, "send: calls -> 15551234567 ; rehearsal ; until 2026-10-26\n")
    assert rules.allowed("calls", "15551234567", date(2026, 10, 27), p) is False


def test_until_revoked_has_no_end_date(tmp_path):
    p = write(tmp_path, "send: calls -> 15551234567 ; the Owner's phone ; until revoked\n")
    assert rules.switches(p)[0].until == date.max
    assert rules.allowed("calls", "15551234567", date(2031, 1, 1), p) is True


def test_repo_rules_file_keeps_whatsapp_to_the_owner_on_with_no_end_date():
    # Owner ruling 2026-10-29: Marco texts the Owner on WhatsApp indefinitely
    whatsapp = [s for s in rules.switches() if s.tool == "whatsapp"]
    assert [(s.destination, s.until) for s in whatsapp] == [("owner", date.max)]


def test_malformed_line_is_ignored(tmp_path):
    p = write(tmp_path, "send: calls -> restaurant ; no number ; until 2026-11-04\nsend calls 15551234567\n")
    assert rules.switches(p) == []


def test_owner_destination_matches_only_the_owner_number(tmp_path, monkeypatch):
    p = write(tmp_path, "send: whatsapp -> owner ; replies to the Owner ; until 2026-11-04\n")
    today = date(2026, 10, 28)
    monkeypatch.setattr(rules.config, "get", lambda key: "+15551234567" if key == "OWNER_WHATSAPP" else None)
    assert rules.allowed("whatsapp", "15551234567", today, p) is True
    assert rules.allowed("whatsapp", "15559999999", today, p) is False
    assert rules.allowed("calls", "15551234567", today, p) is False
    assert rules.allowed("whatsapp", "owner", today, p) is False


def test_owner_destination_is_off_while_owner_unset(tmp_path, monkeypatch):
    p = write(tmp_path, "send: whatsapp -> owner ; replies to the Owner ; until 2026-11-04\n")
    monkeypatch.setattr(rules.config, "get", lambda key: None)
    assert rules.allowed("whatsapp", "", date(2026, 10, 28), p) is False
    assert rules.allowed("whatsapp", "15551234567", date(2026, 10, 28), p) is False


def test_repo_rules_file_reaches_the_owner_and_whom_he_names():
    # RULES.md in this repository turns on WhatsApp and calls to the Owner, talkback and Logic, and calls to a
    # number the Owner names in that request (Owner 2026-10-31); nothing else reaches anyone.
    assert [(s.tool, s.destination) for s in rules.switches()] == [
        ("whatsapp", "owner"), ("talkback", "*"), ("logic", "*"), ("calls", "owner"), ("calls", "named"),
        ("calls", "places"), ("unsubscribe", "*"), ("mail", "*")]


def test_named_line_needs_the_owner_to_have_named_the_number(tmp_path):
    p = write(tmp_path, "send: calls -> named ; whom the Owner names ; until revoked\n")
    today = date(2026, 10, 31)
    assert rules.allowed("calls", "15557770000", today, p, named_by_owner=True)
    assert not rules.allowed("calls", "15557770000", today, p)
    assert not rules.allowed("whatsapp", "15557770000", today, p, named_by_owner=True)


def test_read_grants_exact_address_and_domain(tmp_path):
    p = write(tmp_path, "read: mail <- lucie@example.com ; the dinner email ; until 2026-11-04\n"
                        "read: mail <- @resy.com ; booking proof ; until 2026-11-04\n"
                        "read: mail <- @old.com ; expired ; until 2026-10-01\n")
    today = date(2026, 10, 28)
    assert rules.may_read("Lucie@Example.com", p, today)
    assert rules.may_read("no-reply@resy.com", p, today)
    assert not rules.may_read("someone@example.com", p, today)
    assert not rules.may_read("a@old.com", p, today)
    assert not rules.may_read("x@resy.com.evil.io", p, today)


def test_repo_rules_file_grants_vendor_receipts_and_the_inbox():
    """The Owner's yes of 2026-10-29: plug-in vendors' receipts; and of 2026-10-31: every email, to sort it into
    Marco's labels and link it to his tasks."""
    grants = rules.read_grants()
    everything = [g for g in grants if g.sender == "*"]
    assert len(everything) == 1 and "sort every email" in everything[0].purpose
    assert all(g.sender == "*" or (g.sender.startswith("@") and "license receipts" in g.purpose) for g in grants)
    assert rules.may_read("someone@gmail.com")


def test_nothing_in_the_repo_rules_ends_on_a_date():
    # Owner 2026-10-30: the hackathon work carries on as the product; no switch or grant ends on Nov 4
    assert all(s.until == date.max for s in rules.switches())
    assert rules.read_grants(today=date(2031, 1, 1)) and all(g.until == date.max for g in rules.read_grants())


def test_a_read_grant_until_revoked_has_no_end_date(tmp_path):
    p = write(tmp_path, "read: mail <- @fabfilter.com ; license receipts ; until revoked\n")
    assert rules.may_read("orders@fabfilter.com", p, date(2031, 1, 1))


def test_a_read_all_line_covers_every_sender_and_only_while_live(tmp_path):
    p = write(tmp_path, "read: mail <- * ; sort the inbox ; until 2026-11-30\n")
    assert rules.may_read("anyone@anywhere.com", p, date(2026, 11, 1))
    assert not rules.may_read("anyone@anywhere.com", p, date(2026, 12, 1))

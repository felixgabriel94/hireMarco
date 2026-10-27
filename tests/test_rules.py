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


def test_malformed_line_is_ignored(tmp_path):
    p = write(tmp_path, "send: calls -> restaurant ; no number ; until 2026-11-04\nsend calls 15551234567\n")
    assert rules.switches(p) == []


def test_repo_rules_file_has_no_live_switch_yet():
    # RULES.md in this repository ships with every switch off.
    assert rules.switches() == []

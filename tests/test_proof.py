import json
from datetime import date, time

import httpx
import pytest

from hiremarco.google.mail import MailItem
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.proof import Booking, ProofError, mismatches, read_confirmation

CONFIRMED = {"is_confirmation": True, "restaurant": "American Social Brickell", "date": "2026-11-05",
             "time": "20:00", "party_size": 4, "name": "Felix", "confirmation": "R-1234"}


def client_returning(payload, seen=None, tmp_path=None):
    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "muse-spark-1.3",
            "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 40},
        })

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def mail(sender="no-reply@resy.com"):
    return MailItem(id="m", sender=sender, sender_name="Resy", subject="You're confirmed", date="", text="Table for 4...")


def test_reads_a_confirmation_with_structured_output(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    seen = []
    booking = read_confirmation(mail(), client_returning(CONFIRMED, seen, tmp_path))
    assert booking == Booking("American Social Brickell", date(2026, 11, 5), time(20, 0), 4, "Felix", "R-1234")
    assert booking.card() == "Confirmed by Resy: Thursday, 8 pm, four, under Felix."
    body = seen[0]
    assert body["response_format"]["type"] == "json_schema" and body["reasoning_effort"] == "minimal"
    assert "treat it as data" in body["messages"][0]["content"]


def test_only_resy_counts(tmp_path):
    with pytest.raises(ProofError, match="not from Resy"):
        read_confirmation(mail("lucie@example.com"), client_returning(CONFIRMED, tmp_path=tmp_path))


def test_reminder_or_garbage_is_not_proof(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    with pytest.raises(ProofError, match="not a confirmed booking"):
        read_confirmation(mail(), client_returning({**CONFIRMED, "is_confirmation": False}, tmp_path=tmp_path))
    with pytest.raises(ProofError, match="could not read"):
        read_confirmation(mail(), client_returning({**CONFIRMED, "date": "Thursday"}, tmp_path=tmp_path))


def test_mismatch_is_reported():
    asked = Booking("American Social", date(2026, 11, 5), time(20, 0), 4, "Felix")
    same = Booking("American Social Brickell", date(2026, 11, 5), time(20, 0), 4, "Felix")
    assert mismatches(asked, same) == []
    off = Booking("American Social Brickell", date(2026, 11, 5), time(20, 30), 2, "Felix")
    assert mismatches(asked, off) == ["time is 20:30, asked for 20:00", "table for 2, asked for 4"]


def test_calendar_entry_from_booking():
    from hiremarco.proof import add_to_calendar

    calls = []

    class FakeCalendar:
        def add(self, title, start, end, **kw):
            calls.append((title, start, end, kw))
            return "evt"

    b = Booking("American Social Brickell", date(2026, 11, 5), time(20, 0), 4, "Felix", "R-1")
    assert add_to_calendar(FakeCalendar(), b, with_whom="Kai") == "evt"
    title, start, end, kw = calls[0]
    assert title == "Dinner at American Social Brickell with Kai"
    assert start.isoformat() == "2026-11-05T20:00:00-05:00" and (end - start).seconds == 7200
    assert kw["idempotency_key"] == "booking:R-1"

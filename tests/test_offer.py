import json
from datetime import date

import httpx
import pytest

from hiremarco.google.mail import MailItem
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.offer import OfferError, Place, load_places, make_offer, next_weekday

TODAY = date(2026, 11, 2)  # a Monday
TASK = {"is_task": True, "kind": "dinner", "summary": "Lucie suggests dinner with Kai The Producer and his manager",
        "with_whom": "Kai The Producer", "party_size": 4, "weekday": "thursday", "hour": 20, "purpose": "meet before the session"}
PLACES = [Place("bistro", "Corner Bistro", "15555550123", "Last visit with a producer, to talk about a record"),
          Place("grill", "Harbor Grill", "15555550188")]


def scripted(*answers, tmp_path):
    queue = list(answers)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "muse-spark-1.3",
            "choices": [{"message": {"role": "assistant", "content": json.dumps(queue.pop(0))}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 30},
        })

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler)), seen


class Cal:
    def __init__(self, clear=True):
        self.clear, self.asked = clear, []

    def is_clear(self, start, end):
        self.asked.append((start, end))
        return self.clear


LUCIE = MailItem(id="m1", sender="lucie@example.com", sender_name="Lucie", subject="Dinner with Kai",
                 date="", text="Kai is coming with his manager. You and Hector should meet them Thursday at 8.")


def test_next_weekday():
    assert next_weekday("thursday", TODAY) == date(2026, 11, 5)
    assert next_weekday("monday", TODAY) == date(2026, 11, 9)


def test_offer_same_as_last_time(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    client, seen = scripted(TASK, {"place_id": "bistro", "reason": "where you meet producers"}, tmp_path=tmp_path)
    cal = Cal()
    offer = make_offer(LUCIE, client, cal, today=TODAY, places=PLACES)
    assert offer.text() == "Same as last time? Corner Bistro, table for four, Thursday at eight. Your calendar's clear."
    assert cal.asked[0][0].isoformat() == "2026-11-05T20:00:00-05:00"
    assert "Corner Bistro" in seen[1]["messages"][1]["content"]
    assert seen[0]["response_format"]["json_schema"]["name"] == "task"


def test_busy_calendar_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    client, _ = scripted(TASK, {"place_id": "grill", "reason": "quiet"}, tmp_path=tmp_path)
    offer = make_offer(LUCIE, client, Cal(clear=False), today=TODAY, places=PLACES)
    assert offer.text() == "Harbor Grill, table for four, Thursday at eight. You have something then, so say if you want another time."


def test_place_must_come_from_the_list(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    client, _ = scripted(TASK, {"place_id": "somewhere-from-the-web", "reason": "x"}, tmp_path=tmp_path)
    with pytest.raises(OfferError, match="not on the list"):
        make_offer(LUCIE, client, Cal(), today=TODAY, places=PLACES)


def test_not_a_task_makes_no_offer(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    client, seen = scripted({**TASK, "is_task": False}, tmp_path=tmp_path)
    assert make_offer(LUCIE, client, Cal(), today=TODAY, places=PLACES) is None
    assert len(seen) == 1


def test_example_places_file_loads():
    from pathlib import Path

    places = load_places(Path(__file__).resolve().parents[1] / "docs" / "places.example.json")
    assert [p.id for p in places] == ["corner-bistro", "harbor-grill"]

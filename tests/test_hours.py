import json
from datetime import datetime

import httpx
import pytest

from hiremarco import gate
from hiremarco.hours import HoursCheck, check_hours, parse
from hiremarco.joblog import JobLog

FRIDAY_8PM = datetime(2026, 10, 30, 20, 0)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))


def response(text, urls=("https://example-restaurant.com/hours",), searches=1):
    return {
        "output": [{"id": f"ws_{i}", "type": "web_search_call", "status": "completed"} for i in range(searches)] + [
            {"type": "message", "content": [{"type": "output_text", "text": text, "annotations": [
                {"type": "url_citation", "url": u, "title": "Hours", "start_index": 0, "end_index": 4} for u in urls]}]}],
        "usage": {"input_tokens": 1200, "output_tokens": 30},
    }


def run(tmp_path, data, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json=data)

    log = JobLog(tmp_path / "j.jsonl")
    return check_hours("American Social", "Miami", FRIDAY_8PM, joblog=log, api_key="k",
                       transport=httpx.MockTransport(handler)), log


def test_open_with_a_source_lets_the_call_go(tmp_path):
    seen = []
    result, log = run(tmp_path, response("OPEN | 11:30 am to 2 am"), seen)
    assert result == HoursCheck("OPEN", "11:30 am to 2 am", ["https://example-restaurant.com/hours"])
    assert result.may_call
    body = seen[0]
    assert body["model"] == "muse-spark-1.3" and body["tools"][0]["type"] == "web_search"
    assert "Friday 2026-10-30 08:00 PM" in body["input"]
    (row,) = log.rows()
    assert row["job"] == "hours_check" and "1 search" in row["note"]
    assert row["cost_usd"] == pytest.approx((1200 * 1.25 + 30 * 4.25) / 1e6 + 0.0025)


def test_closed_holds(tmp_path):
    result, _ = run(tmp_path, response("CLOSED | closed Fridays for a private event"))
    assert result.verdict == "CLOSED" and not result.may_call


def test_no_cited_source_is_unsure(tmp_path):
    result, _ = run(tmp_path, response("OPEN | 5 pm to 11 pm", urls=()))
    assert result.verdict == "UNSURE" and not result.may_call


def test_unparseable_answer_is_unsure():
    assert parse(response("They are probably open, call 305-555-0100!")).verdict == "UNSURE"


def test_a_page_cannot_smuggle_a_number_or_link_into_the_hours_line():
    injected = response("OPEN | 5 pm to 11 pm call 13055550100 now https://evil.example/x <script>")
    result = parse(injected)
    assert result.verdict == "OPEN"
    assert "13055550100" not in result.hours and "http" not in result.hours and "<" not in result.hours


def test_http_error_is_unsure_and_logged(tmp_path):
    log = JobLog(tmp_path / "j.jsonl")
    result = check_hours("X", "Miami", FRIDAY_8PM, joblog=log, api_key="k",
                         transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert result.verdict == "UNSURE" and log.rows()[0]["ok"] is False


def test_kill_switch_stops_it(tmp_path):
    gate.set_kill_switch(True)
    try:
        with pytest.raises(gate.Refused):
            check_hours("X", "Miami", FRIDAY_8PM, joblog=JobLog(tmp_path / "j.jsonl"), api_key="k",
                        transport=httpx.MockTransport(lambda r: pytest.fail("no request")))
    finally:
        gate.set_kill_switch(False)

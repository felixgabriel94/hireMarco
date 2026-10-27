import json

import httpx
import pytest

from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark, MuseSparkError


def fake_api(status=200, content="ready.", usage=None):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        if status >= 400:
            return httpx.Response(status, json={"error": {"message": "nope"}})
        return httpx.Response(status, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "muse-spark-1.3",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": usage or {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        })

    return httpx.MockTransport(handler), seen


def test_round_trip_logs_cost(tmp_path):
    transport, seen = fake_api()
    log = JobLog(tmp_path / "jobs.jsonl")
    client = MuseSpark(api_key="test-key", joblog=log, transport=transport)
    reply = client.ask("hi", developer="Be brief.", job="ping")

    assert seen["url"] == "https://api.meta.ai/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "muse-spark-1.3"
    assert seen["body"]["messages"][0] == {"role": "developer", "content": "Be brief."}
    assert seen["body"]["max_completion_tokens"] == 600
    assert "max_tokens" not in seen["body"]

    assert reply.text == "ready."
    assert reply.prompt_tokens == 12 and reply.completion_tokens == 3
    assert reply.cost_usd == pytest.approx((12 * 1.25 + 3 * 4.25) / 1_000_000)
    rows = log.rows()
    assert len(rows) == 1 and rows[0]["job"] == "ping" and rows[0]["ok"] is True
    assert rows[0]["cost_usd"] == pytest.approx(reply.cost_usd)


def test_cached_tokens_read_from_usage_details(tmp_path):
    usage = {"prompt_tokens": 100, "completion_tokens": 1, "total_tokens": 101,
             "prompt_tokens_details": {"cached_tokens": 80}}
    transport, _ = fake_api(usage=usage)
    client = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=transport)
    reply = client.ask("hi")
    assert reply.cached_tokens == 80
    assert reply.cost_usd == pytest.approx((80 * 0.15 + 20 * 1.25 + 1 * 4.25) / 1_000_000)


def test_http_error_is_logged_without_body(tmp_path):
    transport, _ = fake_api(status=401)
    log = JobLog(tmp_path / "jobs.jsonl")
    client = MuseSpark(api_key="k", joblog=log, transport=transport)
    with pytest.raises(MuseSparkError):
        client.ask("hi")
    rows = log.rows()
    assert rows[0]["ok"] is False and rows[0]["note"] == "http 401"
    assert "nope" not in json.dumps(rows)


def test_missing_key_is_named(monkeypatch, tmp_path):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("HIREMARCO_ENV", str(tmp_path / "no-env"))
    with pytest.raises(KeyError):
        MuseSpark()

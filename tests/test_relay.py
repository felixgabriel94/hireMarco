import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.relay import make_relay


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("RELAY_TOKEN", "relay-secret")
    monkeypatch.setenv("MODEL_API_KEY", "meta-key")
    seen = []

    def upstream(request):
        body = json.loads(request.content)
        seen.append((request.headers.get("authorization"), body))
        if body.get("stream"):
            lines = [
                'data: {"choices":[{"delta":{"content":"Table for four"}}]}',
                'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":5}}',
                "data: [DONE]",
            ]
            return httpx.Response(200, text="\n".join(lines) + "\n", headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    log = JobLog(tmp_path / "jobs.jsonl")
    app = Starlette(routes=[Route("/llm/v1/chat/completions",
                                  make_relay(transport=httpx.MockTransport(upstream), joblog=log), methods=["POST"])])
    return TestClient(app), seen, log


def post(client, body, token="relay-secret"):
    return client.post("/llm/v1/chat/completions", json=body, headers={"authorization": f"Bearer {token}"})


def test_needs_the_relay_token(setup):
    client, seen, _ = setup
    assert post(client, {"messages": []}, token="wrong").status_code == 401
    assert seen == []


def test_pins_the_model_and_uses_the_macs_key(setup):
    client, seen, log = setup
    r = post(client, {"model": "gpt-something", "max_tokens": 50, "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    auth, body = seen[0]
    assert auth == "Bearer meta-key" and body["model"] == "muse-spark-1.3"
    assert body["max_completion_tokens"] == 50 and "max_tokens" not in body
    assert log.rows()[-1]["job"] == "call-relay" and log.rows()[-1]["prompt_tokens"] == 10


def test_streams_and_logs_usage(setup):
    client, seen, log = setup
    r = post(client, {"stream": True, "messages": [{"role": "user", "content": "book a table"}]})
    assert "Table for four" in r.text and "[DONE]" in r.text
    assert seen[0][1]["stream_options"] == {"include_usage": True}
    assert log.rows()[-1]["completion_tokens"] == 5


def test_kill_switch_stops_the_call_brain(setup):
    client, seen, _ = setup
    gate.set_kill_switch(True)
    r = post(client, {"messages": [{"role": "user", "content": "hi"}]})
    gate.set_kill_switch(False)
    assert r.status_code == 403 and seen == []

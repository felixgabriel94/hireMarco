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


OPENING = "Hi, just so you know, this call is recorded. I'm calling to book a table for Felix."
CALL_SYSTEM = {"role": "system", "content": f"You are Marco.\n\nYour first words, exactly: {OPENING}\n\nWhy: x"}


def test_first_reply_is_the_opening_word_for_word_with_no_model_call(setup):
    client, seen, log = setup
    r = post(client, {"messages": [CALL_SYSTEM]})
    assert r.json()["choices"][0]["message"]["content"] == OPENING
    r = post(client, {"stream": True, "messages": [CALL_SYSTEM, {"role": "user", "content": "Hello?"}]})
    spoken = "".join(json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                     for line in r.text.splitlines() if line.startswith("data: {"))
    assert spoken == OPENING and "[DONE]" in r.text
    assert seen == [] and log.rows()[-1]["note"] == "opening line, no model call"


def test_an_opening_without_the_notice_is_replaced_by_the_notice(setup):
    client, seen, _ = setup
    bad = {"role": "system", "content": "Your first words, exactly: Hey, it's Marco, booking for Felix."}
    assert post(client, {"messages": [bad]}).json()["choices"][0]["message"]["content"] == gate.RECORDING_OPENING
    assert seen == []


def test_later_turns_ask_for_minimal_reasoning_and_few_tokens(setup):
    client, seen, _ = setup
    post(client, {"max_tokens": 5000, "messages": [CALL_SYSTEM, {"role": "assistant", "content": OPENING},
                                                   {"role": "user", "content": "For when?"}]})
    body = seen[0][1]
    assert body["reasoning_effort"] == "minimal" and body["max_completion_tokens"] == 300


def test_audio_tags_are_taken_out_even_split_across_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_TOKEN", "relay-secret")
    monkeypatch.setenv("MODEL_API_KEY", "meta-key")

    def upstream(request):
        if json.loads(request.content).get("stream"):
            parts = ["[ha", "ppy] Thursday", " at eight. [warm]", " Thanks"]
            lines = [f'data: {{"choices":[{{"delta":{{"content":{json.dumps(p)}}}}}]}}' for p in parts] + ["data: [DONE]"]
            return httpx.Response(200, text="\n".join(lines) + "\n", headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "[happy] Sure thing."}}], "usage": {}})

    app = Starlette(routes=[Route("/llm/v1/chat/completions", make_relay(
        transport=httpx.MockTransport(upstream), joblog=JobLog(tmp_path / "j.jsonl")), methods=["POST"])])
    client = TestClient(app)
    turn = [{"role": "assistant", "content": OPENING}, {"role": "user", "content": "When?"}]
    assert post(client, {"messages": turn}).json()["choices"][0]["message"]["content"] == "Sure thing."
    r = post(client, {"stream": True, "messages": turn})
    spoken = "".join(json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                     for line in r.text.splitlines() if line.startswith("data: {"))
    assert spoken == "Thursday at eight. Thanks"

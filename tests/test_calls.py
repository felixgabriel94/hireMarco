import json
from datetime import date

import httpx
import pytest

from hiremarco import config, gate
from hiremarco.calls import AGENT_NAME, PHONE_LABEL, SECRET_NAME, TTS_FALLBACK, TTS_MODEL, CallError, Calls, first_message
from hiremarco.calls.twilio import TwilioCheck, masked
from hiremarco.joblog import JobLog

TODAY = date(2026, 10, 31)
OWNER = "15551230000"
LLM_URL = "https://marco.example.ngrok.app/llm/v1"


def test_book_a_table_opening_is_word_for_word():
    assert first_message("book a table") == (
        "Hi, just so you know, this call is recorded. I'm calling to book a table for Felix."
    )
    assert first_message("book a table") == gate.RECORDING_NOTICE
    with pytest.raises(CallError):
        first_message("  ")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-1")
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    rules = tmp_path / "RULES.md"
    rules.write_text("## Send switches\n\n    send: calls -> owner ; test calls to the Owner ; until revoked\n")
    return {"rules": rules, "log": JobLog(tmp_path / "jobs.jsonl"), "tmp": tmp_path}


def fake(routes):
    seen = []

    def handler(request):
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, dict(request.url.params), body))
        assert request.headers["xi-api-key"] == "el-key"
        for (method, path), reply in routes.items():
            if request.method == method and request.url.path == path:
                return reply(body) if callable(reply) else httpx.Response(200, json=reply)
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler), seen


PHONES = [{"provider": "twilio", "label": "other", "phone_number": "+15550000000", "phone_number_id": "pn-other"},
          {"provider": "twilio", "label": PHONE_LABEL, "phone_number": "+15559990000", "phone_number_id": "pn-marco"}]


def test_setup_creates_agent_secret_and_stores_ids(env):
    transport, seen = fake({
        ("GET", "/v1/convai/secrets"): {"secrets": []},
        ("POST", "/v1/convai/secrets"): {"type": "stored", "secret_id": "sec-1", "name": SECRET_NAME},
        ("GET", "/v1/convai/agents"): {"agents": [{"agent_id": "near", "name": AGENT_NAME + " old"}], "has_more": False},
        ("POST", "/v1/convai/agents/create"): {"agent_id": "agent-1"},
        ("GET", "/v1/convai/phone-numbers"): PHONES,
    })
    made = Calls(transport=transport, joblog=env["log"]).setup(LLM_URL)
    assert made == {"agent_id": "agent-1", "phone_number_id": "pn-marco", "tts_model": TTS_MODEL}
    token = config.get("RELAY_TOKEN")
    assert token and len(token) > 30
    secret_post = next(s for s in seen if s[:2] == ("POST", "/v1/convai/secrets"))
    assert secret_post[3] == {"type": "new", "name": SECRET_NAME, "value": token}
    body = next(s for s in seen if s[1] == "/v1/convai/agents/create")[3]
    assert body["name"] == AGENT_NAME
    prompt = body["conversation_config"]["agent"]["prompt"]
    assert prompt["llm"] == "custom-llm"
    assert prompt["custom_llm"] == {"url": LLM_URL, "model_id": "muse-spark", "api_key": {"secret_id": "sec-1"}}
    assert set(prompt["built_in_tools"]) == {"end_call", "voicemail_detection"}
    assert prompt["built_in_tools"]["end_call"]["params"] == {"system_tool_type": "end_call"}
    assert "never claim or imply that you are human" in prompt["prompt"].lower()
    assert "say truthfully that you are an ai assistant" in prompt["prompt"].lower()
    assert "payment" in prompt["prompt"]
    tts = body["conversation_config"]["tts"]
    assert tts["model_id"] == TTS_MODEL and tts["voice_id"] == "voice-1"
    assert tts["expressive_mode"] is False and tts["stability"] >= 0.7 and tts["speed"] == 1.0
    assert body["conversation_config"]["conversation"]["max_duration_seconds"] == 300
    # he waits for the callee, then speaks after 3 s of silence; the relay says the opening
    agent = body["conversation_config"]["agent"]
    assert agent["first_message"] == "" and body["conversation_config"]["turn"]["initial_wait_time"] == 3.0
    assert "Your first words, exactly: {{opening}}" in prompt["prompt"]
    assert prompt["backup_llm_config"] == {"preference": "disabled"}
    lowered = prompt["prompt"].lower()
    assert "no exclamation marks" in lowered and "never invent a date, a time, a party size or a name" in lowered
    stored = config.load_env()
    assert stored["ELEVENLABS_CALL_AGENT_ID"] == "agent-1"
    assert stored["ELEVENLABS_PHONE_NUMBER_ID"] == "pn-marco"
    assert stored["CALL_RELAY_URL"] == LLM_URL


def test_setup_updates_existing_and_falls_back_on_refused_voice_model(env, monkeypatch):
    monkeypatch.setenv("RELAY_TOKEN", "kept-token")
    patches = []

    def patch_agent(body):
        patches.append(body["conversation_config"]["tts"]["model_id"])
        if body["conversation_config"]["tts"]["model_id"] == TTS_MODEL:
            return httpx.Response(422, json={"detail": f"{TTS_MODEL} is not available for agents"})
        return httpx.Response(200, json={"agent_id": "agent-9"})

    transport, seen = fake({
        ("GET", "/v1/convai/secrets"): {"secrets": [{"secret_id": "sec-9", "name": SECRET_NAME}]},
        ("PATCH", "/v1/convai/secrets/sec-9"): {"type": "stored", "secret_id": "sec-9", "name": SECRET_NAME},
        ("GET", "/v1/convai/agents"): {"agents": [{"agent_id": "agent-9", "name": AGENT_NAME}], "has_more": False},
        ("PATCH", "/v1/convai/agents/agent-9"): patch_agent,
        ("GET", "/v1/convai/phone-numbers"): PHONES,
    })
    made = Calls(transport=transport, joblog=env["log"]).setup(LLM_URL + "/")
    assert made["agent_id"] == "agent-9" and made["tts_model"] == TTS_FALLBACK
    assert patches == [TTS_MODEL, TTS_FALLBACK]
    assert not any(s[1] == "/v1/convai/agents/create" for s in seen)
    assert next(s for s in seen if s[0] == "PATCH" and "secrets" in s[1])[3]["value"] == "kept-token"


def test_setup_refuses_a_plain_address_and_a_missing_line(env):
    transport, _ = fake({("GET", "/v1/convai/phone-numbers"): PHONES[:1],
                         ("GET", "/v1/convai/secrets"): {"secrets": [{"secret_id": "s", "name": SECRET_NAME}]},
                         ("PATCH", "/v1/convai/secrets/s"): {},
                         ("GET", "/v1/convai/agents"): {"agents": []},
                         ("POST", "/v1/convai/agents/create"): {"agent_id": "a"}})
    calls = Calls(transport=transport, joblog=env["log"])
    with pytest.raises(CallError, match="https"):
        calls.setup("http://marco.example/llm/v1")
    with pytest.raises(CallError, match="labelled"):
        calls.setup(LLM_URL)


@pytest.fixture
def placing(env, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_CALL_AGENT_ID", "agent-1")
    monkeypatch.setenv("ELEVENLABS_PHONE_NUMBER_ID", "pn-marco")
    transport, seen = fake({("POST", "/v1/convai/twilio/outbound-call"):
                            {"success": True, "message": "ok", "conversation_id": "conv_1", "callSid": "CA123"}})
    calls = Calls(transport=transport, conn=gate.connect(":memory:"), joblog=env["log"], rules_path=env["rules"])
    return calls, seen


def test_place_sends_opening_details_and_machine_hangup(placing, env):
    calls, seen = placing
    placed = calls.place("+" + OWNER, "book a table", "test call, no booking", today=TODAY)
    assert placed == {"conversation_id": "conv_1", "callSid": "CA123"}
    body = seen[0][3]
    assert body["agent_id"] == "agent-1" and body["agent_phone_number_id"] == "pn-marco"
    assert body["to_number"] == "+" + OWNER
    client = body["conversation_initiation_client_data"]
    assert client["dynamic_variables"] == {
        "opening": "Hi, just so you know, this call is recorded. I'm calling to book a table for Felix.",
        "purpose": "book a table", "details": "test call, no booking"}
    amd = body["telephony_call_config"]["twilio_machine_detection"]
    assert amd["actions"] == [{"action": "hang_up", "answered_by": ["machine_start", "fax"]}]
    row = env["log"].rows()[-1]
    assert row["job"] == "call" and "conv_1" in row["note"] and "CA123" in row["note"]
    assert OWNER not in json.dumps(env["log"].rows())


def test_place_is_refused_without_switch_twice_or_by_critic(placing, env):
    calls, seen = placing
    with pytest.raises(gate.Refused, match="no send switch"):
        calls.place("+15557770000", "book a table", today=TODAY)
    calls.place("+" + OWNER, "book a table", today=TODAY)
    with pytest.raises(gate.Refused, match="already done"):
        calls.place("+" + OWNER, "book a table", today=TODAY)
    with pytest.raises(gate.Refused, match="critic held"):
        calls.place("+" + OWNER, "ask the hours", critic=lambda d: (False, "no"), today=TODAY)
    assert len(seen) == 1
    env["rules"].write_text("## Send switches\n")
    with pytest.raises(gate.Refused, match="no send switch"):
        calls.place("+" + OWNER, "say hello", today=TODAY)


def test_critic_is_told_it_is_the_owners_number_and_never_sees_it(placing, env):
    calls, seen = placing
    descriptions = []
    calls.place("+" + OWNER, "book a table", "test call, no booking",
                critic=lambda d: (descriptions.append(d) or True, "ok"), today=TODAY)
    assert descriptions[0].startswith("call via voice to the Owner's own number: Hi, just so you know")
    assert OWNER not in descriptions[0] and len(seen) == 1


def test_named_switch_calls_only_the_number_in_the_owners_words(placing, env):
    calls, seen = placing
    env["rules"].write_text("## Send switches\n\n    send: calls -> named ; whom the Owner names ; until revoked\n")
    with pytest.raises(gate.Refused, match="no send switch"):
        calls.place("+15557770000", "book a table", today=TODAY)
    with pytest.raises(gate.Refused, match="no send switch"):
        calls.place("+15557770000", "book a table", owner_request="call the bistro at +1 555 777 0001", today=TODAY)
    descriptions = []
    placed = calls.place("+15557770000", "book a table", owner_request="Marco, call +1 (555) 777-0000 for a table",
                         critic=lambda d: (descriptions.append(d) or True, "ok"), today=TODAY)
    assert placed["conversation_id"] == "conv_1" and len(seen) == 1
    assert "the Owner asked: Marco, call +1 (555) 777-0000" in descriptions[0]
    assert "5557770000" not in json.dumps(env["log"].rows())


def test_named_switch_never_opens_whatsapp_to_anyone_else(env):
    env["rules"].write_text("## Send switches\n\n    send: calls -> named ; whom the Owner names ; until revoked\n")
    conn = gate.connect(":memory:")
    with pytest.raises(gate.Refused):
        gate.check_outbound(conn, tenant_id="owner", idempotency_key="w", capability="send_message", channel="whatsapp",
                            target="15557770000", message="hi", department="assistant", today=TODAY,
                            rules_path=env["rules"], owner_request="text +15557770000")


def test_place_needs_plus_number(placing):
    calls, seen = placing
    with pytest.raises(CallError, match="E.164"):
        calls.place(OWNER, "book a table", today=TODAY)
    assert not seen


def test_gate_takes_any_purpose_but_only_with_the_opening(env):
    conn = gate.connect(":memory:")
    fields = dict(tenant_id="owner", capability="call", channel="voice", target=OWNER, department="assistant",
                  today=TODAY, rules_path=env["rules"])
    gate.check_outbound(conn, idempotency_key="a", message=first_message("ask the opening hours"), **fields)
    with pytest.raises(gate.Refused, match="recording notice"):
        gate.check_outbound(conn, idempotency_key="b", message="Hello, ask the opening hours.", **fields)
    with pytest.raises(gate.Refused, match="recording notice"):
        gate.check_outbound(conn, idempotency_key="c", message="Hi, I'm calling to ask the opening hours for Felix.",
                            **fields)


def test_transcript_saved_outside_repo_with_cost(env):
    conv = {"status": "done", "conversation_id": "conv_1", "agent_id": "agent-1",
            "transcript": [{"role": "agent", "time_in_call_secs": 0, "message": "Hi, just so you know, this call is recorded."},
                           {"role": "user", "time_in_call_secs": 4, "message": "Hello"}],
            "metadata": {"call_duration_secs": 42, "cost_fiat": 0.07, "cost": 350}}
    transport, _ = fake({("GET", "/v1/convai/conversations/conv_1"): conv})
    path = Calls(transport=transport, joblog=env["log"]).transcript("conv_1", env["tmp"] / "calls")
    assert json.loads(path.read_text())["transcript"][1]["message"] == "Hello"
    row = env["log"].rows()[-1]
    assert row["job"] == "call-cost" and row["cost_usd"] == 0.07 and row["duration_ms"] == 42000
    with pytest.raises(CallError):
        Calls(transport=transport, joblog=env["log"]).transcript("../etc")


def test_twilio_check_reads_only_and_masks(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC" + "0" * 32)
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK1")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "shh")
    methods = []

    def handler(request):
        methods.append(request.method)
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path.endswith("/OutgoingCallerIds.json"):
            return httpx.Response(200, json={"outgoing_caller_ids": [
                {"friendly_name": "Marco (AT&T line)", "phone_number": "+15551234567"}]})
        assert request.url.params["PageSize"] == "3"
        return httpx.Response(200, json={"calls": [{"sid": "CA1", "status": "completed", "direction": "outbound-api",
                                                    "start_time": "Sat, 31 Oct 2026", "duration": "42",
                                                    "to": "+15557654321"}]})

    check = TwilioCheck(transport=httpx.MockTransport(handler))
    assert check.caller_ids() == [{"label": "Marco (AT&T line)", "number": "...4567"}]
    assert check.recent_calls(3)[0]["to"] == "...4321"
    assert set(methods) == {"GET"}
    assert masked(None) == "?"

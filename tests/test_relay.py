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


OPENING = "Hi, just so you know, this call is recorded. I'm calling to book a table for Felix Gabriel."
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


def test_a_profile_respelling_is_said_and_spelling_out_is_left_alone(tmp_path, monkeypatch):
    from hiremarco.calls import brief as briefs

    monkeypatch.setenv("RELAY_TOKEN", "relay-secret")
    monkeypatch.setenv("MODEL_API_KEY", "meta-key")
    briefs.save_profile({**briefs.PROFILE_FIELDS, "say_as": "Zorrilla=Zor-illa; =x; bad"})
    assert briefs.say_as() == {"Zorrilla": "Zor-illa"}

    def upstream(request):
        if json.loads(request.content).get("stream"):
            parts = ["Under Felix Zorr", "illa. That's Z O R", " R I L L A, Zorrilla"]
            lines = [f'data: {{"choices":[{{"delta":{{"content":{json.dumps(p)}}}}}]}}' for p in parts] + ["data: [DONE]"]
            return httpx.Response(200, text="\n".join(lines) + "\n", headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Felix Zorrilla, yes."}}], "usage": {}})

    app = Starlette(routes=[Route("/llm/v1/chat/completions", make_relay(
        transport=httpx.MockTransport(upstream), joblog=JobLog(tmp_path / "j.jsonl")), methods=["POST"])])
    client = TestClient(app)
    turn = [{"role": "assistant", "content": OPENING}, {"role": "user", "content": "Name?"}]
    assert post(client, {"messages": turn}).json()["choices"][0]["message"]["content"] == "Felix Zor-illa, yes."
    r = post(client, {"stream": True, "messages": turn})
    spoken = "".join(json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                     for line in r.text.splitlines() if line.startswith("data: {"))
    assert spoken == "Under Felix Zor-illa. That's Z O R R I L L A, Zor-illa"


def test_a_narrating_sentence_is_never_spoken_and_dashes_become_commas(tmp_path, monkeypatch):
    from hiremarco.relay import unnarrate

    assert unnarrate("Voicemail detected \u2014 I'll leave the message.") == ""
    assert unnarrate("Thanks so much, see you Thursday. Bye. I'll end the call now.") == "Thanks so much, see you Thursday. Bye."
    assert unnarrate("Booking confirmed \u2014 thanks.") == "Booking confirmed, thanks."
    monkeypatch.setenv("RELAY_TOKEN", "relay-secret")
    monkeypatch.setenv("MODEL_API_KEY", "meta-key")

    def upstream(request):
        parts = ["Voicemail det", "ected \u2014 I'll leave", " the message."]
        lines = [f'data: {{"choices":[{{"delta":{{"content":{json.dumps(p)}}}}}]}}' for p in parts] + ["data: [DONE]"]
        return httpx.Response(200, text="\n".join(lines) + "\n", headers={"content-type": "text/event-stream"})

    app = Starlette(routes=[Route("/llm/v1/chat/completions", make_relay(
        transport=httpx.MockTransport(upstream), joblog=JobLog(tmp_path / "j.jsonl")), methods=["POST"])])
    r = post(TestClient(app), {"stream": True, "messages": [{"role": "assistant", "content": OPENING},
                                                            {"role": "user", "content": "At the tone, record."}]})
    spoken = "".join(json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                     for line in r.text.splitlines() if line.startswith("data: {"))
    assert spoken == ""


CALL_TOOLS = [{"type": "function", "function": {"name": n}} for n in
              ("end_call", "voicemail_detection", "skip_turn", "play_keypad_touch_tone")]


def tool_called(r) -> str | None:
    if r.headers["content-type"].startswith("application/json"):
        calls = r.json()["choices"][0]["message"].get("tool_calls") or []
    else:
        calls = [c for line in r.text.splitlines() if line.startswith("data: {")
                 for c in (json.loads(line[6:])["choices"][0]["delta"].get("tool_calls") or [])]
    return calls[0]["function"]["name"] if calls else None


def test_a_voicemail_greeting_is_waited_out_then_the_message_is_left(setup):
    client, seen, log = setup
    start = "Your call has been forwarded to voicemail. The person you're trying to reach is not available."
    r = post(client, {"stream": True, "tools": CALL_TOOLS, "messages": [CALL_SYSTEM, {"role": "user", "content": start}]})
    assert tool_called(r) == "skip_turn" and '"content"' not in r.text  # silent over the greeting, no opening
    end = start + " At the tone, please record your message."
    r = post(client, {"stream": True, "tools": CALL_TOOLS, "messages": [CALL_SYSTEM, {"role": "user", "content": end}]})
    assert tool_called(r) == "voicemail_detection"
    waited = [CALL_SYSTEM, {"role": "user", "content": start},
              {"role": "assistant", "tool_calls": [{"function": {"name": "skip_turn"}}]},
              {"role": "user", "content": "The mailbox is not available."}]
    assert tool_called(post(client, {"tools": CALL_TOOLS, "messages": waited})) == "voicemail_detection"
    assert seen == [] and log.rows()[-1]["note"] == "voicemail: voicemail_detection, no model call"


def test_an_ai_receptionist_is_talked_to_not_left_a_message(setup):
    client, seen, _ = setup
    for greeting in ("Thanks for calling American Social, this is the virtual assistant. How can I help you today?",
                     "To leave a message for the manager, press 2. For reservations, press 1.",
                     "Hi, I'm the AI assistant for the restaurant. Are you calling about a reservation?"):
        r = post(client, {"tools": CALL_TOOLS, "messages": [CALL_SYSTEM, {"role": "user", "content": greeting}]})
        assert tool_called(r) is None and r.json()["choices"][0]["message"]["content"] == OPENING
    assert seen == []


def test_without_the_tools_the_relay_does_not_act_on_a_voicemail(setup):
    client, _, _ = setup
    r = post(client, {"messages": [CALL_SYSTEM, {"role": "user", "content": "At the tone, record your message."}]})
    assert tool_called(r) is None and r.json()["choices"][0]["message"]["content"] == OPENING


def test_the_model_sees_the_real_spelling_not_the_spoken_one(setup):
    from hiremarco.calls import brief as briefs

    client, seen, _ = setup
    briefs.save_profile({**briefs.PROFILE_FIELDS, "say_as": "Zorrilla=Zor-illa"})
    post(client, {"messages": [CALL_SYSTEM, {"role": "assistant", "content": OPENING},
                               {"role": "assistant", "content": "It's under Felix Zor-illa."},
                               {"role": "user", "content": "So that's Felix Zor-illa, correct?"}]})
    sent = [m["content"] for m in seen[0][1]["messages"]]
    assert "It's under Felix Zorrilla." in sent and "So that's Felix Zorrilla, correct?" in sent
    assert not any("Zor-illa" in m for m in sent)


def test_text_leaves_a_clause_at_a_time_and_a_dropped_stream_is_logged(tmp_path, monkeypatch):
    from hiremarco.relay import TagFilter

    f = TagFilter()
    assert f.feed("Yeah, eight fif") == "Yeah,"
    assert f.feed("teen works, perfect") == " eight fifteen works,"
    assert f.flush() == " perfect"
    assert TagFilter().feed("Voicemail detected, I'll leave the message. ") == ""

    monkeypatch.setenv("RELAY_TOKEN", "relay-secret")
    monkeypatch.setenv("MODEL_API_KEY", "meta-key")
    log = JobLog(tmp_path / "j.jsonl")

    def upstream(request):
        lines = ['data: {"choices":[{"delta":{"content":"Yes, that is right."}}]}'] * 50 + ["data: [DONE]"]
        return httpx.Response(200, text="\n".join(lines) + "\n", headers={"content-type": "text/event-stream"})

    app = Starlette(routes=[Route("/llm/v1/chat/completions", make_relay(
        transport=httpx.MockTransport(upstream), joblog=log), methods=["POST"])])
    client = TestClient(app)
    with client.stream("POST", "/llm/v1/chat/completions", headers={"authorization": "Bearer relay-secret"},
                       json={"stream": True, "messages": [{"role": "assistant", "content": OPENING},
                                                          {"role": "user", "content": "Right?"}]}) as r:
        for _ in r.iter_lines():
            break
    row = log.rows()[-1]
    assert row["ok"] is False and row["note"].startswith("caller dropped it after") and "first text at" in row["note"]


def test_a_cut_off_notice_is_said_again_first(setup):
    client, seen, _ = setup
    cut = [CALL_SYSTEM, {"role": "assistant", "content": "Hi, just so you..."},
           {"role": "user", "content": "This is Ava, the virtual assistant. For reservations, press one."}]
    # the whole opening again, from the relay, with no model call (so no filler can come first)
    assert post(client, {"messages": cut}).json()["choices"][0]["message"]["content"] == OPENING
    r = post(client, {"stream": True, "messages": cut})
    spoken = "".join(c["delta"].get("content", "") for line in r.text.splitlines() if line.startswith("data: {")
                     for c in json.loads(line[6:]).get("choices") or [])
    assert spoken == OPENING and seen == []
    # cut off more than twice: the notice is put in front of the model's answer instead
    cut_thrice = [CALL_SYSTEM] + [{"role": "assistant", "content": "Hi, just so you..."}] * 3 + cut[-1:]
    assert post(client, {"messages": cut_thrice}).json()["choices"][0]["message"]["content"].startswith(
        "Hi, just so you know, this call is recorded. ok")
    whole = [CALL_SYSTEM, {"role": "assistant", "content": OPENING}, {"role": "user", "content": "For when?"}]
    assert post(client, {"messages": whole}).json()["choices"][0]["message"]["content"] == "ok"


def test_pressing_and_holding_are_never_narrated():
    from hiremarco.relay import unnarrate

    assert unnarrate("I'll press one to reach reservations.") == ""
    assert unnarrate("Mm-hm. I'll wait on hold for the host.") == ""
    assert unnarrate("Mhm, no, that's everything, thanks.") == "no, that's everything, thanks."
    assert unnarrate("Uh-huh. Indoor please.") == "Indoor please."
    assert unnarrate("One sec. Those don't work for us, unfortunately.") == "Those don't work for us, unfortunately."
    assert unnarrate("Indoor at half past eight works.") == "Indoor at half past eight works."


def test_their_yes_to_a_time_gets_the_name_and_the_contact_question_not_a_hang_up():
    # live 2026-11-04, twice: "Eight thirty works." then "I'll lock in the details." and the call ended
    from hiremarco.relay import booking_line

    system = {"role": "system", "content": "Call brief:\n- name on the booking (first and last): Felix Gabriel\n- party size: 4"}
    talk = [system, {"role": "assistant", "content": "Hi, just so you know, this call is recorded."},
            {"role": "user", "content": "For when?"}, {"role": "assistant", "content": "Thursday at eight, for four."},
            {"role": "user", "content": "Eight thirty works."}]
    assert booking_line(talk) == "Perfect. It's under Felix Gabriel. Do you need a phone number or an email for it?"
    assert booking_line(talk[:-1] + [{"role": "user", "content": "We have Saturday at 7. Does that work?"}]) is None
    assert booking_line(talk[:-1] + [{"role": "user", "content": "Sorry, nothing is available."}]) is None
    said = talk + [{"role": "assistant", "content": "Perfect. It's under Felix Gabriel."}, {"role": "user", "content": "Works."}]
    assert booking_line(said) is None                                  # once a call
    assert booking_line([talk[1], *talk[2:]]) is None                  # not a booking call

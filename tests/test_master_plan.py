"""The plan: the deepest brain reads the audit and the rulebook, names roles the room can fill, then the settings."""

import json

import httpx
import numpy as np
import pytest

from hiremarco.joblog import JobLog
from hiremarco.master import plan
from hiremarco.meta.client import MuseSpark
from hiremarco.mix import audit
from hiremarco.studio.chain import Chain, Slot
from hiremarco.studio.plugins import PluginState

RATE = 48000


def wonder(tmp_path, content, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-wonder-1.0", "choices": [{"message": {"content": content},
                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 3000, "completion_tokens": 300}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


@pytest.fixture
def track():
    rng = np.random.default_rng(1)
    return audit.audit_audio(rng.standard_normal((4 * RATE, 2)) * 0.1, RATE, "song mix")


def test_roles_for_keeps_only_roles_the_room_fills_in_order(tmp_path, track):
    seen = []
    reply = json.dumps({"roles": [
        {"role": "limiter", "plugin": "Pro-L 2", "why": "the demo target needs 6 dB"},
        {"role": "corrective_eq", "plugin": "Pro-Q 3", "why": "a resonance at 240 Hz"},
        {"role": "glue", "plugin": "Rented Comp", "why": "not in the room, 2 dB of glue"},
        {"role": "width", "plugin": "Ozone 11 Imager", "why": "chorus 3 dB narrower than the references"},
        {"role": "karaoke", "plugin": "Pro-Q 3", "why": "no such role"},
        {"role": "limiter", "plugin": "Pro-L 2", "why": "named twice: 6 dB"},
    ], "target_lufs": -10.0, "ceiling_dbtp": -0.3, "audit": "The track is a clean Afrobeat mix. It needs little."})
    room = {"Pro-L 2", "Pro-Q 3", "Ozone 11 Imager", "Channel EQ", "Adaptive Limiter"}
    p = plan.roles_for(track, None, room, purpose="demo", client=wonder(tmp_path, reply, seen))
    assert [r["role"] for r in p.roles] == ["corrective_eq", "width", "limiter"]
    assert p.chain == {"corrective_eq": "Pro-Q 3", "width": "Ozone 11 Imager", "limiter": "Pro-L 2"}
    assert p.target_lufs == -10.0 and p.ceiling_dbtp == -1.0        # the ceiling never rises above the purpose's
    assert p.audit_text.startswith("The track is")
    sent = seen[0]
    assert sent["model"] == "muse-wonder-1.0" and sent["reasoning_effort"] == "max"
    body = json.loads(sent["messages"][-1]["content"])
    assert body["purpose"] == "demo" and "MASTERING RULEBOOK" in body["rulebook"]
    assert body["audit"]["base"]["name"] == "song mix" and body["room"]["candidates"]["limiter"] == ["Pro-L 2", "Adaptive Limiter"]


def test_stock_only_swaps_a_premium_pick_for_the_stock_one(tmp_path, track):
    reply = json.dumps({"roles": [{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB short of -10 LUFS"}],
                        "target_lufs": -14, "ceiling_dbtp": -1, "audit": "ok"})
    room = {"Pro-L 2", "Adaptive Limiter"}
    p = plan.roles_for(track, None, room, purpose="streaming", stock_only=True, client=wonder(tmp_path, reply, []))
    assert p.chain == {"limiter": "Adaptive Limiter"} and p.stock_only


def test_a_plan_with_no_usable_role_is_an_error(tmp_path, track):
    reply = json.dumps({"roles": [{"role": "glue", "plugin": "Nothing", "why": "3 dB"}], "target_lufs": -10,
                        "ceiling_dbtp": -1, "audit": ""})
    with pytest.raises(RuntimeError):
        plan.roles_for(track, None, {"Pro-L 2"}, client=wonder(tmp_path, reply, []))
    with pytest.raises(ValueError):
        plan.roles_for(track, None, {"Pro-L 2"}, purpose="vinyl", client=wonder(tmp_path, reply, []))


def test_the_critic_judges_the_plan(tmp_path, track):
    reply = json.dumps({"roles": [{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB short of -10 LUFS"}],
                        "target_lufs": -10, "ceiling_dbtp": -1, "audit": "ok"})
    heard = []
    p = plan.roles_for(track, None, {"Pro-L 2"}, client=wonder(tmp_path, reply, []),
                       critic=lambda text: heard.append(text) or (True, "within the rules"))
    assert p.critic == (True, "within the rules")
    assert "limiter with Pro-L 2" in heard[0] and "WhatsApp" in heard[0]


def test_a_plan_with_no_numbers_in_its_reasons_is_asked_again(tmp_path, track):
    seen = []
    replies = iter([json.dumps({"roles": [{"role": "limiter", "plugin": "Pro-L 2", "why": "turn the tracksuit bolt"}],
                                "target_lufs": -10, "ceiling_dbtp": -1, "audit": "ok"}),
                    json.dumps({"roles": [{"role": "limiter", "plugin": "Pro-L 2", "why": "true peak 1.5 dBTP over -1"}],
                                "target_lufs": -10, "ceiling_dbtp": -1, "audit": "ok"})])

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-wonder-1.0", "choices": [{"message": {"content": next(replies)},
                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 10}})

    client = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))
    p = plan.roles_for(track, None, {"Pro-L 2"}, client=client)
    assert len(seen) == 2 and p.roles[0]["why"].startswith("true peak")
    assert "every reason must name a number" in json.loads(seen[1]["messages"][-1]["content"])["note"]


def test_a_server_error_is_tried_again_and_a_client_error_is_not(tmp_path, track, monkeypatch):
    reply = json.dumps({"roles": [{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB short of -10 LUFS"}],
                        "target_lufs": -10, "ceiling_dbtp": -1, "audit": "ok"})
    codes = iter([503, 503, 200])
    waited = []
    monkeypatch.setattr(plan, "sleep", waited.append)

    def handler(request):
        code = next(codes)
        if code != 200:
            return httpx.Response(code, json={"error": "busy"})
        return httpx.Response(200, json={"model": "muse-wonder-1.0", "choices": [{"message": {"content": reply},
                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 10}})

    client = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))
    p = plan.roles_for(track, None, {"Pro-L 2"}, client=client)
    assert p.chain == {"limiter": "Pro-L 2"} and waited == [15.0, 45.0]

    bad = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "k.jsonl"),
                    transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "bad"})))
    with pytest.raises(Exception):
        plan.roles_for(track, None, {"Pro-L 2"}, client=bad)
    assert waited == [15.0, 45.0]                   # no retry on a 400


def test_settings_for_reads_the_chain_and_returns_changes(tmp_path, track):
    seen = []
    reply = json.dumps({"changes": [
        {"slot": 2, "parameter": "Gain", "value": 3.5, "unit": "dB", "why": "6 dB short of -10 LUFS, in stages"},
        {"slot": 1, "parameter": "Band 1 Gain", "value": 48, "unit": "%", "why": "the 240 Hz resonance, -1 dB"},
        {"slot": 9, "parameter": "Nope"},
    ], "said": "A half dB off the low mids and the limiter up in stages."})
    chain = Chain([Slot(1, "Pro-Q 3", False, PluginState("Pro-Q 3", {"Band 1 Gain": 30000.0}, {"Band 1 Gain": (0, 60000)}, {})),
                   Slot(2, "Pro-L 2", False, PluginState("Pro-L 2", {"Gain": 0.0}, {"Gain": (0, 100)}, {}))])
    p = plan.MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB short of -10 LUFS"}], -10.0, -1.0, "ok", "demo")
    s = plan.settings_for(chain, track, None, p, client=wonder(tmp_path, reply, seen))
    assert [c["slot"] for c in s.changes] == [2, 1] and s.changes[0]["unit"] == "dB"
    assert s.said.startswith("A half dB")
    body = json.loads(seen[0]["messages"][-1]["content"])
    assert body["targets"] == {"lufs": -10.0, "ceiling_dbtp": -1.0} and body["chain"][1]["plugin"] == "Pro-L 2"

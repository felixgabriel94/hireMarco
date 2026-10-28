from datetime import date

import pytest

from hiremarco import gate
from hiremarco.joblog import JobLog, JobRow

OWNER = "13055550100"
SHOP = "17865550111"
TODAY = date(2026, 10, 28)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("OWNER_WHATSAPP", OWNER)
    rules_path = tmp_path / "RULES.md"
    rules_path.write_text(
        f"send: whatsapp -> {OWNER} ; the Owner's own chat ; until 2026-11-04\n"
        f"send: calls -> {SHOP} ; one booking ; until 2026-11-04\n"
        "send: logic -> * ; transport and knobs ; until 2026-11-04\n"
    )
    return {"conn": gate.connect(":memory:"), "rules_path": rules_path}


def act(env, **over):
    fields = dict(
        tenant_id="owner", idempotency_key="k1", capability="send_message", channel="whatsapp",
        target=OWNER, message="Morning, Felix", department="assistant",
    )
    fields.update(over)
    return gate.execute_effect(env["conn"], lambda: "sent", **fields, today=TODAY, rules_path=env["rules_path"])


def test_allowed_action_runs_and_is_recorded(env):
    assert act(env) == "sent"
    (count,) = env["conn"].execute("select count(*) from effects where ok = 1").fetchone()
    assert count == 1


def test_kill_switch_refuses_a_send(env):
    gate.set_kill_switch(True, "test")
    with pytest.raises(gate.Refused, match="kill switch"):
        act(env)
    gate.set_kill_switch(False)
    assert act(env) == "sent"


def test_same_message_twice_second_refused(env):
    act(env, idempotency_key="a")
    with pytest.raises(gate.Refused, match="same message"):
        act(env, idempotency_key="b")


def test_same_key_twice_refused(env):
    act(env, idempotency_key="a", message="one")
    with pytest.raises(gate.Refused, match="already done"):
        act(env, idempotency_key="a", message="two")


def test_failed_run_does_not_block_a_retry(env):
    def boom():
        raise RuntimeError("network")

    with pytest.raises(RuntimeError):
        gate.execute_effect(env["conn"], boom, tenant_id="owner", idempotency_key="a", capability="send_message",
                            channel="whatsapp", target=OWNER, message="hi", department="assistant",
                            today=TODAY, rules_path=env["rules_path"])
    assert act(env, idempotency_key="a", message="hi") == "sent"


def test_whatsapp_only_to_the_owner(env):
    with pytest.raises(gate.Refused, match="Owner only"):
        act(env, target=SHOP)


def test_call_needs_its_switch_and_the_notice(env):
    with pytest.raises(gate.Refused, match="recording notice"):
        act(env, channel="voice", target=SHOP, message="Hi, table for four?")
    ok = act(env, channel="voice", target=SHOP, message=gate.RECORDING_NOTICE + " Thursday at eight.")
    assert ok == "sent"
    with pytest.raises(gate.Refused, match="no send switch"):
        act(env, idempotency_key="k2", channel="voice", target="17865559999",
            message=gate.RECORDING_NOTICE + " Thursday.")


def test_tool_without_a_switch_is_off(env):
    with pytest.raises(gate.Refused, match="no send switch for export"):
        act(env, channel="files", target="*", message="stems.zip")


def test_unknown_channel_refused(env):
    with pytest.raises(gate.Refused, match="unknown channel"):
        act(env, channel="sms")


def test_critic_hold_and_failure_both_refuse(env):
    fields = dict(tenant_id="owner", capability="call", channel="voice", target=SHOP,
                  message=gate.RECORDING_NOTICE, department="assistant", today=TODAY, rules_path=env["rules_path"])
    with pytest.raises(gate.Refused, match="critic held it: wrong day"):
        gate.execute_effect(env["conn"], lambda: "x", idempotency_key="c1", critic=lambda d: (False, "wrong day"), **fields)

    def broken(description):
        raise TimeoutError

    with pytest.raises(gate.Refused, match="critic unavailable"):
        gate.execute_effect(env["conn"], lambda: "x", idempotency_key="c2", critic=broken, **fields)
    assert gate.execute_effect(env["conn"], lambda: "x", idempotency_key="c3", critic=lambda d: (True, "ok"), **fields) == "x"


def test_daily_limit(env, monkeypatch):
    monkeypatch.setitem(gate.DAILY_LIMITS, "whatsapp", 2)
    act(env, idempotency_key="a", message="1")
    act(env, idempotency_key="b", message="2")
    with pytest.raises(gate.Refused, match="daily limit"):
        act(env, idempotency_key="c", message="3")


def test_model_call_checks(env, tmp_path):
    log = JobLog(tmp_path / "jobs.jsonl")
    gate.check_model_call("owner", model="muse-spark-1.3", system="Be brief.", prompt="hi", joblog=log)
    with pytest.raises(gate.Refused, match="no price"):
        gate.check_model_call("owner", model="muse-unknown", system="", prompt="hi", joblog=log)
    with pytest.raises(gate.Refused, match="secret"):
        gate.check_model_call("owner", model="muse-spark-1.3", system="", prompt="key EAA" + "x" * 50, joblog=log)
    log.append(JobRow(job="big", model="muse-spark-1.3", cost_usd=gate.DAILY_MODEL_CAP_USD))
    with pytest.raises(gate.Refused, match="cap"):
        gate.check_model_call("owner", model="muse-spark-1.3", system="", prompt="hi", joblog=log)
    gate.set_kill_switch(True)
    with pytest.raises(gate.Refused, match="kill switch"):
        gate.check_model_call("owner", model="muse-spark-1.3", system="", prompt="hi", joblog=JobLog(tmp_path / "x.jsonl"))
    gate.set_kill_switch(False)


def test_signatures_match_the_product_shape():
    import inspect

    out = inspect.signature(gate.check_outbound)
    assert list(out.parameters)[:10] == [
        "conn", "tenant_id", "idempotency_key", "capability", "channel", "target", "message", "department",
        "workflow_name", "today",
    ]
    assert out.parameters["tenant_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert out.parameters["workflow_name"].default is None
    model = inspect.signature(gate.check_model_call)
    assert list(model.parameters)[:4] == ["tenant_id", "model", "system", "prompt"]
    assert model.parameters["model"].kind is inspect.Parameter.KEYWORD_ONLY

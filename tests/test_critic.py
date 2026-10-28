import json

import httpx
import pytest

from hiremarco import gate
from hiremarco.critic import Critic, parse
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark


@pytest.mark.parametrize("text,expected", [
    ("APPROVE: matches the Owner's yes", (True, "matches the Owner's yes")),
    ("HOLD: wrong restaurant", (False, "wrong restaurant")),
    ("approve: fine\nextra", (True, "fine")),
    ("Sure, go ahead!", (False, "the critic's answer was unreadable")),
    ("", (False, "the critic's answer was unreadable")),
])
def test_parse_fails_closed(text, expected):
    assert parse(text) == expected


def test_critic_sends_rules_and_action(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "model": "muse-spark-1.3",
            "choices": [{"message": {"role": "assistant", "content": "HOLD: no yes from the Owner"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 6},
        })

    rules_path = tmp_path / "RULES.md"
    rules_path.write_text("Nothing sends outbound without a send switch.\n")
    client = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))
    approved, reason = Critic(client, rules_path)("call via voice to 17865550111: book a table")
    assert (approved, reason) == (False, "no yes from the Owner")
    developer = seen["body"]["messages"][0]
    assert developer["role"] == "developer" and "Nothing sends outbound" in developer["content"]
    assert seen["body"]["messages"][1]["content"].startswith("call via voice")


def test_critic_refuses_when_kill_switch_on(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    gate.set_kill_switch(True)
    client = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"),
                       transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(gate.Refused):
        Critic(client)("anything")

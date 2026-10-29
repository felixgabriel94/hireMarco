import json

import httpx
import pytest

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.studio.chain import Channel, bounded, parse_list
from hiremarco.studio.plugins import PluginError


class FakeChain:
    """Stands in for chain_io.applescript: three slots, one bypassed."""

    def __init__(self):
        self.plugins = {
            1: ("Pro-Q 3", {"Band 1 Gain": 50.0, "Band 1 Frequency": 30.0, "Output Gain": 50.0}, False),
            2: ("CLA-76", {"Input": 40.0, "Output": 60.0, "Attack": 20.0}, False),
            3: ("ValhallaVintageVerb", {"Mix": 20.0, "Decay": 42.0, "Size": 50.0}, True),
        }
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "list":
            return "\n".join(f"{n}\t{name}\t{'bypassed' if byp else 'on'}" for n, (name, _, byp) in self.plugins.items())
        number = int(args[1])
        name, params, _ = self.plugins[number]
        if args[0] == "set":
            pairs = args[2:]
            for k, v in zip(pairs[::2], pairs[1::2]):
                params[k] = float(v)
        return f"plugin\t{name}\n" + "\n".join(f"{k}\t{v}" for k, v in params.items())


@pytest.fixture
def rules(tmp_path):
    p = tmp_path / "RULES.md"
    p.write_text("send: logic -> * ; Logic ; until 2099-01-01\n")
    return p


def wonder(tmp_path, content, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-wonder-1.0", "choices": [{"message": {"content": content},
                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 3000, "completion_tokens": 300}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def test_list_parses_slots_and_bypass():
    slots = parse_list("1\tPro-Q 3\ton\n2\tCLA-76\tbypassed\nnoise")
    assert [(s.number, s.name, s.bypassed) for s in slots] == [(1, "Pro-Q 3", False), (2, "CLA-76", True)]


def test_read_opens_only_the_active_plugins(rules):
    fake = FakeChain()
    chain = Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules).read()
    assert [c[:2] for c in fake.calls] == [["list"], ["read", "1"], ["read", "2"]]
    assert chain.slots[2].state is None and chain.slots[0].state.params["Band 1 Gain"] == 50.0


def test_level_controls_move_at_most_one_step():
    assert bounded("Output Gain", 50, 100) == 65 and bounded("Threshold", 50, 0) == 35
    assert bounded("Attack", 20, 90) == 90 and bounded("Mix", 10, 140) == 100


def test_design_across_the_chain_then_put_back(tmp_path, rules):
    fake, seen = FakeChain(), []
    reply = json.dumps({"changes": [
        {"slot": 1, "parameter": "Band 1 Gain", "value": 62},
        {"slot": 1, "parameter": "Output Gain", "value": 95},     # level: held to one step
        {"slot": 2, "parameter": "Attack", "value": 45},
        {"slot": 3, "parameter": "Mix", "value": 70},             # bypassed: left alone
        {"slot": 2, "parameter": "Shimmer", "value": 50},         # no such parameter: dropped
    ], "said": "A little more air up top and a softer attack on the 76."})
    channel = Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules, client=wonder(tmp_path, reply, seen))
    results, said = channel.design("brighter and smoother")
    assert said.startswith("A little more air")
    assert fake.plugins[1][1]["Band 1 Gain"] == 62 and fake.plugins[1][1]["Output Gain"] == 65
    assert fake.plugins[2][1]["Attack"] == 45 and fake.plugins[3][1]["Mix"] == 20
    body = seen[0]
    assert body["model"] == "muse-wonder-1.0" and body["reasoning_effort"] == "medium"
    sent = json.loads(body["messages"][1]["content"])
    assert [s["plugin"] for s in sent["chain"]] == ["Pro-Q 3", "CLA-76", "ValhallaVintageVerb"]
    assert sent["chain"][2]["bypassed"] is True and sent["chain"][2]["parameters"] == {}
    channel.put_back()
    assert fake.plugins[1][1]["Band 1 Gain"] == 50 and fake.plugins[1][1]["Output Gain"] == 50
    assert fake.plugins[2][1]["Attack"] == 20
    with pytest.raises(gate.Refused, match="nothing to put back"):
        channel.put_back()


def test_nothing_usable_is_an_error(tmp_path, rules):
    reply = json.dumps({"changes": [{"slot": 3, "parameter": "Mix", "value": 70}], "said": "ok"})
    channel = Channel(run=FakeChain(), conn=gate.connect(":memory:"), rules_path=rules,
                      client=wonder(tmp_path, reply, []))
    with pytest.raises(PluginError, match="no usable change"):
        channel.design("wetter")

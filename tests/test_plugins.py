import json

import httpx
import pytest

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.studio.commands import Command, understand
from hiremarco.studio.plugins import Plugin, PluginError, parse

VALHALLA = {"Mix": 93.0, "PreDelay": 25.0, "Decay": 42.0, "Size": 100.0, "ModRate": 33.0, "ModDepth": 4.0,
            "HighCut": 59.0, "ColorMode": 0.0}


class FakeLogic:
    """Stands in for plugin_io.applescript: holds the plugin's values, applies sets, reports them."""

    def __init__(self, params=None, sticky=True):
        self.params = dict(params or VALHALLA)
        self.sticky = sticky
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "set" and self.sticky:
            pairs = args[2:]
            for name, value in zip(pairs[::2], pairs[1::2]):
                self.params[name] = float(value)
        return "plugin\tValhallaVintageVerb\n" + "\n".join(f"{k}\t{v}" for k, v in self.params.items())


def rules(tmp_path):
    p = tmp_path / "RULES.md"
    p.write_text("send: logic -> * ; Logic ; until 2099-01-01\n")
    return p


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))


def test_parse_reads_the_plugin_and_its_values():
    state = parse(FakeLogic()(["read", "-"]))
    assert state.plugin == "ValhallaVintageVerb" and state.params["Mix"] == 93.0
    with pytest.raises(PluginError):
        parse("")


def test_set_applies_clamps_and_verifies(tmp_path):
    logic = FakeLogic()
    plugin = Plugin(run=logic, conn=gate.connect(":memory:"), rules_path=rules(tmp_path))
    after = plugin.set({"Mix": 40, "Decay": 140})
    assert after.params["Mix"] == 40 and after.params["Decay"] == 100
    assert plugin.before.params["Mix"] == 93.0
    with pytest.raises(gate.Refused, match="no parameter Shimmer"):
        plugin.set({"Shimmer": 50})


def test_a_value_that_does_not_stick_is_an_error(tmp_path):
    plugin = Plugin(run=FakeLogic(sticky=False), conn=gate.connect(":memory:"), rules_path=rules(tmp_path))
    with pytest.raises(PluginError, match="did not take"):
        plugin.set({"Mix": 40})


def test_without_the_logic_switch_nothing_is_set(tmp_path):
    logic = FakeLogic()
    empty = tmp_path / "none.md"
    empty.write_text("")
    with pytest.raises(gate.Refused, match="no send switch"):
        Plugin(run=logic, conn=gate.connect(":memory:"), rules_path=empty).set({"Mix": 40})
    assert all(call[0] == "read" for call in logic.calls)


def spark(tmp_path, content, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-spark-1.3", "choices": [{"message": {"content": content},
                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 400, "completion_tokens": 60}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def test_design_turns_words_into_real_parameters_and_put_back_restores(tmp_path):
    seen = []
    reply = json.dumps({"changes": [{"parameter": "Size", "value": 100}, {"parameter": "Decay", "value": 80},
                                    {"parameter": "ModDepth", "value": 45}, {"parameter": "Shimmer", "value": 90}],
                        "said": "Bigger room, longer tail, a little movement for that space."})
    logic = FakeLogic()
    plugin = Plugin(run=logic, conn=gate.connect(":memory:"), rules_path=rules(tmp_path),
                    client=spark(tmp_path, reply, seen))
    state, said = plugin.design("more spacey")
    assert state.params["Decay"] == 80 and state.params["ModDepth"] == 45  # Shimmer does not exist: dropped
    assert said.startswith("Bigger room")
    sent = json.loads(seen[0]["messages"][1]["content"])
    assert sent["plugin"] == "ValhallaVintageVerb" and sent["wants"] == "more spacey" and "Mix" in sent["parameters"]
    assert seen[0]["response_format"]["json_schema"]["strict"] is True
    back = plugin.put_back()
    assert back.params["Decay"] == 42.0 and back.params["ModDepth"] == 4.0


@pytest.mark.parametrize("line, command", [
    ("Marco, make it more spacey", Command("sound", text="more spacey")),
    ("Marco, I want my voice to sound a bit more metallic", Command("sound", text="a bit more metallic")),
    ("Marco, give me a dreamy hall", Command("sound", text="a dreamy hall")),
    ("Marco, put it back", Command("put_back")),
])
def test_sound_lines_skip_the_model(line, command):
    assert understand(line, client=None) == command

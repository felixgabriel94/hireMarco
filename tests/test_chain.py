import json

import httpx
import pytest

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.studio.chain import Channel, bounded, control_named, parse_list
from hiremarco.studio.plugins import PluginError


class FakeChain:
    """Stands in for chain_io.applescript: three slots, one bypassed."""

    def __init__(self):
        self.plugins = {
            1: ("Pro-Q 3", {"Band 1 Gain": 30000.0, "Band 1 Frequency": 18000.0, "Output Gain": 30000.0}, False),
            2: ("CLA-76", {"Input": 4000.0, "Output": 6000.0, "Attack": 2000.0}, False),
            3: ("ValhallaVintageVerb", {"Mix": 20.0, "Decay": 42.0, "Size": 50.0}, True),
        }
        self.scales = {1: 60000, 2: 10000, 3: 100}  # each plugin's own scale, as Logic reports it
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "list":
            return "\n".join(f"{n}\t{name}\t{'bypassed' if byp else 'on'}" for n, (name, _, byp) in self.plugins.items())
        if args[0] == "readall":
            return "\n".join(f"slot\t{n}\n" + self(["read", str(n)]) for n, (_, _, byp) in self.plugins.items()
                             if not byp)
        if args[0] == "setmany":
            blocks, rest = [], args[1:]
            while rest:
                end = rest.index(";")
                number, pairs, rest = rest[0], rest[1:end], rest[end + 1:]
                blocks.append(f"slot\t{number}\n" + self(["set", number, *pairs]))
            return "\n".join(blocks)
        number = int(args[1])
        name, params, _ = self.plugins[number]
        if args[0] == "set":
            pairs = args[2:]
            for k, v in zip(pairs[::2], pairs[1::2]):
                # "=2.5 dB" is in the control's own shown unit: the 76 prints raw/1000 dB
                params[k] = float(v[1:].split()[0]) * 1000 if v.startswith("=") else float(v)
        top = self.scales[number]
        shown = (lambda k, v: f"\t{v / 1000:+.2f} dB") if number == 2 else (lambda k, v: "")
        return f"plugin\t{name}\n" + "\n".join(f"{k}\t{v}\t0\t{top}{shown(k, v)}" for k, v in params.items())


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
    assert fake.calls[0] == ["list"] and fake.calls[1] == ["readall"]  # one run reads every active plugin
    assert [c[:2] for c in fake.calls[2:]] == [["read", "1"], ["read", "2"]]
    assert chain.slots[2].state is None and chain.slots[0].state.percent("Band 1 Gain") == 50.0


def test_level_controls_move_at_most_one_step():
    assert bounded("Output Gain", 50, 100) == 65 and bounded("Threshold", 50, 0) == 35
    assert bounded("Attack", 20, 90) == 90 and bounded("Mix", 10, 140) == 100


def test_design_across_the_chain_then_put_back(tmp_path, rules):
    fake, seen = FakeChain(), []
    reply = json.dumps({"changes": [
        {"slot": 1, "parameter": "Band 1 Gain", "value": 62, "unit": "%", "why": "air above 10 kHz"},
        {"slot": 1, "parameter": "Output Gain", "value": 95},     # level: held to one step
        {"slot": 2, "parameter": "Attack", "value": 45},
        {"slot": 3, "parameter": "Mix", "value": 70},             # bypassed: left alone
        {"slot": 2, "parameter": "Shimmer", "value": 50},         # no such parameter: dropped
    ], "said": "A little more air up top and a softer attack on the 76."})
    channel = Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules, client=wonder(tmp_path, reply, seen))
    results, said = channel.design("brighter and smoother")
    assert said.startswith("A little more air")
    assert channel.reasons[(1, "Band 1 Gain")] == "air above 10 kHz"
    # percents land on each plugin's own scale: 62% of 60000, Output held to 50% + 15
    assert fake.plugins[1][1]["Band 1 Gain"] == 37200 and fake.plugins[1][1]["Output Gain"] == 39000
    assert fake.plugins[2][1]["Attack"] == 4500 and fake.plugins[3][1]["Mix"] == 20
    body = seen[0]
    assert body["model"] == "muse-wonder-1.0" and body["reasoning_effort"] == "medium"
    sent = json.loads(body["messages"][1]["content"])
    assert [s["plugin"] for s in sent["chain"]] == ["Pro-Q 3", "CLA-76", "ValhallaVintageVerb"]
    assert sent["chain"][2]["bypassed"] is True and sent["chain"][2]["parameters"] == {}
    assert sent["chain"][0]["parameters"]["Band 1 Gain"] == 50.0  # the model sees percents, not 30000
    channel.put_back()
    assert fake.plugins[1][1]["Band 1 Gain"] == 30000 and fake.plugins[1][1]["Output Gain"] == 30000
    assert fake.plugins[2][1]["Attack"] == 2000
    with pytest.raises(gate.Refused, match="nothing to put back"):
        channel.put_back()


def test_nothing_usable_is_an_error(tmp_path, rules):
    reply = json.dumps({"changes": [{"slot": 3, "parameter": "Mix", "value": 70}], "said": "ok"})
    channel = Channel(run=FakeChain(), conn=gate.connect(":memory:"), rules_path=rules,
                      client=wonder(tmp_path, reply, []))
    with pytest.raises(PluginError, match="no usable change"):
        channel.design("wetter")


def test_put_back_works_from_a_new_command(tmp_path, rules):
    fake = FakeChain()
    reply = json.dumps({"changes": [{"slot": 2, "parameter": "Attack", "value": 45}], "said": "Softer attack."})
    Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules, client=wonder(tmp_path, reply, [])).design("x")
    assert fake.plugins[2][1]["Attack"] == 4500
    Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules).put_back()  # a fresh process, same disk
    assert fake.plugins[2][1]["Attack"] == 2000


def test_a_second_request_reuses_the_chain_it_read(tmp_path, rules):
    fake = FakeChain()
    reply = json.dumps({"changes": [{"slot": 2, "parameter": "Attack", "value": 45}], "said": "Softer."})
    Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules, client=wonder(tmp_path, reply, [])).read()
    fake.calls.clear()
    Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules, client=wonder(tmp_path, reply, [])).design("x")
    assert [c[0] for c in fake.calls] == ["list", "setmany", "set"]  # no readall: the cache held it
    fake.plugins[3] = ("ValhallaVintageVerb", fake.plugins[3][1], False)  # un-bypassed by hand
    fake.calls.clear()
    Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules, client=wonder(tmp_path, reply, [])).design("x")
    assert "readall" in [c[0] for c in fake.calls]  # the slot list changed, so it reads again


def test_a_change_in_the_units_the_plugin_shows_lands_on_its_reading(tmp_path, rules):
    fake = FakeChain()
    channel = Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules)
    chain = channel.read()
    state = next(s.state for s in chain.slots if s.number == 2)
    assert state.shown["Input"] == "+4.00 dB" and state.units_of("Input") == (4.0, "dB")
    assert state.for_model()["in_units"]["Input"] == "+4.00 dB"
    assert state.in_shown_unit("Input", "dB") and state.in_shown_unit("Input", "dBTP") and not state.in_shown_unit("Input", "ms")
    assert next(s.state for s in chain.slots if s.number == 1).units_of("Band 1 Gain") is None   # no shown column
    channel.apply_changes([{"slot": 2, "parameter": "Input", "value": 2.5, "unit": "dB", "why": "2 dB of drive less"},
                           {"slot": 2, "parameter": "Output", "value": 30, "unit": "dB", "why": "far too much"},
                           {"slot": 2, "parameter": "Attack", "value": 45, "unit": "%", "why": ""}])
    sent = [a for a in fake.calls if a[0] == "setmany"][-1]
    assert "=2.5 dB" in sent and "=18 dB" in sent                       # Output: a level control, +6 held to +12 at most
    assert fake.plugins[2][1]["Input"] == 2500 and fake.plugins[2][1]["Output"] == 18000 and fake.plugins[2][1]["Attack"] == 4500
    assert next(s.state for s in channel.chain.slots if s.number == 2).shown["Input"] == "+2.50 dB"
    channel.put_back()
    assert fake.plugins[2][1]["Input"] == 4000 and fake.plugins[2][1]["Output"] == 6000


def test_a_control_named_with_the_slot_in_front_still_lands():
    controls = ["Gain", "Band 1 Gain", "Output Level"]
    assert control_named("Gain", controls) == "Gain"
    assert control_named("Slot 2 \u2014 Gain: Gain", controls) == "Gain"
    assert control_named("Slot 4 \u2014 Pro-Q 3: Band 1 Gain", controls) == "Band 1 Gain"
    assert control_named("Slot 7 Output Level", controls) == "Output Level"
    assert control_named("Pro-L 2 Gain", controls) == "Gain" and control_named("Regain", controls) is None
    assert control_named("Threshold", controls) is None


def test_a_prefixed_parameter_is_applied_and_its_reason_kept(tmp_path, rules):
    fake = FakeChain()
    channel = Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules)
    channel.read()
    channel.apply_changes([{"slot": 2, "parameter": "Slot 2 \u2014 CLA-76: Input", "value": 3, "unit": "dB", "why": "a dB down"}])
    assert fake.plugins[2][1]["Input"] == 3000 and channel.reasons[(2, "Input")] == "a dB down"


def test_a_slot_whose_window_did_not_open_is_read_as_an_error_and_the_rest_still_land():
    from hiremarco.studio.chain import split_blocks

    states = split_blocks("slot\t1\nplugin\tsoothe2\nerror\t~the plugin window for soothe2 did not open\n"
                          "slot\t2\nplugin\tPro-L 2\nGain\t750\t0\t40000\t+0.75 dB\n")
    assert states[1].fixed["error"].startswith("the plugin window") and states[1].params == {}
    assert states[2].shown["Gain"] == "+0.75 dB"


def test_a_control_named_with_its_value_in_brackets_and_a_slot_counted_from_zero_still_land(tmp_path, rules):
    assert control_named("Gain (+5.50 dB)", ["Gain", "Output Level"]) == "Gain"
    fake = FakeChain()
    channel = Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules)
    channel.read()
    # slot 1 is Pro-Q 3 (no Input); the brain's "slot 1 Input" means slot 2, the 76, counted from zero
    channel.apply_changes([{"slot": 1, "parameter": "Input (+4.00 dB)", "value": 3, "unit": "db", "why": "a dB down"}])
    assert fake.plugins[2][1]["Input"] == 3000 and fake.plugins[1][1]["Band 1 Gain"] == 30000


def test_a_word_in_choice_on_a_plain_control_is_noise_and_the_value_still_lands(tmp_path, rules):
    # run 37 (2026-11-03): the menu field came back as "gain", "-1.0 dB", "Band 1 Frequency" on controls that are not
    # menus, and every change carrying one was dropped unsaid; the record listed them as set
    fake = FakeChain()
    channel = Channel(run=fake, conn=gate.connect(":memory:"), rules_path=rules)
    channel.read()
    channel.apply_changes([{"slot": 1, "parameter": "Band 1 Gain", "value": 40, "unit": "%", "choice": "-1.0 dB", "why": "mud"},
                           {"slot": 1, "parameter": "Band 1 Shape", "value": 0, "unit": "", "choice": "Tilt Shelf", "why": "bell"},
                           {"slot": 1, "parameter": "Band 1 Slope", "value": 0, "unit": "", "choice": "steep", "why": "x"}])
    assert fake.plugins[1][1]["Band 1 Gain"] == 24000
    assert [(c["parameter"], c["choice"]) for c in channel.landed] == [("Band 1 Gain", "")]
    assert len(channel.dropped) == 2 and "Band 1 Shape" in channel.dropped[0] and "'steep'" in channel.dropped[1]

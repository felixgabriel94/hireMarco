"""What Marco learns about the artist: the parts read through fakes, the profile from a mock brain."""

import json

import httpx

from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.studio import taste
from hiremarco.studio.chain import Chain, Slot
from hiremarco.studio.plugins import PluginState


def test_read_parts_keeps_going_past_a_failed_read():
    selected = []
    flows = iter([["Lead Chorus", "LEAD", "VOCALS", "FG Master"], ["x"]])
    chains = iter([[{"slot": 1, "plugin": "Pro-Q 3", "bypassed": False, "settings": {"Band 1 Gain": "-2.0 dB"}}]])

    def chain():
        try:
            return next(chains)
        except StopIteration:
            raise RuntimeError("the plugin window did not open")

    reads = taste.read_parts([("lead", 7, "Lead Chorus"), ("fx", 38, "Robo 1")], select=selected.append,
                             flow=lambda: next(flows), chain=chain, log=lambda s: None)
    assert selected == [7, 38]
    assert reads[0].flow[-1] == "FG Master" and reads[0].inserts[0]["settings"]["Band 1 Gain"] == "-2.0 dB"
    assert reads[1].error.startswith("RuntimeError") and reads[1].inserts == []


def test_chain_for_model_shows_units_where_the_plugin_prints_them():
    state = PluginState("Pro-L 2", {"Gain": 750.0, "Attack": 4072.0}, {"Gain": (0, 40000), "Attack": (0, 10000)}, {},
                        {"Gain": "+0.75 dB"})
    rows = taste.chain_for_model(Chain([Slot(1, "Pro-L 2", False, state), Slot(2, "EchoBoy", True, None)]))
    assert rows[0]["settings"]["Gain"] == "+0.75 dB" and rows[0]["settings"]["Attack"] == "40.7 percent"
    assert rows[1] == {"slot": 2, "plugin": "EchoBoy", "bypassed": True, "settings": {}}


def test_the_profile_is_written_part_by_part_with_its_evidence(tmp_path):
    seen = []
    reply = json.dumps({"parts": [{"part": "lead", "learned": "He tunes hard and de-esses after compression.",
                                   "evidence": "UAD Auto-Tune Retune Speed 10; Pro-DS after Pro-C 2"}],
                        "signature": ["The tape slap on the lead."], "costs": ["Pro-C 2 at 8 dB of gain reduction flattens the verses."],
                        "questions": ["Do you want the ad-libs wider than the lead?"], "summary": "A bright, tight, tuned lead."})

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-wonder-1.0", "choices": [{"message": {"content": reply},
                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 3000, "completion_tokens": 300}})

    client = MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))
    reads = [taste.PartRead("lead", 7, "Lead Chorus", ["Lead Chorus", "FG Master"],
                            [{"slot": 1, "plugin": "UAD Auto-Tune", "bypassed": False, "settings": {"Retune Speed": "10"}}])]
    prof = taste.profile(reads, {"lufs": -15.5}, {"audiobox_aesthetics": {"mix": {"PQ": 8.3}}}, artist="FEGA", client=client)
    assert prof.parts[0]["evidence"].startswith("UAD Auto-Tune") and prof.summary == "A bright, tight, tuned lead."
    sent = json.loads(seen[0]["messages"][-1]["content"])
    assert sent["parts"][0]["inserts"][0]["plugin"] == "UAD Auto-Tune" and sent["hearing"]["audiobox_aesthetics"]["heard"]["mix"]["PQ"] == 8.3
    md = prof.markdown("What Marco learned about FEGA's sound")
    assert "**lead.** He tunes hard" in md and "- The tape slap on the lead." in md and "—" not in md


def test_nothing_read_means_no_profile_call(tmp_path):
    import pytest

    reads = [taste.PartRead("lead", 7, "Lead Chorus", [], [], "RuntimeError: no Single view button")]
    with pytest.raises(RuntimeError, match="no part was read"):
        taste.profile(reads, None, None, artist="FEGA", client=MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl")))

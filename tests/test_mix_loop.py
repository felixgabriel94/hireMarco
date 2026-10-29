import json

import httpx
import pytest

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.mix.ears import Collision, EarsReport, TrackReport
from hiremarco.mix.loop import Mixer, Track, collision_gap, judge, session_for_model
from hiremarco.studio.plugins import PluginState


def state(plugin, params, top):
    return PluginState(plugin, dict(params), {k: (0.0, float(top)) for k in params})


def report(gap=None, peak=-6.0):
    r = EarsReport(tracks=[TrackReport("Bass", 3, -20, -8, -8, 10, {"bass": -2}),
                           TrackReport("Kick", 3, -20, -6, -6, 12, {"bass": -1})])
    if gap is not None:
        r.collisions = [Collision("Kick", "Bass", "bass", gap)]
    r.mix = TrackReport("Mix", 3, -16, peak, peak, 10, {})
    r.mix_notes = ["true peak -1 dBFS: leave at least 3 dB of headroom"] if peak > -3 else []
    return r


class FakeSession:
    def __init__(self, after):
        self.after = after
        self.list = [
            Track("Bass", "audio", -3.0, {1: state("Pro-Q 3", {"Band 1 Gain": 30000.0, "Band 1 Frequency": 2000.0}, 60000)}),
            Track("Kick", "audio", 0.0, {1: state("Pro-C 2", {"Threshold": 30000.0, "Ratio": 5000.0}, 60000)}),
            Track("Vocal", "audio", 0.0, {1: state("ValhallaVintageVerb", {"Mix": 30.0}, 100)}),
        ]
        self.calls = []

    def tracks(self):
        return self.list

    def set_plugin(self, track, slot, raw):
        self.calls.append(("plugin", track, slot, raw))
        st = next(t for t in self.list if t.name == track).inserts[slot]
        st.params.update(raw)
        return st

    def set_fader(self, track, db):
        self.calls.append(("fader", track, db))
        next(t for t in self.list if t.name == track).fader_db = db
        return db

    def export_and_listen(self):
        self.calls.append(("export",))
        return self.after


def wonder(tmp_path, plan, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-wonder-1.0", "choices": [{"message": {"content": json.dumps(plan)},
                              "finish_reason": "stop"}], "usage": {"prompt_tokens": 6000, "completion_tokens": 900}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


PLAN = {"plugin_moves": [{"track": "Bass", "slot": 1, "parameter": "Band 1 Gain", "value": 44,
                          "why": "the bass masks the kick's 60 Hz fundamental"},
                         {"track": "Vocal", "slot": 1, "parameter": "Mix", "value": 20, "why": "less wash"},
                         {"track": "Ghost", "slot": 1, "parameter": "Mix", "value": 20, "why": "x"}],
        "fader_moves": [{"track": "Bass", "db": -9.0, "why": "the bass sits above the kick"}],
        "recommendations": [{"what": "Move Pro-DS before CLA-76 on the vocal",
                             "why": "the 1176 brightens sibilance it is fed"},
                            {"what": "", "why": "empty is dropped"}],
        "to_buses": ["Vocal: ValhallaVintageVerb"],
        "targets": ["Kick / Bass / bass"],
        "said": "I dipped the bass under the kick and pulled the bass down a touch."}


@pytest.fixture
def rules(tmp_path):
    p = tmp_path / "RULES.md"
    p.write_text("send: logic -> * ; Logic ; until 2099-01-01\n")
    return p


def test_a_pass_that_separates_the_collision_is_kept(tmp_path, rules):
    seen = []
    session = FakeSession(after=report(gap=None))
    result = Mixer(session, client=wonder(tmp_path, PLAN, seen), conn=gate.connect(":memory:"), rules_path=rules,
                   log=lambda line: None, owned={"de-esser": ["FabFilter Pro-DS"]}).pass_("give the kick room",
                                                                                        report(gap=2.0))
    assert result.kept and "gone" in result.why
    assert result.plan.reasons["Bass / 1 / Band 1 Gain"].startswith("the bass masks")
    assert result.plan.recommendations == [("Move Pro-DS before CLA-76 on the vocal",
                                            "the 1176 brightens sibilance it is fed")]
    assert ("plugin", "Bass", 1, {"Band 1 Gain": 26400.0}) in session.calls  # 44% of 60000, the level step held
    assert ("fader", "Bass", -6.0) in session.calls                          # -3 dB toward -9, one 3 dB step
    assert not any(c[1] == "Ghost" for c in session.calls if c[0] == "plugin")
    assert result.plan.to_buses == ["Vocal: ValhallaVintageVerb"]
    sent = json.loads(seen[0]["messages"][1]["content"])
    assert sent["measurements"]["collisions"] == ["Kick / Bass / bass (within 2.0 dB)"]
    assert sent["session"][2]["inserts"][0]["belongs_on"] == "bus"
    assert "MIXING RULEBOOK" in seen[0]["messages"][0]["content"]
    assert sent["owned_plugins"] == {"de-esser": ["FabFilter Pro-DS"]}


def test_a_pass_that_makes_it_worse_is_put_back(tmp_path, rules):
    session = FakeSession(after=report(gap=1.0))
    result = Mixer(session, client=wonder(tmp_path, PLAN, []), conn=gate.connect(":memory:"), rules_path=rules,
                   log=lambda line: None, owned={}).pass_("give the kick room", report(gap=2.0))
    assert not result.kept and "did not improve" in result.why
    bass = session.list[0]
    assert bass.inserts[1].params["Band 1 Gain"] == 30000.0 and bass.fader_db == -3.0


def test_losing_headroom_is_put_back():
    kept, why = judge(report(gap=2.0), report(gap=None, peak=-1.0), ["Kick / Bass / bass"])
    assert not kept and "headroom" in why


def test_collision_gap_reads_targets():
    assert collision_gap(report(gap=2.5), "Kick / Bass / bass (within 2.5 dB)") == 2.5
    assert collision_gap(report(gap=None), "Kick / Bass / bass") is None


def test_session_for_model_names_kinds_and_placement():
    view = session_for_model(FakeSession(report()).list)
    assert view[0]["inserts"][0]["kind"] == "eq" and view[0]["inserts"][0]["belongs_on"] == "insert"
    assert view[0]["inserts"][0]["parameters"]["Band 1 Gain"] == 50.0

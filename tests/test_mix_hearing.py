import json

import httpx
import numpy as np
import soundfile as sf

from hiremarco.joblog import JobLog
from hiremarco.meta.client import MuseSpark
from hiremarco.mix import hearing
from hiremarco.mix.ears import EarsReport, TrackReport
from hiremarco.studio.commands import Command, understand


def track(name, lufs, bands):
    full = {b: -40.0 for b in ("sub", "bass", "low mids", "mids", "upper mids", "presence", "air")}
    full.update(bands)
    return TrackReport(name, 10.0, lufs, -6.0, -6.0, 10.0, full, 1.0, 1.0, 0)


REPORT = EarsReport(tracks=[track("Kick", -9, {"bass": -1}), track("808", -11, {"sub": -2, "bass": -3}),
                            track("Lead Vox", -12, {"upper mids": -1}), track("Harmony 1", -18, {"upper mids": -2})])


def wonder(tmp_path, answers):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "muse-wonder-1.0", "choices": [{"message": {
            "content": answers[len(seen) - 1]}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 120}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler)), seen


def test_the_hearing_reads_first_then_speaks_and_asks(tmp_path):
    client, seen = wonder(tmp_path, ["The lead sits on top and the 808 carries the low end, though it and the kick "
                                     "fight around 60 Hz. The harmonies are a little buried. How do you feel about it "
                                     "right now?"])
    view, prefs = hearing.hear(REPORT, "Let Me Love You", client=client)
    assert prefs.heard.endswith("right now?") and view.tracks[0].name == "Kick"
    sent = json.loads(seen[0]["messages"][1]["content"])
    assert "fights" in sent and "tracks" in sent
    assert hearing.load("Let Me Love You").heard == prefs.heard


def test_the_answer_becomes_guardrails_and_merges(tmp_path):
    client, seen = wonder(tmp_path, [
        json.dumps({"keep": ["Lead Vox"], "wishes": [{"track": "Harmony 1", "wish": "sit wider and softer"},
                                                      {"track": "808", "wish": "hit harder"},
                                                      {"track": "Ghost", "wish": "x"}],
                    "reference": "", "overall": "keep it clean"}),
        json.dumps({"keep": [], "wishes": [{"track": "Lead Vox", "wish": "a touch more air"}],
                    "reference": "Travis Scott", "overall": ""}),
    ])
    names = ["Kick", "808", "Lead Vox", "Harmony 1"]
    prefs = hearing.answer("Let Me Love You", "the lead is right, harmonies wider and softer, 808 harder", names,
                           client=client)
    assert prefs.keep == ["Lead Vox"] and prefs.wishes == {"Harmony 1": "sit wider and softer", "808": "hit harder"}
    prefs = hearing.answer("Let Me Love You", "a touch more air on the lead, like Travis", names, client=client)
    assert prefs.keep == [] and prefs.wishes["Lead Vox"] == "a touch more air" and prefs.reference == "Travis Scott"
    assert "Ghost" not in prefs.wishes and hearing.load("Let Me Love You").wishes["808"] == "hit harder"
    assert json.loads(seen[0]["messages"][1]["content"])["tracks"] == names


def test_a_reference_is_a_signature_plus_measured_numbers(tmp_path):
    client, _ = wonder(tmp_path, ["Vocal: heavy tuning as an instrument, wide doubles, long dark reverb; low end "
                                  "808-led; drums hard and dry; overall loud and saturated. Generalized."])
    t = np.arange(48000 * 2) / 48000
    sf.write(tmp_path / "ref.wav", np.column_stack([0.1 * np.sin(2 * np.pi * 55 * t)] * 2), 48000)
    prefs = hearing.reference("Let Me Love You", "Travis Scott", reference_file=tmp_path / "ref.wav", client=client)
    assert prefs.reference == "Travis Scott" and prefs.signature.startswith("Vocal:")
    assert prefs.reference_numbers["bands_db"]["sub"] > -3 and prefs.guardrails()["reference_numbers"]["lufs"] < 0


def test_hearing_and_reference_lines_skip_the_model():
    assert understand("Marco, how does it sound?", client=None) == Command("hearing")
    assert understand("Marco, give me a hearing", client=None) == Command("hearing")
    assert understand("Marco, I want to sound like Travis Scott", client=None) == Command("reference", text="Travis Scott")
    assert understand("Marco, make me sound like Ariana Grande", client=None) == Command("reference", text="Ariana Grande")

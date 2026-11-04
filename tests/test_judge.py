"""Knowledge and wisdom: the ears hear two matched clips, the brain decides inside the rule, and an answer outside the
choices is an error, never a verdict."""

import json
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from hiremarco.joblog import JobLog
from hiremarco.master import judge as judging
from hiremarco.meta.client import MuseSpark


def client(tmp_path, content, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "x", "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 300, "completion_tokens": 50}})

    return MuseSpark(api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=httpx.MockTransport(handler))


def two_prints(tmp_path) -> tuple[Path, Path]:
    rate = 48000
    rng = np.random.default_rng(7)
    loud = rng.standard_normal((rate * 3, 2)).astype("float32") * 0.2
    a, b = tmp_path / "with.wav", tmp_path / "without.wav"
    sf.write(str(a), loud, rate, subtype="FLOAT")
    sf.write(str(b), loud * 0.5, rate, subtype="FLOAT")
    return a, b


def test_the_ears_get_two_clips_matched_in_level(tmp_path):
    a, b = two_prints(tmp_path)
    clip_a, clip_b, rate = judging.matched_clips(a, b, seconds=1.0)
    rms = lambda x: float(np.sqrt(np.mean(np.square(x))))   # noqa: E731
    assert rate == 48000 and abs(rms(clip_a) - rms(clip_b)) < 1e-4 and float(np.max(np.abs(clip_a))) <= 0.5


def test_the_ears_say_what_differs_and_the_brain_decides_inside_the_rule(tmp_path, monkeypatch):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    a, b = two_prints(tmp_path)
    seen = []
    ears = judging.Judge(client(tmp_path, json.dumps({"hears": "the low end tightens with it", "note": "I hear the bass hold together.",
                                                     "difference": "helps"}), seen))
    from hiremarco.studio import aloud

    played = []
    monkeypatch.setattr(aloud, "play", lambda pcm, rate, **k: played.append((len(pcm), rate)))
    heard = ears.hear(a, b, job="bench_ear", what=("with Pro-L 2", "without Pro-L 2"))
    assert played == [(2 * 48000 * 3 + int(48000 * judging.GAP_S), 48000)]   # the room hears the pair, both clips, a breath between
    assert heard == {"hears": "the low end tightens with it", "note": "I hear the bass hold together.", "difference": "helps"}
    assert seen[0]["model"] == "muse-spark-1.2" and [c["type"] for c in seen[0]["messages"][1]["content"]] == ["text", "input_audio", "input_audio"]

    brain = judging.Judge(client(tmp_path, json.dumps({"decision": "keep", "why": "level -3.0 dB without it, past earn_db",
                                                      "plain": "I keep it. The song is thinner without it."}), seen))
    call = brain.decide("bench_verdict", ("keep", "remove"), rule=judging.BENCH_RULE,
                        numbers={"without_it": {"level_db": 3.0}, "earn_db": 0.5}, heard=heard)
    assert call.decision == "keep" and call.why.startswith("level -3.0") and call.plain.startswith("I keep it.")
    sent = json.loads(seen[-1]["messages"][-1]["content"])
    assert sent["rule"] == judging.BENCH_RULE and sent["heard"] == heard and seen[-1]["model"] == "muse-wonder-1.0"
    assert seen[-1]["reasoning_effort"] == "medium"


def test_an_answer_outside_the_choices_is_an_error_not_a_verdict(tmp_path):
    import pytest

    brain = judging.Judge(client(tmp_path, json.dumps({"decision": "maybe", "why": "", "plain": ""}), []))
    with pytest.raises(RuntimeError, match="not one of keep, remove"):
        brain.decide("bench_verdict", ("keep", "remove"), rule="r", numbers={})


def test_a_thin_hearing_is_asked_once_more_then_counts_as_unknown(tmp_path, monkeypatch):
    # run 39 (2026-11-03): the ears answered "no audio?" on the finished song; a verdict is never built on that
    from hiremarco import config
    from hiremarco.studio import aloud

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(aloud, "play", lambda pcm, rate, **k: None)
    a, b = two_prints(tmp_path)
    seen = []
    ears = judging.Judge(client(tmp_path, json.dumps({"hears": "no audio?", "note": "at plain?", "difference": "none"}), seen))
    assert ears.hear(a, b, job="check_ear", what=("the original", "the finished version")) == {"hears": "", "note": "", "difference": "unknown"}
    assert len(seen) == 2   # asked twice, then given up on

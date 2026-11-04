"""A few spoken checkpoints through the master job, not commentary (Owner 2026-11-04): the balance checked, the before
and after, the marks before he sends; the booth says them, a job run elsewhere stays silent."""

import numpy as np

from hiremarco.master import job as jobs
from hiremarco.master.judge import GAP_S
from tests.test_master_job import FakeJudge, _events, _judged_run, _plain_run

BALANCE = "I've checked your balance. Now I'll finish it."
BEFORE_AFTER = "Here's your song before my work, then after, at the same level."


def speaker(said):
    return lambda moment, facts, plain: said.append((moment, facts, plain))


def test_silent_with_no_booth_and_a_failing_voice_changes_nothing():
    jobs.checkpoint("x", {}, "nothing")   # no speaker: nothing happens
    def broken(moment, facts, plain):
        raise RuntimeError("the line is down")
    with jobs.speaking(broken):
        jobs.checkpoint("x", {}, "said")
    assert jobs._SPEAKER == []


def test_the_balance_then_the_marks_before_the_send(tmp_path, monkeypatch):
    said = []
    with jobs.speaking(speaker(said)):
        _plain_run(tmp_path, monkeypatch, deliver=lambda p, c: "sent")
    plains = [p for _, _, p in said]
    assert plains == [BALANCE, "It hits the marks. Sending it to you now."]
    last = said[-1][1]
    assert last["marks_met"] is True and last["loudness_lufs"] == -12.0 and last["goal_lufs"] == -12.0
    assert jobs._SPEAKER == []


def test_the_before_and_after_is_cued_and_said_before_the_ears_hear_it(tmp_path, monkeypatch):
    said, order = [], []
    judge = FakeJudge({"Gain": ("keep", "I keep it."), "Pro-L 2": ("keep", "I keep it.")})
    hear = judge.hear
    judge.hear = lambda a, b, *, job, what: order.append(job) or hear(a, b, job=job, what=what)
    with jobs.speaking(lambda m, f, p: (said.append(p), order.append(p))):
        _judged_run(tmp_path, monkeypatch, judge)
    assert BEFORE_AFTER in said and order.index(BEFORE_AFTER) < order.index("check_ear")
    assert any(r.get("plain") == "Marco plays your song before his work, then after, at the same level." for r in _events(tmp_path))


def test_the_room_hears_a_breath_between_before_and_after(tmp_path, monkeypatch):
    import soundfile as sf

    from hiremarco.master import judge as judging
    from hiremarco.studio import aloud

    rate = 8000
    for name, level in (("a.wav", 0.2), ("b.wav", 0.4)):
        sf.write(str(tmp_path / name), np.full((rate * 12, 2), level, dtype="float32"), rate)
    played = []
    monkeypatch.setattr(aloud, "play", lambda pcm, r: played.append((pcm, r)))
    monkeypatch.setattr(judging.gate, "check_model_call", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop here")))
    try:
        judging.Judge(client=type("C", (), {"joblog": None})()).hear(tmp_path / "a.wav", tmp_path / "b.wav", job="j", what=("a", "b"))
    except RuntimeError:
        pass
    pcm, r = played[0]
    gap = int(rate * GAP_S)
    clip = (pcm.shape[0] - gap) // 2
    assert r == rate and clip > 0 and pcm[:clip].all() and not pcm[clip:clip + gap].any() and pcm[clip + gap:].all()


def test_the_booth_speaks_the_jobs_checkpoints_while_it_runs_it(monkeypatch):
    import time

    from hiremarco.studio.commands import Command
    from tests.test_beat_in import booth_with

    b, said = booth_with(lambda p: "unused")
    b.master = lambda words: jobs.checkpoint("a checkpoint", {}, "Checkpoint.") or "done"
    b._master(Command("export"))
    for _ in range(200):
        if "Checkpoint." in said and not b.busy:
            break
        time.sleep(0.01)
    assert "Checkpoint." in said and jobs._SPEAKER == []

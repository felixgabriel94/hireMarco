"""Marco Live: runtime rows in the page's words, paced, honest about what is running; the page is one file with no network."""

import json
import os
import re
from pathlib import Path

import httpx

from hiremarco import critic, events, tracewindow
from hiremarco.joblog import JobLog
from hiremarco.meta import image
from hiremarco.studio import face


def row(kind, **fields):
    return {"ts": "2026-11-02T20:00:00.000-05:00", "kind": kind, "source": "marco", "status": "ok", "summary": "", **fields}


def test_a_model_call_is_a_start_and_an_end_with_one_id():
    start = events.for_page(row("model_call_started", source="meta", model="muse-wonder-1.0", status="running", operation="mastering plan",
                                task="Write the plan", call_id="a", request_id="00001"))
    end = events.for_page(row("model_call_completed", source="meta", model="muse-wonder-1.0", summary="7 jobs.", call_id="a", latency_ms=9,
                              metrics=[{"label": "Loudness", "value": "-10", "unit": "LUFS"}]))
    assert start["type"] == "call_start" and start["task"] == "Write the plan" and start["status"] == "running"
    assert end["type"] == "call_end" and end["call_id"] == "a" and end["metrics"] == {"Loudness": "-10 LUFS"} and end["status"] == "ok"


def test_no_status_of_ours_reads_as_ok_on_the_page():
    # the page treats any status it does not know as ok; a refusal or a failure must not reach it that way
    for ours, theirs in (("failed", "error"), ("retry", "error"), ("refused", "held"), ("low_confidence", "held")):
        assert events.for_page(row("model_call_completed", source="meta", model="sam-3.1", status=ours, call_id="a"))["status"] == theirs


def test_catches_get_their_own_event_and_a_pass_stays_quiet():
    caught = events.for_page(row("verification_completed", status="failed", summary="not verified", plain="Marco goes back.", stage="Build"))
    assert caught["type"] == "self_catch" and caught["stage"] == "Build" and caught["plain"] == "Marco goes back." and "status" not in caught
    assert events.for_page(row("verification_completed", summary="verified")) is None
    assert events.for_page(row("tool_skipped", status="refused", plain="Marco left it out."))["type"] == "tool_skipped"
    assert events.for_page(row("tool_invoked", status="refused", summary="held"))["status"] == "held"


def test_small_hands_stay_off_the_page_and_a_long_step_shows_with_its_tool():
    assert events.for_page(row("tool_invoked", status="running", tool="Logic Pro", summary="a key")) is None
    step = events.for_page(row("tool_invoked", status="running", tool="Logic Pro", task="Print the master", call_id="s"))
    assert step["type"] == "call_start" and step["model"] == "Logic Pro"


def test_the_path_is_sent_once_and_a_thought_carries_its_words():
    started = events.for_page(row("job_started", stages=["Listen", "Think"], stage="Listen", plain="Marco is listening."))
    assert started["stages"] == ["Listen", "Think"] and started["plain"] == "Marco is listening."
    moved = events.for_page(row("stage", stage="Think", plain="Marco is thinking."))
    assert "stages" not in moved and moved["stage"] == "Think"
    assert events.for_page(row("decision_made", thought="I clear the mud.", summary="eq"))["thought"] == "I clear the mud."
    assert events.for_page(row("decision_made", summary="corrective eq: Pro-Q 3")) is None
    assert events.for_page(row("analysis_generated", summary="-18.0 LUFS")) is None


def test_lines_fit_the_budgets_and_end_on_a_word(tmp_path):
    at = tmp_path / "e.jsonl"
    long = "Marco is doing a thing that goes on for a very long time, " * 6
    out = events.emit("stage", source="marco", stage="Think", plain=long, at=at)
    assert len(out["plain"]) <= events.PLAIN_CHARS and not out["plain"].endswith(" ") and long.startswith(out["plain"])
    two = events.emit("thought", source="marco", thought="First sentence here. " + "x " * 80, at=at)
    assert len(two["thought"]) <= events.LINE_CHARS


def test_a_step_shows_a_failure_as_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "path", lambda: tmp_path / "e.jsonl")
    with events.step("Print the master") as line:
        line["summary"] = "Printed."
    try:
        with events.step("Print again"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    rows = list(events.read_all(tmp_path / "e.jsonl"))
    assert [r["status"] for r in rows] == ["running", "ok", "running", "failed"] and rows[1]["summary"] == "Printed."
    assert rows[0]["call_id"] == rows[1]["call_id"] != rows[2]["call_id"]


def test_the_pacer_spaces_events_and_beats_only_while_the_job_lives():
    pacer = tracewindow.Pacer()
    pacer.add([row("thought", thought="one"), row("thought", thought="two")])
    assert len(pacer.due(100.0)) == 1 and pacer.due(100.5) == [] and len(pacer.due(101.7)) == 1
    assert pacer.beat(200.0) is False   # no job
    pacer.add([row("job_started", pid=os.getpid(), stage="Listen", plain="x")])
    pacer.due(300.0)
    assert pacer.beat(400.0) is True and pacer.beat(400.1) is False
    pacer.add([row("job_ended")])
    assert pacer.beat(500.0) is False


def test_a_job_whose_process_is_gone_does_not_keep_the_page_live():
    gone = row("job_started", pid=2 ** 22 + 1)
    assert tracewindow.resume_point([gone, row("stage", stage="Think")]) == []
    here = row("job_started", pid=os.getpid())
    assert tracewindow.resume_point([row("note"), here, row("stage", stage="Think")])[0] is here
    assert tracewindow.resume_point([here, row("job_ended")]) == []


def test_the_page_has_no_network_and_no_sample_and_its_assets_are_there():
    page = tracewindow.PAGE.read_text()
    assert not re.findall(r"https?://(?!www\.w3\.org)", page)
    assert "marco-sample" not in page and "MARCO_SAMPLE" not in page
    assert page.count("@font-face") == 2 and "window.marco" in page
    for name in re.findall(r"assets/[\w.-]+", page):
        assert (tracewindow.PAGE.parent / name).exists(), name


def test_the_critic_and_the_face_say_what_happened():
    assert critic.verdict_line("HOLD: not on the list") == ("refused", "Held. not on the list")
    assert critic.verdict_line("APPROVE: fine") == ("ok", "Approved.")
    assert face._face_line(json.dumps({"plugin": "AMEK", "licensed": False, "notice": "Activation Required"})) == "AMEK: Activation Required"


def test_mail_stays_off_the_screen_until_turned_on(tmp_path, monkeypatch):
    monkeypatch.setattr(events.config, "STATE_DIR", tmp_path)
    assert events.show_mail() is False
    events.mail_flag().write_text("on")
    assert events.show_mail() is True


def test_muse_image_reaches_the_stream(tmp_path, monkeypatch):
    monkeypatch.setattr(image.gate, "check_model_call", lambda *a, **k: None)
    payload = {"data": [{"b64_json": "aGk="}]}
    done = image.generate("paper", job="dress-backdrop", joblog=JobLog(tmp_path / "j.jsonl"), api_key="k",
                          transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    assert done == b"hi"
    rows = list(events.read_all())
    assert [r["kind"] for r in rows][-2:] == ["model_call_started", "model_call_completed"]
    assert rows[-1]["model"] == "muse-image-1.0" and rows[-1]["call_id"] == rows[-2]["call_id"]
    assert rows[-2]["task"] == "Paint the paper of the look board"


SOURCES = ("master/job.py", "master/ladder.py", "mix/verify.py", "critic.py", "studio/face.py")


def screen_lines() -> list[str]:
    """Every fixed sentence these files put on the big lines of the page, placeholders taken out."""
    root = Path(events.__file__).parent
    found = []
    for name in SOURCES:
        text = (root / name).read_text()
        found += re.findall(r'''(?:\bplain=\(?|events\.stage\("\w+", |events\.step\(|\bthought=|events\.thought\(|\bsummary=)f?"([^"]+)"''', text)
    return [re.sub(r"\{[^}]*\}", "X", line) for line in found]


def test_the_big_lines_are_in_everyday_words():
    lines = screen_lines() + list(events.TASKS.values()) + [words for _, words in events.PLAIN_FINDINGS]
    assert len(lines) > 40
    bad = [line for line in lines if events.JARGON.search(line)]
    assert not bad, bad


def test_a_now_line_fits_its_budget():
    root = Path(events.__file__).parent
    text = (root / "master/job.py").read_text()
    for line in re.findall(r'''(?:\bplain=|events\.stage\("\w+", )f?"([^"]+)"''', text):
        assert len(re.sub(r"\{[^}]*\}", "a name", line)) <= events.PLAIN_CHARS, line


def test_a_model_line_with_trade_words_stays_off_the_screen():
    assert events.readable("Lifted to -10 LUFS. It sounds clearer now.") == "It sounds clearer now."
    assert events.readable("Gain at 3 dB on the limiter.") == ""
    assert events.plain_findings(["low end below 120 Hz is wide (correlation 0.59)", "114 clicks or dropouts", "77 s of silence at the tail"]) == [
        "The bass spreads too wide. It could weaken on a club system.", "I hear small clicks in the recording."]

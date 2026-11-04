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


def test_a_band_menu_is_offered_and_placement_is_a_closed_list():
    from hiremarco.studio.plugins import PLACEMENTS, PluginState

    state = PluginState("Pro-Q 3", params={"Band 1 Used": 1.0, "Band 1 Gain": 30000.0}, ranges={"Band 1 Used": (0.0, 1.0), "Band 1 Gain": (0.0, 60000.0)},
                        fixed={"Band 1 Stereo Placement": "Stereo", "Band 1 Shape": "Bell", "Band 1 Speakers": "All"})
    view = state.for_model()
    assert view["menus"] == {"Band 1 Stereo Placement": "Stereo", "Band 1 Shape": "Bell"} and "Band 1 Stereo Placement" not in view["fixed"]
    assert "Band 1 Stereo Placement" not in state.changeable() and "Side" in PLACEMENTS


def test_the_audition_only_takes_what_the_audit_named_and_shapes_the_slice():
    import numpy as np

    from hiremarco.master import audition

    class Base:
        low_mono = 0.59

    class Quiet:
        low_mono = 0.95

    class R:
        hz, note = 260.7, "C4"

    class Audit:
        base, resonances = Base, [R]

    class Clean:
        base, resonances = Quiet, []

    assert audition.targets(Clean) == []
    found = audition.targets(Audit)
    assert found[0].placement == "Side" and found[0].below == 120.0 and found[1].hz == 260.7
    rate = 48000
    t = np.arange(rate) / rate
    low, high = np.sin(2 * np.pi * 60 * t), np.sin(2 * np.pi * 5000 * t)
    stereo = np.column_stack([low + high, -low + high])   # the 60 Hz lives only in the sides
    part = audition.slice_of(stereo, rate, found[0])
    assert abs(float(np.sqrt(np.mean(part ** 2))) - float(np.sqrt(np.mean(low ** 2)))) < 0.02   # the sides below 120: the 60 Hz, no 5 kHz
    bell = audition.slice_of(stereo, rate, audition.Target("5 kHz", hz=5000.0))
    assert abs(float(np.sqrt(np.mean(bell ** 2))) - float(np.sqrt(np.mean(high ** 2)))) < 0.02


def test_talk_in_the_room_stays_off_the_screen_during_a_job_and_a_stopped_job_says_so():
    pacer = tracewindow.Pacer()
    pacer.add([row("job_started", pid=os.getpid(), stage="Listen", plain="x")])
    pacer.add([row("model_call_completed", source="meta", model=events.VOICE_MODEL, summary="Wow.", call_id="v")])
    assert len(pacer.waiting) == 1
    pacer.add([row("job_ended", status="failed", summary="RuntimeError: x", plain="Marco stopped here.")])
    assert pacer.waiting[-1]["type"] == "self_catch" and pacer.waiting[-1]["plain"] == "Marco stopped here."
    pacer.add([row("model_call_completed", source="meta", model=events.VOICE_MODEL, summary="Solo it.", call_id="w")])
    assert pacer.waiting[-1]["call_id"] == "w"
    assert events.for_page(row("job_ended", status="ok", summary="Done")) is None


def test_the_page_says_testing_lights_a_running_model_and_counts_one_job(tmp_path):
    # Owner 2026-11-03: done only for a finished result; a model lit the whole time it is in use; the header's count
    # is this job's, not the day's
    page = tracewindow.PAGE.read_text()
    assert "'decided':(l.word||'done')" in page and "l.word.replace(/ed$/,'ing'):'using'" in page
    assert "[...S.calls.values()].filter(l=>l.status==='running').concat(" in page
    assert page.count("S.runs++;S.calls=new Map();S.catches=0;}") == 1


def test_a_song_file_gets_the_wave_file_mark_and_loudness_keeps_the_meter():
    # Owner 2026-11-03, option B: a square tile with a waveform for anything that is a song file
    page = tracewindow.PAGE.read_text()
    assert "if(mo==='wavefile')return '<span class=\"mk sv wavefile\">" in page and "const MOTIFS={wavefile:0," in page
    assert "'rec','bars','wavefile']" in page and ".mk.wavefile{height:36px}.mk.wavefile svg{width:28px;height:36px}" in page and ">WAV</text>" in page
    route = page[page.index("return 'wavefile';"):]
    assert page.index("return 'wavefile';") < page.index("return 'rec';") and "the final version" in page[page.index("function motifOf"):page.index("return 'wavefile';")]


def test_a_running_demo_reads_as_licensed_even_beside_a_buy_button():
    # Owner 2026-11-03: Shadow Hills in demo says DEMO ACTIVE - 14 DAYS with BUY beside it; BUY alone must not fail it
    assert "DEMO ACTIVE" in face.INSTRUCTIONS and "A running demo counts as licensed" in face.INSTRUCTIONS
    assert face._face_line(json.dumps({"plugin": "UAD Shadow Hills Mastering Compressor", "licensed": True, "notice": ""})) == "UAD Shadow Hills Mastering Compressor is licensed."

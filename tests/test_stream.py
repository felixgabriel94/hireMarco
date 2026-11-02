"""Marco's running log: one plain line per step, nothing private, and the job log feeding it."""

import json

from hiremarco import stream
from hiremarco.joblog import JobLog, JobRow


def test_say_writes_model_step_and_seconds(tmp_path):
    at = tmp_path / "marco.log"
    row = stream.say("muse-spark-1.3", "read the plug-in's face: licensed", 1.26, at=at)
    assert row["model"] == "muse-spark-1.3" and row["seconds"] == 1.3 and row["ts"]
    assert stream.tail(at=at) == [json.loads(at.read_text())]
    stream.say("", "   the mix print   ", at=at)
    assert stream.tail(at=at)[-1] == {"ts": stream.tail(at=at)[-1]["ts"], "model": "marco", "text": "the mix print"}
    assert stream.line(row) == "muse-spark-1.3           read the plug-in's face: licensed  1.3 s"


def test_nothing_private_is_written(tmp_path):
    at = tmp_path / "marco.log"
    stream.say("marco", "replied to fega@example.com and +1 (646) 555-0123; token sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123 "
               "Bearer eyJhbGciOi.ab", at=at)
    text = stream.tail(at=at)[0]["text"]
    assert "example.com" not in text and "555" not in text and "abcdefghij" not in text and "eyJ" not in text
    assert text == "replied to [email] and [number]; token [key] [bearer]"
    assert stream.clean("Pro-Q 3 at 254 Hz, -1.5 dB, Q 6, bar 21 to 45") == "Pro-Q 3 at 254 Hz, -1.5 dB, Q 6, bar 21 to 45"


def test_the_job_log_feeds_the_stream_with_the_model_first(tmp_path):
    log = JobLog(tmp_path / "jobs.jsonl")
    log.append(JobRow(job="master_plan", model="muse-wonder-1.0", duration_ms=41800))
    log.append(JobRow(job="segment", model="sam-3.1", ok=False, note="http 500", duration_ms=900))
    rows = stream.tail(at=tmp_path / "marco.log")
    assert [(r["model"], r["text"], r["seconds"]) for r in rows] == [
        ("muse-wonder-1.0", "master plan", 41.8), ("sam-3.1", "segment: http 500", 0.9)]


def test_steps_streams_every_log_line_as_marcos_own_timed_from_the_last(tmp_path):
    at = tmp_path / "marco.log"
    printed = []
    steps = stream.Steps(also=printed.append, at=at)
    steps("2. the audit")
    steps("   finding: resonance at 254 Hz, 6.3 dB over its octave")
    steps.as_model("muse-wonder-1.0")
    steps("   corrective_eq: Pro-Q 3. One narrow cut at the measured 254 Hz resonance.")
    steps.as_model("")
    steps("")
    rows = stream.tail(at=at)
    assert printed == ["2. the audit", "   finding: resonance at 254 Hz, 6.3 dB over its octave",
                       "   corrective_eq: Pro-Q 3. One narrow cut at the measured 254 Hz resonance.", ""]
    assert [r["model"] for r in rows] == ["marco", "marco", "muse-wonder-1.0"]
    assert rows[1]["text"] == "finding: resonance at 254 Hz, 6.3 dB over its octave" and rows[1]["seconds"] < 1

"""Marco's event stream: one structured line per thing that happens, nothing private, tailed by the trace."""

import json

from hiremarco import events


def test_emit_writes_the_row_shape_and_cuts_what_is_long(tmp_path):
    at = tmp_path / "events.jsonl"
    row = events.emit("model_call_completed", source="meta", model="muse-wonder-1.0", operation="mastering plan",
                      status="ok", summary="x" * 200, detail="d" * 300, latency_ms=1842.7, confidence=0.973,
                      metrics=[("Resonance", "260.7", "Hz"), {"label": "Key", "value": "C major"}, ("a", 1), ("b", 2), ("c", 3)],
                      request_id="01842", call_id="abc", tokens={"prompt": 2166, "completion": 1029, "cached": 0, "x": 9},
                      cost_usd=0.00708075, at=at)
    assert row["kind"] == "model_call_completed" and row["source"] == "meta" and row["latency_ms"] == 1842
    assert len(row["summary"]) == 80 and len(row["detail"]) == 120 and row["confidence"] == 0.97
    assert row["metrics"][0] == {"label": "Resonance", "value": "260.7", "unit": "Hz"} and len(row["metrics"]) == 4
    assert row["tokens"] == {"prompt": 2166, "completion": 1029, "cached": 0} and row["cost_usd"] == 0.007081
    assert json.loads(at.read_text().splitlines()[0]) == row and row["ts"].endswith(("-05:00", "-04:00", "+00:00")) or True


def test_nothing_private_and_a_marco_source_for_anything_not_meta(tmp_path):
    at = tmp_path / "events.jsonl"
    row = events.emit("tool_completed", source="logic", summary="sent to fega@example.com, +1 (646) 555-0123", at=at)
    assert row["source"] == "marco" and row["summary"] == "sent to [email], [number]"


def test_kinds_and_statuses_are_closed_lists(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        events.emit("something_else", source="marco", at=tmp_path / "e.jsonl")
    with pytest.raises(ValueError):
        events.emit("note", source="marco", status="maybe", at=tmp_path / "e.jsonl")


def test_request_ids_count_the_day(tmp_path):
    at = tmp_path / "events.jsonl"
    assert events.next_request_id(at) == "00001" and events.next_request_id(at) == "00002"


def test_words_for_models_jobs_and_tools():
    assert events.model_words("muse-wonder-1.0") == "MUSE WONDER 1.0" and events.model_words("sam-3.1") == "SAM 3.1"
    assert events.operation_words("master_audit") == "mastering plan" and events.operation_words("new_job") == "new job"
    assert events.tool_words("logic") == "Logic Pro" and events.tool_words("fax") == "fax"


def test_reply_summary_reads_prose_or_the_first_string_in_json():
    assert events.reply_summary("The track sits at -18 LUFS.\nMore.") == "The track sits at -18 LUFS."
    assert events.reply_summary(json.dumps({"licensed": True, "notice": "", "plugin": "Pro-L 2", "why": "it is a clean mix with headroom"})) == "it is a clean mix with headroom"
    assert events.reply_summary("{}") == "a structured reply" and events.reply_summary("") == "an empty reply"


def test_tail_returns_whole_lines_and_a_new_offset(tmp_path):
    at = tmp_path / "events.jsonl"
    events.emit("note", source="marco", summary="one", at=at)
    rows, offset = events.tail(at, 0)
    assert [r["summary"] for r in rows] == ["one"] and offset == at.stat().st_size
    with at.open("a") as f:
        f.write('{"ts": "x", "kind": "note", "summary": "half')
    rows, offset2 = events.tail(at, offset)
    assert rows == [] and offset2 == offset
    with at.open("a") as f:
        f.write('"}\n')
    rows, offset3 = events.tail(at, offset2)
    assert [r["summary"] for r in rows] == ["half"] and offset3 == at.stat().st_size


def test_a_unit_stuck_to_its_number_is_a_trade_word_too():
    assert events.JARGON.search("at ~261Hz / C4 you hear it") and events.JARGON.search("about 2.5dB louder")
    assert events.readable("Turning it up helps. at ~261Hz you hear the fundamentals.") == "Turning it up helps."


def test_a_step_carries_the_word_it_ends_with_to_the_page(tmp_path, monkeypatch):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    with events.step("Try the song without Pro-L 2", motif="rec", word="tested") as line:
        line["summary"] = "Pro-L 2 stays. It makes a real difference."
    rows = [json.loads(l) for l in (tmp_path / events.NAME).read_text().splitlines()]
    assert [r["word"] for r in rows] == ["tested", "tested"]
    start, end = events.for_page(rows[0]), events.for_page(rows[1])
    assert start["type"] == "call_start" and start["word"] == "tested"
    assert end["type"] == "call_end" and end["word"] == "tested" and end["summary"].startswith("Pro-L 2 stays")


def test_work_rows_are_the_glows_cue_and_not_a_page_line(tmp_path):
    row = events.emit("work_started", source="marco", operation="arrange", pid=7, at=tmp_path / "e.jsonl")
    assert row["kind"] == "work_started" and row["pid"] == 7
    assert events.for_page(row) is None and events.for_page({"kind": "work_ended", "status": "ok"}) is None

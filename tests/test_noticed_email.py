"""An email he finds on his own takes him off standby: the Now line is the macro, the moment its detail (Owner
2026-11-04). Every name here is made up."""

import json

from hiremarco import events
from hiremarco.server import NOTICED_EMAIL, NOTICED_HOLD_S, notice_email, on_standby
from hiremarco.studio.booth import WAITING

DATA = {"offer_id": "mail-m1", "kind": "table", "who": "Dana Reyes", "subject": "Dinner Thursday?", "says": "a body"}


def rows(at):
    return [json.loads(line) for line in at.read_text().splitlines() if line.strip()]


def headlines(at):
    return [r["plain"] for r in rows(at) if r.get("plain")]


def test_standby_takes_the_email_headline_then_returns(tmp_path):
    at, waits = tmp_path / "events.jsonl", []
    events.emit("stage", source="marco", operation="waiting", plain=WAITING, at=at)
    assert notice_email(DATA, at=at, later=lambda s, f: waits.append((s, f)))
    assert headlines(at)[-1] == NOTICED_EMAIL
    assert waits and waits[0][0] == NOTICED_HOLD_S
    waits[0][1]()
    assert headlines(at)[-1] == WAITING


def test_nothing_on_screen_in_the_middle_of_a_task(tmp_path):
    at = tmp_path / "events.jsonl"
    events.emit("work_started", source="marco", operation="flex_pass", pid=4242, at=at)
    events.emit("stage", source="marco", operation="flex pass", plain="Marco tunes the vocal.", at=at)
    assert not notice_email(DATA, at=at, alive=lambda pid: True, later=lambda s, f: None)
    assert headlines(at) == ["Marco tunes the vocal."]
    assert not [r for r in rows(at) if r["kind"] == "email_received"]


def test_a_task_that_ended_is_standby(tmp_path):
    at = tmp_path / "events.jsonl"
    events.emit("work_started", source="marco", operation="flex_pass", pid=4242, at=at)
    events.emit("work_ended", source="marco", operation="flex_pass", pid=4242, at=at)
    assert on_standby(rows(at), alive=lambda pid: True)
    assert on_standby([], alive=lambda pid: True)


def test_a_job_that_died_without_its_last_row_is_standby(tmp_path):
    at = tmp_path / "events.jsonl"
    events.emit("job_started", source="marco", operation="Mastering the song", pid=4242, at=at)
    assert not on_standby(rows(at), alive=lambda pid: True)
    assert on_standby(rows(at), alive=lambda pid: False)


def test_the_return_waits_if_something_else_took_the_headline(tmp_path):
    at, waits = tmp_path / "events.jsonl", []
    notice_email(DATA, at=at, later=lambda s, f: waits.append(f))
    events.emit("stage", source="marco", operation="record", plain="Marco rolls a take.", at=at)
    waits[0]()
    assert headlines(at)[-1] == "Marco rolls a take."


def test_the_moment_gives_who_and_what_only_with_mail_on(tmp_path, monkeypatch):
    at = tmp_path / "events.jsonl"
    notice_email(DATA, at=at, later=lambda s, f: None)
    assert not [r for r in rows(at) if r["kind"] == "email_received"]
    monkeypatch.setattr(events, "show_mail", lambda: True)
    notice_email(DATA, at=at, later=lambda s, f: None)
    mail = [r for r in rows(at) if r["kind"] == "email_received"]
    assert len(mail) == 1 and mail[0]["sender"] == "Dana Reyes" and mail[0]["subject"] == "Dinner Thursday?"
    assert "a body" not in json.dumps(mail[0])
    page = events.for_page(mail[0])
    assert page["from"] == "Dana Reyes" and NOTICED_EMAIL not in json.dumps(page)   # the moment never echoes the headline

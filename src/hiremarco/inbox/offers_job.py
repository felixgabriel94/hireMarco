"""The offers job: a direct email becomes one WhatsApp to Felix, an offer to help or a heads-up (Owner 2026-11-02).

It runs apart from the sweep, on its own state file and budget line, so a fault here can't stop the inbox sorting. It
reads what the sweep labelled To Respond, newer than two days, and only reads: it adds no label and moves nothing. Mail
from Felix, mail he already answered and mail it already read are skipped; one message per email, eight a day at most.

It holds no WhatsApp key. It hands each offer, signed, to the Mini's relay on a loopback-only port, which wakes the
MacBook if it must and passes it to serve; "delivered" means serve accepted it. Between 11 pm and 8 am New York time
nothing is read and nothing is handed off, so nothing wakes the MacBook, and what waits goes after 8, unless
HIREMARCO_OFFER_QUIET_HOURS is off. A failed handoff is
tried three times quickly, then at most hourly, twelve attempts a day in all, and given up after 24 hours.

Its log carries counts and ids, never a sender, a subject or a body. The kill switch is checked by the caller before
this state opens.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from hiremarco import config, events, gate
from hiremarco.joblog import JobLog, JobRow
from hiremarco.offer import (HEADER_OFFER, HEADER_SIGNATURE, HEADER_TIME, READ_JOB, Place, Reading, offer_line,
                             read_email, sign)

NEW_YORK = ZoneInfo("America/New_York")
QUIET_FROM, QUIET_UNTIL = 23, 8
QUERY = "label:to-respond newer_than:2d -from:me -in:sent -in:drafts -in:spam -in:trash"
DAILY_MESSAGES = 8
DAILY_ATTEMPTS = 12
QUICK_TRIES, QUICK_NAP_S = 3, 3.0
RETRY_EVERY = timedelta(hours=1)
GIVE_UP_AFTER = timedelta(hours=24)
CAP_USD = 1.0  # a day, on this job's own line, far under the gate's cap for everything
RELAY = "http://127.0.0.1:8789"

SQL = """
create table if not exists read (message_id text primary key, offer_id text not null, kind text not null,
                                 status text not null, payload text not null default '', read_at text not null,
                                 day text not null, done_at text);
create table if not exists attempts (ts text not null, day text not null, offer_id text not null, code integer not null);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = path or config.STATE_DIR / "inbox-offers.sqlite"
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SQL)
    return conn


def quiet_hours_on() -> bool:
    """HIREMARCO_OFFER_QUIET_HOURS=off lifts the overnight hold, in the process or the env file (Owner 2026-11-02: to
    test at night). Off, a run reads and hands off at any hour and wakes the MacBook if it must; its log says so."""
    return (config.get("HIREMARCO_OFFER_QUIET_HOURS") or "").strip().lower() != "off"


def quiet(now: datetime) -> bool:
    hour = now.astimezone(NEW_YORK).hour
    return hour >= QUIET_FROM or hour < QUIET_UNTIL


def handoff(payload: dict, *, url: str | None = None, token: str | None = None, transport=None) -> int:
    """POST one signed offer. The status code, 0 when nothing answered; the caller keeps no body."""
    token = token or config.require("HIREMARCO_OFFER_TOKEN")
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    stamp = str(int(time.time()))
    # the relay can take its wake ceiling, then serve its turn
    with httpx.Client(timeout=httpx.Timeout(100.0, connect=5.0), transport=transport, trust_env=False) as http:
        try:
            return http.post(f"{url or config.get('HIREMARCO_OFFER_RELAY') or RELAY}/internal/offer", content=body,
                             headers={"content-type": "application/json", HEADER_TIME: stamp,
                                      HEADER_OFFER: payload["offer_id"],
                                      HEADER_SIGNATURE: sign(token, stamp, payload["offer_id"], body)}).status_code
        except httpx.HTTPError:
            return 0


def _messages_today(conn, day: str) -> int:
    (n,) = conn.execute("select count(*) from read where day = ? and kind in ('table', 'reply', 'heads_up')",
                        (day,)).fetchone()
    return n


def _note(conn, message_id: str, reading_kind: str, status: str, payload: str, now: datetime) -> None:
    conn.execute("insert or ignore into read (message_id, offer_id, kind, status, payload, read_at, day)"
                 " values (?, ?, ?, ?, ?, ?, ?)", (message_id, f"mail-{message_id}", reading_kind, status, payload,
                                                   now.isoformat(), now.astimezone(NEW_YORK).date().isoformat()))
    conn.commit()


def read_new(mail, client, conn, places: list[Place], *, now: datetime, joblog: JobLog, dry_run: bool, limit: int,
             counts: dict) -> list[Reading]:
    """Read what is new, once each. A dry run records nothing. Stops at the message cap, the budget, or a gate refusal;
    what it did not reach waits for the next run while it is still in the query's two days."""
    from hiremarco import inbox

    local = now.astimezone(NEW_YORK).date()
    own, found = mail.own_address().lower(), []
    skip_body = lambda sender, name, subject: bool(inbox.SENSITIVE.search(f"{sender} {name} {subject}"))  # noqa: E731
    for message_id in mail.search(QUERY, limit=limit):
        if conn.execute("select 1 from read where message_id = ?", (message_id,)).fetchone():
            continue
        sent = _messages_today(conn, local.isoformat()) + (len(found) if dry_run else 0)
        if sent >= DAILY_MESSAGES:
            counts["capped"] = f"{DAILY_MESSAGES} messages today"
            break
        if joblog.total_usd(local.isoformat(), READ_JOB) >= CAP_USD:
            counts["capped"] = f"{CAP_USD:.2f} USD today on this job"
            break
        item = mail.item(message_id, skip_body)
        if item.sender == own:
            counts["his own"] = counts.get("his own", 0) + 1
            if not dry_run:
                _note(conn, message_id, "skip", "his own", "", now)
            continue
        if mail.replied(message_id):
            counts["answered"] = counts.get("answered", 0) + 1
            if not dry_run:
                _note(conn, message_id, "skip", "answered", "", now)
            continue
        if not dry_run and events.show_mail() and not skip_body(item.sender, getattr(item, "name", ""), getattr(item, "subject", "")):
            # the screen shows who and what, never the body, and only while the Owner has it on for a shot
            events.emit("email_received", source="marco", status="ok", via="Gmail", sender=getattr(item, "name", "") or "an email",
                        subject=getattr(item, "subject", ""))
        try:
            reading = read_email(item, client, places, today=local)
        except gate.Refused as refused:
            counts["capped"] = refused.reason
            break
        counts["read"] = counts.get("read", 0) + 1
        if reading is None:
            counts["unread"] = counts.get("unread", 0) + 1
            continue
        if reading.kind == "none":
            counts["nothing to offer"] = counts.get("nothing to offer", 0) + 1
        else:
            found.append(reading)
        if not dry_run:
            _note(conn, message_id, reading.kind, "none" if reading.kind == "none" else "waiting",
                  "" if reading.kind == "none" else json.dumps(reading.payload(), ensure_ascii=False), now)
    return found


def _may_try(conn, now: datetime, counts: dict) -> int:
    """How many tries this run may make for the next offer: 0 while the last failure is under an hour old."""
    day = now.astimezone(NEW_YORK).date().isoformat()
    (used,) = conn.execute("select count(*) from attempts where day = ?", (day,)).fetchone()
    if used >= DAILY_ATTEMPTS:
        counts["attempt ceiling"] = DAILY_ATTEMPTS
        return 0
    last = conn.execute("select ts, code from attempts order by rowid desc limit 1").fetchone()
    failing = last is not None and not 200 <= last[1] < 300
    if failing and now - datetime.fromisoformat(last[0]) < RETRY_EVERY:
        counts["waiting to retry"] = True
        return 0
    return min(1 if failing else QUICK_TRIES, DAILY_ATTEMPTS - used)


def hand_over(conn, mail, post: Callable[[dict], int], *, now: datetime, nap: Callable[[float], None], counts: dict) -> None:
    """Every offer still waiting, oldest first. The relay or the MacBook failing is the same for the next one, so the
    first failure ends the run; the hour between retries holds for all of them."""
    rows = conn.execute("select message_id, offer_id, payload, read_at from read where status = 'waiting'"
                        " order by read_at").fetchall()
    day = now.astimezone(NEW_YORK).date().isoformat()
    for at, (message_id, offer_id, payload, read_at) in enumerate(rows):
        if now - datetime.fromisoformat(read_at) > GIVE_UP_AFTER:
            conn.execute("update read set status = 'gave up', done_at = ? where message_id = ?", (now.isoformat(), message_id))
            conn.commit()
            counts["gave up"] = counts.get("gave up", 0) + 1
            continue
        if mail.replied(message_id):  # he answered it himself while it waited
            conn.execute("update read set status = 'answered', done_at = ? where message_id = ?", (now.isoformat(), message_id))
            conn.commit()
            counts["answered"] = counts.get("answered", 0) + 1
            continue
        tries = _may_try(conn, now, counts)
        delivered = False
        for n in range(tries):
            code = post(json.loads(payload))
            conn.execute("insert into attempts (ts, day, offer_id, code) values (?, ?, ?, ?)",
                         (now.isoformat(), day, offer_id, code))
            conn.commit()
            counts["last code"] = code
            if 200 <= code < 300:
                delivered = True
                break
            if n + 1 < tries:
                nap(QUICK_NAP_S)
        if not delivered:
            counts["waiting"] = len(rows) - at
            return
        conn.execute("update read set status = 'delivered', done_at = ? where message_id = ?", (now.isoformat(), message_id))
        conn.commit()
        counts["delivered"] = counts.get("delivered", 0) + 1


def run(mail, client, conn, *, places: list[Place], post: Callable[[dict], int] | None = None,
        now: datetime | None = None, dry_run: bool = False, nap: Callable[[float], None] = time.sleep,
        joblog: JobLog | None = None, limit: int = 50) -> tuple[dict, list[dict]]:
    """One pass. (counts, what a dry run would hand off). A dry run ignores the quiet hours, says it would have held,
    records nothing and sends nothing."""
    now = now or datetime.now(timezone.utc)
    joblog = joblog or JobLog()
    counts: dict = {}
    if quiet(now) and not quiet_hours_on():
        counts["quiet hours off"] = True
    elif quiet(now):
        if not dry_run:
            return {"quiet hours": True}, []
        counts["quiet hours, would hold until 8 am"] = True
    readings = read_new(mail, client, conn, places, now=now, joblog=joblog, dry_run=dry_run, limit=limit, counts=counts)
    if dry_run:
        out = []
        for r in readings:
            kind, line = offer_line(r.payload(), places)
            out.append({"id": r.message_id, "read_as": r.kind, "kind": kind, "line": line})
        return counts, out
    hand_over(conn, mail, post or handoff, now=now, nap=nap, counts=counts)
    joblog.append(JobRow(job=READ_JOB, ok="waiting" not in counts, note=summary(counts)))
    return counts, []


def summary(counts: dict) -> str:
    return ", ".join(k if v is True else f"{k} {v}" for k, v in counts.items()) or "nothing new"

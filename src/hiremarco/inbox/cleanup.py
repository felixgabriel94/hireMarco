"""The inbox cleanup: unsubscribe from and trash the senders the Owner marked, and nothing else.

Owner 2026-10-31: "I want to clean contact@felixgabriel.com up." The marked list is a CSV (sender, suggested),
confirmed by its sha256 on the command line, so a list nobody confirmed does nothing. For a sender marked
Unsubscribe or Unsubscribe and trash, Marco uses the sender's one-click unsubscribe (RFC 8058: a POST of
"List-Unsubscribe=One-Click" to its https link) through the gate's ``unsubscribe`` switch. A sender with no
one-click link (a web page, an email address, or nothing) is put on Marco's auto-trash list instead (a list on Felix's
Mac, nothing is set in Gmail), and the inbox sort moves its new mail to Trash on arrival; the web-page ones are listed for Felix. For Unsubscribe and trash, the
sender's mail moves to Gmail's Trash (Gmail empties it after 30 days; Marco never deletes for good), except
starred mail and anything that looks like an order, receipt, invoice, shipping or booking confirmation (the
receipt guard). A sender marked "Trash all but the latest" (Owner 2026-10-31, for Sezzle's billing notices) keeps
only its newest email; nothing is sent to it. Every unsubscribe and every move is logged; ``undo`` takes the moved
mail back out of Trash.
"""

from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import httpx

from hiremarco import config, gate

TENANT = "owner"
SQL = """
create table if not exists cleanup (id integer primary key, ts text not null, sender text not null,
                                    action text not null, message_id text, detail text not null default '',
                                    undone integer not null default 0);
create table if not exists blocked (sender text primary key, how text not null, ts text not null);
"""
# what the receipt guard keeps: any of these words in the subject (as a Gmail search, and as a pattern)
GUARD = ("receipt", "invoice", "order", "shipped", "shipping", "delivered", "delivery", "confirmation", "confirmed",
         "booking", "reservation", "payment", "refund", "ticket", "itinerary")
GUARD_QUERY = " ".join(f"-subject:{w}" for w in GUARD)
GUARD_WORDS = re.compile(r"\b(" + "|".join(GUARD) + r")\b", re.I)


def guarded(subject: str) -> bool:
    return bool(GUARD_WORDS.search(subject or ""))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = path or config.STATE_DIR / "cleanup.sqlite"
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SQL)
    return conn


def plan_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_plan(path: Path) -> list[tuple[str, str]]:
    """(sender, action) for every sender marked Unsubscribe or Unsubscribe and trash; the rest is left alone."""
    out = []
    with Path(path).open(newline="") as f:
        for row in csv.DictReader(f):
            action = (row.get("suggested") or "").strip()
            sender = (row.get("sender") or "").strip().lower()
            if action in ("Unsubscribe", "Unsubscribe and trash", "Trash all but the latest") and "@" in sender:
                out.append((sender, action))
    return out


def _log(conn, sender, action, message_id=None, detail=""):
    conn.execute("insert into cleanup (ts, sender, action, message_id, detail) values (?, ?, ?, ?, ?)",
                 (datetime.now(timezone.utc).isoformat(), sender, action, message_id, detail[:200]))
    conn.commit()


def one_click(headers: dict[str, str]) -> str:
    """The sender's one-click unsubscribe link, when it offers one (RFC 8058), else empty."""
    if "one-click" not in headers.get("list-unsubscribe-post", "").lower():
        return ""
    links = re.findall(r"<(https://[^>]+)>", headers.get("list-unsubscribe", ""))
    return links[0] if links else ""


def run(mail, plan_path: Path, confirm: str, conn: sqlite3.Connection, *, gate_conn=None, http=None,
        rules_path: Path | None = None, dry_run: bool = False) -> dict:
    """Carry out the confirmed plan (or only count it). Returns counts and the web links for Felix."""
    if confirm != plan_hash(plan_path):
        raise gate.Refused("the list's fingerprint doesn't match the one confirmed")
    http = http or httpx.Client(timeout=20, follow_redirects=False)
    gate_conn = gate_conn or gate.connect()
    done = {"one_click": 0, "unsubscribed": 0, "trashed": 0, "kept_by_guard": 0,
            "blocked": {"link": 0, "email": 0, "none": 0}, "for_felix": [], "skipped": 0}
    for sender, action in load_plan(plan_path):
        if action == "Trash all but the latest":  # by the Owner's word for this sender: no unsubscribe, no guard
            for message_id in mail.ids_from(sender, keep_starred=True)[1:]:  # Gmail lists newest first
                if not dry_run:
                    mail.trash(message_id)
                    _log(conn, sender, "trashed", message_id, "all but the latest")
                done["trashed"] += 1
                done["all_but_latest"] = done.get("all_but_latest", 0) + 1
            continue
        latest = mail.latest_from(sender)
        if latest is None:
            done["skipped"] += 1
            continue
        link = one_click(latest[1])
        if not link:  # nothing is sent: the sender goes on the auto-trash list, and a web link is listed for Felix
            listed = latest[1].get("list-unsubscribe", "")
            pages = re.findall(r"<(https://[^>]+)>", listed)
            how = "link" if pages else "email" if "mailto:" in listed else "none"
            done["blocked"][how] += 1
            if pages:
                done["for_felix"].append((sender, pages[0][:160]))
            if not dry_run:
                conn.execute("insert or ignore into blocked (sender, how, ts) values (?, ?, ?)",
                             (sender, how, datetime.now(timezone.utc).isoformat()))
                conn.commit()
        else:
            done["one_click"] += 1
            if not dry_run:
                def post(link=link):
                    response = http.post(link, data={"List-Unsubscribe": "One-Click"})
                    if response.status_code >= 400:
                        raise RuntimeError(f"HTTP {response.status_code}")
                    return response.status_code
                try:
                    code = gate.execute_effect(gate_conn, post, tenant_id=TENANT, idempotency_key=f"unsub:{sender}",
                                               capability="unsubscribe", channel="unsubscribe", target="*",
                                               message=f"one-click unsubscribe from {sender}",
                                               department="assistant", rules_path=rules_path)
                    _log(conn, sender, "unsubscribed", detail=f"HTTP {code}")
                    done["unsubscribed"] += 1
                except gate.Refused as refused:
                    if "already done" not in refused.reason:
                        raise
                    # a rerun after a stop: this sender was unsubscribed the first time
                    done["already"] = done.get("already", 0) + 1
                except Exception as exc:  # their link failed: on the auto-trash list instead, nothing else changes
                    conn.execute("insert or ignore into blocked (sender, how, ts) values (?, ?, ?)",
                                 (sender, "one-click failed", datetime.now(timezone.utc).isoformat()))
                    conn.commit()
                    _log(conn, sender, "unsubscribe failed", detail=type(exc).__name__)
        if action == "Unsubscribe and trash":
            every = mail.ids_from(sender, keep_starred=True)
            movable = mail.ids_from(sender, keep_starred=True, exclude=GUARD_QUERY)
            done["kept_by_guard"] += len(every) - len(movable)
            for message_id in movable:
                if not dry_run:
                    try:
                        mail.trash(message_id)
                    except RuntimeError as exc:  # one email Gmail won't move: logged and left, the run goes on
                        _log(conn, sender, "not moved", message_id, str(exc))
                        done["not_moved"] = done.get("not_moved", 0) + 1
                        continue
                    _log(conn, sender, "trashed", message_id)
                done["trashed"] += 1
    return done


def blocked(conn: sqlite3.Connection, sender: str) -> bool:
    return conn.execute("select 1 from blocked where sender = ?", (sender.lower(),)).fetchone() is not None


def trash_blocked(mail, conn: sqlite3.Connection, items) -> list[str]:
    """New mail from a sender on the auto-trash list goes to Trash on arrival, receipts and Watch senders excepted;
    logged for undo. Costs no model call. Returns the ids moved."""
    from hiremarco.inbox import WATCH

    moved = []
    for item in items:
        if blocked(conn, item.sender) and not guarded(item.subject) and not WATCH.search(item.sender):
            mail.trash(item.id)
            _log(conn, item.sender, "trashed", item.id, "auto-trash list, on arrival")
            moved.append(item.id)
    return moved


WATCH_EXPIRY = ("label:Watch -is:starred is:read older_than:30d", "label:Watch -is:starred is:unread older_than:60d")


def expire_watch(mail, conn: sqlite3.Connection, limit: int = 100) -> int:
    """Watch mail past its time goes to Trash, logged for undo: read after 30 days, unread after 60, starred never
    (Owner 2026-11-01). Gmail's search is the clock: older_than counts from when the email arrived."""
    moved = 0
    for query in WATCH_EXPIRY:
        for message_id, sender in mail.found(query, limit=limit):
            mail.trash(message_id)
            _log(conn, sender, "trashed", message_id, "watch expiry")
            moved += 1
    return moved


# an appointment reminder is for the days before it: past that it is noise, and the upcoming ones stay (Owner 2026-11-01)
OLD_REMINDERS = ('{subject:"appointment reminder" subject:"appointment is coming up" subject:"upcoming appointment"}'
                 " -is:starred older_than:14d")


def expire_reminders(mail, conn: sqlite3.Connection, limit: int = 100) -> int:
    """Appointment reminders two weeks old go to Trash, logged for undo. Nothing newer is touched."""
    moved = 0
    for message_id, sender in mail.found(OLD_REMINDERS, limit=limit):
        mail.trash(message_id)
        _log(conn, sender, "trashed", message_id, "old appointment reminder")
        moved += 1
    return moved


def undo(mail, conn: sqlite3.Connection, sender: str | None = None) -> int:
    """Take the mail Marco moved to Trash back out (all of it, or one sender's)."""
    rows = conn.execute("select id, message_id from cleanup where action = 'trashed' and undone = 0"
                        + (" and sender = ?" if sender else ""), ((sender,) if sender else ())).fetchall()
    for row_id, message_id in rows:
        mail.untrash(message_id)
        conn.execute("update cleanup set undone = 1 where id = ?", (row_id,))
    conn.commit()
    return len(rows)

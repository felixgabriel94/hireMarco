"""What Marco and Felix said to each other on WhatsApp, kept on this Mac so Marco remembers yesterday.

Owner 2026-10-30: "I need him to remember even a conversation from yesterday." Every text in and out is one row in
the gate's own database (local state, never the repository); the brain reads the last rows back as the conversation.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SCHEMA = """
create table if not exists thread (
    id integer primary key autoincrement,
    ts text not null,
    who text not null,
    text text not null
);
"""
HOME = ZoneInfo("America/New_York")


def remember(conn: sqlite3.Connection, who: str, text: str, ts: datetime | None = None) -> None:
    """One line of the conversation: who is "felix" or "marco"."""
    text = (text or "").strip()
    if not text:
        return
    conn.executescript(SCHEMA)
    conn.execute("insert into thread (ts, who, text) values (?, ?, ?)",
                 ((ts or datetime.now(timezone.utc)).isoformat(), who, text))
    conn.commit()


def recall(conn: sqlite3.Connection, limit: int = 40) -> list[tuple[datetime, str, str]]:
    """The last ``limit`` lines, oldest first, whatever day they were said."""
    conn.executescript(SCHEMA)
    rows = conn.execute("select ts, who, text from thread order by id desc limit ?", (limit,)).fetchall()
    return [(datetime.fromisoformat(ts), who, text) for ts, who, text in reversed(rows)]


def when(ts: datetime) -> str:
    """A time as he would say it, in New York time: "Thu Oct 30, 10:12 pm"."""
    local = ts.astimezone(HOME)
    return local.strftime("%a %b %-d, %-I:%M ") + local.strftime("%p").lower()

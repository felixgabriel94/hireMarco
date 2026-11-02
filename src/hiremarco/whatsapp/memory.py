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
    """A time as Marco writes it, in New York time: "Thu Oct 30, 10:12pm"."""
    from hiremarco.style import clock_time

    local = ts.astimezone(HOME)
    return f"{local.strftime('%a %b %-d')}, {clock_time(local.hour, local.minute)}"


def note_words(conn: sqlite3.Connection, message_id: str, said: str) -> None:
    """His words under their message id, so a later question can point at the exact message."""
    conn.execute("create table if not exists his_words (wa_message_id text primary key, ts text not null, said text not null)")
    conn.execute("insert or ignore into his_words (wa_message_id, ts, said) values (?, ?, ?)",
                 (message_id, datetime.now(timezone.utc).isoformat(), said))
    conn.commit()


def earlier_words(conn: sqlite3.Connection, but: str, limit: int = 6) -> dict[str, tuple[str, str]]:
    """His last messages before this one, by a short ref the brain can name: {"a": (message id, words)}, oldest first."""
    conn.execute("create table if not exists his_words (wa_message_id text primary key, ts text not null, said text not null)")
    rows = conn.execute("select wa_message_id, said from his_words where wa_message_id != ? order by ts desc limit ?",
                        (but, limit)).fetchall()
    return {"abcdef"[n]: row for n, row in enumerate(reversed(rows))}


def note_sent(conn: sqlite3.Connection, message_id: str, said: str) -> None:
    """What Marco sent under its message id, so a message of his that Felix quotes can be read back."""
    if not message_id:
        return
    conn.execute("create table if not exists marco_words (wa_message_id text primary key, ts text not null, said text not null)")
    conn.execute("insert or ignore into marco_words (wa_message_id, ts, said) values (?, ?, ?)",
                 (message_id, datetime.now(timezone.utc).isoformat(), said))
    conn.commit()


def quoted_words(conn: sqlite3.Connection, message_id: str) -> tuple[str, str] | None:
    """(who, words) for a message Felix quoted; None for one sent before these were kept."""
    conn.execute("create table if not exists marco_words (wa_message_id text primary key, ts text not null, said text not null)")
    conn.execute("create table if not exists his_words (wa_message_id text primary key, ts text not null, said text not null)")
    for who, table in (("marco", "marco_words"), ("felix", "his_words")):
        row = conn.execute(f"select said from {table} where wa_message_id = ?", (message_id,)).fetchone()
        if row:
            return who, row[0]
    return None

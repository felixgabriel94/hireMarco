"""What Felix has told Marco that lasts: his words, dated, kept on this Mac, his to list and to forget.

Owner 2026-10-30: a mini version of the product's memory. Only what Felix stated goes in, never a guess; each fact
carries when he said it. Before each reply, the facts most related to what he just said go to the brain inside a
small budget, the way the product pushes a facts block before each turn. "Forget that" marks a fact forgotten, so
the record stays and the brain stops reading it.
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import datetime, timezone

from hiremarco.whatsapp.memory import when

SCHEMA = """
create table if not exists facts (
    id integer primary key autoincrement,
    ts text not null,
    text text not null,
    forgotten text
);
"""
BUDGET_TOKENS = 400
WORD = re.compile(r"[\w']+")


def _words(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text) if len(w) > 2}


def _tokens(text: str) -> int:
    return math.ceil(len(text.split()) * 1.3)


def keep(conn: sqlite3.Connection, text: str, ts: datetime | None = None) -> bool:
    """One fact in Felix's words. False when the same words are already kept."""
    text = " ".join((text or "").split()).strip(" .")
    if not text:
        return False
    conn.executescript(SCHEMA)
    if conn.execute("select 1 from facts where lower(text) = lower(?) and forgotten is null", (text,)).fetchone():
        return False
    conn.execute("insert into facts (ts, text) values (?, ?)", ((ts or datetime.now(timezone.utc)).isoformat(), text))
    conn.commit()
    return True


def forget(conn: sqlite3.Connection, about: str, ts: datetime | None = None) -> list[str]:
    """Facts that share most of their words with ``about`` are marked forgotten, never deleted; the texts marked."""
    conn.executescript(SCHEMA)
    wanted = _words(about)
    if not wanted:
        return []
    gone = []
    for fid, text in conn.execute("select id, text from facts where forgotten is null").fetchall():
        have = _words(text)
        if have and len(wanted & have) / min(len(wanted), len(have)) >= 0.6:
            conn.execute("update facts set forgotten = ? where id = ?",
                         ((ts or datetime.now(timezone.utc)).isoformat(), fid))
            gone.append(text)
    conn.commit()
    return gone


def known(conn: sqlite3.Connection) -> list[tuple[datetime, str]]:
    """Every fact still remembered, oldest first."""
    conn.executescript(SCHEMA)
    return [(datetime.fromisoformat(ts), text)
            for ts, text in conn.execute("select ts, text from facts where forgotten is null order by id").fetchall()]


def block(conn: sqlite3.Connection, question: str = "", budget_tokens: int = BUDGET_TOKENS) -> list[str]:
    """The facts for this turn: ranked by the words they share with ``question`` (ties: newest first), as many as fit
    the budget, each with the day it was said."""
    asked = _words(question)
    ranked = sorted(known(conn), key=lambda f: (-len(asked & _words(f[1])), -f[0].timestamp()))
    out, used = [], 0
    for ts, text in ranked:
        line = f"{when(ts)}: {text}"
        cost = _tokens(line)
        if used + cost > budget_tokens:
            continue
        out.append(line)
        used += cost
    return out

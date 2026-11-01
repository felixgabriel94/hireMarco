"""Offer calls: Marco asks on WhatsApp whether to call a place, and the Owner's yes places that one call.

Before dialing, Marco asks once on WhatsApp for the fallbacks (Owner 2026-10-31: everything he may need, asked
before the call, never during it): another day or time if the slot is gone, indoor or patio, a card hold by link,
anything else to tell them. One reply answers them all; "whatever works" stands as flexible.

Owner 2026-10-31: "Yes to his offer calls." The offer names the place, the day, the time and the party ("Want me
to call Corner Bistro to book Thursday at eight for four?"), so his yes is to one exact call. The offer waits in
``offers.sqlite`` in the state folder. A yes within ``YES_WINDOW`` of the offer accepts it once; the brief is
built from the offer and the profile, and a gap is asked about on WhatsApp before dialing, never mid-call. The
place's number comes only from the private places file. The gate lets the call through the ``places`` switch
only with the accepted offer as its evidence. After the call, one WhatsApp tells him how it went.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hiremarco import config
from hiremarco.calls import brief as briefs
from hiremarco.offer import NUMBER_WORDS, Place, load_places

YES_WINDOW = timedelta(minutes=30)
POLL_S, POLL_MAX_S = 15.0, 420.0

SCHEMA = """
create table if not exists offers (
    id integer primary key,
    offered_at text not null,
    place_id text not null,
    weekday text not null,
    day text not null,
    hour integer not null,
    party_size integer not null,
    occasion text not null default '',
    status text not null,
    accepted_at text,
    fallbacks text not null default ''
);
"""


@dataclass(frozen=True)
class CallOffer:
    id: int
    offered_at: datetime
    place_id: str
    weekday: str
    day: str
    hour: int
    party_size: int
    occasion: str
    status: str
    accepted_at: datetime | None = None
    fallbacks: str = ""

    def clock(self) -> str:
        hour = self.hour - 12 if self.hour > 12 else self.hour
        return NUMBER_WORDS.get(hour, str(hour))

    def text(self, place: Place) -> str:
        party = NUMBER_WORDS.get(self.party_size, str(self.party_size))
        return f"Want me to call {place.name} to book {self.weekday.capitalize()} at {self.clock()} for {party}?"

    def evidence(self, place: Place) -> dict:
        """What the gate checks for the places switch: this offer, its place's number, when it was offered and taken."""
        return {"offer_id": self.id, "place_name": place.name, "place_phone": place.phone.lstrip("+"),
                "offered_at": self.offered_at, "accepted_at": self.accepted_at}


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = path or config.STATE_DIR / "offers.sqlite"
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def _row(r) -> CallOffer:
    return CallOffer(r[0], datetime.fromisoformat(r[1]), r[2], r[3], r[4], r[5], r[6], r[7], r[8],
                     datetime.fromisoformat(r[9]) if r[9] else None, r[10] or "")


def record_offer(conn: sqlite3.Connection, place: Place, *, weekday: str, day: str, hour: int, party_size: int,
                 occasion: str = "", now: datetime | None = None) -> CallOffer:
    now = now or datetime.now(timezone.utc)
    # a newer offer replaces any still pending, so a yes answers the latest question only
    conn.execute("update offers set status = 'replaced' where status = 'pending'")
    cur = conn.execute(
        "insert into offers (offered_at, place_id, weekday, day, hour, party_size, occasion, status)"
        " values (?, ?, ?, ?, ?, ?, ?, 'pending')",
        (now.isoformat(), place.id, weekday.lower(), day, hour, party_size, occasion))
    conn.commit()
    return get(conn, cur.lastrowid)


def get(conn: sqlite3.Connection, offer_id: int) -> CallOffer:
    return _row(conn.execute("select * from offers where id = ?", (offer_id,)).fetchone())


def pending(conn: sqlite3.Connection, now: datetime | None = None) -> CallOffer | None:
    """The latest offer still waiting for his word, and only inside the yes window."""
    now = now or datetime.now(timezone.utc)
    r = conn.execute("select * from offers where status = 'pending' order by id desc limit 1").fetchone()
    if r is None:
        return None
    offer = _row(r)
    return offer if now - offer.offered_at <= YES_WINDOW else None


def asking(conn: sqlite3.Connection, now: datetime | None = None) -> CallOffer | None:
    """The offer whose fallback questions are waiting for his one reply, inside the yes window."""
    now = now or datetime.now(timezone.utc)
    r = conn.execute("select * from offers where status = 'questions' order by id desc limit 1").fetchone()
    if r is None:
        return None
    offer = _row(r)
    return offer if now - offer.offered_at <= YES_WINDOW else None


QUESTIONS = ("1. If Thursday at eight is gone, what other day or time works?",
             "2. Indoor or patio, or either?",
             "3. If they want a card to hold it, is a link to you OK?",
             "4. Any allergies, an occasion, or anything else to tell them?")
FLEXIBLE = re.compile(r"\b(whatever works|anything works|either|flexible|up to you|you decide|any)\b", re.I)


def questions_text(offer: CallOffer) -> str:
    first = QUESTIONS[0].replace("Thursday at eight", f"{offer.weekday.capitalize()} at {offer.clock()}")
    return "Before I call, a few quick ones (one reply is fine):\n" + "\n".join((first,) + QUESTIONS[1:])


def ask_fallbacks(conn: sqlite3.Connection, offer: CallOffer) -> None:
    conn.execute("update offers set status = 'questions' where id = ? and status = 'pending'", (offer.id,))
    conn.commit()


def record_fallbacks(conn: sqlite3.Connection, offer: CallOffer, said: str) -> CallOffer:
    words = " ".join((said or "").split())
    stored = f"flexible ({words})" if FLEXIBLE.search(words) and len(words.split()) <= 4 else words
    conn.execute("update offers set fallbacks = ? where id = ?", (stored, offer.id))
    conn.commit()
    return get(conn, offer.id)


def accept(conn: sqlite3.Connection, offer: CallOffer, now: datetime | None = None) -> CallOffer | None:
    """Mark the offer taken, once. None when it was already taken or is no longer waiting."""
    now = now or datetime.now(timezone.utc)
    cur = conn.execute("update offers set status = 'accepted', accepted_at = ? where id = ?"
                       " and status in ('pending', 'questions')", (now.isoformat(), offer.id))
    conn.commit()
    return get(conn, offer.id) if cur.rowcount == 1 else None


def set_status(conn: sqlite3.Connection, offer_id: int, status: str) -> None:
    conn.execute("update offers set status = ? where id = ?", (status, offer_id))
    conn.commit()


def place_for(offer: CallOffer, places: list[Place] | None = None) -> Place | None:
    return next((p for p in (places if places is not None else load_places()) if p.id == offer.place_id), None)


def brief_for(offer: CallOffer) -> dict[str, str]:
    """The reservation brief from the offer itself; the profile fills the standing facts."""
    given = {"party_size": str(offer.party_size), "date": f"{offer.weekday.capitalize()} ({offer.day})",
             "time": f"{offer.clock()} pm" if offer.hour >= 12 else f"{offer.clock()} am",
             "occasion": offer.occasion or "none"}
    if offer.fallbacks:
        given["fallbacks"] = offer.fallbacks
        # his one reply answers the window, the seating and the requests the profile leaves open (live 2026-10-31:
        # the profile had none of them, Marco asked for them first, and the answer went to plain chat)
        standing = briefs.load_profile()
        for field in ("time_window", "seating", "special_requests"):
            if not standing.get(field):
                given[field] = "see Felix's fallbacks below"
    return given


def ask_for_gaps(gap: briefs.BriefIncomplete) -> str:
    """The question he gets on WhatsApp before any dialing, when the brief has a gap."""
    wanted = ", ".join(briefs.LABELS.get(k, k.replace("_", " ")) for k in gap.missing)
    return f"Before I call, I need: {wanted}."


def outcome(data: dict) -> tuple[str, str]:
    """How a call went, from Marco's own last words: booked, waitlisted or nothing settled, and that line."""
    said = [str(t.get("message") or "").strip() for t in data.get("transcript") or [] if t.get("role") == "agent"]
    said = [s for s in said if s]
    last = said[-1] if said else ""
    words = " ".join(said[-3:]).lower()
    if re.search(r"waitlist|wait list|adding us|cancellation", words):
        kind = "waitlisted"
    elif re.search(r"see you", last.lower()):
        kind = "booked"
    else:
        kind = "nothing settled"
    return kind, last


def result_text(place: Place, offer: CallOffer, data: dict, off_brief: str) -> str:
    status = data.get("status")
    if status != "done":
        return f"The call to {place.name} didn't go through. Want me to try again later?"
    kind, last = outcome(data)
    lead = {"booked": f"Booked: {place.name}, {offer.weekday.capitalize()} at {offer.clock()} for {offer.party_size}.",
            "waitlisted": f"{place.name} was full; you're on their waitlist for {offer.weekday.capitalize()}.",
            "nothing settled": f"Nothing settled with {place.name}."}[kind]
    text = lead + (f' He closed with: "{last}"' if last else "")
    if off_brief:
        text += " They also asked: " + "; ".join(line.strip() for line in off_brief.splitlines() if line.strip()) + "."
    return re.sub(r"\+?\d[\d ()-]{7,}\d", lambda m: "..." + re.sub(r"\D", "", m.group())[-4:], text)


def wait_for_result(fetch: Callable[[], dict], sleep=time.sleep, poll_s: float = POLL_S,
                    max_s: float = POLL_MAX_S) -> dict:
    """The conversation once it is done or failed, or the last state seen when the wait runs out."""
    waited, data = 0.0, {}
    while waited <= max_s:
        data = fetch()
        if data.get("status") in ("done", "failed"):
            return data
        sleep(poll_s)
        waited += poll_s
    return data


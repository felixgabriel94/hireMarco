"""Offer calls: Marco asks on WhatsApp whether to call a place, and the Owner's yes places that one call.

Before dialing, Marco asks once on WhatsApp for the fallbacks (Owner 2026-10-31: everything he may need, asked
before the call, never during it): another day or time if the slot is gone, indoor or patio, a card hold by link,
anything else to tell them. One reply answers them all; "whatever works" stands as flexible.

Owner 2026-10-31: "Yes to his offer calls." The offer names the place, the day, the time and the party ("Want me
to call Corner Bistro to book Thursday at 8pm for four?"), so his yes is to one exact call. The offer waits in
``offers.sqlite`` in the state folder. A yes within ``YES_WINDOW`` of the offer accepts it once; the brief is
built from the offer and the profile, and a gap is asked about on WhatsApp before dialing, never mid-call. The
place's number comes only from the private places file. The gate lets the call through the ``places`` switch
only with the accepted offer as its evidence. After the call, one WhatsApp tells him how it went.

Owner 2026-11-02: an email can start an offer too, of three kinds: table (the flow above), reply (his yes, then what to
say, then the outbox's draft and his "send") and heads_up (nothing to accept: it never takes a yes away from a table or a
reply). A message WhatsApp's window refuses is held, and goes out after his next text if it is under a day old. In the
booth, Marco says one short line about it after a take, once; a spoken yes counts as the yes to that exact text.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from hiremarco import config
from hiremarco.calls import brief as briefs
from hiremarco.offer import MIAMI, NUMBER_WORDS, Place, load_places
from hiremarco.style import clock_time, times_settled_on

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

EMAIL_COLUMNS = {"kind": "text not null default 'table'", "offer_key": "text", "source_id": "text",
                 "who": "text not null default ''", "message": "text not null default ''",
                 "yes_by": "text not null default ''", "texted_at": "text", "spoken_at": "text",
                 "minute": "integer not null default 0", "asked_id": "text",
                 "message_ids": "text not null default ''"}
HOLD_MAX = timedelta(hours=24)


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
    kind: str = "table"
    offer_key: str | None = None
    source_id: str | None = None
    who: str = ""
    message: str = ""
    yes_by: str = ""
    texted_at: datetime | None = None
    spoken_at: datetime | None = None
    minute: int = 0
    asked_id: str | None = None  # the message of his that said yes: its result quotes it
    message_ids: str = ""        # Marco's messages about this offer: what he can quote to point at it

    def clock(self) -> str:
        """The time as he reads it: 8pm, 8:30pm, noon."""
        return clock_time(self.hour, self.minute)

    def spoken_clock(self) -> str:
        """The time for the call's brief, which the voice says aloud: unchanged by how a time is written."""
        hour = self.hour - 12 if self.hour > 12 else self.hour
        words = NUMBER_WORDS.get(hour, str(hour))
        return f"{words} {self.minute:02d}" if self.minute else words

    def text(self, place: Place) -> str:
        party = NUMBER_WORDS.get(self.party_size, str(self.party_size))
        return f"Want me to call {place.name} to book {self.weekday.capitalize()} at {self.clock()} for {party}?"

    def evidence(self, place: Place) -> dict:
        """What the gate checks for the places switch: this offer, its place's number, when it was offered and taken."""
        return {"offer_id": self.id, "place_name": place.name, "place_phone": place.phone.lstrip("+"),
                "offered_at": self.offered_at, "accepted_at": self.accepted_at,
                "yes_by": self.yes_by or "whatsapp", "texted_at": self.texted_at}


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = path or config.STATE_DIR / "offers.sqlite"
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SCHEMA)
    have = {row[1] for row in conn.execute("pragma table_info(offers)")}
    for name, kind in EMAIL_COLUMNS.items():  # a file from before email offers keeps its rows
        if name not in have:
            conn.execute(f"alter table offers add column {name} {kind}")
    conn.execute("create unique index if not exists offers_key on offers(offer_key) where offer_key is not null")
    conn.commit()
    return conn


def _when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _row(r) -> CallOffer:
    return CallOffer(r[0], datetime.fromisoformat(r[1]), r[2], r[3], r[4], r[5], r[6], r[7], r[8], _when(r[9]),
                     r[10] or "", r[11], r[12], r[13], r[14], r[15], r[16], _when(r[17]), _when(r[18]), r[19], r[20], r[21])


def record_offer(conn: sqlite3.Connection, place: Place, *, weekday: str, day: str, hour: int, party_size: int,
                 occasion: str = "", now: datetime | None = None, minute: int = 0) -> CallOffer:
    now = now or datetime.now(timezone.utc)
    # a newer offer replaces any still pending, so a yes answers the latest question only
    conn.execute("update offers set status = 'replaced' where status = 'pending' and kind != 'heads_up'")
    cur = conn.execute(
        "insert into offers (offered_at, place_id, weekday, day, hour, party_size, occasion, status, minute)"
        " values (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (now.isoformat(), place.id, weekday.lower(), day, hour, party_size, occasion, minute))
    conn.commit()
    return get(conn, cur.lastrowid)


def get(conn: sqlite3.Connection, offer_id: int) -> CallOffer:
    return _row(conn.execute("select * from offers where id = ?", (offer_id,)).fetchone())


def pending(conn: sqlite3.Connection, now: datetime | None = None) -> CallOffer | None:
    """The latest offer still waiting for his word, and only inside the yes window. A yes goes to a table or a reply
    before a heads-up, which asks nothing."""
    now = now or datetime.now(timezone.utc)
    for kinds in ("kind != 'heads_up'", "kind = 'heads_up'"):
        r = conn.execute(f"select * from offers where status = 'pending' and {kinds} order by id desc limit 1").fetchone()
        if r is not None and now - _row(r).offered_at <= YES_WINDOW:
            return _row(r)
    return None


def record_email_offer(conn: sqlite3.Connection, key: str, kind: str, message: str, data: dict,
                       now: datetime | None = None) -> CallOffer | None:
    """An offer from an email, held until the text goes out. None when this key was already taken: a replay is a no-op."""
    now = now or datetime.now(timezone.utc)
    cur = conn.execute(
        "insert or ignore into offers (offered_at, place_id, weekday, day, hour, party_size, occasion, status, kind,"
        " offer_key, source_id, who, message, minute) values (?, ?, ?, ?, ?, ?, ?, 'held', ?, ?, ?, ?, ?, ?)",
        (now.isoformat(), data.get("place_id") or "", str(data.get("weekday") or "").lower(), data.get("day") or "",
         int(data.get("hour") or 0), int(data.get("party_size") or 0), data.get("occasion") or "", kind, key,
         data.get("message_id") or "", data.get("who") or "", message, int(data.get("minute") or 0)))
    conn.commit()
    return get(conn, cur.lastrowid) if cur.rowcount == 1 else None


def mark_texted(conn: sqlite3.Connection, offer: CallOffer, now: datetime | None = None) -> CallOffer:
    """The text went out: its yes window starts now, and it replaces any older question of its class."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    same = "kind = 'heads_up'" if offer.kind == "heads_up" else "kind != 'heads_up'"
    conn.execute(f"update offers set status = 'replaced' where status = 'pending' and {same} and id != ?", (offer.id,))
    conn.execute("update offers set status = 'pending', offered_at = ?, texted_at = ? where id = ?",
                 (stamp, stamp, offer.id))
    conn.commit()
    return get(conn, offer.id)


def held(conn: sqlite3.Connection) -> list[CallOffer]:
    return [_row(r) for r in conn.execute("select * from offers where status = 'held' order by id").fetchall()]


def add_message(conn: sqlite3.Connection, offer_id: int, message_id: str | None) -> None:
    if message_id:
        conn.execute("update offers set message_ids = trim(message_ids || ' ' || ?) where id = ?", (message_id, offer_id))
        conn.commit()


def by_message(conn: sqlite3.Connection, message_id: str) -> CallOffer | None:
    """The offer one of Marco's messages was about, for a reply that quotes it."""
    r = conn.execute("select * from offers where instr(' ' || message_ids || ' ', ?) > 0 order by id desc limit 1",
                     (f" {message_id} ",)).fetchone()
    return _row(r) if r else None


def still_open(offer: CallOffer, now: datetime | None = None) -> bool:
    """He can still answer it: inside its yes window, and not taken. A newer offer replacing it only moved the plain yes
    along; quoting it points at it anyway."""
    now = now or datetime.now(timezone.utc)
    since = offer.accepted_at if offer.status == "what to say" and offer.accepted_at else offer.offered_at
    return offer.status in ("pending", "replaced", "questions", "what to say") and now - since <= YES_WINDOW


def taken(offer: CallOffer) -> bool:
    return offer.status in ("accepted", "called", "held", "drafting", "drafted", "answered", "declined", "test done")


def reopen(conn: sqlite3.Connection, offer: CallOffer) -> CallOffer:
    """He quoted an offer a newer one had replaced: it is the one in question again, beside the newer one."""
    conn.execute("update offers set status = 'pending' where id = ? and status = 'replaced'", (offer.id,))
    conn.commit()
    return get(conn, offer.id)


def set_asked(conn: sqlite3.Connection, offer_id: int, message_id: str) -> None:
    """The message of his that started this, once; a later reply doesn't move it."""
    conn.execute("update offers set asked_id = coalesce(asked_id, ?) where id = ?", (message_id, offer_id))
    conn.commit()


def set_yes_by(conn: sqlite3.Connection, offer_id: int, how: str) -> CallOffer:
    conn.execute("update offers set yes_by = ? where id = ?", (how, offer_id))
    conn.commit()
    return get(conn, offer_id)


def ask_what_to_say(conn: sqlite3.Connection, offer: CallOffer, now: datetime | None = None) -> None:
    conn.execute("update offers set status = 'what to say', accepted_at = ? where id = ?",
                 ((now or datetime.now(timezone.utc)).isoformat(), offer.id))
    conn.commit()


def waiting_for_words(conn: sqlite3.Connection, now: datetime | None = None) -> CallOffer | None:
    """The reply offer he said yes to, waiting for what to say, inside the yes window of that yes."""
    now = now or datetime.now(timezone.utc)
    r = conn.execute("select * from offers where status = 'what to say' order by id desc limit 1").fetchone()
    if r is None:
        return None
    offer = _row(r)
    return offer if offer.accepted_at and now - offer.accepted_at <= YES_WINDOW else None


def open_days(calendar, now: datetime, ahead: int = 7, shown: int = 5) -> list[date]:
    """His open days coming up, as dates only: a yes or no per day, never what an event is. Empty when the calendar
    can't be read. style.days_span says them."""
    from datetime import time as clock

    today, out = now.astimezone(MIAMI).date(), []
    try:
        for n in range(1, ahead + 1):
            day = today + timedelta(days=n)
            if calendar.is_clear(datetime.combine(day, clock(10), MIAMI), datetime.combine(day, clock(19), MIAMI)):
                out.append(day)
    except Exception:
        return []
    return out[:shown]


def voice_yes_on(path: Path | None = None) -> bool:
    """A spoken yes can lead to a call only once the Owner's calls -> places line says so; absent means off."""
    from hiremarco import rules

    return any(s.tool == "calls" and s.destination == "places" and "by voice" in s.purpose for s in rules.switches(path))


class BoothOffers:
    """What the booth may know of an email offer: that one was texted, and who from. It says so once after a take; a
    spoken yes inside the yes window is his yes to that exact text."""

    def __init__(self, conn: sqlite3.Connection | None = None, *, yes: Callable[[CallOffer], None] | None = None,
                 now: Callable[[], datetime] | None = None, rules_path: Path | None = None):
        self.conn = conn or connect()
        self.rules_path = rules_path
        self._yes = yes
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _live(self, spoken: str) -> CallOffer | None:
        r = self.conn.execute(f"select * from offers where status = 'pending' and offer_key is not null and {spoken}"
                              " order by id desc limit 1").fetchone()
        return _row(r) if r is not None and self._now() - _row(r).offered_at <= YES_WINDOW else None

    def to_mention(self) -> CallOffer | None:
        return self._live("spoken_at is null")

    def mentioned(self, offer: CallOffer) -> None:
        self.conn.execute("update offers set spoken_at = ? where id = ?", (self._now().isoformat(), offer.id))
        self.conn.commit()

    def spoken(self) -> CallOffer | None:
        offer = self._live("spoken_at is not null")
        return None if offer and offer.kind == "table" and not voice_yes_on(self.rules_path) else offer

    def yes(self, offer: CallOffer) -> None:
        import threading

        if self._yes is not None:
            self._yes(offer)
            return
        from hiremarco import config
        from hiremarco.server import offer_yes_by_voice

        threading.Thread(target=offer_yes_by_voice, args=(offer, config.require("OWNER_WHATSAPP")), daemon=True).start()


def asking(conn: sqlite3.Connection, now: datetime | None = None) -> CallOffer | None:
    """The offer whose fallback questions are waiting for his one reply, inside the yes window."""
    now = now or datetime.now(timezone.utc)
    r = conn.execute("select * from offers where status = 'questions' order by id desc limit 1").fetchone()
    if r is None:
        return None
    offer = _row(r)
    return offer if now - offer.offered_at <= YES_WINDOW else None


QUESTIONS = ("1. If Thursday at 8pm is gone, what other day or time works?",
             "2. Indoor or patio, or either?",
             "3. If they want a card to hold it, is a link to you OK?",
             "4. Any allergies, an occasion, or anything else to tell them?")
FLEXIBLE = re.compile(r"\b(whatever works|anything works|either|flexible|up to you|you decide|any)\b", re.I)


def questions_text(offer: CallOffer) -> str:
    first = QUESTIONS[0].replace("Thursday at 8pm", f"{offer.weekday.capitalize()} at {offer.clock()}")
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


def preferences_known(profile: dict | None = None) -> bool:
    """True when his profile already answers the fallback questions (window, seating, requests; the card is always
    a link), so a yes dials at once (Owner 2026-11-04: "he shouldn't have to ask me every time")."""
    profile = briefs.load_profile() if profile is None else profile
    return all(str(profile.get(k) or "").strip() for k in ("time_window", "seating", "special_requests"))


def held_to_retry(conn: sqlite3.Connection, now: datetime | None = None) -> CallOffer | None:
    """The newest table offer held inside the yes window, put back to pending so his yes or "call again" dials it."""
    now = now or datetime.now(timezone.utc)
    r = conn.execute("select * from offers where status = 'held' and kind = 'table' order by id desc limit 1").fetchone()
    if r is None:
        return None
    offer = _row(r)
    if offer.offered_at is None or now - offer.offered_at > YES_WINDOW:
        return None
    conn.execute("update offers set status = 'pending' where id = ? and status = 'held'", (offer.id,))
    conn.commit()
    return get(conn, offer.id)


def set_status(conn: sqlite3.Connection, offer_id: int, status: str) -> None:
    conn.execute("update offers set status = ? where id = ?", (status, offer_id))
    conn.commit()


def place_for(offer: CallOffer, places: list[Place] | None = None) -> Place | None:
    return next((p for p in (places if places is not None else load_places()) if p.id == offer.place_id), None)


def brief_for(offer: CallOffer) -> dict[str, str]:
    """The reservation brief from the offer itself; the profile fills the standing facts."""
    given = {"party_size": str(offer.party_size), "date": f"{offer.weekday.capitalize()} ({offer.day})",
             "time": f"{offer.spoken_clock()} pm" if offer.hour >= 12 else f"{offer.spoken_clock()} am",
             "occasion": offer.occasion or "none"}
    if offer.fallbacks:
        given["fallbacks"] = offer.fallbacks
        # his one reply answers the window, the seating and the requests the profile leaves open (live 2026-10-31:
        # the profile had none of them, Marco asked for them first, and the answer went to plain chat)
        standing = briefs.load_profile()
        for field in ("time_window", "seating", "special_requests"):
            if not standing.get(field):
                given[field] = "see Felix's fallbacks below"
        # live 2026-11-04: he answered "outdoor" and the call asked for indoor, the profile's standing choice
        seating = seating_in(offer.fallbacks)
        if seating:
            given["seating"] = seating
    return given


def ask_for_gaps(gap: briefs.BriefIncomplete) -> str:
    """The question he gets on WhatsApp before any dialing, when the brief has a gap."""
    wanted = ", ".join(briefs.LABELS.get(k, k.replace("_", " ")) for k in gap.missing)
    return f"Before I call, I need: {wanted}."


SETTLED = re.compile(r"\b(?:lock(?:ed)? (?:it |that |the details )?in|all set|you'?re booked|we'?re booked|it'?s booked|"
                     r"booked|confirmed|that works|works for us|works great|perfect, thank)", re.I)
SEATING = (("outdoor", re.compile(r"\b(?:outdoor|outdoors|outside|patio|terrace)\b", re.I)),
           ("indoor", re.compile(r"\b(?:indoor|indoors|inside)\b", re.I)),
           ("any", re.compile(r"\b(?:either|any|anywhere|whatever works)\b", re.I)))


def agreed_on(data: dict) -> str:
    collected = (data.get("analysis") or {}).get("data_collection_results") or {}
    return str((collected.get("agreed") or {}).get("value") or "").strip()


def seating_in(said: str) -> str:
    """The seating his reply names, or nothing: his answer outranks the profile's standing choice."""
    found = [name for name, words in SEATING if words.search(said or "")]
    return found[0] if len(found) == 1 else ""


def outcome(data: dict) -> tuple[str, str]:
    """How a call went, from Marco's own last words: booked, waitlisted or nothing settled, and that line."""
    said = [str(t.get("message") or "").strip() for t in data.get("transcript") or [] if t.get("role") == "agent"]
    said = [s for s in said if s]
    last = said[-1] if said else ""
    words = " ".join(said[-3:]).lower()
    if re.search(r"waitlist|wait list|adding us|cancellation", words):
        kind = "waitlisted"
    elif re.search(r"see you", last.lower()) or (agreed_on(data) and SETTLED.search(last)):
        # live 2026-11-04: "Eight thirty works, I'll lock in the details." then the line closed; the place said yes
        # to 8:30 and he took it, so it is booked, not "nothing settled"
        kind = "booked"
    else:
        kind = "nothing settled"
    return kind, last


def result_text(place: Place, offer: CallOffer, data: dict, off_brief: str) -> str:
    status = data.get("status")
    if status != "done":
        return f"The call to {place.name} didn't go through. Want me to try again later?"
    kind, _ = outcome(data)
    collected = (data.get("analysis") or {}).get("data_collection_results") or {}
    value = lambda key: str((collected.get(key) or {}).get("value") or "").strip().rstrip(".")  # noqa: E731
    # what the call settled, never the offer's own day and time, which a fallback may have replaced (live
    # 2026-10-31); facts and the next step only, no goodbye quote (Owner: the message must be useful)
    agreed, step = briefs.unspell(value("agreed")), briefs.unspell(value("next_step"))
    agreed, step = times_settled_on(agreed, offer.hour >= 12), times_settled_on(step, offer.hour >= 12)
    name = briefs.load_profile().get("full_name", "").strip()
    if kind == "booked":
        text = f"Booked: {place.name}" + (f", {agreed}" if agreed else "") + (f", under {name}" if name else "") + "."
        text += " The confirmation should come to your email."
    elif kind == "waitlisted":
        text = f"{place.name} was full, so you're on their waitlist" + (f": {agreed}" if agreed else "") + "."
    else:
        text = f"Nothing settled with {place.name}" + (f": {agreed}" if agreed else "") + ". Want me to try another time?"
    if step:
        text += f" Next: {step}."
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


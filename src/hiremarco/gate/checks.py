"""The gate's checks and its record of what Marco has done.

The record is a small SQLite file in the state folder. ``conn`` is a
connection to it; tests pass an in-memory one.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TypeVar

from hiremarco import config, rules
from hiremarco.gate.kill import kill_switch_on
from hiremarco.joblog import JobLog
from hiremarco.meta.pricing import (
    PRICES_PER_HOUR,
    PRICES_PER_IMAGE,
    PRICES_PER_MILLION,
    PRICES_PER_THOUSAND_CHARS,
)

T = TypeVar("T")

# Which RULES.md tool a channel needs a send switch for. A channel that reaches
# no person uses the destination "*" in its switch line.
CHANNEL_TOOLS = {
    "whatsapp": "whatsapp",
    "voice": "calls",
    "logic": "logic",
    "files": "export",
    "calendar": "calendar",
    "talkback": "talkback",
    "unsubscribe": "unsubscribe",  # a one-click unsubscribe POST to a sender the Owner marked
}
PERSON_CHANNELS = {"whatsapp", "voice"}

# Every call opens with the recording notice, word for word (ElevenLabs records every call; Florida needs every
# party's consent). The booking call's whole first line is also the film's caption.
RECORDING_OPENING = "Hi, just so you know, this call is recorded."
RECORDING_NOTICE = RECORDING_OPENING + " I'm calling to book a table for Felix."

DAILY_LIMITS = {"voice": 30, "whatsapp": 100}
DUPLICATE_WINDOW_S = 600
DAILY_MODEL_CAP_USD = 5.0

SECRET_SHAPES = re.compile(
    r"(Bearer [A-Za-z0-9._-]{20,}|EAA[A-Za-z0-9]{40,}|sk-[A-Za-z0-9]{20,}|LLM_[A-Za-z0-9_-]{20,}"
    r"|AC[0-9a-f]{32}|-----BEGIN [A-Z ]*PRIVATE KEY)"
)

SCHEMA = """
create table if not exists effects (
    id integer primary key,
    ts text not null,
    day text not null,
    tenant_id text not null,
    idempotency_key text not null,
    capability text not null,
    channel text not null,
    target text not null,
    message_hash text not null,
    department text not null,
    workflow_name text,
    ok integer not null
);
create unique index if not exists effects_key_ok on effects(idempotency_key) where ok = 1;
"""


class Refused(PermissionError):
    """The gate said no. ``reason`` is short enough for Marco's live log."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    if path is None:
        path = config.STATE_DIR / "gate.sqlite"
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # The booth hears on one thread and acts on another; access is sequential, so one handle may cross threads.
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _owner() -> str:
    owner = config.get("OWNER_WHATSAPP")
    if not owner:
        raise Refused("OWNER_WHATSAPP is not set, so no person is allowlisted")
    return owner.lstrip("+")


def check_outbound(
    conn: sqlite3.Connection,
    *,
    tenant_id: str,
    idempotency_key: str,
    capability: str,
    channel: str,
    target: str,
    message: str,
    department: str,
    workflow_name: str | None = None,
    today: date | None = None,
    rules_path: Path | None = None,
    owner_request: str | None = None,
    offer: dict | None = None,
) -> None:
    """Raise ``Refused`` unless this action may happen now.

    ``owner_request`` is the Owner's own words asking for this action. A ``named`` send switch lets a call through
    only when the target's full number (E.164 digits) is in those words.

    ``offer`` is the evidence for a ``places`` switch: an offer the Owner said yes to on WhatsApp. It holds only
    when the target is that offer's place, the number is in his private places file, and the yes came within the
    yes window of the offer and recently.
    """
    if kill_switch_on():
        raise Refused("kill switch is on")
    tool = CHANNEL_TOOLS.get(channel)
    if tool is None:
        raise Refused(f"unknown channel {channel!r}")
    target = target.lstrip("+")

    if channel in PERSON_CHANNELS:
        if not re.fullmatch(r"\d{7,15}", target):
            raise Refused("a person is reached by phone number only")
        if channel == "whatsapp" and target != _owner():
            raise Refused("WhatsApp goes to the Owner only")
        if channel == "voice" and not message.startswith(RECORDING_OPENING):
            raise Refused("a call must open with the recording notice")
    elif target != "*":
        raise Refused(f"{channel} reaches no person; its target is '*'")

    named = channel == "voice" and bool(owner_request) and target in re.sub(r"\D", "", owner_request or "")
    offered = channel == "voice" and offer is not None and offer_holds(offer, target)
    if not rules.allowed(tool, target, today, rules_path, named_by_owner=named, offered=offered):
        raise Refused(f"no send switch for {tool} -> {target}")

    try:
        row = conn.execute(
            "select 1 from effects where idempotency_key = ? and ok = 1", (idempotency_key,)
        ).fetchone()
        if row:
            raise Refused("already done (same idempotency key)")
        since = datetime.fromtimestamp(time.time() - DUPLICATE_WINDOW_S, timezone.utc).isoformat()
        # Repeating "record" in the studio is normal; repeating a message to a person is not.
        row = channel in PERSON_CHANNELS and conn.execute(
            "select 1 from effects where ok = 1 and channel = ? and target = ? and message_hash = ? and ts >= ?",
            (channel, target, _hash(message), since),
        ).fetchone()
        if row:
            raise Refused(f"same message to the same place within {DUPLICATE_WINDOW_S // 60} minutes")
        limit = DAILY_LIMITS.get(channel)
        if limit is not None:
            day = (today or date.today()).isoformat()
            (count,) = conn.execute(
                "select count(*) from effects where ok = 1 and channel = ? and day = ?", (channel, day)
            ).fetchone()
            if count >= limit:
                raise Refused(f"daily limit of {limit} {channel} actions reached")
    except sqlite3.Error as exc:
        raise Refused(f"gate record unreadable: {type(exc).__name__}") from exc


def offer_holds(offer: dict, target: str, now: datetime | None = None) -> bool:
    """True when ``offer`` is an accepted offer to call ``target``, a number in the Owner's places file."""
    from hiremarco.calls.offers import YES_WINDOW
    from hiremarco.offer import load_places

    now = now or datetime.now(timezone.utc)
    offered, accepted = offer.get("offered_at"), offer.get("accepted_at")
    phones = {p.phone.lstrip("+") for p in load_places()}
    return (offer.get("place_phone") == target and target in phones and offered is not None and accepted is not None
            and timedelta(0) <= accepted - offered <= YES_WINDOW and timedelta(0) <= now - accepted <= YES_WINDOW)


def record_effect(
    conn: sqlite3.Connection,
    *,
    tenant_id: str,
    idempotency_key: str,
    capability: str,
    channel: str,
    target: str,
    message: str,
    department: str,
    workflow_name: str | None = None,
    ok: bool = True,
    today: date | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "insert into effects (ts, day, tenant_id, idempotency_key, capability, channel, target, message_hash,"
        " department, workflow_name, ok) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (now, (today or date.today()).isoformat(), tenant_id, idempotency_key, capability, channel,
         target.lstrip("+"), _hash(message), department, workflow_name, int(ok)),
    )
    conn.commit()


def execute_effect(
    conn: sqlite3.Connection,
    run: Callable[[], T],
    *,
    tenant_id: str,
    idempotency_key: str,
    capability: str,
    channel: str,
    target: str,
    message: str,
    department: str,
    workflow_name: str | None = None,
    critic: Callable[[str], tuple[bool, str]] | None = None,
    today: date | None = None,
    rules_path: Path | None = None,
    owner_request: str | None = None,
    offer: dict | None = None,
) -> T:
    """Check, ask the critic if one is given, run, record.

    ``critic`` takes a plain description of the action and returns
    (approved, reason). An exception from it counts as a refusal.
    """
    fields = dict(
        tenant_id=tenant_id, idempotency_key=idempotency_key, capability=capability, channel=channel,
        target=target, message=message, department=department, workflow_name=workflow_name,
    )
    check_outbound(conn, **fields, today=today, rules_path=rules_path, owner_request=owner_request, offer=offer)
    if critic is not None:
        # The Owner's number is private (RULES.md keeps it in the env file), so the critic is told whose it is
        # instead of seeing it; without that it held the first call to the Owner as having no switch.
        owner = (config.get("OWNER_WHATSAPP") or "").lstrip("+")
        shown = "the Owner's own number" if owner and target.lstrip("+") == owner else target
        if offer is not None:  # a places call is to the place, whatever its number (live 2026-10-31: Test Kitchen
            # has the Owner's number for the rehearsal, and the critic held a call it read as to the Owner)
            shown = f"{offer.get('place_name')} (its number from the Owner's places file, offer {offer.get('offer_id')})"
        description = f"{capability} via {channel} to {shown}: {message}"
        if owner_request:
            description += f" (the Owner asked: {owner_request})"
        if offer is not None:
            description += f" (the Owner said yes on WhatsApp to Marco's offer to call {offer.get('place_name')})"
        try:
            approved, reason = critic(description)
        except Exception as exc:
            raise Refused(f"critic unavailable ({type(exc).__name__}), so holding") from exc
        if not approved:
            raise Refused(f"critic held it: {reason}")
    try:
        result = run()
    except Exception:
        record_effect(conn, **fields, ok=False, today=today)
        raise
    record_effect(conn, **fields, ok=True, today=today)
    return result


def check_model_call(
    tenant_id: str,
    *,
    model: str,
    system: str,
    prompt: str,
    joblog: JobLog | None = None,
) -> None:
    """Raise ``Refused`` unless this model call may be made now."""
    if kill_switch_on():
        raise Refused("kill switch is on")
    priced = (PRICES_PER_MILLION, PRICES_PER_HOUR, PRICES_PER_THOUSAND_CHARS, PRICES_PER_IMAGE)
    if not any(model in table for table in priced):
        raise Refused(f"{model} has no price, so its cost cannot be counted")
    if SECRET_SHAPES.search(system or "") or SECRET_SHAPES.search(prompt or ""):
        raise Refused("the prompt holds something shaped like a secret")
    joblog = joblog or JobLog()
    spent = joblog.total_usd(date.today().isoformat())
    if spent >= DAILY_MODEL_CAP_USD:
        raise Refused(f"today's model spend {spent:.2f} USD reached the {DAILY_MODEL_CAP_USD:.2f} USD cap")

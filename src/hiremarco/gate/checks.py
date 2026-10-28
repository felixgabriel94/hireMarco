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
from datetime import date, datetime, timezone
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
}
PERSON_CHANNELS = {"whatsapp", "voice"}

# Every call opens with this line, word for word; it is also the film's caption.
RECORDING_NOTICE = "Hi, this call is recorded. I'm an AI assistant calling to book a table for Felix."

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
    conn = sqlite3.connect(str(path))
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
) -> None:
    """Raise ``Refused`` unless this action may happen now."""
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
        if channel == "voice" and not message.startswith(RECORDING_NOTICE):
            raise Refused("a call must open with the recording notice")
    elif target != "*":
        raise Refused(f"{channel} reaches no person; its target is '*'")

    if not rules.allowed(tool, target, today, rules_path):
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
) -> T:
    """Check, ask the critic if one is given, run, record.

    ``critic`` takes a plain description of the action and returns
    (approved, reason). An exception from it counts as a refusal.
    """
    fields = dict(
        tenant_id=tenant_id, idempotency_key=idempotency_key, capability=capability, channel=channel,
        target=target, message=message, department=department, workflow_name=workflow_name,
    )
    check_outbound(conn, **fields, today=today, rules_path=rules_path)
    if critic is not None:
        description = f"{capability} via {channel} to {target}: {message}"
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

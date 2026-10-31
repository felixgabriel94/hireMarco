"""Send switches, read from RULES.md.

Nothing in this repository sends outbound (a message, a call) unless a line
in RULES.md names the tool and the destination. Absent means off. The line
grammar, one per line under the "Send switches" heading::

    send: <tool> -> <destination> ; <purpose> ; until <YYYY-MM-DD | revoked>

``until revoked`` is a switch with no end date, on until its line is removed
(Owner ruling 2026-10-29 for WhatsApp to the Owner). ``<tool>`` is a package name such as ``whatsapp`` or ``calls``;
``<destination>`` is a phone number in E.164 without the plus, ``owner`` for
the Owner's own number (read from OWNER_WHATSAPP in the private env file, so
it stays out of this public repository), or ``*`` for a tool that reaches no
person (not used for messages or calls).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from hiremarco import config

RULES_PATH = Path(__file__).resolve().parents[2] / "RULES.md"
LINE = re.compile(r"^\s*send:\s*(?P<tool>[\w-]+)\s*->\s*(?P<dest>\*|owner|\d{7,15})\s*;\s*(?P<purpose>[^;]+?)\s*;\s*until\s+(?P<until>\d{4}-\d{2}-\d{2}|revoked)\s*$")


@dataclass(frozen=True)
class Switch:
    tool: str
    destination: str
    purpose: str
    until: date


def switches(path: Path | None = None) -> list[Switch]:
    path = path or RULES_PATH
    if not path.exists():
        return []
    found: list[Switch] = []
    for raw in path.read_text().splitlines():
        m = LINE.match(raw)
        if m:
            until = date.max if m["until"] == "revoked" else date.fromisoformat(m["until"])
            found.append(Switch(m["tool"], m["dest"], m["purpose"].strip(), until))
    return found


def allowed(tool: str, destination: str, today: date | None = None, path: Path | None = None) -> bool:
    """True only when a live switch line names this tool and this destination."""
    today = today or date.today()
    destination = destination.lstrip("+")
    owner = (config.get("OWNER_WHATSAPP") or "").lstrip("+")

    def names(s: Switch) -> bool:
        if s.destination == "owner":
            return owner != "" and destination == owner
        return s.destination == destination

    return any(s.tool == tool and names(s) and s.until >= today for s in switches(path))


class SendNotAllowed(PermissionError):
    pass


def require(tool: str, destination: str, today: date | None = None, path: Path | None = None) -> None:
    if not allowed(tool, destination, today, path):
        raise SendNotAllowed(
            f"no live send switch for {tool} -> {destination}; add a line to RULES.md (absent means off)"
        )


# Read grants: which senders' mail Marco may open. One line each:
#     read: mail <- <address or @domain> ; <purpose> ; until <YYYY-MM-DD | revoked>
# Absent means Marco reads no mail at all.
READ_LINE = re.compile(
    r"^\s*read:\s*mail\s*<-\s*(?P<sender>@[\w.-]+\.\w+|[\w.+-]+@[\w.-]+\.\w+)\s*;\s*(?P<purpose>[^;]+?)\s*;"
    r"\s*until\s+(?P<until>\d{4}-\d{2}-\d{2}|revoked)\s*$"
)


@dataclass(frozen=True)
class ReadGrant:
    sender: str
    purpose: str
    until: date


def read_grants(path: Path | None = None, today: date | None = None) -> list[ReadGrant]:
    path = path or RULES_PATH
    today = today or date.today()
    if not path.exists():
        return []
    found = []
    for raw in path.read_text().splitlines():
        m = READ_LINE.match(raw)
        until = date.max if m and m["until"] == "revoked" else (date.fromisoformat(m["until"]) if m else None)
        if m and until >= today:
            found.append(ReadGrant(m["sender"].lower(), m["purpose"].strip(), until))
    return found


def may_read(sender: str, path: Path | None = None, today: date | None = None) -> bool:
    """True when a live read grant names this exact address or its domain."""
    sender = sender.strip().lower()
    domain = "@" + sender.rpartition("@")[2]
    return any(g.sender in (sender, domain) for g in read_grants(path, today))

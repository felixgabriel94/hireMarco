"""Send switches, read from RULES.md.

Nothing in this repository sends outbound (a message, a call) unless a line
in RULES.md names the tool and the destination. Absent means off. The line
grammar, one per line under the "Send switches" heading::

    send: <tool> -> <destination> ; <purpose> ; until <YYYY-MM-DD>

``<tool>`` is a package name such as ``whatsapp`` or ``calls``;
``<destination>`` is a phone number in E.164 without the plus, or ``*`` for
a tool that reaches no person (not used for messages or calls).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parents[2] / "RULES.md"
LINE = re.compile(r"^\s*send:\s*(?P<tool>[\w-]+)\s*->\s*(?P<dest>\*|\d{7,15})\s*;\s*(?P<purpose>[^;]+?)\s*;\s*until\s+(?P<until>\d{4}-\d{2}-\d{2})\s*$")


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
            found.append(Switch(m["tool"], m["dest"], m["purpose"].strip(), date.fromisoformat(m["until"])))
    return found


def allowed(tool: str, destination: str, today: date | None = None, path: Path | None = None) -> bool:
    """True only when a live switch line names this tool and this destination."""
    today = today or date.today()
    destination = destination.lstrip("+")
    return any(
        s.tool == tool and s.destination == destination and s.until >= today
        for s in switches(path)
    )


class SendNotAllowed(PermissionError):
    pass


def require(tool: str, destination: str, today: date | None = None, path: Path | None = None) -> None:
    if not allowed(tool, destination, today, path):
        raise SendNotAllowed(
            f"no live send switch for {tool} -> {destination}; add a line to RULES.md (absent means off)"
        )

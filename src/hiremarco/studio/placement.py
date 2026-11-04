"""A new part's track goes inside its stack (Owner 2026-11-04: "create a new harmony" belongs in the harmony stack,
never outside our groups): the stacks opened, the part's stack found by name, its last track selected, so Logic
makes the new track right after it, inside the stack (live 2026-10-31: with a track inside KEYS selected, the new
track went into KEYS). No stack for the part: the session's last track outside every stack, and he says so.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).parent / "scripts"
STACKS = {
    "lead": ("lead", "leads", "lead vocal", "lead vocals", "main", "main vocal", "main vocals"),
    "harmony": ("harmonies", "harmony", "harms", "harmony stack"),
    "ad-lib": ("ad-libs", "ad libs", "adlibs", "ad-lib", "adlib", "ads"),
    "double": ("doubles", "doublers", "double", "dbl", "dbls"),
}
INDENT = 4.0   # points: a member's name sits further right than its stack's


@dataclass(frozen=True)
class Row:
    number: int
    name: str
    stack: str       # "open", "closed" or "" for a plain track
    x: float | None  # where the name starts: the indent


def rows_from(raw: list[dict]) -> list[Row]:
    out = []
    for r in raw:
        m = re.match(r"Track (\d+)\s*[“\"](.*?)[”\"]", str(r.get("desc", "")))
        if not m:
            continue
        tri = r.get("triangle")
        stack = "" if tri in (None, "") else ("open" if str(tri) == "1" else "closed")
        out.append(Row(int(m.group(1)), m.group(2), stack, r.get("name_x")))
    return out


def _words(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9\- ]", " ", name.lower()).split())


def stack_end(kind: str, rows: list[Row]) -> tuple[Row, Row] | None:
    """(the part's stack, the track to select): its last member, or the stack itself when it is empty."""
    names = STACKS.get(kind)
    if not names:
        return None
    for i, row in enumerate(rows):
        if not row.stack or _words(row.name) not in names:
            continue
        last = row
        for after in rows[i + 1:]:
            if row.x is None or after.x is None or after.x <= row.x + INDENT:
                break
            last = after
        return row, last
    return None


def read_headers() -> list[Row]:
    done = subprocess.run(["osascript", "-l", "JavaScript", str(SCRIPTS / "headers.js")], capture_output=True,
                          text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:] or f"osascript exit {done.returncode}")
    return rows_from(json.loads(done.stdout))


def place(kind: str, *, select: Callable[[str], None], select_last: Callable[[], str],
          unstack: Callable[[], dict] | None = None, read: Callable[[], list[Row]] = read_headers) -> str:
    """The track the new one should follow, selected. One line of where it will land; "" for a kind with no stack."""
    if kind not in STACKS:
        return ""
    if unstack is None:
        from hiremarco.studio.organize import open_stacks as unstack
    unstack()
    found = stack_end(kind, read())
    if found is None:
        last = select_last()
        return f"no stack for {kind}: after {last}, outside every stack"
    stack, target = found
    select(f"Track {target.number}")
    if target == stack:
        return f"the {stack.name} stack is empty: right after it"
    return f"inside {stack.name}, after {target.name}"

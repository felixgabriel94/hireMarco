"""The handbook, read by situation: the audit's findings pick what Marco reasons from.

``handbook/situations/*.md`` each open with a header (id, role, job, triggers,
claims) and carry what to look for, the threshold, the why by claim ID, when
the move applies and when it does not, the move in real units, the expected
effect and how it is verified. A trigger is either ``finding: <words>``,
matched against the audit's finding lines, or a measure against a number
(``tilt_db_per_octave < -4.5``, ``problem_bands_db.mud > -8``,
``lufs < target - 0.5``). The plan receives only the situations whose
triggers fire, with their IDs, and its reasons cite them; one shoe size does
not fit all, so a situation's numbers start the reasoning and the reason
names the number measured on this track.
"""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "handbook"
SITUATIONS = ROOT / "situations"
OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
MEASURE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*(<=|>=|<|>)\s*(.+?)\s*$")


@dataclass
class Situation:
    id: str
    role: str
    job: str
    triggers: list[str]
    claims: list[str]
    title: str
    body: str
    path: Path | None = None
    fired: list[str] = field(default_factory=list)   # the triggers that matched, for the record


def _list(value: str) -> list[str]:
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return [p.strip().strip('"').strip("'") for p in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", inner) if p.strip()]


def parse(text: str, path: Path | None = None) -> Situation:
    head, _, rest = text.strip().partition("\n\n")
    fields = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    title = next((ln[2:].strip() for ln in rest.splitlines() if ln.startswith("# ")), fields.get("id", ""))
    return Situation(id=fields.get("id", ""), role=fields.get("role", "none"), job=fields.get("job", "mastering"),
                     triggers=_list(fields.get("triggers", "[]")), claims=_list(fields.get("claims", "[]")),
                     title=title, body=rest.strip(), path=path)


def load(folder: Path = SITUATIONS, job: str | None = None) -> list[Situation]:
    found = [parse(p.read_text(), p) for p in sorted(folder.glob("*.md"))] if folder.exists() else []
    return [s for s in found if job is None or s.job == job]


def _value(name: str, measures: dict) -> float | None:
    node = measures
    for part in name.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return float(node) if isinstance(node, (int, float)) else None


def _number(text: str, measures: dict) -> float | None:
    """A literal, or a measure's name with an optional ``+ n`` / ``- n``: ``target - 0.5``."""
    m = re.match(r"^([A-Za-z_][\w.]*)\s*([+-])\s*([\d.]+)$", text.strip())
    if m:
        base = _value(m.group(1), measures)
        if base is None:
            return None
        return base + float(m.group(3)) * (1 if m.group(2) == "+" else -1)
    try:
        return float(text)
    except ValueError:
        return _value(text.strip(), measures)


def fires(trigger: str, findings: list[str], measures: dict) -> bool:
    if trigger.startswith("finding:"):
        words = trigger[len("finding:"):].strip().lower()
        return any(words in f.lower() for f in findings)
    m = MEASURE.match(trigger)
    if not m:
        return False
    left, limit = _value(m.group(1), measures), _number(m.group(3), measures)
    return left is not None and limit is not None and OPS[m.group(2)](left, limit)


def pick(findings: list[str], measures: dict, situations: list[Situation] | None = None) -> list[Situation]:
    """The situations whose triggers fire on this audit, each remembering which trigger did."""
    chosen = []
    for s in situations if situations is not None else load():
        fired = [t for t in s.triggers if fires(t, findings, measures)]
        if fired:
            chosen.append(Situation(**{**s.__dict__, "fired": fired}))
    return chosen


def measures_of(audit: dict, target_lufs: float | None = None) -> dict:
    """The flat numbers a trigger may name, from the audit's dict: the base report's fields, the audit's own,
    and ``target`` for the purpose's loudness."""
    flat = {}
    base = audit.get("base", {}) if isinstance(audit, dict) else {}
    for k, v in base.items():
        if isinstance(v, (int, float, dict)):
            flat[k] = v
    for k, v in audit.items():
        if k != "base" and isinstance(v, (int, float, dict)):
            flat[k] = v
    if target_lufs is not None:
        flat["target"] = target_lufs
    return flat


def text(situations: list[Situation]) -> str:
    """What the plan reads: each situation in full, headed by its ID and the trigger that fired."""
    parts = []
    for s in situations:
        why = "; ".join(s.fired) if s.fired else ", ".join(s.triggers)
        parts.append(f"[{s.id}] (role {s.role}; fired on: {why}; claims {', '.join(s.claims)})\n{s.body}")
    return "\n\n".join(parts)

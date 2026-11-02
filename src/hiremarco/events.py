"""Marco's event stream: one structured line per thing that happens, for the live trace.

The runtime writes an event at the moment the thing happens (a model call
started, its reply, an analysis, a decision, a hand on Logic, a check), to
``~/.local/state/hiremarco/events.jsonl``; the trace window tails the file
and renders cards from it and from nothing else. Nothing private goes in:
the running log's filter runs on every summary, detail and metric label,
and no prompt, persona text, address or number is ever a field.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from hiremarco import config, stream

NAME = "events.jsonl"
COUNTER = "events.request"
KINDS = ("model_call_started", "model_call_completed", "model_call_failed", "analysis_generated", "decision_made",
         "tool_invoked", "tool_completed", "verification_started", "verification_completed", "note")
STATUSES = ("running", "ok", "failed", "retry", "low_confidence", "refused")
SUMMARY_CHARS = 80
DETAIL_CHARS = 120
METRICS_MAX = 4

# the job names the code already passes, in the words a judge reads; a job not here reads as its name with spaces
OPERATIONS = {
    "master_audit": "mastering plan", "master_settings": "chain settings", "master_critic": "the critic's review",
    "critic": "the critic's review", "plugin_face": "plug-in face", "segment": "finding the pieces in the photo",
    "looks": "three looks from the pieces", "selects": "picking the frames", "organize": "organizing the session",
    "taste": "reading the artist's taste", "mix_plan": "mix pass", "chain_describe": "the channel from a description",
    "feedback": "a producer's note on the take", "hours_check": "checking the hours", "call-relay": "the call",
    "call": "the call", "transcribe": "listening", "command": "a spoken command", "export_computer_use": "the export dialog",
    "mail": "reading the mail", "email-offer": "an offer from the mail", "dress": "dress me",
}
TOOLS = {"logic": "Logic Pro", "whatsapp": "WhatsApp", "twilio": "the phone", "bounce": "Bounce", "mail": "Mail"}


def path() -> Path:
    return Path(config.STATE_DIR) / NAME


def operation_words(job: str) -> str:
    return OPERATIONS.get(job, job.replace("_", " ").replace("-", " "))


def tool_words(channel: str) -> str:
    return TOOLS.get(channel, channel)


def model_words(model: str) -> str:
    """'muse-wonder-1.0' -> 'MUSE WONDER 1.0'; 'sam-3.1' -> 'SAM 3.1'."""
    return " ".join(p.upper() for p in model.replace("_", "-").split("-")) if model else ""


def next_request_id(at: Path | None = None) -> str:
    """The day's count of model calls, five digits, kept in a small file beside the events."""
    counter = (at or path()).with_name(COUNTER)
    today = time.strftime("%Y-%m-%d")
    day, count = today, 0
    try:
        day, text = counter.read_text().split()
        count = int(text) if day == today else 0
    except (OSError, ValueError):
        pass
    count += 1
    counter.parent.mkdir(parents=True, exist_ok=True)
    counter.write_text(f"{today} {count}")
    return f"{count:05d}"


def _metrics(metrics) -> list[dict]:
    out = []
    for m in (metrics or [])[:METRICS_MAX]:
        if isinstance(m, dict):
            label, value, unit = m.get("label", ""), m.get("value", ""), m.get("unit", "")
        else:
            label, value, unit = (list(m) + ["", ""])[:3]
        out.append({"label": stream.clean(str(label))[:32], "value": stream.clean(str(value))[:24], "unit": str(unit)[:8]})
    return out


def emit(kind: str, *, source: str, model: str = "", operation: str = "", status: str = "ok", summary: str = "",
         detail: str = "", metrics=None, latency_ms: int | None = None, confidence: float | None = None,
         tool: str = "", request_id: str = "", attempt: int | None = None, call_id: str = "", tokens: dict | None = None,
         cost_usd: float | None = None, at: Path | None = None) -> dict:
    """One line of the stream, written now; returns the row."""
    if kind not in KINDS:
        raise ValueError(f"not an event kind: {kind}")
    if status not in STATUSES:
        raise ValueError(f"not a status: {status}")
    row = {"ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"), "kind": kind,
           "source": "meta" if source == "meta" else "marco", "model": model, "operation": stream.clean(operation)[:48],
           "status": status, "summary": stream.clean(summary)[:SUMMARY_CHARS]}
    if detail:
        row["detail"] = stream.clean(detail)[:DETAIL_CHARS]
    if metrics:
        row["metrics"] = _metrics(metrics)
    if latency_ms is not None:
        row["latency_ms"] = int(latency_ms)
    if confidence is not None:
        row["confidence"] = round(float(confidence), 2)
    if tool:
        row["tool"] = tool
    if request_id:
        row["request_id"] = request_id
    if attempt is not None:
        row["attempt"] = int(attempt)
    if call_id:
        row["call_id"] = call_id
    if tokens:
        row["tokens"] = {k: int(v) for k, v in tokens.items() if k in ("prompt", "completion", "cached")}
    if cost_usd is not None:
        row["cost_usd"] = round(float(cost_usd), 6)
    target = at or path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass   # the trace never stops the work
    return row


def new_call_id() -> str:
    return uuid.uuid4().hex[:12]


def reply_summary(text: str) -> str:
    """What a reply said, in one line: the first line of prose, or the first string worth reading inside JSON."""
    text = (text or "").strip()
    if not text:
        return "an empty reply"
    if text[0] in "{[":
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data is not None:
            found = _first_string(data)
            if found:
                return found
            return "a structured reply"
    return text.splitlines()[0]


def _first_string(value, depth: int = 0) -> str:
    if depth > 4:
        return ""
    if isinstance(value, str):
        return value.strip() if len(value.strip()) >= 12 else ""
    if isinstance(value, dict):
        for v in value.values():
            found = _first_string(v, depth + 1)
            if found:
                return found
    if isinstance(value, list):
        for v in value:
            found = _first_string(v, depth + 1)
            if found:
                return found
    return ""


def tail(at: Path | None = None, offset: int = 0) -> tuple[list[dict], int]:
    """Rows written since ``offset`` bytes, and the new offset; a half-written last line waits for the next read."""
    target = at or path()
    if not target.exists():
        return [], 0
    with target.open("rb") as f:
        f.seek(offset)
        data = f.read()
    if not data:
        return [], offset
    cut = data.rfind(b"\n")
    if cut < 0:
        return [], offset
    rows = []
    for line in data[:cut].split(b"\n"):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows, offset + cut + 1


def read_all(at: Path | None = None) -> Iterator[dict]:
    rows, _ = tail(at, 0)
    return iter(rows)

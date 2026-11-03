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
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from hiremarco import config, stream

NAME = "events.jsonl"
COUNTER = "events.request"
KINDS = ("model_call_started", "model_call_completed", "model_call_failed", "analysis_generated", "decision_made",
         "tool_invoked", "tool_completed", "tool_skipped", "verification_started", "verification_completed", "note",
         "job_started", "job_ended", "stage", "thought", "learned", "message_sent", "email_received")
STATUSES = ("running", "ok", "failed", "retry", "low_confidence", "refused")
SUMMARY_CHARS = 80
DETAIL_CHARS = 120
METRICS_MAX = 4
PLAIN_CHARS = 90      # the design's budget for the Now sentence (trace/FEED-RULES.md)
LINE_CHARS = 120      # task, thought, a text, the design's hard limit
SUBJECT_CHARS = 40
MAIL_FLAG = "trace.mail"
VOICE_MODEL = "muse-voice-transcribe-1.0"
# Words a judge who has never been in a studio would not follow (Owner, 2026-11-02: nobody gets lost). The sentence on
# the screen says it in everyday words; the trade's words and numbers stay in the proof and the raw events.
JARGON = re.compile(r"(?:\b|(?<=\d))(lufs|lu|dbtp|db|hz|khz|crest|limiter|compressors?|plug-?ins?|chain|mix|mixes|master|mastering|print|prints|printed|printing|"
                    r"bounce|stems?|eq|rms|peaks?|transients?|correlation|mono|bus|inserts?|strip|side ?chain|saturat\w*|resonan\w*|octaves?|"
                    r"s-master-\d+|r-aud-\d+)\b", re.I)
# what the audit's findings mean, in everyday words; a finding not here stays in the proof and off the big lines
PLAIN_FINDINGS = (
    (r"clipped", "Parts of the recording hit the limit and distort."),
    (r"true peak .* over", "The loudest moments go over the safe limit."),
    (r"clicks or dropouts", "I hear small clicks in the recording."),
    (r"rumble", "There is low rumble under the music."),
    (r"mono playback loses", "Part of the sound disappears on a single speaker."),
    (r"low end .* is wide", "The bass spreads too wide. It could weaken on a club system."),
    (r"resonance", "One note rings louder than the rest."),
    (r"already limited hard", "The song is already squeezed hard."),
    (r"little dynamic movement", "The loud and quiet parts sit very close together."),
)

# the job names the code already passes, in the words a judge reads; a job not here reads as its name with spaces
OPERATIONS = {
    "master_audit": "mastering plan", "master_settings": "chain settings", "master_critic": "the critic's review",
    "critic": "the critic's review", "plugin_face": "plug-in face", "segment": "finding the pieces in the photo",
    "looks": "three looks from the pieces", "selects": "picking the frames", "organize": "organizing the session",
    "taste": "reading the artist's taste", "mix_plan": "mix pass", "chain_describe": "the channel from a description",
    "feedback": "a producer's note on the take", "hours_check": "checking the hours", "call-relay": "the call",
    "call": "the call", "transcribe": "listening", "command": "a spoken command", "export_computer_use": "the export dialog",
    "mail": "reading the mail", "email-offer": "an offer from the mail", "dress": "dress me",
    "bench_ear": "the ears on the test", "bench_verdict": "the verdict on the tool", "ladder_verdict": "the next step",
    "check_ear": "the ears on the result", "check_verdict": "the verdict on the goal",
}
# what each job asks a model, present tense, for the live view; a job not here reads as its operation words
TASKS = {
    "master_audit": "Decide what this song needs, from the measurements", "master_settings": "Set every control, and say why",
    "critic": "Second opinion: approve or hold", "plugin_face": "Read the tool's window: is it licensed?", "segment": "Find the pieces in the photo",
    "dress-looks": "Build three looks from the pieces", "dress-pick": "Pick the look", "dress-backdrop": "Paint the paper of the look board",
    "selects-pick": "Pick the frames", "organize": "Organize the session", "taste": "Read the artist's taste",
    "mix_pass": "Decide how the parts of the song sit together", "mix_hearing": "Say how the song sounds", "chain_design": "Design the sound from a description",
    "take_feedback": "Listen to the take and give a note", "hours_check": "Check the hours", "call-relay": "Talk on the phone call",
    "call": "Talk on the phone call", "transcribe": "Write down what was said", "listen": "Hear what was said", "studio-command": "Turn the spoken words into one action",
    "booth_line": "Answer in the booth", "export_computer_use": "Work the export dialog", "mail": "Read the mail", "mail-write": "Draft the email",
    "email-offer": "Read the email and find what to offer", "inbox-sort": "Sort the email", "whatsapp-reply": "Answer on WhatsApp",
    "whatsapp-brain": "Answer on WhatsApp", "whatsapp-photo": "Read the photo", "whatsapp-reaction": "React to the message", "proof-read": "Read the proof",
    "sound_design": "Design the sound", "band_audition": "Listen to just this part of the sound", "mix_signature": "Read the song's signature", "mix_preferences": "Read the artist's preferences",
    "bench_ear": "Hear the song with and without the tool", "bench_verdict": "Decide if the tool earns its place",
    "ladder_verdict": "Decide whether to go one step louder", "check_ear": "Hear the finished song against the original",
    "check_verdict": "Decide if the goal is met",
}
TOOLS = {"logic": "Logic Pro", "whatsapp": "WhatsApp", "twilio": "the phone", "bounce": "Bounce", "mail": "Mail"}


def path() -> Path:
    return Path(config.STATE_DIR) / NAME


def operation_words(job: str) -> str:
    return OPERATIONS.get(job, job.replace("_", " ").replace("-", " "))


def task_words(job: str) -> str:
    return TASKS.get(job, operation_words(job))


def readable(text: str) -> str:
    """The first sentence with no trade words in it, or nothing: a line a judge cannot follow stays off the big lines.
    A unit stuck to its number ("~261Hz", run 37) is a trade word too."""
    for sentence in re.split(r"(?<=[.!?])\s+", (text or "").strip()):
        if sentence and not JARGON.search(sentence):
            return sentence
    return ""


def plain_whole(text: str) -> str:
    """A model's plain line as a whole, or nothing: its second sentence alone can read as a fragment on screen."""
    text = (text or "").strip()
    return text if text and not JARGON.search(text) else ""


def plain_findings(findings: list[str], most: int = 3) -> list[str]:
    """The audit's findings a judge can follow, worst first as the audit lists them; each is a measured finding, reworded."""
    out = []
    for finding in findings:
        for pattern, words in PLAIN_FINDINGS:
            if re.search(pattern, finding) and words not in out:
                out.append(words)
                break
    return out[:most]


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


def _cut(text: str, limit: int) -> str:
    """Within the limit, on a sentence or a word when there is one, so a line on screen never ends in half a word."""
    text = stream.clean(text).strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for mark in (". ", "; "):
        end = head.rfind(mark)
        if end >= limit // 2:
            return head[:end + 1].rstrip(";") if mark == ". " else head[:end] + "."
    space = head.rfind(" ")
    return head[:space] if space >= limit // 2 else head


def _metrics(metrics) -> list[dict]:
    out = []
    for m in (metrics or [])[:METRICS_MAX]:
        if isinstance(m, dict):
            label, value, unit = m.get("label", ""), m.get("value", ""), m.get("unit", "")
        else:
            label, value, unit = (list(m) + ["", ""])[:3]
        out.append({"label": stream.clean(str(label))[:32], "value": stream.clean(str(value))[:24], "unit": str(unit)[:8]})
    return out


_ASIDE = threading.local()


@contextmanager
def aside() -> Iterator[None]:
    """Room business that is not Marco's work (the speakers' level on the Owner's word, a crew command on set):
    nothing emitted inside the block reaches the stream, so Marco Live never shows it (Owner 2026-11-03)."""
    before = getattr(_ASIDE, "on", False)
    _ASIDE.on = True
    try:
        yield
    finally:
        _ASIDE.on = before


def in_aside() -> bool:
    return bool(getattr(_ASIDE, "on", False))


def emit(kind: str, *, source: str, model: str = "", operation: str = "", status: str = "ok", summary: str = "",
         detail: str = "", metrics=None, latency_ms: int | None = None, confidence: float | None = None,
         tool: str = "", request_id: str = "", attempt: int | None = None, call_id: str = "", tokens: dict | None = None,
         cost_usd: float | None = None, plain: str = "", stage: str = "", stages: list[str] | None = None, task: str = "",
         thought: str = "", motif: str = "", via: str = "", text: str = "", sender: str = "", subject: str = "",
         pid: int | None = None, word: str = "", at: Path | None = None) -> dict:
    """One line of the stream, written now; returns the row. ``word`` is what a finished step says it was on the
    screen (tested, checked), in place of done, which is kept for a finished result (Owner 2026-11-03)."""
    if kind not in KINDS:
        raise ValueError(f"not an event kind: {kind}")
    if status not in STATUSES:
        raise ValueError(f"not a status: {status}")
    row = {"ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"), "kind": kind,
           "source": "meta" if source == "meta" else "marco", "model": model, "operation": stream.clean(operation)[:48],
           "status": status, "summary": _cut(summary, SUMMARY_CHARS)}
    if detail:
        row["detail"] = _cut(detail, DETAIL_CHARS)
    if word:
        row["word"] = word
    for name, value, limit in (("plain", plain, PLAIN_CHARS), ("task", task, LINE_CHARS), ("thought", thought, LINE_CHARS),
                               ("text", text, LINE_CHARS), ("sender", sender, SUMMARY_CHARS), ("subject", subject, SUBJECT_CHARS)):
        if value:
            row[name] = _cut(value, limit)
    if stage:
        row["stage"] = stage
    if stages:
        row["stages"] = list(stages)
    if motif:
        row["motif"] = motif
    if via:
        row["via"] = via
    if pid is not None:
        row["pid"] = int(pid)
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
    if in_aside():
        return row   # built, not written: the room's business stays off the screen
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


def stage(name: str, plain: str, **fields) -> dict:
    """The path moves and the big sentence says why; the design goes stale when a stage flips without one."""
    return emit("stage", source="marco", status="ok", stage=name, plain=plain, **fields)


def thought(words: str, *, detail: str = "", motif: str = "", learned: bool = False) -> dict:
    """Marco thinking: only words the run really produced (a finding, a model's reason), never written for the screen."""
    return emit("learned" if learned else "thought", source="marco", status="ok", thought=words, detail=detail, motif=motif)


@contextmanager
def step(task: str, *, tool: str = "Logic Pro", motif: str = "", done: str = "", plain: str = "", word: str = "") -> Iterator[dict]:
    """A long step with no model in it (a print, a measurement): on the screen with a running clock, so Marco at work
    never reads as idle. ``result["summary"]`` set inside the block is what the line says when it ends; ``word`` is
    the label it ends with (tested, checked) where done would overclaim: done is for a finished result."""
    call_id, began, result = new_call_id(), time.monotonic(), {"summary": done or task}
    emit("tool_invoked", source="marco", tool=tool, operation="step", status="running", summary=task, task=task,
         motif=motif, plain=plain, call_id=call_id, word=word)
    try:
        yield result
    except Exception as exc:
        emit("tool_completed", source="marco", tool=tool, operation="step", status="failed", summary=f"{task}: {type(exc).__name__}",
             call_id=call_id, latency_ms=int((time.monotonic() - began) * 1000), word=word)
        raise
    emit("tool_completed", source="marco", tool=tool, operation="step", status="ok", summary=result["summary"], call_id=call_id,
         latency_ms=int((time.monotonic() - began) * 1000), metrics=result.get("metrics"), word=word)


def mail_flag() -> Path:
    return Path(config.STATE_DIR) / MAIL_FLAG


def show_mail() -> bool:
    """An email's sender and subject reach the screen only when the Owner turned it on for a shot (marco trace mail on)."""
    return mail_flag().exists()


PAGE_STATUS = {"ok": "ok", "running": "running", "failed": "error", "retry": "error", "refused": "held", "low_confidence": "held"}


def _page_metrics(row: dict) -> dict | None:
    out = {}
    for m in row.get("metrics") or []:
        out[m["label"]] = f"{m['value']} {m['unit']}".strip()
    return out or None


def for_page(row: dict) -> dict | None:
    """One runtime row in the live page's words (trace/FEED-RULES.md), or None for a row the page has no place for;
    nothing here adds a fact the row does not hold."""
    kind, status = row.get("kind", ""), row.get("status", "ok")
    out = {k: row[k] for k in ("ts", "plain", "stage", "stages", "motif", "pid") if row.get(k)}

    def line(type_: str, **fields) -> dict:
        return {**out, "type": type_, **{k: v for k, v in fields.items() if v not in (None, "")}}

    if kind in ("model_call_started", "model_call_completed", "model_call_failed") or (kind in ("tool_invoked", "tool_completed") and row.get("call_id")):
        name = row.get("model") or row.get("tool") or ""
        if not row.get("call_id"):   # a retry announced apart from the call that failed
            return line("thought", thought=row.get("summary"))
        if status == "running":
            return line("call_start", call_id=row["call_id"], model=name, task=row.get("task") or row.get("operation"),
                        status="running", request_id=row.get("request_id"), attempt=row.get("attempt"), word=row.get("word"))
        return line("call_end", call_id=row["call_id"], model=name, status=PAGE_STATUS.get(status, "ok"), summary=row.get("summary"),
                    detail=row.get("detail"), latency_ms=row.get("latency_ms"), request_id=row.get("request_id"),
                    metrics=_page_metrics(row), word=row.get("word"))
    if kind in ("tool_invoked", "tool_completed"):
        if status == "refused":
            return line("held", status="held", summary=row.get("summary"), detail=row.get("detail"))
        return line("tool_failed", status="error", summary=row.get("summary"), detail=row.get("detail")) if status == "failed" else None
    if kind == "tool_skipped":
        return line("tool_skipped", summary=row.get("summary"), detail=row.get("detail"))
    if kind == "job_ended":
        if status == "ok" or not row.get("plain"):
            return None
        return line("self_catch", summary=row.get("summary"), detail=row.get("detail"))
    if kind in ("job_started", "stage"):
        return line("stage", job=row.get("operation"))
    if kind in ("thought", "learned"):
        return line(kind, thought=row.get("thought"), detail=row.get("detail"))
    if kind in ("decision_made", "analysis_generated"):   # shown only when the run gave words a judge can follow
        return line("thought", thought=row["thought"], detail=row.get("detail")) if row.get("thought") else None
    if kind == "verification_completed":
        if status == "ok":
            return line("thought", thought=row.get("thought") or row.get("summary")) if row.get("thought") or row.get("plain") else None
        return line("self_catch", summary=row.get("summary"), detail=row.get("detail"))
    if kind == "message_sent":
        return line("message_sent", direction="out", via=row.get("via"), text=row.get("text"))
    if kind == "email_received":
        return line("email_received", direction="in", via=row.get("via") or "Gmail", **{"from": row.get("sender")},
                    subject=row.get("subject"), text=row.get("text"))
    return out if out.get("plain") or out.get("stage") else None


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

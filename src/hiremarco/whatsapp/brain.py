"""Marco's judgment on WhatsApp: every text Felix sends goes to his brain with the studio's real state and the
conversation so far, and he decides what to do.

Owner 2026-10-30, after "try again" was taken as a song title and "no" was answered blind: "He should know the
difference between an instruction and everything else." The brain picks one action and writes the reply; the code
carries the action out and reports what really happened, so Marco never says he did something he did not do. The
fixed patterns in ``server.instruction`` stay only as the fallback when the brain cannot be reached.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from hiremarco.whatsapp.memory import recall, when

ACTIONS = ("reply", "start", "retry", "rename", "cancel")
SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "title": {"type": "string"},
        "reply": {"type": "string"},
    },
    "required": ["action", "title", "reply"],
    "additionalProperties": False,
}
RULES = """You are answering Felix on WhatsApp. Each message you get carries the time, the real state of his studio \
(read from his Mac a moment ago) and what he just said; the turns before it are your conversation, oldest first, \
with the time each was said. Use all of it: what he asked earlier, what you told him, and what happened since.

Decide one action, then write the text you send him.
- start: set up a Logic session with the beat he sent (studio.beat_sent). Put the song name in title if he gave one.
- retry: a setup failed or stalled (studio.last_setup_attempt) and he wants it tried again. When he fixes the name \
and also asks to set it up or try again, the action is retry, with the fixed name in title.
- rename: he is giving or correcting the song's title. title is required. To undo a wrong title, rename it back \
to the beat's file name without its extension.
- cancel: he does not want the waiting beat set up.
- reply: everything else: a question, a status, chat, or when you are not sure what he wants.

Choose start, retry, rename or cancel only when his words, read with the conversation, clearly ask for it. A short \
reaction ("no", "wait", "what?", "try again") is never a song title. When an instruction is unclear, ask one short \
question with reply. For a status, answer from studio, never from memory.

The text: one or two short sentences, in English unless he asks for another language. The text claims only what \
your action does: with reply, nothing changes, so never say you renamed, dropped, started or retried anything. Never \
say something is done or ready unless studio shows it. After start or retry, say you're on it; the booth texts him when the session is \
ready. If the last setup failed, tell him why in plain words and what you need from him, if anything. Leave title \
empty unless the action is start, retry or rename."""


@dataclass
class Decision:
    action: str
    title: str
    reply: str


def studio(inbox: Path, running: Callable[[], bool]) -> dict:
    """The state the brain reads: the beat he sent, the beat waiting for the booth, the last session set up, the
    booth's last attempt and its result, and whether the booth is running."""
    from hiremarco.studio.beat_in import last_loaded, last_setup, latest_received, pending, requested_name

    def beat(path: Path | None) -> dict | None:
        return None if path is None else {"file": path.name, "title": requested_name(path) or ""}

    waiting = pending(inbox)
    attempt = last_setup(inbox)
    if attempt.get("ts"):
        attempt = {**attempt, "ts": when(datetime.fromisoformat(attempt["ts"]))}
    return {
        "beat_sent": beat(latest_received(inbox)),
        "beat_waiting_for_the_booth": beat(waiting[-1]) if waiting else None,
        "last_session_set_up": beat(last_loaded(inbox)),
        "last_setup_attempt": attempt or None,
        "booth_running": running(),
    }


def history(conn, limit: int = 40) -> list[dict]:
    """The conversation as chat turns, each with the time it was said."""
    return [{"role": "user" if who == "felix" else "assistant", "content": f"[{when(ts)}] {text}"}
            for ts, who, text in recall(conn, limit)]


def decide(marco, said: str, state: dict, turns: list[dict], *, instructions: str = "",
           now: datetime | None = None) -> Decision:
    """One brain call. Raises when the brain cannot be reached or answers outside the schema."""
    asked = json.dumps({"now": when(now or datetime.now(timezone.utc)), "studio": state, "felix_says": said},
                       ensure_ascii=False)
    # live 2026-10-30: at 1500 tokens a "No" was all thinking and no answer; low thinking used 995 of 4000
    reply = marco.converse(turns, asked, instructions=f"{RULES}\n\n{instructions}".strip(), job="whatsapp-brain",
                           max_completion_tokens=4000, reasoning_effort="low",
                           response_format={"type": "json_schema",
                                            "json_schema": {"name": "decision", "schema": SCHEMA, "strict": True}})
    data = json.loads(reply.text)
    if data.get("action") not in ACTIONS or not str(data.get("reply", "")).strip():
        raise ValueError(f"the brain answered outside the schema: {str(data)[:80]}")
    return Decision(data["action"], str(data.get("title") or "").strip(), data["reply"].strip())

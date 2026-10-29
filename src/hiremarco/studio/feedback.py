"""The take note: "Marco, how was that take?" answered by Muse Spark 1.2 listening.

The take goes in as audio, mono 16 kHz WAV, base64 in a Chat Completions
``input_audio`` part. That is Meta's documented shape, and 1.2 is the version
Meta recommends for audio input (dev.meta.ai video and audio understanding
page, read 2026-10-28). The reply comes back as structured output: a short
note Marco can say in the headphones, and whether a punch-in would fix it,
which becomes the question "Want to punch it?". The note says what to fix;
Marco does nothing about it until Felix answers.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass

import numpy as np
import soundfile as sf

from hiremarco import gate
from hiremarco.meta.client import MuseSpark

MODEL = "muse-spark-1.2"
TENANT = "owner"
RATE = 16000
MAX_SECONDS = 6 * 60
PUNCH_QUESTION = "Want to punch it?"

INSTRUCTIONS = (
    "You are Marco, producing a vocal session for an artist; you are in it together. Listen to the take and "
    "give the note a good producer gives between takes: one or two short spoken sentences. When the take is "
    "good, say so like you mean it ('That was a great take, you're killing it') and move to what's next; when "
    "something needs work, be specific about where (the line or the section) and what (pitch, timing, breath, "
    "energy, diction), honest and encouraging, never harsh. If one "
    "short spot would be fixed by recording it again, set punch to true and say where in punch_where; if the "
    "take is a keeper or needs a full new pass, punch is false. Never mention being an AI."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "note": {"type": "string", "description": "one or two short sentences, said aloud between takes"},
        "punch": {"type": "boolean"},
        "punch_where": {"type": "string", "description": "the line or section to punch, else empty"},
    },
    "required": ["note", "punch", "punch_where"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class TakeNote:
    note: str
    punch: bool
    punch_where: str = ""

    @property
    def spoken(self) -> str:
        return f"{self.note} {PUNCH_QUESTION}" if self.punch else self.note


def take_wav(audio: np.ndarray, rate: int) -> bytes:
    """Mono 16-bit WAV at 16 kHz, the last MAX_SECONDS of the take."""
    data = audio.astype(np.float64)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if np.issubdtype(audio.dtype, np.integer):
        data = data / 32768.0
    if rate != RATE and data.size:
        duration = data.size / rate
        target = np.linspace(0, duration, int(round(duration * RATE)), endpoint=False)
        data = np.interp(target, np.arange(data.size) / rate, data)
    data = data[-MAX_SECONDS * RATE:]
    buf = io.BytesIO()
    sf.write(buf, (np.clip(data, -1, 1) * 32767).astype("<i2"), RATE, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def how_was_that_take(audio: np.ndarray, rate: int, *, context: str = "", client: MuseSpark | None = None) -> TakeNote:
    if audio.size == 0:
        raise ValueError("the take is empty")
    question = "How was that take?" + (f" Context: {context}" if context else "")
    gate.check_model_call(TENANT, model=MODEL, system=INSTRUCTIONS, prompt=question,
                          joblog=client.joblog if client else None)
    client = client or MuseSpark()
    wav = base64.b64encode(take_wav(audio, rate)).decode()
    reply = client.chat(
        [
            {"role": "developer", "content": INSTRUCTIONS},
            {"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "input_audio", "input_audio": {"data": wav, "format": "wav"}},
            ]},
        ],
        job="take_feedback", model=MODEL, max_completion_tokens=4000,
        response_format={"type": "json_schema", "json_schema": {"name": "take_note", "schema": SCHEMA, "strict": True}},
    )
    try:
        data = json.loads(reply.text)
        note = str(data["note"]).strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("the note came back unreadable") from exc
    if not note:
        raise ValueError("the note came back empty")
    return TakeNote(note, bool(data.get("punch")), str(data.get("punch_where") or "").strip())

"""The 6176 read: the preamp's settings, from one photo, into the mix notes.

SAM 3.1 finds every knob in the photo first, so the read is anchored to real
controls; then Muse Spark 1.3 looks at the same photo with those boxes listed
by number and says, for each one, the printed label nearest it and where it
points, in structured output. A knob the model skips is left out, not guessed,
and a photo where SAM finds no knob is an error to report, not an empty note.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from hiremarco import gate
from hiremarco.meta.client import MuseSpark
from hiremarco.sam import Box, data_url, segment

MODEL = "muse-spark-1.3"
TENANT = "owner"
PHRASE = "knob"

INSTRUCTIONS = (
    "This photo shows a studio preamp and compressor. Numbered boxes give pixel coordinates of its knobs "
    "(x1, y1 top left; x2, y2 bottom right). For each box you can read, give the printed label nearest the knob "
    "exactly as printed, and its setting: the number on the scale it points at if there is one, else the "
    "clock position (for example 2 o'clock). Leave out any box you cannot read with confidence. Do not guess."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "readings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "knob": {"type": "integer", "description": "the box number"},
                    "label": {"type": "string"},
                    "setting": {"type": "string"},
                },
                "required": ["knob", "label", "setting"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["readings"],
    "additionalProperties": False,
}


class NoKnobsFound(ValueError):
    pass


@dataclass(frozen=True)
class KnobReading:
    knob: int
    label: str
    setting: str
    box: Box


def reading_order(boxes: list[Box]) -> list[Box]:
    """Rows top to bottom, then left to right, the way the panel is read."""
    if not boxes:
        return []
    row_height = max(b.y2 - b.y1 for b in boxes) or 1
    return sorted(boxes, key=lambda b: (round(b.center[1] / row_height), b.center[0]))


def read_6176(photo: bytes, *, mime: str = "image/jpeg", client: MuseSpark | None = None,
              find: Callable[..., list[Box]] = segment) -> list[KnobReading]:
    boxes = reading_order(find(photo, PHRASE, mime=mime, joblog=client.joblog if client else None))
    if not boxes:
        raise NoKnobsFound("SAM found no knob in the photo")
    listing = "\n".join(f"{i}: x1={b.x1} y1={b.y1} x2={b.x2} y2={b.y2}" for i, b in enumerate(boxes, 1))
    prompt = f"Image is {boxes[0].width}x{boxes[0].height} pixels. Knobs:\n{listing}"
    gate.check_model_call(TENANT, model=MODEL, system=INSTRUCTIONS, prompt=prompt,
                          joblog=client.joblog if client else None)
    client = client or MuseSpark()
    reply = client.chat(
        [
            {"role": "developer", "content": INSTRUCTIONS},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url(photo, mime)}},
            ]},
        ],
        job="read_6176", model=MODEL, max_completion_tokens=1500,
        response_format={"type": "json_schema", "json_schema": {"name": "knobs", "schema": SCHEMA, "strict": True}},
    )
    try:
        rows = json.loads(reply.text)["readings"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("the reading came back unreadable") from exc
    readings, seen = [], set()
    for row in rows:
        try:
            knob, label, setting = int(row["knob"]), str(row["label"]).strip(), str(row["setting"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= knob <= len(boxes) and knob not in seen and label and setting:
            seen.add(knob)
            readings.append(KnobReading(knob, label[:40], setting[:40], boxes[knob - 1]))
    return sorted(readings, key=lambda r: r.knob)


def as_note(readings: list[KnobReading]) -> str:
    """The line that goes in MIX_NOTES.md."""
    return "6176: " + "; ".join(f"{r.label} {r.setting}" for r in readings) if readings else "6176: not read"

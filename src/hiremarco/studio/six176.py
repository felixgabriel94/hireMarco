"""The 6176 read: the preamp's settings, from one photo, into the mix notes.

SAM 3.1 finds every knob in the photo first, so the read is anchored to real
controls; then Muse Spark 1.3 looks at the same photo with those boxes listed
by number and says, for each one, the printed label nearest it and where it
points, in structured output. A knob the model skips is left out, not guessed,
and a photo where SAM finds no knob is an error to report, not an empty note.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def find_knobs(photo: bytes, *, mime: str = "image/jpeg", client: MuseSpark | None = None,
               find: Callable[..., list[Box]] = segment) -> list[Box]:
    """SAM's knobs in reading order, numbered as they will be on the picture and in the read."""
    return reading_order(find(photo, PHRASE, mime=mime, joblog=client.joblog if client else None))


def read_6176(photo: bytes, *, mime: str = "image/jpeg", client: MuseSpark | None = None,
              find: Callable[..., list[Box]] = segment, boxes: list[Box] | None = None) -> list[KnobReading]:
    boxes = boxes if boxes is not None else find_knobs(photo, mime=mime, client=client, find=find)
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


# "Marco, save my 6176", "read my 6176", "keep the 6176 settings" (Owner 2026-11-04, film shot): a photo of the unit,
# sent from the glasses like Dress me's, becomes the recall.
SAVE_SAID = re.compile(r"\b(?:save|read|keep|recall|log|remember|note|snap)\b.*\b(?:6176|61 ?76|sixty[- ]one seventy[- ]six)\b|"
                       r"\b(?:6176|61 ?76)\b.*\b(?:settings|recall)\b", re.IGNORECASE)
WINDOW = timedelta(minutes=10)  # "save my 6176" with no photo yet waits this long for it


def wants(said: str) -> bool:
    return bool(SAVE_SAID.search(said or ""))


def _waiting_path() -> Path:
    from hiremarco import config

    return Path(config.STATE_DIR) / "six176-waiting"


def wait_for_photo(said: str, now: datetime | None = None) -> None:
    path = _waiting_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": (now or datetime.now(timezone.utc)).isoformat(), "said": said}))


def waiting(now: datetime | None = None) -> str | None:
    """His words when "save my 6176" came first and the photo has not, within WINDOW; else None."""
    path = _waiting_path()
    try:
        data = json.loads(path.read_text())
        at = datetime.fromisoformat(data["at"])
    except (OSError, ValueError, KeyError):
        return None
    if (now or datetime.now(timezone.utc)) - at > WINDOW:
        return None
    return str(data.get("said") or "save my 6176")


def done_waiting() -> None:
    _waiting_path().unlink(missing_ok=True)


def what_sam_sees(photo: bytes, boxes: list[Box], long_side: int = 1600):
    """The photo with every knob SAM found outlined in its own color and numbered big, like Dress me's first picture."""
    from PIL import Image, ImageDraw

    from hiremarco.dress import COLORS, font

    base = Image.open(io.BytesIO(photo)).convert("RGB")
    width, height = boxes[0].width or base.width, boxes[0].height or base.height  # SAM's coordinates are on its size
    scale = long_side / max(base.size)
    base = base.resize((round(base.width * scale), round(base.height * scale)), Image.LANCZOS)
    sx, sy = base.width / width, base.height / height
    draw = ImageDraw.Draw(base)
    longest = max(base.size)
    ring = max(5, round(longest * 0.006))
    radius = max(18, round(longest * 0.022))
    numbers = font(round(radius * 1.25))
    for i, b in enumerate(boxes, 1):
        color = COLORS[(i - 1) % len(COLORS)]
        x1, y1, x2, y2 = b.x1 * sx, b.y1 * sy, b.x2 * sx, b.y2 * sy
        draw.rectangle((x1, y1, x2, y2), outline=color, width=ring)
        cx = min(max(x1, radius + 4), base.width - radius - 4)
        cy = min(max(y1, radius + 4), base.height - radius - 4)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color, outline=(255, 255, 255),
                     width=max(3, radius // 7))
        draw.text((cx, cy), str(i), font=numbers, fill=(255, 255, 255), anchor="mm",
                  stroke_width=max(2, radius // 14), stroke_fill=(0, 0, 0))
    return base


@dataclass
class Saved:
    note: str
    readings: list[KnobReading] = field(default_factory=list)
    found: int = 0
    picture: Path | None = None


def recall_path() -> Path:
    from hiremarco import config

    return Path(config.STATE_DIR) / "recall" / "6176.jsonl"


def save(photo_path: Path, *, send: Callable[[bytes, str, str], object] | None, client: MuseSpark | None = None,
         find: Callable[..., list[Box]] | None = None, film: Path | None = None, now: datetime | None = None) -> Saved:
    """The whole shot from one photo: SAM finds the knobs, he sends what SAM sees, Spark reads them, and the reading
    is kept as the recall (one line per save, the newest last). ``send(jpeg, caption, step)`` sends one picture."""
    from hiremarco.dress import jpeg_of, png

    client = client or MuseSpark()
    now = now or datetime.now(timezone.utc)
    photo = Path(photo_path).read_bytes()
    boxes = find_knobs(photo, client=client, find=find or segment)
    if not boxes:
        raise NoKnobsFound("SAM found no knob in the photo")
    seen = what_sam_sees(photo, boxes)
    stamp = now.astimezone().strftime("%Y-%m-%d-%H%M%S")
    out = recall_path().parent / f"{stamp}-6176-what-sam-sees.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png(seen))
    if film is not None and film.is_dir():
        (film / out.name).write_bytes(out.read_bytes())
    if send is not None:
        send(jpeg_of(seen), f"I see {len(boxes)} knob{'s' if len(boxes) != 1 else ''}. Reading them now.", "sees")
    readings = read_6176(photo, client=client, boxes=boxes)
    note = as_note(readings)
    if not readings:  # nothing read with confidence is not a recall: the last good one stands
        return Saved(note, [], len(boxes), out)
    with recall_path().open("a") as f:
        f.write(json.dumps({"at": now.isoformat(), "unit": "6176", "note": note, "found": len(boxes),
                            "readings": [{"knob": r.knob, "label": r.label, "setting": r.setting} for r in readings],
                            "photo": str(photo_path), "picture": str(out)}) + "\n")
    return Saved(note, readings, len(boxes), out)


def latest_recall() -> dict | None:
    try:
        lines = recall_path().read_text().strip().splitlines()
    except OSError:
        return None
    return json.loads(lines[-1]) if lines else None

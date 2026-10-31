"""Felix's look, read from his mood board: Marco studies the pictures once and keeps what he sees as facts.

Owner 2026-10-30: his Cosmos board, so Marco dresses him and builds mood boards from his real taste. Each batch of
pictures is described by Muse Spark; one more call pulls the batches into a short set of lines in plain words. Each
line goes into Marco's facts marked "From your mood board", so it stays apart from what Felix said himself, and the
board's link is kept beside them. Nothing is kept that the pictures do not show.
"""

from __future__ import annotations

import json
from pathlib import Path

from hiremarco import config, gate
from hiremarco.meta.client import MuseSpark
from hiremarco.sam import data_url

TENANT = "owner"
BATCH = 10
MARK = "From your mood board"
SEE = """These pictures are from Felix's mood board: what he wants to look like and feel like as an artist. Describe \
only what the pictures show that tells you his taste: clothes and cuts, colors, fabrics and textures, accessories, \
hair, settings, light, mood, and any references you can name for certain. Short phrases, one per line in "notes"; no \
guesses about who anyone is."""
SUM = """These are notes on every picture in Felix's mood board, batch by batch. The board is the vibe he is going \
for, not his wardrobe or his body: the people in it are not Felix, so never say what he wears, has or looks like. \
Write the vibe as at most 12 short lines, each one plain sentence that starts with "The vibe" ("The vibe's palette is \
washed black and cream, never loud color."): palette, light and grain, textures, clothes, accessories, settings, \
mood. Keep what repeats across the board; drop what shows up once. Put the strongest patterns first. Nothing the \
notes do not support."""
NOTES = {"type": "object", "properties": {"notes": {"type": "array", "items": {"type": "string"}}},
         "required": ["notes"], "additionalProperties": False}
LOOK = {"type": "object", "properties": {"look": {"type": "array", "items": {"type": "string"}}},
        "required": ["look"], "additionalProperties": False}


def _ask(client: MuseSpark, system: str, content, schema: dict, job: str, name: str) -> dict:
    gate.check_model_call(TENANT, model=client.model, system=system, prompt=job, joblog=client.joblog)
    reply = client.chat([{"role": "developer", "content": system}, {"role": "user", "content": content}], job=job,
                        max_completion_tokens=4000, reasoning_effort="low",
                        response_format={"type": "json_schema",
                                         "json_schema": {"name": name, "schema": schema, "strict": True}})
    return json.loads(reply.text)


def study(pictures: list[Path], client: MuseSpark | None = None) -> tuple[list[str], list[str]]:
    """(the look in at most 12 lines, every batch's notes). One call per ten pictures, then one to pull them in."""
    client = client or MuseSpark()
    notes: list[str] = []
    for start in range(0, len(pictures), BATCH):
        batch = pictures[start:start + BATCH]
        content = [{"type": "text", "text": f"Pictures {start + 1} to {start + len(batch)} of {len(pictures)}."}]
        content += [{"type": "image_url", "image_url": {"url": data_url(p.read_bytes(), "image/jpeg")}} for p in batch]
        notes += _ask(client, SEE, content, NOTES, "look-see", "notes")["notes"]
    look = _ask(client, SUM, "\n".join(notes), LOOK, "look-sum", "look")["look"]
    return [" ".join(line.split()) for line in look if line.strip()][:12], notes


def keep_look(conn, look: list[str], board: str) -> int:
    """The look and the board's link into Marco's facts, each marked as read from the board. How many were new."""
    from hiremarco.whatsapp.facts import keep

    kept = sum(keep(conn, f"{MARK}: {line}") for line in look)
    kept += keep(conn, f"Your mood board is {board}")
    return kept


def run(folder: Path, board: str, client: MuseSpark | None = None, conn=None) -> str:
    pictures = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))
    if not pictures:
        return f"no pictures in {folder}"
    look, notes = study(pictures, client)
    (config.STATE_DIR / "look.json").write_text(json.dumps({"board": board, "pictures": len(pictures),
                                                            "look": look, "notes": notes}, ensure_ascii=False,
                                                           indent=1))
    kept = keep_look(conn or gate.connect(), look, board)
    return f"{len(pictures)} pictures, {len(look)} lines of his look, {kept} new facts"

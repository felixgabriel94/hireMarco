"""Photos Felix sends Marco on WhatsApp: kept, remembered, and seen.

Owner 2026-11-01: any photo he sends is downloaded into a dated folder under the state dir, one row in the gate's
database, and one line in the conversation; Muse Spark sees it, so Marco answers about any photo, not only clothes.
The caption is his words. The words can also come just before the photo or just after it, as a text or a voice note:
a photo counts as his latest for ten minutes.
"""

from __future__ import annotations

import io
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hiremarco import config, gate
from hiremarco.whatsapp.memory import remember, when

WINDOW = timedelta(minutes=10)
TENANT = "owner"
MODEL = "muse-spark-1.3"
LONG_SIDE = 2048  # what the models see; a phone photo is cut down to this, turned upright

SCHEMA = """
create table if not exists photos (
    id integer primary key autoincrement,
    ts text not null,
    message_id text not null,
    path text not null,
    caption text not null default ''
);
"""

SEE = ("Felix sent you this photo on WhatsApp. If he said something with it, answer that, about the photo. If he "
       "said nothing, say in one short line what you see and ask what he wants you to do with it. One or two short "
       "sentences. Say only what the photo shows; no guesses about who anyone is.")


@dataclass(frozen=True)
class Photo:
    id: int
    ts: datetime
    message_id: str
    path: Path
    caption: str

    def jpeg(self) -> bytes:
        return self.path.read_bytes()


def folder(now: datetime | None = None) -> Path:
    return config.STATE_DIR / "photos" / (now or datetime.now(timezone.utc)).astimezone().strftime("%Y-%m-%d")


def upright(data: bytes, long_side: int = LONG_SIDE) -> bytes:
    """The photo as the models and the boards use it: turned the way the phone held it, RGB, at most ``long_side``
    pixels on its longer side, JPEG. One copy for everyone, so a box SAM draws lands on the same pixels later."""
    from PIL import Image, ImageOps

    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    image.thumbnail((long_side, long_side))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=92)
    return out.getvalue()


def keep(conn: sqlite3.Connection, data: bytes, message_id: str, caption: str = "",
         now: datetime | None = None) -> Photo:
    """A photo he sent, saved upright in today's folder and remembered in the conversation."""
    now = now or datetime.now(timezone.utc)
    where = folder(now)
    where.mkdir(parents=True, exist_ok=True)
    path = where / f"{now.astimezone().strftime('%H%M%S')}-{(message_id or 'photo')[-6:]}.jpg"
    path.write_bytes(upright(data))
    conn.executescript(SCHEMA)
    cur = conn.execute("insert into photos (ts, message_id, path, caption) values (?, ?, ?, ?)",
                       (now.isoformat(), message_id, str(path), caption or ""))
    conn.commit()
    remember(conn, "felix", f"[sent a photo: {path.name}] {caption or ''}".strip(), ts=now)
    return Photo(cur.lastrowid, now, message_id, path, caption or "")


def latest(conn: sqlite3.Connection, now: datetime | None = None, window: timedelta = WINDOW) -> Photo | None:
    """His last photo, when he sent it within ``window``."""
    conn.executescript(SCHEMA)
    row = conn.execute("select id, ts, message_id, path, caption from photos order by id desc limit 1").fetchone()
    if row is None:
        return None
    photo = Photo(row[0], datetime.fromisoformat(row[1]), row[2], Path(row[3]), row[4])
    if (now or datetime.now(timezone.utc)) - photo.ts > window or not photo.path.exists():
        return None
    return photo


def on_its_way(conn: sqlite3.Connection, sender: str, now: datetime | None = None,
               window: timedelta = WINDOW) -> bool:
    """A photo from him reached the webhook within ``window`` but is not kept yet (it is still downloading)."""
    from hiremarco.whatsapp.client import INBOUND_SCHEMA

    conn.executescript(INBOUND_SCHEMA + SCHEMA)
    since = ((now or datetime.now(timezone.utc)) - window).isoformat()
    arrived = {r[0] for r in conn.execute("select wa_message_id from inbound where from_number = ? and kind = 'image' "
                                          "and ts >= ?", (sender.lstrip("+"), since))}
    kept = {r[0] for r in conn.execute("select message_id from photos where ts >= ?", (since,))}
    return bool(arrived - kept)


def wait_for(conn: sqlite3.Connection, sender: str, *, now=None, sleep=None, tries: int = 15,
             step_s: float = 2.0) -> Photo | None:
    """His last photo; when one is still downloading, wait for it a little (up to ``tries`` x ``step_s``)."""
    import time

    for _ in range(tries):
        photo = latest(conn, now() if now else None)
        if photo is not None or not on_its_way(conn, sender, now() if now else None):
            return photo
        (sleep or time.sleep)(step_s)
    return latest(conn, now() if now else None)


def newer_from(conn: sqlite3.Connection, sender: str, message_id: str) -> bool:
    """He has written again since this message reached the webhook."""
    from hiremarco.whatsapp.client import INBOUND_SCHEMA

    conn.executescript(INBOUND_SCHEMA)
    row = conn.execute("select ts from inbound where wa_message_id = ?", (message_id,)).fetchone()
    if row is None:
        return False
    return conn.execute("select 1 from inbound where from_number = ? and ts > ? and wa_message_id != ? limit 1",
                        (sender.lstrip("+"), row[0], message_id)).fetchone() is not None


def attached(photo: Photo) -> str:
    """How the brain is told the photo it sees is his: when he sent it and what he said with it."""
    return f"the photo he sent {when(photo.ts)}" + (f", saying: {photo.caption}" if photo.caption else "")


def see(photo: Photo, said: str, client=None, instructions: str = "") -> str:
    """Marco's answer about one photo, with his words if there are any."""
    from hiremarco.marco import persona, private_persona_on
    from hiremarco.meta.client import MuseSpark
    from hiremarco.sam import data_url

    client = client or MuseSpark()
    if private_persona_on() and client.model.endswith("-contributor"):
        raise gate.Refused("the private persona never goes to a contributor model")
    system = f"{persona()}\n\n{SEE}" + (f"\n\n{instructions}" if instructions else "")
    words = said.strip() or "(he sent the photo without a word)"
    gate.check_model_call(TENANT, model=MODEL, system=system, prompt=words, joblog=client.joblog)
    reply = client.chat([{"role": "developer", "content": system},
                         {"role": "user", "content": [{"type": "text", "text": words},
                                                      {"type": "image_url",
                                                       "image_url": {"url": data_url(photo.jpeg(), "image/jpeg")}}]}],
                        job="whatsapp-photo", model=MODEL, max_completion_tokens=1500, reasoning_effort="low")
    return reply.text.strip()

"""The selects: Felix sends the frames of a shoot, Marco sends back what SAM sees and his best three.

Owner 2026-11-01, the film's second scene: dressed for the day, Felix shoots in his building, sends 10 to 20 frames on
WhatsApp and says "Marco, pick my selects". SAM 3.1 finds him in each frame, one call per frame in parallel (several
people: the largest is kept and the log says so). From his mask Marco measures how much of the frame he fills, whether
he is cut off at an edge, how sharp he is and how the light falls on him. One contact sheet goes out first, every frame
numbered with him tinted and outlined, made to read at phone size. Muse Spark then gets the frames, the measures, the
mood board and his words and returns exactly three numbers, each with one honest line, plus one line on what the others
missed; a number that is not a frame with him in it is thrown out. The three come back as three separate pictures, one
after another, each his own pixels with its line as the caption. Nothing here edits a frame.
"""

from __future__ import annotations

import io
import json
import math
import re
import shutil
import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from hiremarco import config, gate
from hiremarco.dress import Piece, _full_mask, _piece, font, jpeg_of, mood_board, png
from hiremarco.sam import Found, SamError, data_url, segment_masks

TENANT = "owner"
MODEL = "muse-spark-1.3"
PHRASE = "person"
MIN_CONFIDENCE = 0.5
MIN_FILL = 0.02       # smaller than this in the frame and he is not usable: a stranger across the lobby, not him
SAM_SIDE = 1280       # what SAM gets: masks are drawn back up, and a smaller upload is what keeps a shoot under a minute
SAM_WORKERS = 8       # 8 at once held at 1.5 to 5.5 s a call (live 2026-11-01)
WINDOW = timedelta(minutes=90)
CAP = 30
HOW_MANY = 3
BURST_MIN = 3         # this many frames close together is a burst, not a photo he wants talked about
BURST_GAP = timedelta(seconds=60)
QUIET_S = 45.0        # a burst is acknowledged after this long with nothing new from him
RUN_FOR = timedelta(minutes=5)  # a run this old with no end died; its frames are free again
TINT = (10, 132, 255)
SHEET = (1800, 2400)  # upright: what fills a phone held in the hand
DARK = (24, 24, 27)

INSTRUCTIONS = """Felix just did a short photo shoot of himself and sent you the frames. Choose his selects the way a \
photographer he trusts would. The first image is every frame, numbered. The second is the same frames with him tinted, \
so you can see where he is. The list gives what was measured on him in each frame. Pick exactly the number of frames \
in pick_exactly, best first, only from can_pick. For each one write one honest line on why it works: the framing, the \
light, his energy, the look. If it has a flaw worth knowing, say so in the same line. Then write one line on what the \
others missed, in the same plain voice. His mood board is the vibe he is going for, not a checklist. Short plain words, \
the way you text him. No scores, no percentages, no frame numbers in the lines. Say only what the frames show; do not \
flatter. Never mention tints, masks, measuring, tools or how you see. Never suggest editing or retouching a frame. Not \
a word about a release, posting, a cover or where the photos will go."""

SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {"type": "array", "items": {
            "type": "object",
            "properties": {"frame": {"type": "integer"}, "line": {"type": "string"}},
            "required": ["frame", "line"],
            "additionalProperties": False,
        }},
        "others": {"type": "string"},
    },
    "required": ["picks", "others"],
    "additionalProperties": False,
}

STATE_SCHEMA = """
create table if not exists selects (
    id integer primary key autoincrement,
    ts text not null,
    status text not null,
    last_photo integer not null,
    frames integer not null default 0,
    picks text not null default '',
    folder text not null default ''
);
"""

ASK = re.compile(
    r"\bselects\b|\bselex\b"
    r"|\bbest (?:three|3)\b(?:\s+(?:frames|shots|photos|pictures|pics|images|ones|of (?:them|these|those)))?"
    r"(?:,?\s*marco)?\W*$"
    r"|\b(?:pick|choose|which are|what are|show me|give me)\b.*\bbest\b.*\b(?:frames?|shots?|photos?|pictures?|pics|"
    r"images|ones)(?:,?\s*marco)?\W*$"
    r"|\bwhich (?:frames?|shots?|photos?|pictures?|pics|ones)\b.*\b(?:best|keep|keepers)\b", re.I)
ABOUT_A_PHOTO = re.compile(r"\b(?:this|these|that one|photo|photos|picture|pictures|pic|pics|shot|shots|frame|frames)\b",
                           re.I)
# what must not reach him under a picture: an internal, a score, or the things this scene is not about
OFF = re.compile(r"\b(?:masks?|tint(?:ed|s)?|measur\w*|sam|segment\w*|score\w*|sharpness|release\w*|posting|"
                 r"post it|instagram|album|campaign|cover art|retouch\w*|photoshop\w*)\b|\d\s*%|\d\.\d|\d\s*/\s*10\b", re.I)


class NoOneFound(ValueError):
    pass


class PickError(ValueError):
    pass


def wants(said: str) -> bool:
    """"Marco, pick my selects", "which are the best three?", a voice note saying either."""
    return bool(ASK.search(said or ""))


def about_a_photo(said: str) -> bool:
    return bool(ABOUT_A_PHOTO.search(said or ""))


# --- the set of frames --------------------------------------------------------------------------------------------

def _state(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(STATE_SCHEMA)
    return conn


def _since(conn: sqlite3.Connection, now: datetime) -> int:
    """The newest photo the shoot does not include: the clothes of the last Dress me, or the last selects' last frame."""
    from hiremarco import dress
    from hiremarco.whatsapp import photos

    conn.executescript(photos.SCHEMA)
    dress._state(conn)
    row = conn.execute("select max(p.id) from photos p join dress d on d.photo = p.path").fetchone()
    last = row[0] or 0
    stale = (now - RUN_FOR).isoformat()
    row = _state(conn).execute("select max(last_photo) from selects where status = 'done' or (status = 'running' and "
                               "ts >= ?)", (stale,)).fetchone()
    return max(last, row[0] or 0)


def shoot(conn: sqlite3.Connection, now: datetime | None = None) -> tuple[list, int]:
    """The frames of the current shoot, oldest first, at most ``CAP`` (the latest ones), and how many there were."""
    from hiremarco.whatsapp import photos

    now = now or datetime.now(timezone.utc)
    rows = conn.execute("select id, ts, message_id, path, caption from photos where id > ? and ts >= ? order by id",
                        (_since(conn, now), (now - WINDOW).isoformat())).fetchall()
    frames = [photos.Photo(r[0], datetime.fromisoformat(r[1]), r[2], Path(r[3]), r[4]) for r in rows]
    frames = [f for f in frames if f.path.exists()]
    return frames[-CAP:], len(frames)


def burst(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """How many of the shoot's frames came together, counting back from the newest with no long gap between them."""
    frames, _ = shoot(conn, now)
    count = 1 if frames else 0
    for older, newer in zip(reversed(frames[:-1]), reversed(frames[1:])):
        if newer.ts - older.ts > BURST_GAP:
            break
        count += 1
    return count


def taken(conn: sqlite3.Connection, photo, now: datetime | None = None) -> bool:
    """A selects run has this frame already, finished or still going."""
    return photo.id <= _since(conn, now or datetime.now(timezone.utc))


def running(conn: sqlite3.Connection, now: datetime | None = None) -> bool:
    stale = ((now or datetime.now(timezone.utc)) - RUN_FOR).isoformat()
    return _state(conn).execute("select 1 from selects where status = 'running' and ts >= ? limit 1",
                                (stale,)).fetchone() is not None


def begin(conn: sqlite3.Connection, last_photo: int, frames: int, now: datetime | None = None) -> int:
    cur = _state(conn).execute("insert into selects (ts, status, last_photo, frames) values (?, 'running', ?, ?)",
                               ((now or datetime.now(timezone.utc)).isoformat(), last_photo, frames))
    conn.commit()
    return cur.lastrowid


def finish(conn: sqlite3.Connection, row: int, status: str, picks: list[int] | None = None, folder: str = "") -> None:
    conn.execute("update selects set status = ?, picks = ?, folder = ? where id = ?",
                 (status, json.dumps(picks or []), folder, row))
    conn.commit()


# --- SAM and the measures -----------------------------------------------------------------------------------------

@dataclass
class Frame:
    number: int
    path: Path                     # upright, what the models and the phone see
    original: Path                 # as he sent it, full resolution
    size: tuple[int, int] = (0, 0)
    person: Piece | None = None
    people: int = 0
    fill: float = 0.0              # share of the frame he covers
    cut: list[str] = field(default_factory=list)   # the frame edges his mask reaches
    sharp: float = 0.0             # variance of the Laplacian inside his mask, at one fixed size
    light: float = 0.0             # mean brightness on him, 0 to 1
    blown: float = 0.0             # share of him at pure white
    crushed: float = 0.0           # share of him at pure black
    failed: bool = False           # SAM could not be asked about this frame

    @property
    def usable(self) -> bool:
        return self.person is not None and self.fill >= MIN_FILL


def measure(frame: Frame, photo: Image.Image, side: int = 1024) -> None:
    """Fill, cut, sharpness and exposure from his mask. Sharpness and light are read at one size, so frames compare."""
    p = frame.person
    if p is None:
        return
    w, h = photo.size
    frame.fill = p.area() / float(w * h)
    margin = max(1, round(0.01 * max(w, h)))
    frame.cut = [edge for edge, hit in (("top", p.box[1] <= margin), ("bottom", p.box[3] >= h - 1 - margin),
                                        ("left", p.box[0] <= margin), ("right", p.box[2] >= w - 1 - margin)) if hit]
    scale = min(1.0, side / max(w, h))
    small = (max(1, round(w * scale)), max(1, round(h * scale)))
    gray = np.asarray(photo.convert("L").resize(small, Image.BILINEAR), dtype=np.float32)
    mask = _full_mask(p, small, scale)
    # his outline against the wall is the strongest edge in the frame and says nothing about focus: read inside it
    inner = np.asarray(mask.filter(ImageFilter.MinFilter(11))) > 127
    whole = np.asarray(mask) > 127
    inner = inner if inner.sum() >= 50 else whole
    if whole.sum() == 0:
        return
    laplacian = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4 * gray[1:-1, 1:-1]
    inside = laplacian[inner[1:-1, 1:-1]]
    frame.sharp = float(inside.var()) if inside.size else 0.0
    on_him = gray[whole]
    frame.light = float(on_him.mean() / 255)
    frame.blown = float((on_him >= 250).mean())
    frame.crushed = float((on_him <= 5).mean())


def find_him(frame: Frame, *, find: Callable[..., list[Found]] | None = None, joblog=None,
             wait: Callable[[float], None] = time.sleep) -> str | None:
    """One SAM call for the frame, tried once more if it fails. A line for the log when the frame needs one."""
    find = find or segment_masks
    photo = Image.open(frame.path).convert("RGB")
    frame.size = photo.size
    small = photo.copy()
    small.thumbnail((SAM_SIDE, SAM_SIDE))
    out = io.BytesIO()
    small.save(out, "JPEG", quality=88)
    for attempt in (1, 2):
        try:
            found = find(out.getvalue(), PHRASE, mime="image/jpeg", min_confidence=MIN_CONFIDENCE, joblog=joblog)
            break
        except SamError as exc:
            if attempt == 2:
                frame.failed = True
                return f"frame {frame.number}: {exc}"
            wait(1.0)
    pieces = [_piece(f, PHRASE, photo.size) for f in found if f.box.confidence >= MIN_CONFIDENCE]
    frame.people = len(pieces)
    if pieces:
        frame.person = max(pieces, key=lambda p: p.area())
        measure(frame, photo)
    return f"frame {frame.number}: {len(pieces)} people, kept the largest" if len(pieces) > 1 else None


def find_all(frames: list[Frame], *, find=None, joblog=None, wait=time.sleep) -> list[str]:
    """Every frame at once, ``SAM_WORKERS`` at a time. Only when every call fails is it an error."""
    with ThreadPoolExecutor(max_workers=SAM_WORKERS) as pool:
        lines = list(pool.map(lambda f: find_him(f, find=find, joblog=joblog, wait=wait), frames))
    if frames and all(f.failed for f in frames):
        raise SamError("every segmentation call failed")
    return [line for line in lines if line]


# --- drawing -----------------------------------------------------------------------------------------------------

def _grid(n: int, aspect: float, canvas: tuple[int, int], gap: int) -> tuple[int, int, int, int]:
    """Columns, rows and the cell size that make each frame largest on the canvas."""
    best = (1, n, 1, 1)
    best_w = 0.0
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        w = min((canvas[0] - gap * (cols + 1)) / cols, (canvas[1] - gap * (rows + 1)) / rows * aspect)
        if w > best_w:
            best_w, best = w, (cols, rows, max(1, int(w)), max(1, int(w / aspect)))
    return best


def contact_sheet(frames: list[Frame], tinted: bool = True, canvas: tuple[int, int] = SHEET) -> Image.Image:
    """Every frame in one picture, numbered big in its corner. ``tinted``: him tinted and outlined, for the phone; else
    the plain frames, for choosing. A frame with nobody found is dimmed."""
    gap = 14
    aspects = sorted(f.size[0] / f.size[1] for f in frames) or [1.0]
    cols, rows, cell_w, cell_h = _grid(len(frames), aspects[len(aspects) // 2], canvas, gap)
    sheet = Image.new("RGB", (cols * cell_w + gap * (cols + 1), rows * cell_h + gap * (rows + 1)), DARK)
    radius = max(26, round(min(cell_w, cell_h) * 0.15))
    numbers = font(round(radius * 1.2))
    for i, frame in enumerate(frames):
        photo = Image.open(frame.path).convert("RGB")
        scale = min(cell_w / photo.width, cell_h / photo.height)
        small = photo.resize((max(1, round(photo.width * scale)), max(1, round(photo.height * scale))), Image.LANCZOS)
        small = small.convert("RGBA")
        if tinted and frame.person is not None:
            mask = _full_mask(frame.person, small.size, scale)
            tint = Image.new("RGBA", small.size, (0, 0, 0, 0))
            tint.paste((*TINT, 120), mask=mask)
            ring = max(5, round(max(small.size) * 0.016)) | 1
            edge = mask.filter(ImageFilter.GaussianBlur(ring / 2)).point(lambda v: 255 if 24 < v < 232 else 0)
            tint.paste((*TINT, 255), mask=edge)
            small = Image.alpha_composite(small, tint)
        elif tinted:
            small = Image.blend(small, Image.new("RGBA", small.size, (*DARK, 255)), 0.6)
        x = gap + (i % cols) * (cell_w + gap) + (cell_w - small.width) // 2
        y = gap + (i // cols) * (cell_h + gap) + (cell_h - small.height) // 2
        sheet.paste(small.convert("RGB"), (x, y))
        draw = ImageDraw.Draw(sheet)
        cx, cy = x + radius + 8, y + radius + 8
        color = TINT if frame.person is not None or not tinted else (110, 110, 115)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color, outline=(255, 255, 255),
                     width=max(3, radius // 8))
        draw.text((cx, cy), str(frame.number), font=numbers, fill=(255, 255, 255), anchor="mm",
                  stroke_width=max(1, radius // 16), stroke_fill=(0, 0, 0))
    return sheet


def combined(chosen: list[Frame], long_side: int = 2400) -> Image.Image:
    """The picks together for the film folder, numbered above his untouched pixels: tall frames side by side, wide ones
    stacked. Never sent; he gets them one at a time."""
    photos = [Image.open(f.path).convert("RGB") for f in chosen]
    side_by_side = sum(p.width for p in photos) <= sum(p.height for p in photos)
    band, gap = 130, 20
    labels = font(96)
    if side_by_side:
        height = min(long_side * 3 // 4, max(p.height for p in photos))
        sized = [p.resize((round(p.width * height / p.height), height), Image.LANCZOS) for p in photos]
        canvas = Image.new("RGB", (sum(p.width for p in sized) + gap * (len(sized) + 1), height + band + gap), DARK)
    else:
        width = min(long_side * 3 // 4, max(p.width for p in photos))
        sized = [p.resize((width, round(p.height * width / p.width)), Image.LANCZOS) for p in photos]
        canvas = Image.new("RGB", (width + 2 * gap, sum(p.height + band for p in sized) + gap), DARK)
    draw = ImageDraw.Draw(canvas)
    x, y = gap, 0
    for frame, picture in zip(chosen, sized):
        draw.text((x, y + band // 2), str(frame.number), font=labels, fill=(255, 255, 255), anchor="lm")
        canvas.paste(picture, (x, y + band))
        x, y = (x + picture.width + gap, y) if side_by_side else (x, y + band + picture.height)
    return canvas


# --- the pick -----------------------------------------------------------------------------------------------------

@dataclass
class Picks:
    picks: list[tuple[int, str]]
    others: str
    thrown: list[int] = field(default_factory=list)  # numbers the model named that are not frames he is in


def checked(data: dict, can_pick: set[int], need: int) -> Picks:
    """Exactly ``need`` frames he is in, each with its line. A number that is not one is thrown out; too few left, a
    line missing or a line that should not reach him fails the answer."""
    picks, thrown = [], []
    for row in data.get("picks") or []:
        try:
            number = int(row.get("frame"))
        except (TypeError, ValueError):
            continue
        if number not in can_pick:
            thrown.append(number)
        elif number not in [n for n, _ in picks]:
            picks.append((number, " ".join(str(row.get("line") or "").split())[:300]))
    picks = picks[:need]
    if len(picks) < need:
        raise PickError(f"{len(picks)} real frames came back, not {need}")
    others = " ".join(str(data.get("others") or "").split())[:300]
    for number, line in picks:
        if not line:
            raise PickError(f"frame {number} came back with no line")
    if any(OFF.search(line) for _, line in picks):
        raise PickError("a line would have shown him a score or the wrong subject")
    return Picks(picks, "" if OFF.search(others) else others, thrown)  # the closing line is worth less than the scene


def pick(frames: list[Frame], plain_jpeg: bytes, seen_jpeg: bytes, said: str, *, mood: list[str], facts: list[str],
         client=None) -> Picks:
    """Muse Spark's picks, held to the frames he is in. A wrong answer gets one more try, then fails."""
    from hiremarco.marco import persona, private_persona_on
    from hiremarco.meta.client import MuseSpark

    client = client or MuseSpark()
    if private_persona_on() and client.model.endswith("-contributor"):
        raise gate.Refused("the private persona never goes to a contributor model")
    usable = [f for f in frames if f.usable]
    need = min(HOW_MANY, len(usable))
    sharpest = max((f.sharp for f in usable), default=0.0) or 1.0
    listing = [{"frame": f.number, "he_fills_of_the_frame": f"{f.fill:.0%}", "cut_off_at": f.cut,
                "sharpness_against_the_sharpest_frame": round(f.sharp / sharpest, 2),
                "light_on_him_0_dark_1_bright": round(f.light, 2), "blown_out": f"{f.blown:.0%}",
                "crushed_black": f"{f.crushed:.0%}", **({"people_in_frame": f.people} if f.people > 1 else {})}
               for f in usable]
    prompt = json.dumps({"felix_says": said, "pick_exactly": need, "can_pick": [f.number for f in usable],
                         "frames": listing, "mood_board": mood, "facts": facts}, ensure_ascii=False)
    system = f"{persona()}\n\n{INSTRUCTIONS}"
    gate.check_model_call(TENANT, model=MODEL, system=system, prompt=prompt, joblog=client.joblog)
    failure = None
    for _ in range(2):
        reply = client.chat(
            [{"role": "developer", "content": system},
             {"role": "user", "content": [
                 {"type": "text", "text": prompt},
                 {"type": "image_url", "image_url": {"url": data_url(plain_jpeg, "image/jpeg")}},
                 {"type": "image_url", "image_url": {"url": data_url(seen_jpeg, "image/jpeg")}},
             ]}],
            job="selects-pick", model=MODEL, max_completion_tokens=4000, reasoning_effort="low",
            response_format={"type": "json_schema", "json_schema": {"name": "selects", "schema": SCHEMA,
                                                                    "strict": True}})
        try:
            return checked(json.loads(reply.text), {f.number for f in usable}, need)
        except ValueError as exc:  # PickError is one; unreadable JSON is another
            failure = exc
    raise PickError(str(failure))


# --- the run ------------------------------------------------------------------------------------------------------

@dataclass
class Selected:
    frames: list[Frame]
    picks: Picks
    sheet: Path
    together: Path
    folder: Path
    originals: list[Path]
    copies: list[Path]
    log: list[str]
    seconds: dict[str, float]


def _keep(path: Path, film: Path | None, name: str, copies: list[Path]) -> None:
    if film is not None and film.is_dir():
        shutil.copyfile(path, film / name)
        copies.append(film / name)


def run(frames: list[tuple[Path, Path]], said: str, *, conn: sqlite3.Connection,
        send: Callable[[bytes | None, str, str], object] | None, client=None, find=None, film: Path | None = None,
        now: datetime | None = None, noted: str = "", pause: Callable[[float], None] = time.sleep) -> Selected:
    """The whole scene from (upright, original) pairs. ``send(picture, text, step)`` sends one picture to him, or one
    text when picture is None; None for a dry run, which only writes the files."""
    from hiremarco.meta.client import MuseSpark
    from hiremarco.whatsapp.facts import block

    client = client or MuseSpark()
    now = now or datetime.now(timezone.utc)
    clock = time.monotonic()
    seconds: dict[str, float] = {}
    all_frames = [Frame(i, upright, original) for i, (upright, original) in enumerate(frames, 1)]
    log = find_all(all_frames, find=find, joblog=client.joblog, wait=pause)
    seconds["sam"] = time.monotonic() - clock
    usable = [f for f in all_frames if f.usable]
    if not usable:
        raise NoOneFound(f"nobody found in {len(all_frames)} frames")

    stamp = now.astimezone().strftime("%Y-%m-%d-%H%M%S")
    folder = config.STATE_DIR / "selects" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    copies: list[Path] = []
    step = time.monotonic()
    seen = contact_sheet(all_frames)
    sheet = folder / "contact-sheet.png"
    sheet.write_bytes(png(seen))
    _keep(sheet, film, f"{stamp}-selects-contact-sheet.png", copies)
    seconds["sheet"] = time.monotonic() - step
    seen_jpeg = jpeg_of(seen)
    if send is not None:
        step = time.monotonic()
        total = len(all_frames)
        where = f"I've got you in all {total} frames." if len(usable) == total else \
            f"I can see you in {len(usable)} of {total} frames."
        send(seen_jpeg, f"{where} {noted}Going through them now.", "sees")
        seconds["send_sheet"] = time.monotonic() - step

    step = time.monotonic()
    picks = pick(all_frames, jpeg_of(contact_sheet(all_frames, tinted=False)), seen_jpeg, said, mood=mood_board(conn),
                 facts=block(conn, said), client=client)
    seconds["pick"] = time.monotonic() - step
    log += [f"threw out frame {n}: not a frame he is in" for n in picks.thrown]

    by_number = {f.number: f for f in all_frames}
    chosen = [by_number[n] for n, _ in picks.picks]
    together = folder / "selects.png"
    together.write_bytes(png(combined(chosen)))
    _keep(together, film, f"{stamp}-selects.png", copies)
    originals = []
    for frame in chosen:
        kept = folder / f"select-{frame.number:02d}{frame.original.suffix.lower()}"
        shutil.copyfile(frame.original, kept)
        originals.append(kept)
        _keep(kept, film, f"{stamp}-{kept.name}", copies)
    if send is not None:
        step = time.monotonic()
        for i, (frame, (number, line)) in enumerate(zip(chosen, picks.picks)):
            if i:
                pause(1.0)  # WhatsApp shows them in the order they land
            send(frame.path.read_bytes(), f"{number}. {line}", f"pick-{number}")
        closing = " ".join(part for part in (
            f"Only {len(usable)} frame{'s' if len(usable) != 1 else ''} had you in {'them' if len(usable) != 1 else 'it'}"
            f", so that's all I could pick." if len(usable) < HOW_MANY else "",
            picks.others if len(usable) > len(chosen) else "") if part)
        if closing:
            pause(1.0)
            send(None, closing, "others")
        seconds["send_picks"] = time.monotonic() - step
    seconds["total"] = time.monotonic() - clock
    return Selected(all_frames, picks, sheet, together, folder, originals, copies, log, seconds)

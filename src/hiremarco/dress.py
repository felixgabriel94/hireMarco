"""Dress me: the clothes on the bed become three looks, A, B and C, built only from his real pieces.

Owner 2026-11-01, the film's first scene: Felix lays his clothes out, the glasses send the photo, he says "Marco,
dress me. Studio today, dinner tonight." SAM 3.1 finds each piece (one call per noun phrase, low confidence dropped,
the same piece found by two phrases kept once, a pair of shoes kept as one) and cuts it out on its mask, or on its box
when no mask can be read. Marco first shows what SAM sees: the photo with every piece tinted, outlined and numbered,
big enough for the lens. Muse Spark then gets the photo, the numbered pieces, the mood board and his words, and
returns three looks in structured output; a piece number that is not in the photo is thrown out, and a look left
with no real piece fails the run rather than reach him. The board is built from the cut-outs themselves on a backdrop
Muse Image painted once (never a drawn piece of clothing). His answer, "B", locks the look in as a dated fact.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from hiremarco import config, gate
from hiremarco.sam import Found, SamError, data_url, segment_masks

TENANT = "owner"
MODEL = "muse-spark-1.3"
PHRASES = ("shirt", "t-shirt", "sweater", "hoodie", "jacket", "pants", "jeans", "shorts", "shoes", "sneakers", "boots",
           "hat", "cap", "sunglasses", "watch", "bag")
PAIRS = {"shoes", "sneakers", "boots"}
MIN_CONFIDENCE = 0.5
SAME_PIECE = 0.5      # two finds overlapping this much (intersection over union) are one piece
MAX_PIECES = 12
LETTERS = ("A", "B", "C")
OPEN_FOR = timedelta(hours=12)  # a board waits this long for his pick
WINDOW = timedelta(minutes=10)  # "dress me" waits this long for the photo
BACKDROP = "backdrop.png"
BACKDROP_PROMPT = (
    "A calm, empty backdrop for a fashion look board: warm off-white paper with a fine texture, soft natural window "
    "light falling from the left, a gentle shadow gradient toward the bottom. Minimal and quiet. No people, no "
    "clothes, no objects, no text, no letters, no logos.")

COLORS = [(255, 59, 48), (0, 122, 255), (52, 199, 89), (255, 149, 0), (175, 82, 222), (255, 45, 85),
          (90, 200, 250), (255, 204, 0), (88, 86, 214), (0, 199, 190), (162, 132, 94), (142, 142, 147)]
INK = (29, 29, 31)
ACCENT = (255, 59, 48)
FONTS = ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

INSTRUCTIONS = """Felix laid his clothes out and asked you to dress him. The first image is his photo. The second is \
the same photo with every piece found in it tinted and numbered; the list gives each number and what it is. Build \
exactly three looks, A, B and C, for the day he describes, each made only of numbered pieces: a piece may be in more \
than one look, a piece that is not numbered may not be in any. Each look has a name of at most three words, its piece \
numbers, and one plain line on why it works for his day. Each look is one outfit for everything he names that day: \
when he names more than one stop ("shoot first, then the studio"), every look works for all of them with no change of \
clothes, never one look per stop. Choose with his mood board in mind: it is the vibe he is \
going for, not his wardrobe. Then recommend one, and write the caption he reads under the board: one or two short \
sentences in your voice, naming your pick and why, ending by asking him A, B or C. Plain words; never mention the \
tools, the numbers' source or how you see."""

SCHEMA = {
    "type": "object",
    "properties": {
        "looks": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "letter": {"type": "string", "enum": list(LETTERS)},
                "name": {"type": "string"},
                "pieces": {"type": "array", "items": {"type": "integer"}},
                "line": {"type": "string"},
            },
            "required": ["letter", "name", "pieces", "line"],
            "additionalProperties": False,
        }},
        "recommend": {"type": "string", "enum": list(LETTERS)},
        "caption": {"type": "string"},
    },
    "required": ["looks", "recommend", "caption"],
    "additionalProperties": False,
}

WARM = ("Felix just picked the look below for today. Write him one warm line back, in your voice, the way a friend "
        "who dressed him would text: short, no question, no list of the clothes.")

STATE_SCHEMA = """
create table if not exists dress (
    id integer primary key autoincrement,
    ts text not null,
    status text not null,
    said text not null default '',
    photo text not null default '',
    looks text not null default '',
    recommend text not null default '',
    picked text not null default '',
    picked_ts text
);
"""


class NoClothesFound(ValueError):
    pass


class LooksError(ValueError):
    pass


@dataclass
class Piece:
    number: int
    label: str
    box: tuple[int, int, int, int]   # x1, y1, x2, y2, inclusive, in the photo's pixels
    mask: np.ndarray | None           # bool, box-local (rows, columns); None when only the box is known
    confidence: float

    @property
    def size(self) -> tuple[int, int]:
        return self.box[2] - self.box[0] + 1, self.box[3] - self.box[1] + 1

    def area(self) -> int:
        return int(self.mask.sum()) if self.mask is not None else self.size[0] * self.size[1]

    def filled(self) -> np.ndarray:
        return self.mask if self.mask is not None else np.ones(self.size[::-1], dtype=bool)

    def center(self) -> tuple[float, float]:
        rows, cols = np.nonzero(self.filled())
        if len(rows) == 0:
            return (self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2
        return self.box[0] + float(cols.mean()), self.box[1] + float(rows.mean())


@dataclass
class Look:
    letter: str
    name: str
    pieces: list[int]
    line: str


@dataclass
class Looks:
    looks: list[Look]
    recommend: str
    caption: str
    dropped: list[int] = field(default_factory=list)  # piece numbers the model named that are not in the photo

    def get(self, letter: str) -> Look:
        return next(look for look in self.looks if look.letter == letter)


# --- finding the pieces -------------------------------------------------------------------------------------------

def _piece(found: Found, label: str, size: tuple[int, int]) -> Piece:
    """A SAM find in the photo's pixels (the answer's own frame size is scaled if it differs)."""
    b = found.box
    sx, sy = size[0] / (b.width or size[0]), size[1] / (b.height or size[1])
    x1, y1 = max(0, round(b.x1 * sx)), max(0, round(b.y1 * sy))
    x2, y2 = min(size[0] - 1, max(x1, round(b.x2 * sx))), min(size[1] - 1, max(y1, round(b.y2 * sy)))
    mask = None
    if found.mask is not None and found.mask_size[0] > 0 and found.mask_size[1] > 0:
        w, h = found.mask_size
        raster = Image.fromarray((np.frombuffer(found.mask, dtype=np.uint8).reshape(h, w) * 255).astype(np.uint8))
        mask = np.asarray(raster.resize((x2 - x1 + 1, y2 - y1 + 1), Image.NEAREST)) > 127
        if not mask.any():
            mask = None
    return Piece(0, label, (x1, y1, x2, y2), mask, b.confidence)


def overlap(a: Piece, b: Piece) -> float:
    """Intersection over union, on the masks when both have one, else on the boxes."""
    ix1, iy1, ix2, iy2 = max(a.box[0], b.box[0]), max(a.box[1], b.box[1]), min(a.box[2], b.box[2]), \
        min(a.box[3], b.box[3])
    if ix2 < ix1 or iy2 < iy1:
        return 0.0
    ma = a.filled()[iy1 - a.box[1]:iy2 - a.box[1] + 1, ix1 - a.box[0]:ix2 - a.box[0] + 1]
    mb = b.filled()[iy1 - b.box[1]:iy2 - b.box[1] + 1, ix1 - b.box[0]:ix2 - b.box[0] + 1]
    inter = int((ma & mb).sum())
    union = a.area() + b.area() - inter
    return inter / union if union else 0.0


def union(a: Piece, b: Piece) -> Piece:
    """One piece from two: a pair of shoes."""
    box = (min(a.box[0], b.box[0]), min(a.box[1], b.box[1]), max(a.box[2], b.box[2]), max(a.box[3], b.box[3]))
    mask = np.zeros((box[3] - box[1] + 1, box[2] - box[0] + 1), dtype=bool)
    for p in (a, b):
        mask[p.box[1] - box[1]:p.box[3] - box[1] + 1, p.box[0] - box[0]:p.box[2] - box[0] + 1] |= p.filled()
    return Piece(0, a.label, box, mask, max(a.confidence, b.confidence))


def _pair_up(pieces: list[Piece]) -> list[Piece]:
    """Two shoes close together and about the same size are one pair; a pair takes no third."""
    out: list[tuple[Piece, int]] = []
    for p in sorted(pieces, key=lambda p: p.box[0]):
        for i, (q, count) in enumerate(out):
            gap = max(0, p.box[0] - q.box[2], q.box[0] - p.box[2], p.box[1] - q.box[3], q.box[1] - p.box[3])
            similar = min(p.area(), q.area()) / max(p.area(), q.area(), 1) > 0.35
            if count == 1 and similar and gap <= 0.6 * max(*p.size, *q.size):
                out[i] = (union(q, p), 2)
                break
        else:
            out.append((p, 1))
    return [p for p, _ in out]


def reading_order(pieces: list[Piece]) -> list[Piece]:
    """Rows top to bottom, then left to right, so the numbers read like a page."""
    if not pieces:
        return []
    row = float(np.median([p.size[1] for p in pieces])) or 1.0
    return sorted(pieces, key=lambda p: (round(p.center()[1] / row), p.center()[0]))


def find_pieces(photo: bytes, size: tuple[int, int], *, find: Callable[..., list[Found]] | None = None,
                joblog=None, phrases=PHRASES, min_confidence: float = MIN_CONFIDENCE) -> list[Piece]:
    """Every clothing piece in the photo, numbered in reading order. One SAM call per phrase, in parallel; a phrase
    whose call fails is skipped, and only when every call fails is it an error."""
    find = find or segment_masks

    def ask(phrase: str):
        try:
            return phrase, find(photo, phrase, mime="image/jpeg", min_confidence=min_confidence, joblog=joblog)
        except SamError as exc:
            return phrase, exc

    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = list(pool.map(ask, phrases))
    failed = [phrase for phrase, got in answers if isinstance(got, Exception)]
    if failed and len(failed) == len(phrases):
        raise SamError(f"every segmentation call failed ({answers[0][1]})")
    candidates: list[Piece] = []
    for phrase, got in answers:
        if isinstance(got, Exception):
            continue
        found = [_piece(f, phrase, size) for f in got if f.box.confidence >= min_confidence]
        candidates += _pair_up(found) if phrase in PAIRS else found
    kept: list[Piece] = []
    for p in sorted(candidates, key=lambda p: -p.confidence):
        if all(overlap(p, k) < SAME_PIECE for k in kept):
            kept.append(p)
    kept = kept[:MAX_PIECES]
    for number, p in enumerate(reading_order(kept), 1):
        p.number = number
    return sorted(kept, key=lambda p: p.number)


# --- drawing -----------------------------------------------------------------------------------------------------

def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _full_mask(piece: Piece, size: tuple[int, int], scale: float) -> Image.Image:
    """The piece's mask over the whole (scaled) photo, as an L image."""
    full = Image.new("L", size, 0)
    local = Image.fromarray(piece.filled().astype(np.uint8) * 255)
    w, h = max(1, round(piece.size[0] * scale)), max(1, round(piece.size[1] * scale))
    full.paste(local.resize((w, h), Image.NEAREST), (round(piece.box[0] * scale), round(piece.box[1] * scale)))
    return full


def what_sam_sees(photo: Image.Image, pieces: list[Piece], long_side: int = 1600) -> Image.Image:
    """The photo with every piece tinted in its own color, outlined thick and numbered big: made to read on the lens."""
    base = photo.convert("RGB")
    scale = long_side / max(base.size)
    base = base.resize((round(base.width * scale), round(base.height * scale)), Image.LANCZOS).convert("RGBA")
    longest = max(base.size)
    ring = max(5, round(longest * 0.009)) | 1
    tint = Image.new("RGBA", base.size, (0, 0, 0, 0))
    lines = Image.new("RGBA", base.size, (0, 0, 0, 0))
    for p in pieces:
        color = COLORS[(p.number - 1) % len(COLORS)]
        mask = _full_mask(p, base.size, scale)
        tint.paste((*color, 105), mask=mask)
        # a band across the mask's edge, about ``ring`` wide: blur the mask and keep the grey between in and out
        edge = mask.filter(ImageFilter.GaussianBlur(ring / 2)).point(lambda v: 255 if 24 < v < 232 else 0)
        lines.paste((*color, 255), mask=edge)
    out = Image.alpha_composite(Image.alpha_composite(base, tint), lines)
    draw = ImageDraw.Draw(out)
    radius = max(22, round(longest * 0.04))
    numbers = font(round(radius * 1.25))
    for p in pieces:
        color = COLORS[(p.number - 1) % len(COLORS)]
        cx, cy = (v * scale for v in p.center())
        cx = min(max(cx, radius + 4), out.width - radius - 4)
        cy = min(max(cy, radius + 4), out.height - radius - 4)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*color, 255),
                     outline=(255, 255, 255, 255), width=max(4, radius // 7))
        draw.text((cx, cy), str(p.number), font=numbers, fill=(255, 255, 255, 255), anchor="mm",
                  stroke_width=max(2, radius // 14), stroke_fill=(0, 0, 0, 255))
    return out.convert("RGB")


def cutout(photo: Image.Image, piece: Piece) -> Image.Image:
    """The piece alone on transparency, trimmed to its mask; the plain box crop when no mask was read."""
    x1, y1, x2, y2 = piece.box
    crop = photo.convert("RGB").crop((x1, y1, x2 + 1, y2 + 1)).convert("RGBA")
    if piece.mask is not None:
        alpha = Image.fromarray(piece.mask.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(0.8))
        crop.putalpha(alpha)
        bbox = alpha.getbbox()
        if bbox:
            crop = crop.crop(bbox)
    return crop


SLOTS = {"hat": 0, "cap": 0, "sunglasses": 0, "jacket": 1, "hoodie": 1, "sweater": 2, "shirt": 2, "t-shirt": 2,
         "pants": 3, "jeans": 3, "shorts": 3, "shoes": 4, "sneakers": 4, "boots": 4, "watch": 5, "bag": 5}
SIDE = {"hat", "cap", "sunglasses", "watch", "bag"}  # small things go in the side strip when there is a main stack


def _stack(canvas: Image.Image, images: list[Image.Image], box: tuple[int, int, int, int], gap: int,
           max_scale: float) -> None:
    """Images one above the other at one shared scale, centered in ``box``."""
    if not images:
        return
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    total = sum(i.height for i in images)
    scale = min(width / max(i.width for i in images), (height - gap * (len(images) - 1)) / max(total, 1), max_scale)
    sized = [i.resize((max(1, round(i.width * scale)), max(1, round(i.height * scale))), Image.LANCZOS)
             for i in images]
    y = y0 + (height - sum(i.height for i in sized) - gap * (len(sized) - 1)) // 2
    for i in sized:
        x = x0 + (width - i.width) // 2
        shadow = Image.new("RGBA", (i.width + 40, i.height + 40), (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 255), (20, 20), mask=i.getchannel("A").point(lambda a: a * 0.32))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(9)), (x - 14, y - 12))
        canvas.alpha_composite(i, (x, y))
        y += i.height + gap


def _wrap(draw: ImageDraw.ImageDraw, text: str, face, width: int, lines: int = 2) -> list[str]:
    out, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=face) <= width or not line:
            line = trial
        else:
            out.append(line)
            line = word
    out.append(line)
    return out[:lines]


def board(photo: Image.Image, pieces: list[Piece], looks: Looks, backdrop: Image.Image | None = None,
          size: tuple[int, int] = (1800, 1200)) -> Image.Image:
    """A, B and C side by side, each made of the real cut-outs; the pick outlined. Letters and names sized for the
    lens. The backdrop, when there is one, is only paper behind the cut-outs."""
    W, H = size
    if backdrop is not None:
        bg = backdrop.convert("RGB")
        ratio = max(W / bg.width, H / bg.height)
        bg = bg.resize((round(bg.width * ratio) + 1, round(bg.height * ratio) + 1), Image.LANCZOS)
        canvas = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W,
                          (bg.height - H) // 2 + H)).convert("RGBA")
    else:
        canvas = Image.new("RGBA", size, (239, 233, 225, 255))
    by_number = {p.number: p for p in pieces}
    cuts = {n: cutout(photo, p) for n, p in by_number.items()}
    draw = ImageDraw.Draw(canvas)
    column, pad = W // 3, 22
    letter_face, name_face, pick_face = font(170), font(56), font(38)
    for i, look in enumerate(looks.looks):
        x0, x1 = i * column + pad, (i + 1) * column - pad
        picked = look.letter == looks.recommend
        panel = Image.new("RGBA", (x1 - x0, H - 2 * pad), (255, 255, 255, 0))
        ImageDraw.Draw(panel).rounded_rectangle((0, 0, panel.width - 1, panel.height - 1), radius=36,
                                                fill=(255, 255, 255, 150))
        canvas.alpha_composite(panel, (x0, pad))
        if picked:
            draw.rounded_rectangle((x0, pad, x1, H - pad), radius=36, outline=(*ACCENT, 255), width=12)
        draw.text((x0 + 36, pad + 18), look.letter, font=letter_face, fill=(*INK, 255))
        if picked:
            draw.text((x1 - 34, pad + 52), "MARCO'S PICK", font=pick_face, fill=(*ACCENT, 255), anchor="ra")
        y = pad + 205
        for text in _wrap(draw, look.name.upper(), name_face, x1 - x0 - 72):
            draw.text((x0 + 36, y), text, font=name_face, fill=(*INK, 255))
            y += 64
        area = (x0 + 30, pad + 345, x1 - 30, H - pad - 30)
        chosen = sorted((n for n in look.pieces if n in cuts), key=lambda n: (SLOTS.get(by_number[n].label, 9), n))
        main = [cuts[n] for n in chosen if by_number[n].label not in SIDE]
        side = [cuts[n] for n in chosen if by_number[n].label in SIDE]
        if main and side:
            split = area[0] + round((area[2] - area[0]) * 0.68)
            _stack(canvas, main, (area[0], area[1], split, area[3]), 18, 2.0)
            _stack(canvas, side, (split + 12, area[1], area[2], area[3]), 18, 2.0)
        else:
            _stack(canvas, main or side, area, 18, 2.0)
    return canvas.convert("RGB")


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def jpeg_of(image: Image.Image) -> bytes:
    """What goes over WhatsApp: a photo-heavy PNG can pass its 5 MB image limit; the film keeps the PNG."""
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


def backdrop(generate=None, refresh: bool = False) -> Image.Image | None:
    """The board's paper, painted once by Muse Image and kept in the state dir. The live path only reads the kept
    file (``generate`` is passed by the command that paints it), so a board never waits on a picture."""
    path = config.STATE_DIR / "dress" / BACKDROP
    if generate is not None and (refresh or not path.exists()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(generate(BACKDROP_PROMPT, size="1536x1024", job="dress-backdrop"))
    try:
        return Image.open(path).convert("RGB") if path.exists() else None
    except OSError:
        return None


# --- the looks ---------------------------------------------------------------------------------------------------

def mood_board(conn: sqlite3.Connection) -> list[str]:
    from hiremarco.look import MARK
    from hiremarco.whatsapp.facts import known

    return [text for _, text in known(conn) if text.startswith(MARK)]


def three_looks(photo_jpeg: bytes, seen_jpeg: bytes, pieces: list[Piece], said: str, *, mood: list[str],
                facts: list[str], client=None) -> Looks:
    """Muse Spark's three looks, held to the pieces in the photo."""
    from hiremarco.marco import persona, private_persona_on
    from hiremarco.meta.client import MuseSpark

    client = client or MuseSpark()
    if private_persona_on() and client.model.endswith("-contributor"):
        raise gate.Refused("the private persona never goes to a contributor model")
    listing = "\n".join(f"{p.number}: {p.label}" for p in pieces)
    prompt = json.dumps({"felix_says": said, "pieces": listing, "mood_board": mood, "facts": facts},
                        ensure_ascii=False)
    system = f"{persona()}\n\n{INSTRUCTIONS}"
    gate.check_model_call(TENANT, model=MODEL, system=system, prompt=prompt, joblog=client.joblog)
    reply = client.chat(
        [{"role": "developer", "content": system},
         {"role": "user", "content": [
             {"type": "text", "text": prompt},
             {"type": "image_url", "image_url": {"url": data_url(photo_jpeg, "image/jpeg")}},
             {"type": "image_url", "image_url": {"url": data_url(seen_jpeg, "image/jpeg")}},
         ]}],
        job="dress-looks", model=MODEL, max_completion_tokens=4000, reasoning_effort="low",
        response_format={"type": "json_schema", "json_schema": {"name": "looks", "schema": SCHEMA, "strict": True}})
    try:
        data = json.loads(reply.text)
    except ValueError as exc:
        raise LooksError("the looks came back unreadable") from exc
    return checked(data, {p.number for p in pieces})


def checked(data: dict, numbers: set[int]) -> Looks:
    """Exactly A, B and C, each of real pieces only. A number not in the photo is thrown out; a look with no real
    piece left, a missing letter or a pick that is not one of the three fails the whole answer."""
    looks, dropped = {}, []
    for row in data.get("looks") or []:
        letter = str(row.get("letter") or "").strip().upper()
        if letter not in LETTERS or letter in looks:
            raise LooksError(f"look {letter or '?'} is not one of A, B, C once each")
        real = []
        for n in row.get("pieces") or []:
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if n in numbers and n not in real:
                real.append(n)
            elif n not in numbers:
                dropped.append(n)
        if not real:
            raise LooksError(f"look {letter} has no piece from the photo")
        looks[letter] = Look(letter, " ".join(str(row.get("name") or "").split())[:40] or f"Look {letter}", real,
                             " ".join(str(row.get("line") or "").split())[:200])
    if set(looks) != set(LETTERS):
        raise LooksError(f"looks came back as {sorted(looks)}, not A, B and C")
    recommend = str(data.get("recommend") or "").strip().upper()
    if recommend not in LETTERS:
        raise LooksError("the pick is not A, B or C")
    caption = " ".join(str(data.get("caption") or "").split()) or f"I'd go {recommend}. A, B or C?"
    return Looks([looks[letter] for letter in LETTERS], recommend, caption[:600], dropped)


# --- the run, the waiting instruction, the pick --------------------------------------------------------------------

DRESS = re.compile(r"\bdress me\b|\bwhat (?:should|do|can) i wear\b|\bstyle me\b|\b(?:pick|choose|build) (?:me )?"
                   r"(?:an? |my )?(?:outfit|look|fit)\b|\bput (?:a |an )?(?:outfit|look|fit) together\b", re.I)
SPOKEN = {"a": "A", "ay": "A", "eh": "A", "b": "B", "be": "B", "bee": "B", "c": "C", "see": "C", "sea": "C"}
PICK = re.compile(r"^\W*(?:(?:i'?ll |let'?s |i )?(?:go with|take|wear|pick|choose|want|do)\s+)?(?:look|option|outfit)?"
                  r"\s*(?P<letter>[abc]|ay|eh|bee|be|see|sea)\b(?:\s+(?:please|it is|then))?\W*$", re.I)


def wants_dressing(said: str) -> bool:
    return bool(DRESS.search(said or ""))


def picked(said: str) -> str | None:
    """"B", "b", "look B", "I'll go with B", a voice note's "Bee." The letter, or None."""
    m = PICK.match((said or "").strip())
    return SPOKEN.get(m["letter"].lower()) if m else None


def _state(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(STATE_SCHEMA)
    return conn


def wait_for_photo(conn: sqlite3.Connection, said: str, now: datetime | None = None) -> int:
    """His "dress me" came before the photo: it waits ten minutes for one."""
    cur = _state(conn).execute("insert into dress (ts, status, said) values (?, 'waiting', ?)",
                               ((now or datetime.now(timezone.utc)).isoformat(), said))
    conn.commit()
    return cur.lastrowid


def waiting(conn: sqlite3.Connection, now: datetime | None = None) -> tuple[int, str] | None:
    """The instruction waiting for a photo, if it came in the last ten minutes."""
    since = ((now or datetime.now(timezone.utc)) - WINDOW).isoformat()
    row = _state(conn).execute("select id, said from dress where status = 'waiting' and ts >= ? order by id desc "
                               "limit 1", (since,)).fetchone()
    return (row[0], row[1]) if row else None


def open_board(conn: sqlite3.Connection, now: datetime | None = None) -> dict | None:
    """The last board sent, while it still waits for his pick."""
    since = ((now or datetime.now(timezone.utc)) - OPEN_FOR).isoformat()
    row = _state(conn).execute("select id, ts, looks, recommend from dress where status = 'open' and ts >= ? "
                               "order by id desc limit 1", (since,)).fetchone()
    if row is None:
        return None
    return {"id": row[0], "ts": row[1], "looks": json.loads(row[2]), "recommend": row[3]}


@dataclass
class Dressed:
    pieces: list[Piece]
    looks: Looks
    seen: Path
    board: Path
    copies: list[Path]
    row: int | None


def film_dir() -> Path:
    return Path(config.get("HIREMARCO_DRESS_FILM_DIR") or Path.home() / "Movies" / "hireMarco Hackathon" /
                "01-the-look").expanduser()


def _save(image: Image.Image, name: str, film: Path | None) -> tuple[Path, Path | None]:
    out = config.STATE_DIR / "dress" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png(image))
    copy = None
    if film is not None and film.is_dir():
        copy = film / name
        shutil.copyfile(out, copy)
    return out, copy


def dress(photo_path: Path, said: str, *, conn: sqlite3.Connection, send: Callable[[bytes, str, str], object] | None,
          client=None, find: Callable[..., list[Found]] | None = None, film: Path | None = None,
          now: datetime | None = None, waiting_row: int | None = None) -> Dressed:
    """The whole scene from one upright photo: find, show what SAM sees, build three looks, send the board.
    ``send(jpeg, caption, step)`` sends one picture to him; None for a dry run, which only writes the images."""
    from hiremarco.meta.client import MuseSpark
    from hiremarco.whatsapp.facts import block

    client = client or MuseSpark()
    now = now or datetime.now(timezone.utc)
    jpeg = photo_path.read_bytes()
    photo = Image.open(io.BytesIO(jpeg)).convert("RGB")
    pieces = find_pieces(jpeg, photo.size, find=find, joblog=client.joblog)
    if not pieces:
        raise NoClothesFound("no clothing piece found in the photo")
    stamp = now.astimezone().strftime("%Y-%m-%d-%H%M%S")
    seen_image = what_sam_sees(photo, pieces)
    seen, seen_copy = _save(seen_image, f"{stamp}-what-sam-sees.png", film)
    if send is not None:
        send(jpeg_of(seen_image), f"I see {len(pieces)} pieces. Give me a sec to put three looks together.", "sees")
    looks = three_looks(jpeg, jpeg_of(seen_image), pieces, said, mood=mood_board(conn), facts=block(conn, said),
                        client=client)
    made_image = board(photo, pieces, looks, backdrop())
    made, made_copy = _save(made_image, f"{stamp}-board.png", film)
    row = None
    if send is not None:
        send(jpeg_of(made_image), looks.caption, "board")
        record = json.dumps([{"letter": lk.letter, "name": lk.name, "line": lk.line,
                              "pieces": [{"n": n, "label": next(p.label for p in pieces if p.number == n)}
                                         for n in lk.pieces]} for lk in looks.looks], ensure_ascii=False)
        _state(conn)
        conn.execute("update dress set status = 'done' where status = 'open'")  # one open board at a time
        if waiting_row is not None:
            conn.execute("update dress set status = 'open', photo = ?, looks = ?, recommend = ? where id = ?",
                         (str(photo_path), record, looks.recommend, waiting_row))
            row = waiting_row
        else:
            row = conn.execute("insert into dress (ts, status, said, photo, looks, recommend) values "
                               "(?, 'open', ?, ?, ?, ?)", (now.isoformat(), said, str(photo_path), record,
                                                            looks.recommend)).lastrowid
        conn.commit()
    from hiremarco import reveal  # what SAM sees in motion, for the edit: after both pictures are sent

    clip = reveal.try_clip([what_sam_sees(photo, [p for p in pieces if p.number <= k]) for k in range(len(pieces) + 1)],
                           seen.with_suffix(".mp4"))
    clip_copy = None
    if clip is not None and film is not None and film.is_dir():
        clip_copy = film / clip.name
        shutil.copyfile(clip, clip_copy)
    return Dressed(pieces, looks, seen, made, [c for c in (seen_copy, made_copy, clip_copy) if c], row)


def lock_in(conn: sqlite3.Connection, letter: str, *, client=None, now: datetime | None = None) -> tuple[str, str]:
    """His pick on the open board: the look locked in, kept as a dated fact, and Marco's one warm line back.
    (reply text, log line). Raises LookupError when no board is open."""
    from hiremarco.whatsapp.facts import keep
    from hiremarco.whatsapp.memory import HOME

    now = now or datetime.now(timezone.utc)
    current = open_board(conn, now)
    if current is None:
        raise LookupError("no board is open")
    look = next(lk for lk in current["looks"] if lk["letter"] == letter)
    names = ", ".join(p["label"] for p in look["pieces"])
    day = now.astimezone(HOME).strftime("%a %b %-d, %Y")
    keep(conn, f"Wearing look {letter} on {day}: {look['name']} ({names})", ts=now)
    conn.execute("update dress set status = 'picked', picked = ?, picked_ts = ? where id = ?",
                 (letter, now.isoformat(), current["id"]))
    conn.commit()
    return warm(letter, look, client), f"look {letter} locked in ({names})"


def warm(letter: str, look: dict, client=None) -> str:
    """One warm line in Marco's voice; a plain one when he cannot be reached."""
    from hiremarco.marco import Marco

    fallback = f"{letter} it is. {look['line']}".strip() if look.get("line") else f"{letter} it is. You're set."
    try:
        marco = Marco(client) if client is not None else Marco()
        text = marco.answer(f"Look {letter}: {look['name']}. {look.get('line', '')}", job="dress-pick",
                            instructions=WARM).text.strip()
    except gate.Refused:
        raise
    except Exception:  # the pick is locked in either way; only the line falls back
        return fallback
    return text or fallback

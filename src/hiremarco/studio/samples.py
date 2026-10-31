"""His sample packs, catalogued so Marco picks by genre first and by ear second.

Owner 2026-10-31: Marco matched sounds to a song by ear alone and reached into a reggaeton pack for an Afrobeat song.
A producer chooses from the right shelf first. So every pack gets a genre (Marco drafts it from what he knows of the
pack and its producer, the Owner corrects it once, and the file is his to edit), every sound gets a kind (kick, snare,
clap, hat, open hat, 808, perc, crash, instrument, loop, vocal, FX, MIDI), and loops get the tempo and key their names carry. The
catalog points at the files where they are: nothing moves, so the sessions that already use them keep working.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from hiremarco import config

ROOT = Path.home() / "Music" / "Logic" / "My Packs"
PACKS = Path.home() / ".config" / "hiremarco" / "packs.tsv"
CATALOG = config.STATE_DIR / "samples.sqlite"
AUDIO = {".wav", ".aif", ".aiff", ".mp3", ".flac"}
MIDI = {".mid", ".midi"}
ONE_SHOT_S = 2.5  # longer than this and it is a loop or a phrase, not a hit

# the first kind whose words match, folder names and file name together, decides; order matters (an "open hat" is
# not a hat, a "snare roll loop" is a loop, an "808 kick" is an 808 only when it is not called a kick)
KINDS = [
    ("midi", r"\.midi?$|\bmidi\b"),
    ("loop", r"\bloops?\b|\bbreaks?\b|\bstems?\b|\bmelod|\d{2,3}\s?-?\s?bpm|\bbpm\b|\bdembows?\b"),
    ("vocal", r"vocal|\bvox\b|chant|acapella|a cappella|adlib|ad-lib|chanteo"),
    ("fx", r"\bfx|sfx|riser|sweep|impact|transition|reverse|\btags?\b|noise"),
    ("open hat", r"open ?hi-?hats?|open ?hat|^ ohh? |openhat|\bohh\b|hihat open|hat open"),
    ("crash", r"crash|cymbal|\bride\b"),
    ("kick", r"kick|\bkck|\bbd\b|\bbd-|bombo|\bkik"),
    ("808", r"\b808s?\b|\bsubs?\b|\bbass\b|\bbajo\b"),
    ("snare", r"snare|snear|\bsnr\b|\brim|\bcaja\b"),
    ("clap", r"clap|\bclp|snap"),
    ("hat", r"hi-?hats?|\bhats?\b|\bhatz\b|\bhh\b|\bchh\b|closed|shaker"),
    ("perc", r"perc|conga|bongo|\btoms?\d*\b|cowbell|clave|guiro|guacharaca|tamb|timbal|block"),
    ("instrument", r"piano|guitar|\bkeys?\b|keyboard|organ|strings?|synth|\bpads?\b|bell|brass|flute|orchestr|choir|"
                   r"\bgrand\b|strat|violin|cello|horn|sax|marimba|kalimba|harp|pluck"),
]
GENRES = ("afrobeats", "dancehall", "reggaeton", "dembow", "latin", "trap", "plugg", "hip-hop", "r&b", "lo-fi",
          "edm", "mixed")


@dataclass(frozen=True)
class Sound:
    path: Path
    pack: str
    genre: str
    kind: str
    seconds: float
    bpm: float
    key: str


def kind_of(path: Path, root: Path = ROOT) -> str:
    """The kind of a sound from what it is called, then from its folders, nearest first; blank when nothing says.
    The pack's own name is left out: "Oh GAWD" made a pack's snares open hats, "808 Mafia" its bells 808s and
    "Free Loop Kit" its cymbals loops (live 2026-10-31)."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = (path.name,)
    inside = list(parts[1:]) if len(parts) > 1 else list(parts)
    if path.suffix.lower() in MIDI:
        return "midi"
    levels = [Path(part).stem if i == len(inside) - 1 else part for i, part in enumerate(inside)][::-1]
    if len(parts) > 1:
        levels.append(parts[0])  # the pack's own name, last: a pack called "Vocals" holds vocals
    for part in levels:
        words = re.sub(r"[_.()\[\]#'&+,-]+", " ", part.lower())
        for kind, pattern in KINDS:
            if re.search(pattern, " " + words + " "):
                return kind
    return ""


def tempo_of(name: str) -> float:
    found = re.search(r"(\d{2,3}(?:[.,]\d+)?)\s?-?\s?bpm|bpm\s?(\d{2,3})", name, re.I)
    if not found:
        return 0.0
    value = float((found.group(1) or found.group(2)).replace(",", "."))
    return value if 50 <= value <= 200 else 0.0


def key_of(name: str) -> str:
    """A key a file name carries: "Am", "F#m", "Bbm", "C# min", "Fmin", "D major"; blank when it carries none."""
    found = re.search(r"(?<![A-Za-z])([A-G](?:#|b)?)\s?(m|min|minor|maj|major)(?![A-Za-z])", name)
    if not found:
        return ""
    quality = found.group(2).lower()
    return f"{found.group(1)} {'major' if quality.startswith('maj') else 'minor'}"


def read_packs(path: Path = PACKS) -> dict[str, str]:
    """pack name to genre, from his file: one pack a line, name TAB genre TAB how sure TAB why; # starts a note."""
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    out[_name(parts[0])] = parts[1].strip().lower()
    return out


def _name(text: str) -> str:
    """One spelling for a pack's name: macOS hands folder names over decomposed (an á as a plus an accent), a typed
    file composed, so "Julián" from the folder and from the file did not match (live 2026-10-31)."""
    return unicodedata.normalize("NFC", text.strip())


def genre_of(parts: tuple[str, ...], packs: dict[str, str]) -> str:
    """The genre of the deepest folder his file names: a line "Pack/Folder" outranks the pack's own line, so the
    Afro dancehall folder inside a reggaeton producer's pack is Afrobeats."""
    for depth in range(len(parts) - 1, 0, -1):
        found = packs.get(_name("/".join(parts[:depth])))
        if found:
            return found
    return ""


SONGS = Path.home() / ".config" / "hiremarco" / "songs.tsv"


def song_genre(song: str, path: Path = SONGS) -> str:
    """The genre he gave a song: one song a line, name TAB genre."""
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and not line.startswith("#") and _name(parts[0]).lower() == _name(song).lower():
                return parts[1].strip().lower()
    return ""


def connect(path: Path = CATALOG) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("create table if not exists sounds (path text primary key, pack text, genre text, kind text, "
                 "seconds real, bpm real, key text)")
    return conn


def scan(root: Path = ROOT, packs: dict[str, str] | None = None, conn: sqlite3.Connection | None = None,
         ear=None) -> dict[str, int]:
    """Every sound under ``root`` into the catalog, its pack's genre beside it. A one-shot whose name says nothing is
    heard by ``ear`` (the drum ear names it kick, snare or hat when it is sure). Returns counts by kind."""
    import soundfile as sf

    packs = read_packs() if packs is None else packs
    conn = conn or connect()
    counts: dict[str, int] = {}
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO | MIDI):
        parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in parts):
            continue
        pack = _name(parts[0]) if len(parts) > 1 else ""
        genre = genre_of(parts, packs)
        kind = kind_of(path, root)
        seconds = 0.0
        if path.suffix.lower() in AUDIO:
            try:
                seconds = float(sf.info(str(path)).duration)
            except Exception:  # an mp3 the reader cannot open, a broken file: catalogued without a length
                seconds = 0.0
            if seconds > ONE_SHOT_S and kind not in ("loop", "vocal", "fx", "midi", "808", "crash", "instrument"):
                kind = "loop"
            if not kind and ear is not None and 0 < seconds <= ONE_SHOT_S:
                kind = ear(path)
        counts[kind or "unknown"] = counts.get(kind or "unknown", 0) + 1
        rows.append((str(path), pack, genre, kind, seconds, tempo_of(path.name), key_of(path.stem)))
    conn.execute("delete from sounds")
    conn.executemany("insert or replace into sounds values (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    return counts


def drum_ear(model=None):
    """The drum ear as a namer of one-shots: the first attack heard as kick, snare or hat when it is sure of one."""
    import librosa
    import numpy as np

    from hiremarco.studio import drums

    model = model or drums.load_model()

    def hear(path: Path) -> str:
        try:
            y, rate = librosa.load(str(path), sr=drums.RATE, mono=True, duration=1.0)
        except Exception:
            return ""
        y = np.concatenate([np.zeros(int(0.05 * rate), dtype=np.float32), y])  # room before the attack
        frames = drums.attacks(y, rate)
        if not frames:
            return ""
        chance = model.predict_proba(drums.features(drums._mel(y, rate), frames[0])[None, :])[0]
        best = int(np.argmax(chance))
        return drums.KINDS[best] if chance[best] >= 0.8 and sorted(chance)[-2] < 0.5 else ""

    return hear


def find(kind: str, genre: str = "", conn: sqlite3.Connection | None = None, *, only: bool = False) -> list[Sound]:
    """The sounds of one kind, the genre's packs first and then the rest (``only``: the genre's alone)."""
    conn = conn or connect()
    rows = conn.execute("select path, pack, genre, kind, seconds, bpm, key from sounds where kind = ? "
                        + ("and genre = ? " if only else "") + "order by (genre = ?) desc, pack, path",
                        (kind, genre.lower(), genre.lower()) if only else (kind, genre.lower())).fetchall()
    return [Sound(Path(r[0]), r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]


def closest(candidates: list[Sound], like, *, load=None, top: int = 3) -> list[tuple[float, Sound]]:
    """The candidates that sound most like ``like`` (a spectrum shape, the mean of a song's own hits of that kind),
    best first: the genre has already chosen the shelf, this chooses on it."""
    import numpy as np

    def shape(path: Path):
        import librosa

        from hiremarco.studio import drums

        y, rate = librosa.load(str(path), sr=drums.RATE, mono=True, duration=0.4)
        if y.size < 2048:
            y = np.pad(y, (0, 2048 - y.size))
        v = drums._mel(y[: int(0.1 * rate)] if y.size > int(0.1 * rate) else y, rate).mean(axis=1)
        return v / (np.linalg.norm(v) + 1e-9)

    load = load or shape
    scored = []
    for sound in candidates:
        try:
            scored.append((float(load(sound.path) @ like), sound))
        except Exception:  # a file the reader cannot open is passed over, not a stop
            continue
    return sorted(scored, key=lambda t: -t[0])[:top]

"""A beat the artist sends goes on the Beat track, in a session of its own.

The Owner's rule (2026-10-29): any beat or instrumental he sends Marco lands
on the track named "Beat" inside the PROD stack of his template, "hireMarco
Vocal Session". The template is copied into a new session named after the
beat, so his template is never opened for writing; Logic opens the copy, the
Beat track is selected by a real click on its header (Logic ignores a
selection set through Accessibility), the playhead goes to the start, and
File > Import > Audio File puts the beat there. The region on the Beat track is
read back before the load counts as done; the booth then reads the beat (key,
tempo, level, tuning) and offers to set the session, as it does when asked.

A beat reaches Marco through the inbox folder: the artist saves or AirDrops it
there and the booth sets it up. A beat sent on WhatsApp waits in the inbox's
"received" folder until he says to start (Owner 2026-10-30: his instruction
starts it, by text, caption or voice note); then it moves into the inbox. A
song name he gives ("start a session for me for Midnight Drive", "call it
Midnight Drive") travels beside the file as "<file>.session" and names the
session. A file is taken only after its size holds still for one poll, and is
moved to the inbox's "loaded" folder after its load, never deleted.

The beat lines up with the grid (Owner 2026-10-30): a session's timeline starts at bar 1, so the beat's first hit
cannot sit on bar 1 with its lead-in before it. Marco measures the first hit and imports an aligned copy, the
whole file with just enough silence in front that the first hit falls on a bar line (bar 2 for a short lead-in):
nothing is cut, the original file is kept, and bar 1 is a count-in bar.

Every keystroke and click goes to Logic only while Logic is the app in front
(live 2026-10-29: a word typed for Logic landed in another app when it came
to the front).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from hiremarco import gate
from hiremarco.studio.tracks import TENANT, _osascript

AUDIO = (".wav", ".aif", ".aiff", ".mp3", ".m4a", ".flac", ".caf")
TEMPLATE = Path.home() / "Music" / "Audio Music Apps" / "Project Templates" / "hireMarco Vocal Session.logicx"
SESSIONS = Path.home() / "Music" / "Logic" / "hireMarco Sessions"
INBOX = Path.home() / "Music" / "hireMarco Inbox"
BEAT_TRACK = "Beat"
BEAT_STACK = "PROD"
VISIBLE = (175.0, 880.0)  # the part of the Tracks area a click can reach on this screen, in points
MIME_EXT = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav", "audio/vnd.wave": ".wav",
            "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
            "audio/aac": ".m4a", "audio/aiff": ".aif", "audio/x-aiff": ".aif", "audio/flac": ".flac",
            "audio/x-flac": ".flac"}


SETUP_RECORD = ".last-setup.json"  # in the inbox: the booth's last setup and its result
SIDECAR = ".session"  # beside a beat in the inbox: the session name the artist asked for


class LoadError(RuntimeError):
    pass


def first_hit(audio, rate: int, threshold: float = 0.1) -> float:
    """Seconds from the file's start to the attack of its first hit: where the 5 ms envelope first passes
    ``threshold`` of the file's loudest moment, walked back (at most 30 ms) to where the attack began."""
    import numpy as np

    level = np.abs(np.asarray(audio, dtype=np.float32))
    width = max(1, int(rate * 0.005))
    env = np.convolve(level, np.ones(width, dtype=np.float32) / width, mode="same")
    peak = float(env.max()) if env.size else 0.0
    if peak <= 0:
        return 0.0
    i = int(np.argmax(env > threshold * peak))
    floor, stop = 0.2 * threshold * peak, max(0, i - int(rate * 0.03))
    while i > stop and env[i - 1] > floor:
        i -= 1
    return i / rate


def first_sound(audio, rate: int) -> float:
    """Seconds to the beat's first sound, quiet or loud: the first hit at 1% of the loudest moment (-40 dB). Live
    2026-10-31 the 10% hit skipped a beat's quiet opening: the file sounded from 0.0 s, the hit chosen was at 0.156
    s, and the beat's start landed two sixteenths before bar 2."""
    return first_hit(audio, rate, threshold=0.01)


def aligned_copy(beat: Path, folder: Path, bpm: float, *, read=None, write=None, locate=None) -> tuple:
    """The whole beat with silence in front so its 1 lands on a bar line when it starts at bar 1: (the copy, the 1 in
    seconds, the bar it lands on, how sure). The 1 comes from the downbeat model (``studio.the_one``), else the first
    sound; whatever comes before it (a riser, a pickup) sits in the bars before. A lead-in shorter than a bar puts the
    1 on bar 2."""
    import math

    import numpy as np
    import soundfile as sf

    from hiremarco.studio import the_one

    data, rate = (read or (lambda p: sf.read(str(p), dtype="float32", always_2d=True)))(beat)
    one = (locate or (lambda: the_one.find(data.mean(axis=1), rate, the_one.downbeats(beat), bpm)))()
    hit = one.seconds
    bar = 4 * 60.0 / bpm
    bars = max(1, math.ceil(hit / bar - 1e-9))
    pad = int(round((bars * bar - hit) * rate))
    out = np.concatenate([np.zeros((pad, data.shape[1]), dtype=np.float32), data])
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{beat.stem}.wav"
    (write or (lambda p, d, r: sf.write(str(p), d, r, subtype="PCM_24")))(target, out, rate)
    return target, hit, 1 + bars, one


def beat_tempo(beat: Path) -> float:
    """The whole tempo the session will take: the producer's label in the file name, else Marco's ear, rounded."""
    from hiremarco.studio.analyze import label, read, settle_tempo

    return settle_tempo(read(beat).bpm, label(beat.stem)[1], None)[0]


def session_name(caption: str) -> str | None:
    """The song name in a caption sent with a beat, or None. "Start a session for me for Midnight Drive. Here's the
    beat" and "call it Midnight Drive" both give "Midnight Drive"; a caption that names nothing gives None."""
    text = " ".join((caption or "").split())
    if not text:
        return None
    end = r"(?=[.!?,;]|\s+here(?:'s|s| is)\b|\s+(?:please|thanks)\b|$)"
    patterns = (r"\b(?:call|name|title)\s+(?:it|the session|this|the song)\s+[\"“']?(?P<n>.+?)[\"”']?" + end,
                r"\b(?:called|named|titled)\s+[\"“']?(?P<n>.+?)[\"”']?" + end,
                r"\b(?:session|song)\b.*?\bfor\s+(?!me\b|us\b|you\b)[\"“']?(?P<n>.+?)[\"”']?" + end)
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            name = title(m.group("n"))
            if name:
                return name
    return None


def wants_session(text: str) -> bool:
    """He is telling Marco to set up a session: "start a session for Midnight Drive", "set it up", "load the beat",
    "let's start the session". A song name alone counts too ("call it Midnight Drive")."""
    said = " ".join((text or "").lower().split())
    if not said:
        return False
    if re.search(r"\bset (?:it|this|that|the session|everything) up\b", said):
        return True
    if re.search(r"\b(?:start|set up|setup|open|begin|load|create|make|build|spin up|get)\b.{0,30}?"
                 r"\b(?:session|it up|the beat|this beat|that beat|a project|the project)\b", said):
        return True
    return re.search(r"\b(?:call|name|title)\s+(?:it|the session|this|the song)\b", said) is not None


def received_folder(inbox: Path = INBOX) -> Path:
    return inbox / "received"


def keep_received(data: bytes, name: str, inbox: Path = INBOX) -> Path:
    """A sent beat kept, not set up: it waits in the inbox's "received" folder for his instruction."""
    folder = received_folder(inbox)
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / name, 2
    while target.exists():
        target, n = folder / f"{Path(name).stem} {n}{Path(name).suffix}", n + 1
    partial = target.with_name(f".{target.name}.part")
    partial.write_bytes(data)
    partial.rename(target)
    return target


def latest_received(inbox: Path = INBOX) -> Path | None:
    folder = received_folder(inbox)
    if not folder.is_dir():
        return None
    beats = [p for p in folder.iterdir() if is_beat(p)]
    return max(beats, key=lambda p: p.stat().st_mtime) if beats else None


def start_session(inbox: Path = INBOX, name: str | None = None) -> Path | None:
    """His instruction: the last beat he sent moves into the inbox, with the song name beside it, and the booth sets
    the session up. None when no beat is waiting."""
    beat = latest_received(inbox)
    if beat is None:
        return None
    name = name or requested_name(beat)  # a title he gave before saying start
    target, n = inbox / beat.name, 2
    while target.exists():
        target, n = inbox / f"{beat.stem} {n}{beat.suffix}", n + 1
    if name:  # beside the beat before the beat appears, so the booth sees both at once
        sidecar(target).write_text(name)
    sidecar(beat).unlink(missing_ok=True)
    shutil.move(str(beat), target)
    return target


def name_received(name: str, inbox: Path = INBOX) -> Path | None:
    """His title for the beat he sent but has not said to start: kept beside it until he does."""
    beat = latest_received(inbox)
    if beat is None:
        return None
    sidecar(beat).write_text(name)
    return beat


def retry_pending(inbox: Path = INBOX) -> Path | None:
    """He asked to try again: the waiting beat is touched, so the booth takes it as new (a failed beat is tried once
    per change). None when nothing is waiting."""
    waiting = pending(inbox)
    if not waiting:
        return None
    os.utime(waiting[-1])
    return waiting[-1]


def cancel_pending(inbox: Path = INBOX) -> Path | None:
    """He does not want the waiting beat set up: it goes back to "received" with its title, never deleted."""
    waiting = pending(inbox)
    if not waiting:
        return None
    beat = waiting[-1]
    folder = received_folder(inbox)
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / beat.name, 2
    while target.exists():
        target, n = folder / f"{beat.stem} {n}{beat.suffix}", n + 1
    if sidecar(beat).exists():
        shutil.move(str(sidecar(beat)), sidecar(target))
    shutil.move(str(beat), target)
    return target


def record_setup(beat: str, result: str, inbox: Path = INBOX) -> None:
    """The booth's last setup and how it went, beside the inbox (a dot file the booth skips), for Marco's brain to
    read when Felix texts."""
    import json
    from datetime import datetime, timezone

    (inbox / SETUP_RECORD).write_text(json.dumps(
        {"ts": datetime.now(timezone.utc).isoformat(), "beat": beat, "result": result}, ensure_ascii=False))


def last_setup(inbox: Path = INBOX) -> dict:
    import json

    try:
        return json.loads((inbox / SETUP_RECORD).read_text())
    except (OSError, ValueError):
        return {}


def pending(inbox: Path = INBOX) -> list[Path]:
    """Beats he has said to start that the booth has not set up yet (they sit in the inbox itself)."""
    if not inbox.is_dir():
        return []
    return sorted((p for p in inbox.iterdir() if is_beat(p)), key=lambda p: p.stat().st_mtime)


def rename_pending(name: str, inbox: Path = INBOX) -> Path | None:
    """His correction of the song name, before the booth sets the session up: the newest waiting beat takes it."""
    waiting = pending(inbox)
    if not waiting:
        return None
    sidecar(waiting[-1]).write_text(name)
    return waiting[-1]


def last_loaded(inbox: Path = INBOX, within_s: float = 6 * 3600, now: float | None = None) -> Path | None:
    """The beat the booth set up most recently, if it was within ``within_s``."""
    folder = inbox / "loaded"
    if not folder.is_dir():
        return None
    beats = [p for p in folder.iterdir() if is_beat(p)]
    if not beats:
        return None
    newest = max(beats, key=lambda p: p.stat().st_mtime)
    return newest if (now or time.time()) - newest.stat().st_mtime <= within_s else None


def title(text: str) -> str:
    """A song title as Marco keeps it: lowercase, the way he texts (Owner 2026-10-30); an all-caps name stays."""
    from hiremarco.style import casual

    return re.sub(r"[/:\x00]", "-", casual(" ".join(text.split()).strip(" .!\"'“”")))[:60]


def sidecar(path: Path) -> Path:
    return path.with_name(path.name + SIDECAR)


def requested_name(path: Path) -> str | None:
    """The session name sent with this beat, if one was."""
    try:
        return sidecar(path).read_text().strip() or None
    except OSError:
        return None


def is_beat(path: Path) -> bool:
    return path.is_file() and not path.name.startswith(".") and path.suffix.lower() in AUDIO


def beat_file_name(filename: str, mime_type: str, fallback: str) -> str | None:
    """The name a sent file is saved under in the inbox, or None when it is not audio Logic imports (a voice note
    arrives as Ogg and is a voice note, not a beat)."""
    name = Path(filename or "").name
    ext = Path(name).suffix.lower()
    if ext not in AUDIO:
        ext = MIME_EXT.get((mime_type or "").split(";")[0].strip().lower(), "")
        if not ext:
            return None
        name = (Path(name).stem or fallback) + ext
    return re.sub(r"[/:\x00]", "-", name)


def session_path(beat: Path, sessions: Path, today: date, name: str | None = None) -> Path:
    """A new session's package, named after the song he named or else the beat, and the day; never on top of one
    that exists."""
    stem = re.sub(r"[/:\x00]", "-", name or beat.stem).strip() or "Beat"
    base = f"{stem} {today.isoformat()}"
    candidate, n = sessions / f"{base}.logicx", 2
    while candidate.exists():
        candidate, n = sessions / f"{base} {n}.logicx", n + 1
    return candidate


@dataclass
class Inbox:
    """New beats in a folder, each once, after its size holds still for one poll."""
    folder: Path = INBOX
    sizes: dict[Path, int] = field(default_factory=dict)

    def ready(self) -> list[Path]:
        self.folder.mkdir(parents=True, exist_ok=True)
        seen, out = {}, []
        for path in sorted(self.folder.iterdir()):
            if not is_beat(path):
                continue
            size = path.stat().st_size
            seen[path] = size
            if size > 0 and self.sizes.get(path) == size:
                out.append(path)
        self.sizes = {p: s for p, s in seen.items() if p not in out}
        return out

    def done(self, path: Path) -> Path:
        """Out of the way after its load: moved to the inbox's "loaded" folder, never deleted."""
        target_dir = self.folder / "loaded"
        target_dir.mkdir(parents=True, exist_ok=True)
        target, n = target_dir / path.name, 2
        while target.exists():
            target, n = target_dir / f"{path.stem} {n}{path.suffix}", n + 1
        shutil.move(str(path), target)
        if sidecar(path).exists():
            shutil.move(str(sidecar(path)), sidecar(target))
        return target


def wake_display() -> None:
    """Light the screen if it went dark (Owner 2026-10-30: the Mac waits dark while he is away, and his text wakes
    it); a no-op when it is already on."""
    subprocess.run(["caffeinate", "-u", "-t", "2"], check=False, timeout=10)


def dismiss_notices() -> str:
    """Logic's one-button notices that stop a fresh session (live 2026-10-30: "Plug-ins load as needed"), pressed OK.
    Only a dialog whose sole choice is OK is pressed; a question with Save or Cancel is left for the artist."""
    script = (
        'tell application "System Events" to tell process "Logic Pro"\n'
        '  set pressed to ""\n'
        '  repeat with w in (every window whose subrole is "AXDialog")\n'
        '    set names to title of every button of w\n'
        '    if names contains "OK" and names does not contain "Cancel" and names does not contain "Save" then\n'
        '      set pressed to pressed & (value of static text 1 of w) & ";"\n'
        '      click (first button of w whose title is "OK")\n'
        '    end if\n'
        '  end repeat\n'
        '  return pressed\n'
        'end tell')
    done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    return done.stdout.strip()


def save_question(answer: str = "") -> str:
    """The song Logic is asking about in "Do you want to save the document ...?", or "" when it is not asking.
    With ``answer`` ("Save"), that button is pressed. Live 2026-10-30: an unsaved "Untitled 3" held the setup for
    three minutes."""
    press = f'click (first button of w whose title is "{answer}")\n' if answer else ""
    script = (
        'tell application "System Events" to tell process "Logic Pro"\n'
        '  repeat with w in (every window whose subrole is "AXDialog")\n'
        '    set names to title of every button of w\n'
        '    if names contains "Don’t Save" or names contains "Don\'t Save" then\n'
        '      set asked to value of static text 1 of w\n'
        f'      {press}'
        '      return asked\n'
        '    end if\n'
        '  end repeat\n'
        '  return ""\n'
        'end tell')
    done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    m = re.search(r"[“\"](?P<n>[^”\"]+)[”\"]", done.stdout)
    return m.group("n") if m else ("?" if done.stdout.strip() else "")


def frontmost() -> str:
    return subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of first process whose '
                           'frontmost is true'], capture_output=True, text=True, timeout=10).stdout.strip()


def _scroll(lines: int, at: tuple[float, float] = (400.0, 500.0)) -> None:
    import Quartz

    Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, at, 0))
    time.sleep(0.1)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                       Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, lines))
    time.sleep(0.3)


def _click(x: float, y: float) -> None:
    from hiremarco.studio.recall import click

    click(x, y)


def _go_to_start() -> str:
    from hiremarco.studio.commands import Command
    from hiremarco.studio.logic import Logic

    return Logic().do(Command("go_to_start"))


@dataclass
class Header:
    x: float
    y: float
    w: float
    h: float
    focus: bool
    open: bool | None

    @property
    def middle(self) -> float:
        return self.y + self.h / 2


def parse_header(line: str) -> Header | None:
    parts = line.strip().split("\t")
    if len(parts) != 6:
        return None
    x, y, w, h = (float(v) for v in parts[:4])
    return Header(x, y, w, h, parts[4] == "1", None if parts[5] == "-" else parts[5] == "1")


class BeatLoader:
    def __init__(self, *, run: Callable[[list[str]], str] = _osascript, open_app: Callable[[Path], None] | None = None,
                 tempo: Callable[[Path], float] | None = None, align: Callable[..., tuple[Path, float, int]] | None = None,
                 front: Callable[[], str] = frontmost, click: Callable[[float, float], None] = _click,
                 scroll: Callable[[int], None] = _scroll, go_to_start: Callable[[], str] = _go_to_start,
                 sleep: Callable[[float], None] = time.sleep, template: Path = TEMPLATE, sessions: Path = SESSIONS,
                 conn=None, rules_path: Path | None = None, today: Callable[[], date] = date.today,
                 wait_s: float = 180.0, wake: Callable[[], None] = wake_display,
                 notices: Callable[[], str] = dismiss_notices, asking: Callable[..., str] = save_question):
        self.run, self.front, self.click, self.scroll = run, front, click, scroll
        self.open_app = open_app or (lambda p: subprocess.run(["open", "-a", "Logic Pro", str(p)], check=True,
                                                              timeout=30))
        self.go_to_start, self.sleep = go_to_start, sleep
        self.tempo, self.align = tempo or beat_tempo, align or aligned_copy
        self.template, self.sessions, self.today = template, sessions, today
        self.conn, self.rules_path, self.wait_s = conn, rules_path, wait_s  # Logic opening cold takes over a minute
        self.wake, self.notices, self.asking = wake, notices, asking

    def _in_front(self) -> None:
        if self.front() != "Logic Pro":
            raise LoadError(f"Logic is not the app in front ({self.front() or 'nothing'}); nothing was clicked")

    def _header(self, name: str) -> Header | None:
        return parse_header(self.run(["header", name]))

    def _reach(self, name: str) -> Header:
        """The track's header on screen: its stack opened if it is inside a closed one, scrolled into view."""
        found = self._header(name)
        if found is None and name == BEAT_TRACK:
            stack = self._reach(BEAT_STACK)
            if stack.open is False:
                self._in_front()
                self.click(stack.x + 43, stack.middle)  # the stack's disclosure triangle, left in its header
                self.sleep(0.8)
            found = self._header(name)
        if found is None:
            raise LoadError(f"the session has no track named {name!r}")
        for _ in range(30):
            if VISIBLE[0] <= found.middle <= VISIBLE[1]:
                return found
            self._in_front()
            self.scroll(-5 if found.middle > VISIBLE[1] else 5)
            found = self._header(name) or found
        raise LoadError(f"could not scroll {name!r} into view")

    def select(self, name: str = BEAT_TRACK) -> None:
        target = self._reach(name)
        if target.focus:
            return
        self._in_front()
        self.click(target.x + target.w * 0.85, target.middle)  # the name area, clear of the buttons
        self.sleep(0.5)
        after = self._header(name)
        if after is None or not after.focus:
            raise LoadError(f"the click did not select {name!r}")

    def open_session(self, beat: Path, name: str | None = None, prepare: Callable[[Path], None] | None = None) -> Path:
        if not self.template.exists():
            raise LoadError(f"the template is missing: {self.template}")
        self.sessions.mkdir(parents=True, exist_ok=True)
        target = session_path(beat, self.sessions, self.today(), name)
        shutil.copytree(self.template, target)
        if prepare is not None:  # files that belong in the session go in before Logic opens it
            prepare(target)
        self.wake()
        self.open_app(target)
        waited = 0.0
        while waited < self.wait_s:
            title = ""
            try:
                title = self.run(["window"]).strip()
            except Exception:  # the window is not up yet, or a dialog is in front of it
                pass
            if title.startswith(target.stem):
                self.sleep(1.0)
                self.notices()
                return target
            asked = self._save_question()
            if asked:
                raise LoadError(f"Logic is asking whether to save {asked!r}, an unnamed song, before it opens "
                                f"{target.stem}; I left that choice for you")
            self.sleep(1.0)
            waited += 1.0
        raise LoadError(f"Logic did not show {target.name} within {self.wait_s:g} s "
                        "(an unsaved song may be asking to be saved first)")

    def _save_question(self) -> str:
        """A save question in front of the session: a named song is saved (its work kept, nothing lost) and the wait
        goes on; an unnamed one ("Untitled 3") is returned, since only his Don't Save would discard it."""
        try:
            asked = self.asking()
        except Exception:
            return ""
        if not asked:
            return ""
        if asked == "?" or asked.lower().startswith("untitled"):
            return asked
        self.asking("Save")
        return ""

    def load(self, beat: Path, name: str | None = None) -> str:
        """A new session from the template with the beat on its Beat track at bar 1, read back; named after the
        song he named, else the beat."""
        beat = beat.resolve()
        if not is_beat(beat):
            raise LoadError(f"{beat.name} is not an audio file Logic imports")

        def run() -> str:
            bpm = self.tempo(beat)
            made: dict = {}

            def prepare(package: Path) -> None:
                made["copy"] = self.align(beat, package / "Media" / "Audio Files", bpm)

            session = self.open_session(beat, name, prepare)
            aligned, hit, bar, one = made["copy"]
            self.select(BEAT_TRACK)
            self._in_front()
            self.go_to_start()
            self._in_front()
            self.run(["import", str(aligned)])
            self.sleep(1.0)
            regions = [r.strip() for r in self.run(["regions"]).splitlines() if r.strip()]
            if not any(beat.stem.lower() in r.lower() for r in regions):
                raise LoadError(f"the Beat track shows {regions or 'no region'} after the import")
            sure = getattr(one, "sure", True)
            return (f"{beat.name} on the Beat track in {session.name}, its 1 ({hit:.3f} s in, "
                    f"{getattr(one, 'how', 'first sound')}) on bar {bar} at {bpm:g} BPM"
                    + ("" if sure else f"; CHECK BAR {bar}: not sure where the 1 is"))

        return gate.execute_effect(self.conn or gate.connect(), run, tenant_id=TENANT,
                                   idempotency_key=f"beat:{beat.name}:{time.time_ns()}", capability="load_beat",
                                   channel="logic", target="*", message=f"load {beat.name} onto the Beat track",
                                   department="studio", rules_path=self.rules_path)

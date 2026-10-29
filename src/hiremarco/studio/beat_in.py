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
there, and WhatsApp drops an audio file or document there once the webhook is
public. A file is taken only after its size holds still for one poll, and is
moved to the inbox's "loaded" folder after its load, never deleted.

Every keystroke and click goes to Logic only while Logic is the app in front
(live 2026-10-29: a word typed for Logic landed in another app when it came
to the front).
"""

from __future__ import annotations

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


class LoadError(RuntimeError):
    pass


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


def session_path(beat: Path, sessions: Path, today: date) -> Path:
    """A new session's package, named after the beat and the day, never on top of one that exists."""
    stem = re.sub(r"[/:\x00]", "-", beat.stem).strip() or "Beat"
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
        return target


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
                 front: Callable[[], str] = frontmost, click: Callable[[float, float], None] = _click,
                 scroll: Callable[[int], None] = _scroll, go_to_start: Callable[[], str] = _go_to_start,
                 sleep: Callable[[float], None] = time.sleep, template: Path = TEMPLATE, sessions: Path = SESSIONS,
                 conn=None, rules_path: Path | None = None, today: Callable[[], date] = date.today,
                 wait_s: float = 60.0):
        self.run, self.front, self.click, self.scroll = run, front, click, scroll
        self.open_app = open_app or (lambda p: subprocess.run(["open", "-a", "Logic Pro", str(p)], check=True,
                                                              timeout=30))
        self.go_to_start, self.sleep = go_to_start, sleep
        self.template, self.sessions, self.today = template, sessions, today
        self.conn, self.rules_path, self.wait_s = conn, rules_path, wait_s

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

    def open_session(self, beat: Path) -> Path:
        if not self.template.exists():
            raise LoadError(f"the template is missing: {self.template}")
        self.sessions.mkdir(parents=True, exist_ok=True)
        target = session_path(beat, self.sessions, self.today())
        shutil.copytree(self.template, target)
        self.open_app(target)
        waited = 0.0
        while waited < self.wait_s:
            title = ""
            try:
                title = self.run(["window"]).strip()
            except Exception:  # the window is not up yet, or a dialog is in front of it
                pass
            if title.startswith(target.stem):
                return target
            self.sleep(1.0)
            waited += 1.0
        raise LoadError(f"Logic did not show {target.name} within {self.wait_s:g} s "
                        "(an unsaved song may be asking to be saved first)")

    def load(self, beat: Path) -> str:
        """A new session from the template with the beat on its Beat track at bar 1, read back."""
        beat = beat.resolve()
        if not is_beat(beat):
            raise LoadError(f"{beat.name} is not an audio file Logic imports")

        def run() -> str:
            session = self.open_session(beat)
            self.select(BEAT_TRACK)
            self._in_front()
            self.go_to_start()
            self._in_front()
            self.run(["import", str(beat)])
            self.sleep(1.0)
            regions = [r.strip() for r in self.run(["regions"]).splitlines() if r.strip()]
            if not any(beat.stem.lower() in r.lower() for r in regions):
                raise LoadError(f"the Beat track shows {regions or 'no region'} after the import")
            return f"{beat.name} on the Beat track at bar 1 in {session.name}"

        return gate.execute_effect(self.conn or gate.connect(), run, tenant_id=TENANT,
                                   idempotency_key=f"beat:{beat.name}:{time.time_ns()}", capability="load_beat",
                                   channel="logic", target="*", message=f"load {beat.name} onto the Beat track",
                                   department="studio", rules_path=self.rules_path)

"""Recording and mixing are different jobs; Marco knows which one he is in, and keeps the session tidy.

**Mode.** A session with few tracks and few regions is a recording session:
Marco talks tone, takes and flow, and gives no mix opinion unless asked. A
developed session (many tracks with regions) is a mixing candidate: he
builds the session view and offers a pass. The artist can switch him by
voice at any time, and "keep it balanced as we go" turns on the light watch:
after a take he speaks up only for a clash that is in the way.

**Tidy as we record.** The artist's habit is every track named after the
preset it was made from. Marco asks once per new track, "lead, ad-lib or
harmony?", then names and colors it; takes land on the same track as
Logic's take folders, and comping stays the artist's. Harmonies that pile
up get offered a summing stack.

Rename and list go through ``scripts/tracks_io.applescript``: rename by Logic's own
Rename Track key command (Shift+Return), checked on the track header; grounded in the
live map of 2026-10-28 (the Tracks header's layout items, one per track). Color and stacks wait for their own map: until then they are
planned, said and recorded, not performed, and ``NotMapped`` says so.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from hiremarco import gate
from hiremarco.studio.presets import SCRIPTS

TENANT = "owner"
RECORDING_MAX_TRACKS = 12          # above this many tracks with regions, the session is developed
RECORDING_MAX_REGIONS = 24
TRACK_KINDS = ("lead", "ad-lib", "harmony", "double", "reference", "beat", "other")
DEFAULT_COLORS = {"lead": "blue", "double": "blue", "harmony": "light blue", "ad-lib": "teal",
                  "reference": "gray", "beat": "orange", "other": "gray"}


class NotMapped(RuntimeError):
    """A Logic action Marco can plan but not yet perform: its controls have not been mapped live."""


@dataclass
class TrackInfo:
    number: int
    name: str
    regions: int


@dataclass
class SessionState:
    mode: str                 # "recording" or "mixing"
    tracks: list[TrackInfo]
    balanced_watch: bool = False
    counts: dict[str, int] = field(default_factory=dict)   # how many of each kind named so far
    scan_error: str = ""

    @property
    def developed(self) -> bool:
        with_regions = [t for t in self.tracks if t.regions > 0]
        return len(with_regions) > RECORDING_MAX_TRACKS or sum(t.regions for t in self.tracks) > RECORDING_MAX_REGIONS


def parse_list(report: str) -> list[TrackInfo]:
    out = []
    for line in report.strip().splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit():
            name = re.sub(r'^Track \d+\s*[“"]?(.*?)[”"]?$', r"\1", parts[1])
            try:
                out.append(TrackInfo(int(parts[0]), name, int(parts[2])))
            except ValueError:
                continue
    return out


def _osascript(args: list[str]) -> str:
    done = subprocess.run(["osascript", str(SCRIPTS / "tracks_io.applescript"), *args],
                          capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:] or f"osascript exit {done.returncode}")
    return done.stdout


def track_name(kind: str, counts: dict[str, int]) -> str:
    """'Lead Vox', 'Harmony 2', 'Ad-lib 3': numbered from the second of a kind."""
    counts[kind] = counts.get(kind, 0) + 1
    base = {"lead": "Lead Vox", "ad-lib": "Ad-lib", "harmony": "Harmony", "double": "Double",
            "reference": "Reference", "beat": "Beat", "other": "Track"}[kind]
    return base if counts[kind] == 1 and kind in ("lead", "beat") else f"{base} {counts[kind]}"


class Tracks:
    def __init__(self, *, run: Callable[[list[str]], str] = _osascript, conn=None, rules_path: Path | None = None,
                 dry_run: bool = False, colors: dict[str, str] | None = None):
        self.run = run
        self.conn = conn
        self.rules_path = rules_path
        self.dry_run = dry_run
        self.colors = colors or dict(DEFAULT_COLORS)
        self.planned: list[str] = []

    def scan(self) -> SessionState:
        """The session's tracks and mode. A scan that fails leaves Marco in recording mode with the reason kept."""
        try:
            tracks = parse_list(self.run(["list"]))
        except Exception as exc:  # the booth must still start; the scan is a convenience, not a gate
            state = SessionState("recording", [])
            state.scan_error = f"{type(exc).__name__}: {str(exc)[-160:]}"
            return state
        state = SessionState("recording", tracks)
        state.mode = "mixing" if state.developed else "recording"
        return state

    def _gated(self, run: Callable[[], str], capability: str, message: str) -> str:
        if self.dry_run:
            self.planned.append(message)
            return f"dry run: {message}"
        return gate.execute_effect(self.conn or gate.connect(), run, tenant_id=TENANT,
                                   idempotency_key=f"tracks:{time.time_ns()}", capability=capability,
                                   channel="logic", target="*", message=message, department="studio",
                                   rules_path=self.rules_path)

    def rename(self, name: str) -> str:
        name = name.strip()[:60]
        if not name:
            raise gate.Refused("a track needs a name")

        def run() -> str:
            parts = self.run(["rename", name]).strip().split("\t")
            if len(parts) != 3 or parts[2] != name:
                raise RuntimeError(f"the name did not take (track header: {parts[-1]!r})")
            return f"renamed {parts[1]!r} to {name!r}"

        return self._gated(run, "rename_track", f"rename track to {name}")

    def color(self, color: str) -> str:
        """Planned and recorded; performed once Logic's color palette is mapped live."""
        message = f"color track {color}"
        if self.dry_run:
            self.planned.append(message)
            return f"dry run: {message}"
        raise NotMapped("coloring a track is not mapped yet; it is noted for the handoff")

    def stack(self, names: list[str], kind: str = "summing") -> str:
        message = f"{kind} stack: {', '.join(names)}"
        if self.dry_run:
            self.planned.append(message)
            return f"dry run: {message}"
        raise NotMapped("track stacks are not mapped yet; it is noted for the handoff")

    def label(self, kind: str, state: SessionState) -> tuple[str, str]:
        """Name and color the selected track for its kind. Returns (name, what happened)."""
        if kind not in TRACK_KINDS:
            raise gate.Refused(f"{kind!r} is not a track kind Marco names")
        name = track_name(kind, state.counts)
        said = [self.rename(name)]
        try:
            said.append(self.color(self.colors.get(kind, "gray")))
        except NotMapped as later:
            said.append(str(later))
        return name, "; ".join(said)

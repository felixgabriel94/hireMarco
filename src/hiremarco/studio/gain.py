"""A word or a phrase lifted on its own: the region split around it and that piece's gain raised.

Owner 2026-10-31: after a take, a word or a phrase that dips below the one before it is brought up by itself, to keep
the vocal level without more compression. The clean way an engineer does it is clip gain: cut the region at the
word's edges and raise that piece's Gain in the Region inspector, before the plug-ins, so the compressor sees an even
vocal. Positions are Logic's bar, beat, sixteenth and tick (4/4, 240 ticks to the sixteenth); the playhead is set
through the Control Bar and the region under it selected by Accessibility, so no key but Split reaches Logic.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).parent / "scripts"
TICKS = 240  # per sixteenth
SPLIT = ("t", ("command",))  # Split Regions at Playhead, Logic's default Command-T (the ruler's menu, 2026-10-31)


@dataclass(frozen=True)
class Spot:
    bar: int
    beat: int = 1
    division: int = 1
    tick: int = 1

    def ticks(self) -> int:
        return (((self.bar - 1) * 4 + (self.beat - 1)) * 4 + (self.division - 1)) * TICKS + (self.tick - 1)

    @staticmethod
    def at(ticks: int) -> "Spot":
        sixteenths, tick = divmod(ticks, TICKS)
        beats, division = divmod(sixteenths, 4)
        bar, beat = divmod(beats, 4)
        return Spot(bar + 1, beat + 1, division + 1, tick + 1)

    def args(self) -> list[str]:
        return [str(self.bar), str(self.beat), str(self.division), str(self.tick)]


def _osa(script: str, args: list[str]) -> str:
    done = subprocess.run(["osascript", str(SCRIPTS / script), *args], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:] or f"osascript exit {done.returncode}")
    return done.stdout.strip()


def _split() -> None:
    from hiremarco.studio.logic import Press, _osascript, _script

    _osascript(_script(Press(*SPLIT)))


class Lifter:
    def __init__(self, *, go: Callable[[Spot], object] = lambda s: _osa("markers_io.applescript", ["gotoexact", *s.args()]),
                 select: Callable[[str], str] = lambda track: _osa("regions_io.applescript", ["under", track]),
                 split: Callable[[], None] = _split,
                 set_gain: Callable[[float], str] = lambda db: _osa("regions_io.applescript", ["gain", f"{db:g}"]),
                 selected: Callable[[], str] = lambda: _osa("regions_io.applescript", ["selected"]),
                 deselect: Callable[[str], str] = lambda which: _osa("regions_io.applescript", ["deselect", which]),
                 sleep: Callable[[float], None] = time.sleep):
        self.go, self.select, self.split, self.set_gain, self.sleep = go, select, split, set_gain, sleep
        self.selected, self.deselect = selected, deselect

    def lift(self, track: str, start: Spot, end: Spot, db: float) -> str:
        """The region on ``track`` cut at ``start`` and ``end`` and the piece between them raised by ``db``."""
        if end.ticks() <= start.ticks():
            raise ValueError("the end comes before the start")
        if not -30 <= db <= 30:
            raise ValueError(f"{db:g} dB is outside what a word's lift should be")
        for edge in (start, end):
            # only the one region is selected when it is cut: an arrangement marker cut with it would move the
            # song's structure (Owner 2026-10-31)
            # Deselect All clears the arrangement and markers too; "Deselect Global Tracks" after the region was picked
            # cleared the region as well and the split did nothing (live 2026-10-31)
            self.go(edge)
            self.deselect("all")
            self.select(track)
            self.split()
            self.sleep(0.4)
        self.go(Spot.at((start.ticks() + end.ticks()) // 2))  # inside the piece, never on its edge
        piece = self.select(track)
        got = self.set_gain(db)
        return f"{piece} on {track}: gain {got} dB"

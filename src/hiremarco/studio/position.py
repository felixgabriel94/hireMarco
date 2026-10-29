"""Logic's playhead as bar, beat, division and tick, and a point some seconds into a take.

Logic shows the position as "5 2 3 120": bar, beat, division (a sixteenth
when the display reads /16) and tick, 240 ticks to a division at its 960 per
quarter note, all counted from 1. A take's start is read from the playhead
when it begins; a lyric found some seconds into the take is that many beats
later at the session's tempo. The tempo is constant in the sessions this
serves; a tempo change inside a take moves the answer, and the result is an
estimate either way, as Marco says.
"""

from __future__ import annotations

from dataclasses import dataclass

TICKS_PER_DIVISION = 240
DIVISIONS_PER_BEAT = 4


@dataclass(frozen=True)
class Position:
    bar: int
    beat: int = 1
    division: int = 1
    tick: int = 1

    def ticks(self, beats_per_bar: int = 4) -> int:
        beats = (self.bar - 1) * beats_per_bar + (self.beat - 1)
        return (beats * DIVISIONS_PER_BEAT + (self.division - 1)) * TICKS_PER_DIVISION + (self.tick - 1)

    @classmethod
    def from_ticks(cls, ticks: int, beats_per_bar: int = 4) -> "Position":
        ticks = max(0, ticks)
        division_all, tick = divmod(ticks, TICKS_PER_DIVISION)
        beat_all, division = divmod(division_all, DIVISIONS_PER_BEAT)
        bar, beat = divmod(beat_all, beats_per_bar)
        return cls(bar + 1, beat + 1, division + 1, tick + 1)

    def later(self, seconds: float, tempo: float, beats_per_bar: int = 4) -> "Position":
        beats = seconds * tempo / 60.0
        return Position.from_ticks(self.ticks(beats_per_bar) + round(beats * DIVISIONS_PER_BEAT * TICKS_PER_DIVISION),
                                   beats_per_bar)

    def typed(self) -> str:
        """What Logic's Go to Position takes."""
        return f"{self.bar} {self.beat} {self.division} {self.tick}"


def parse_where(report: str) -> tuple[Position, float, int]:
    """The script's 'bar beat division tick tempo beats_per_bar' line."""
    parts = report.split()
    bar, beat, division, tick = (int(float(x)) for x in parts[:4])
    return Position(bar, beat, division, tick), float(parts[4]), int(parts[5]) if len(parts) > 5 else 4

"""The loudness ladder: as loud as this mix stays clean, found on its loudest eight bars.

The artist's rule (2026-11-02): the goal of a master is the loudest the mix
can be while still sounding like itself, and "clean" is a set of measured
bars, not a feeling. The chain as set is printed over the loudest eight bars
and judged against the same bars of the mix, loudness-matched: no pumping at
the beat or bar rate, every band within the plan's reach, the crest and the
peak-to-loudness over their floors, width and the mono fold unchanged, and,
when the ears are on, roughness and the perceptual distance not past their
lines. Then the limiter's gain goes up one dB and the print and the judgment
repeat, until a bar breaks; the last clean step is the ceiling, the limiter
goes back to it, and the record says which bar gave first and at what
loudness, which tells the artist what in the mix sets the limit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from hiremarco.mix.verify import Verdict

STEP_DB = 1.0
MAX_STEPS = 4
CAP_LUFS = -6.0               # nobody needs louder than this; the ladder stops here even when every bar holds
ROUGHNESS_LIMIT_ASPER = 0.15  # roughness rising more than this over the mix's own bars is grit, not loudness
DISTANCE_FLOOR_MOS = 3.5      # perceptual likeness to the mix under this is a different record


@dataclass
class Step:
    gain_db: float
    lufs: float | None
    passed: bool
    reasons: list[str] = field(default_factory=list)
    print: str = ""


@dataclass
class Ladder:
    steps: list[Step] = field(default_factory=list)
    ceiling_gain_db: float | None = None
    ceiling_lufs: float | None = None
    gave_first: str = ""

    def lines(self) -> list[str]:
        out = []
        for s in self.steps:
            level = f"{s.lufs:.1f} LUFS" if s.lufs is not None else "no reading"
            out.append(f"limiter gain {s.gain_db:+.1f} dB: {level}, " + ("clean" if s.passed else "fails: " + "; ".join(s.reasons)))
        if self.ceiling_gain_db is not None:
            out.append(f"ceiling: limiter gain {self.ceiling_gain_db:+.1f} dB, {self.ceiling_lufs:.1f} LUFS on the loudest bars"
                       + (f"; what gave first: {self.gave_first}" if self.gave_first else "; nothing gave within the ladder"))
        return out

    def as_dict(self) -> dict:
        return {"steps": [s.__dict__ for s in self.steps], "ceiling_gain_db": self.ceiling_gain_db,
                "ceiling_lufs": self.ceiling_lufs, "gave_first": self.gave_first}


def hearing_bars(mix_hearing: dict | None, step_hearing: dict | None) -> list[str]:
    """What the ears refuse: roughness past the line over the mix's bars, likeness under the floor."""
    reasons = []
    if not isinstance(step_hearing, dict) or "error" in step_hearing:
        return reasons
    psy_m = (mix_hearing or {}).get("psychoacoustics") if isinstance(mix_hearing, dict) else None
    psy_s = step_hearing.get("psychoacoustics")
    if isinstance(psy_m, dict) and isinstance(psy_s, dict):
        rise = float(psy_s.get("roughness_asper_mean", 0)) - float(psy_m.get("roughness_asper_mean", 0))
        if rise > ROUGHNESS_LIMIT_ASPER:
            reasons.append(f"roughness rose {rise:+.2f} asper over the mix's bars")
    zim = step_hearing.get("zimtohrli")
    if isinstance(zim, dict) and "mos_mix_vs_reference" in zim:
        mos = float(zim["mos_mix_vs_reference"])
        if mos < DISTANCE_FLOOR_MOS:
            reasons.append(f"likeness to the mix {mos:.2f} of 5, under the {DISTANCE_FLOOR_MOS:g} floor")
    return reasons


def climb(*, start_gain_db: float, set_gain: Callable[[float], float], print_bars: Callable[[str], Path],
          compare: Callable[[Path], Verdict], lufs_of: Callable[[Path], float],
          hear: Callable[[Path], dict | None] | None = None, mix_hearing: dict | None = None,
          step_db: float = STEP_DB, max_steps: int = MAX_STEPS, cap_lufs: float = CAP_LUFS,
          log: Callable[[str], None] = lambda s: None) -> Ladder:
    """Up one dB at a time until a bar breaks or the cap is reached; the limiter left at the last clean step."""
    ladder = Ladder()
    gain = start_gain_db
    last_clean: Step | None = None
    for k in range(max_steps + 1):
        if k > 0:
            gain = round(start_gain_db + k * step_db, 1)
            shown = set_gain(gain)
            log(f"   limiter gain set to {shown:+.1f} dB")
            gain = shown
        path = print_bars(f"ladder {gain:+.1f} dB")
        verdict = compare(path)
        reasons = list(verdict.reasons)
        if hear is not None:
            reasons += hearing_bars(mix_hearing, hear(path))
        level = None
        try:
            level = round(float(lufs_of(path)), 1)
        except Exception:   # noqa: BLE001
            pass
        step = Step(gain, level, not reasons, reasons, str(path))
        ladder.steps.append(step)
        log("   " + ladder.lines()[-1])
        if not step.passed:
            if last_clean is not None:
                set_gain(last_clean.gain_db)
                log(f"   limiter gain back to {last_clean.gain_db:+.1f} dB, the last clean step")
            ladder.gave_first = reasons[0]
            break
        last_clean = step
        if level is not None and level >= cap_lufs:
            log(f"   {level:.1f} LUFS reaches the {cap_lufs:g} LUFS cap; the ladder stops here")
            break
    if last_clean is not None:
        ladder.ceiling_gain_db, ladder.ceiling_lufs = last_clean.gain_db, last_clean.lufs
    return ladder

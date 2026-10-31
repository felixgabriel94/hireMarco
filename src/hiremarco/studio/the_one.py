"""Where a beat's 1 is, from a model trained for it, and how sure Marco is.

Owner 2026-10-31: a beat that opens with a riser or a sound effect must still have its 1 on bar 2, with what comes
before it in the bars before. The 1 comes from Beat This! (a downbeat model; Day 4's bake-off: 33 of 42 test tracks,
both of the Owner's real ones), run in its own environment because its libraries are not Marco's. Its first downbeat
at or after the beat's first sound is the 1, moved onto the attack of the hit there. When no hit sits within 100 ms of
it, Marco is not sure and says so ("check bar 2") rather than guess quietly. Without the model, the first sound is
the 1, and that is never called sure.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hiremarco import config

MODEL_PYTHON = Path.home() / ".local" / "share" / "hiremarco-bakeoff" / "bt" / "bin" / "python"
SNAP_S = 0.1
RUN = """
import json, sys
from beat_this.inference import File2Beats
beats, downbeats = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(sys.argv[1])
print(json.dumps([float(d) for d in downbeats]))
"""


@dataclass(frozen=True)
class One:
    seconds: float   # into the file
    sure: bool
    how: str         # "model, on a hit" / "model, no hit near it" / "first sound (no model)"


def downbeats(path: Path, timeout: float = 120.0) -> list[float] | None:
    """Beat This!'s downbeats in seconds, or None when the model cannot run here."""
    python = Path(config.get("HIREMARCO_BEAT_THIS_PYTHON") or MODEL_PYTHON)
    if not python.exists() or not Path(path).is_file():
        return None
    try:
        done = subprocess.run([str(python), "-I", "-c", RUN, str(path)], capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    try:
        return [float(x) for x in json.loads(done.stdout.strip().splitlines()[-1])]
    except (ValueError, IndexError):
        return None


def find(mono, rate: int, found: list[float] | None, bpm: float = 0.0) -> One:
    """The 1: the model's first downbeat at or after the first sound, moved onto the attack there when one is near.
    Sure when the model's next two downbeats come a bar apart at the beat's tempo (live 2026-10-31: on a riser and a
    reverse cymbal the 1 was right within 11 ms, but no hit jumped out of the swell, so an attack is not required)."""
    import numpy as np

    from hiremarco.studio.beat_in import first_hit, first_sound

    sound = first_sound(mono, rate)
    if not found:
        return One(sound, False, "first sound (no model)")
    later = [d for d in found if d >= sound - 0.05]
    if not later:
        return One(sound, False, "first sound (the model found no 1 after it)")
    guess = later[0]
    steady = False
    if bpm > 0 and len(later) >= 3:
        bar = 240.0 / bpm
        steady = all(abs((later[k + 1] - later[k]) - bar) <= 0.06 * bar for k in range(2))
    hit = _attack(np.asarray(mono, dtype=np.float32), rate, guess)
    at = hit if hit is not None else guess
    sure = steady or (hit is not None and not bpm)
    how = "model" + (", bars steady" if steady else "") + (", on a hit" if hit is not None else "")
    return One(max(0.0, at), sure, how if sure else how + ", bars not steady")


def _attack(mono, rate: int, near: float) -> float | None:
    """The sharpest rise in loudness within SNAP_S of ``near``, walked back to where it starts; None when nothing
    rises there (a riser swells, a hit jumps: only a jump of three times the level before it counts)."""
    import numpy as np

    a, b = max(0, int((near - SNAP_S) * rate)), int((near + SNAP_S) * rate)
    width = max(1, int(rate * 0.005))
    env = np.convolve(np.abs(mono[max(0, a - width):b]), np.ones(width, dtype=np.float32) / width, mode="same")
    if env.size < 3 or float(env.max()) <= 0:
        return None
    step = max(1, int(rate * 0.01))
    rise = env[step:] - env[:-step]
    i = int(np.argmax(rise)) + step
    before = float(env[max(0, i - 2 * step)])
    if float(env[i]) < 3 * max(before, 1e-6):
        return None
    while i > 0 and env[i - 1] > before * 1.2 and env[i - 1] < env[i]:
        i -= 1
    return (max(0, a - width) + i) / rate

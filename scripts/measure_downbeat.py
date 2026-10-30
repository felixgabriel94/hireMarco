"""How often Marco finds the 1: real drum loops (which start on the 1) behind made-up intros.

Each loop is tiled to eight bars or more and given one of five intros: none, silence, a riser that swells into the
1, a pickup hit one beat early, or a reverse-cymbal swell plus silence. The truth is where the loop starts. A find
within 15 ms of it counts as right. Run: uv run python scripts/measure_downbeat.py [N]
"""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from hiremarco.studio.beat_in import first_hit
from hiremarco.studio.downbeat import find

ROOT = Path.home() / "Splice" / "sounds"
LABEL = re.compile(r"_(\d{2,3})_", re.I)


def loops(n: int, seed: int) -> list[tuple[Path, float]]:
    found = []
    for p in sorted(ROOT.rglob("*.wav")):
        if "drum" not in p.name.lower() or "loop" not in p.name.lower():
            continue
        m = LABEL.search(p.name)
        if m and 70 <= int(m.group(1)) <= 170:
            found.append((p, float(m.group(1))))
    random.Random(seed).shuffle(found)
    return found[:n]


def intro(kind: str, loop: np.ndarray, rate: int, bpm: float, rng: random.Random) -> np.ndarray:
    beat = 60.0 / bpm
    if kind == "none":
        return np.zeros(0, dtype=np.float32)
    if kind == "silence":
        return np.zeros(int(rng.uniform(0.1, 1.5) * rate), dtype=np.float32)
    if kind in ("riser", "reverse"):
        length = int(rng.choice([1, 2, 4]) * beat * rate)
        swell = np.linspace(0, 1, length) ** 2 * rng.uniform(0.2, 0.5)
        noise = np.random.default_rng(rng.randrange(10**6)).standard_normal(length).astype(np.float32)
        lead = np.zeros(int(rng.uniform(0.0, 0.8) * rate), dtype=np.float32)
        return np.concatenate([lead, noise * swell]).astype(np.float32)
    if kind == "pickup":  # the loop's own second beat, played one beat before the 1
        hit = loop[int(beat * rate): int(beat * rate) + int(beat * rate)]
        lead = np.zeros(int(rng.uniform(0.2, 1.0) * rate), dtype=np.float32)
        return np.concatenate([lead, hit]).astype(np.float32)
    raise ValueError(kind)


def main(n: int = 40, seed: int = 7) -> None:
    rng = random.Random(seed)
    kinds = ["none", "silence", "riser", "pickup", "reverse"]
    right = sure = sure_right = total = 0
    misses = []
    for path, bpm in loops(n, seed):
        data, rate = sf.read(str(path), dtype="float32", always_2d=True)
        loop = data.mean(axis=1)
        bar = 4 * 60.0 / bpm
        reps = max(2, int(np.ceil(8 * bar / (len(loop) / rate))))
        body = np.tile(loop, reps)
        kind = kinds[total % len(kinds)]
        lead = intro(kind, loop, rate, bpm, rng)
        audio = np.concatenate([lead, body]).astype(np.float32)
        truth = len(lead) / rate + first_hit(body, rate)
        got = find(audio, rate, bpm, first_hit(audio, rate))
        ok = abs(got.first - truth) < 0.015
        total += 1
        right += ok
        sure += got.sure
        sure_right += ok and got.sure
        if not ok:
            misses.append(f"{kind:8} {path.name[:48]:48} off {1000 * (got.first - truth):+.0f} ms sure={got.sure}")
    print(f"{right}/{total} right ({100 * right / total:.0f}%); marked sure {sure}, of those right {sure_right}")
    for line in misses:
        print("  miss", line)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)

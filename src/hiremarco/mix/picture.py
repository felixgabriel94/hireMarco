"""Marco's collision picture: two tracks' spectra on one chart, shaded where they fight.

Drawn from his own measurements (Welch spectra, smoothed to a sixth of an
octave, on a log frequency axis from 20 Hz to 20 kHz), as a plain SVG file
that opens in any browser and reads on camera. A band is shaded where both
tracks are within ``COLLISION_DB`` of each other and both are well above
their own floor: the same rule the ears use to name a collision.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import signal

from hiremarco.mix.ears import COLLISION_DB

WIDTH, HEIGHT, PAD = 900, 380, 48
F_LO, F_HI = 20.0, 20000.0
FLOOR_DB = 30.0  # shade only where both are within this of their own loudest point


def spectrum(audio: np.ndarray, rate: int, points: int = 240) -> tuple[np.ndarray, np.ndarray]:
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    freqs, power = signal.welch(mono, rate, nperseg=min(16384, max(512, mono.size)))
    grid = np.geomspace(F_LO, F_HI, points)
    level = np.empty(points)
    for i, f in enumerate(grid):
        lo, hi = f / 2 ** (1 / 12), f * 2 ** (1 / 12)  # a sixth of an octave around each point
        band = power[(freqs >= lo) & (freqs < hi)]
        level[i] = 10 * np.log10(max(float(band.mean()) if band.size else 1e-14, 1e-14))
    return grid, level


def _x(f: float) -> float:
    return PAD + (np.log10(f) - np.log10(F_LO)) / (np.log10(F_HI) - np.log10(F_LO)) * (WIDTH - 2 * PAD)


def draw(a: tuple[str, np.ndarray, int], b: tuple[str, np.ndarray, int], out: Path) -> list[tuple[float, float]]:
    """Write the SVG; returns the shaded spans as (low Hz, high Hz)."""
    (name_a, audio_a, rate_a), (name_b, audio_b, rate_b) = a, b
    grid, la = spectrum(audio_a, rate_a)
    _, lb = spectrum(audio_b, rate_b)
    top = max(la.max(), lb.max())
    bottom = top - 60

    def y(db: float) -> float:
        return PAD + (top - min(max(db, bottom), top)) / (top - bottom) * (HEIGHT - 2 * PAD)

    fights = (np.abs(la - lb) <= COLLISION_DB) & (la > la.max() - FLOOR_DB) & (lb > lb.max() - FLOOR_DB)
    spans, start = [], None
    for i, hit in enumerate(np.append(fights, False)):
        if hit and start is None:
            start = i
        elif not hit and start is not None:
            spans.append((float(grid[start]), float(grid[min(i, len(grid) - 1)])))
            start = None
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
             f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="Helvetica, Arial, sans-serif">',
             f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#0f1115"/>']
    for lo, hi in spans:
        parts.append(f'<rect x="{_x(lo):.1f}" y="{PAD}" width="{max(_x(hi) - _x(lo), 2):.1f}" '
                     f'height="{HEIGHT - 2 * PAD}" fill="#ff4d4f" fill-opacity="0.22"/>')
    for f, label in ((50, "50"), (100, "100"), (250, "250"), (500, "500"), (1000, "1k"), (2000, "2k"),
                     (4000, "4k"), (8000, "8k"), (16000, "16k")):
        parts.append(f'<line x1="{_x(f):.1f}" y1="{PAD}" x2="{_x(f):.1f}" y2="{HEIGHT - PAD}" stroke="#2a2f3a"/>')
        parts.append(f'<text x="{_x(f):.1f}" y="{HEIGHT - PAD + 18}" fill="#8a93a6" font-size="12" '
                     f'text-anchor="middle">{label}</text>')
    for level, color in ((la, "#4da3ff"), (lb, "#ffb020")):
        path = " ".join(f"{'M' if i == 0 else 'L'}{_x(f):.1f},{y(v):.1f}" for i, (f, v) in enumerate(zip(grid, level)))
        parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>')
    parts.append(f'<text x="{PAD}" y="28" fill="#4da3ff" font-size="16">{name_a}</text>')
    parts.append(f'<text x="{PAD + 260}" y="28" fill="#ffb020" font-size="16">{name_b}</text>')
    parts.append(f'<text x="{WIDTH - PAD}" y="28" fill="#ff4d4f" font-size="14" text-anchor="end">'
                 f'shaded: where they collide</text>')
    parts.append("</svg>")
    Path(out).write_text("\n".join(parts))
    return spans

"""Marco's collision picture: two tracks' spectra on one chart, shaded where they fight.

Drawn from his own measurements (Welch spectra, smoothed to a sixth of an
octave, on a log frequency axis from 20 Hz to 20 kHz) as an SVG that opens in
any browser and reads on camera: the seven mix bands named along the top, a dB
scale, each collision shaded and called out with its frequency span and how
close the two tracks are there. With ``before`` given, the earlier curves are
drawn faint and dashed under the new ones, and each callout says how the gap
changed. A region is a collision by the same rule the ears use: both tracks
within ``COLLISION_DB`` of each other and both well above their own floor.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import signal

from hiremarco.mix.ears import BANDS, COLLISION_DB

WIDTH, HEIGHT = 1280, 680
LEFT, RIGHT, TOP, BOTTOM = 84, 40, 196, 86
F_LO, F_HI = 20.0, 20000.0
RANGE_DB = 60.0
FLOOR_DB = 30.0  # a region counts only where both tracks are within this of their own loudest point
MIN_SPAN_OCTAVES = 1 / 6
COLOR_A, COLOR_B, COLOR_HIT, COLOR_OK = "#4da3ff", "#ffb020", "#ff5a5f", "#3ddc97"
BG, GRID, TEXT, MUTED = "#0d1016", "#232a36", "#e8ecf3", "#8a93a6"
FONT = "-apple-system, 'SF Pro Display', 'Helvetica Neue', Helvetica, Arial, sans-serif"


@dataclass
class Region:
    lo_hz: float
    hi_hz: float
    gap_db: float       # closest the two tracks come inside the region
    peak_hz: float      # where they are closest
    gap_before: float | None = None


def spectrum(audio: np.ndarray, rate: int, points: int = 360) -> tuple[np.ndarray, np.ndarray]:
    """Power in dB on a log grid, smoothed with a sixth-of-an-octave window in log frequency.

    Interpolating first and smoothing after keeps the low end, where FFT bins are sparse, free of steps.
    """
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    freqs, power = signal.welch(mono, rate, nperseg=min(32768, max(512, mono.size)))
    keep = freqs > 0
    grid = np.geomspace(F_LO, F_HI, points)
    db = 10 * np.log10(np.maximum(np.interp(np.log2(grid), np.log2(freqs[keep]), power[keep]), 1e-14))
    step = np.log2(grid[1] / grid[0])                     # octaves per grid point
    sigma = (1 / 6) / 2.355 / step                        # a sixth of an octave, as a Gaussian's full width
    kernel = np.exp(-0.5 * (np.arange(-int(4 * sigma) - 1, int(4 * sigma) + 2) / sigma) ** 2)
    kernel /= kernel.sum()
    power_db = 10 * np.log10(np.convolve(10 ** (db / 10), kernel, mode="same"))
    return grid, power_db


def regions(grid: np.ndarray, la: np.ndarray, lb: np.ndarray, max_regions: int = 4) -> list[Region]:
    """Collision regions, joined when less than a third of an octave apart, the closest fights first."""
    fights = (np.abs(la - lb) <= COLLISION_DB) & (la > la.max() - FLOOR_DB) & (lb > lb.max() - FLOOR_DB)
    spans, start = [], None
    for i, hit in enumerate(np.append(fights, False)):
        if hit and start is None:
            start = i
        elif not hit and start is not None:
            spans.append([start, min(i, len(grid) - 1)])
            start = None
    joined: list[list[int]] = []
    for span in spans:
        if joined and np.log2(grid[span[0]] / grid[joined[-1][1]]) < 1 / 3:
            joined[-1][1] = span[1]
        else:
            joined.append(span)
    found = []
    for a, b in joined:
        if np.log2(grid[b] / grid[a]) < MIN_SPAN_OCTAVES:
            continue
        gaps = np.abs(la[a:b + 1] - lb[a:b + 1])
        at = a + int(np.argmin(gaps))
        found.append(Region(float(grid[a]), float(grid[b]), round(float(gaps.min()), 1), float(grid[at])))
    return sorted(found, key=lambda r: r.gap_db)[:max_regions]


def _hz(f: float) -> str:
    return f"{f / 1000:.1f} kHz".replace(".0 kHz", " kHz") if f >= 1000 else f"{f:.0f} Hz"


def draw(a: tuple[str, np.ndarray, int], b: tuple[str, np.ndarray, int], out: Path,
         before: tuple[np.ndarray, np.ndarray] | None = None, title: str | None = None) -> list[Region]:
    """Write the picture; ``before`` is the (audio a, audio b) of the earlier pass, at the same rates."""
    (name_a, audio_a, rate_a), (name_b, audio_b, rate_b) = a, b
    grid, la = spectrum(audio_a, rate_a)
    _, lb = spectrum(audio_b, rate_b)
    old = None
    if before is not None:
        _, oa = spectrum(before[0], rate_a)
        _, ob = spectrum(before[1], rate_b)
        old = (oa, ob)
    top = max(la.max(), lb.max(), *(x.max() for x in old)) if old else max(la.max(), lb.max())
    top = np.ceil(top / 10) * 10
    bottom = top - RANGE_DB
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM

    def x(f: float) -> float:
        return LEFT + (np.log10(f) - np.log10(F_LO)) / (np.log10(F_HI) - np.log10(F_LO)) * plot_w

    def y(db: float) -> float:
        return TOP + (top - min(max(db, bottom), top)) / RANGE_DB * plot_h

    def path(level: np.ndarray) -> str:
        return " ".join(f"{'M' if i == 0 else 'L'}{x(f):.1f},{y(v):.1f}" for i, (f, v) in enumerate(zip(grid, level)))

    found = regions(grid, la, lb)
    if old:
        before_regions = regions(grid, *old)
        for r in found:
            near = [o for o in before_regions if o.lo_hz <= r.hi_hz and r.lo_hz <= o.hi_hz]  # overlapping
            r.gap_before = near[0].gap_db if near else None
        # collisions the pass removed are shown too, as resolved
        for o in before_regions:
            if not any(r.lo_hz <= o.hi_hz and o.lo_hz <= r.hi_hz for r in found):
                found.append(Region(o.lo_hz, o.hi_hz, float("inf"), o.peak_hz, o.gap_db))
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" '
         f'font-family="{FONT}">',
         "<defs>",
         f'<linearGradient id="fa" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{COLOR_A}" '
         f'stop-opacity="0.28"/><stop offset="1" stop-color="{COLOR_A}" stop-opacity="0"/></linearGradient>',
         f'<linearGradient id="fb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{COLOR_B}" '
         f'stop-opacity="0.24"/><stop offset="1" stop-color="{COLOR_B}" stop-opacity="0"/></linearGradient>',
         f'<pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
         f'<rect width="8" height="8" fill="{COLOR_HIT}" fill-opacity="0.13"/>'
         f'<line x1="0" y1="0" x2="0" y2="8" stroke="{COLOR_HIT}" stroke-opacity="0.35" stroke-width="2"/></pattern>',
         "</defs>",
         f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{BG}"/>']
    # header
    heading = title or f"{name_a} vs {name_b}"
    live = [r for r in found if r.gap_db != float("inf")]
    sub = (f"{len(live)} collision{'s' if len(live) != 1 else ''}" if live else "no collisions") + \
          (" after the pass" if old else "")
    s.append(f'<text x="{LEFT}" y="52" fill="{TEXT}" font-size="30" font-weight="600">{heading}</text>')
    s.append(f'<text x="{LEFT}" y="84" fill="{MUTED}" font-size="17">{sub}</text>')
    lx = WIDTH - RIGHT - 420
    for i, (name, color) in enumerate(((name_a, COLOR_A), (name_b, COLOR_B))):
        s.append(f'<rect x="{lx + i * 210}" y="40" width="22" height="5" rx="2" fill="{color}"/>')
        s.append(f'<text x="{lx + i * 210 + 30}" y="47" fill="{TEXT}" font-size="16">{name}</text>')
    s.append(f'<rect x="{lx}" y="66" width="22" height="12" fill="url(#hatch)"/>')
    s.append(f'<text x="{lx + 30}" y="77" fill="{MUTED}" font-size="14">where they fight'
             + (" (dashed: before)" if old else "") + "</text>")
    # bands across the top of the plot
    for i, (band, lo, hi) in enumerate(BANDS):
        x0, x1 = x(max(lo, F_LO)), x(min(hi, F_HI))
        if i % 2 == 0:
            s.append(f'<rect x="{x0:.1f}" y="{TOP}" width="{x1 - x0:.1f}" height="{plot_h}" fill="#ffffff" '
                     f'fill-opacity="0.018"/>')
        s.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{TOP - 12}" fill="{MUTED}" font-size="13" text-anchor="middle" '
                 f'letter-spacing="0.6">{band.upper()}</text>')
    # grid
    for db in range(int(bottom), int(top) + 1, 10):
        s.append(f'<line x1="{LEFT}" y1="{y(db):.1f}" x2="{WIDTH - RIGHT}" y2="{y(db):.1f}" stroke="{GRID}"/>')
        s.append(f'<text x="{LEFT - 12}" y="{y(db) + 5:.1f}" fill="{MUTED}" font-size="13" text-anchor="end">'
                 f'{int(db - top)} dB</text>')
    for f in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000):
        s.append(f'<line x1="{x(f):.1f}" y1="{TOP}" x2="{x(f):.1f}" y2="{TOP + plot_h}" stroke="{GRID}"/>')
        s.append(f'<text x="{x(f):.1f}" y="{TOP + plot_h + 24}" fill="{MUTED}" font-size="14" '
                 f'text-anchor="middle">{_hz(f)}</text>')
    # collisions
    for r in found:
        resolved = r.gap_db == float("inf")
        x0, x1 = x(r.lo_hz), x(r.hi_hz)
        s.append(f'<rect x="{x0:.1f}" y="{TOP}" width="{max(x1 - x0, 3):.1f}" height="{plot_h}" '
                 + (f'fill="none" stroke="{COLOR_OK}" stroke-opacity="0.55" stroke-dasharray="4 4"/>' if resolved
                    else 'fill="url(#hatch)"/>'))
    # curves
    if old:
        for level, color in ((old[0], COLOR_A), (old[1], COLOR_B)):
            s.append(f'<path d="{path(level)}" fill="none" stroke="{color}" stroke-opacity="0.45" stroke-width="1.6" '
                     f'stroke-dasharray="5 5"/>')
    for level, color, fill in ((la, COLOR_A, "fa"), (lb, COLOR_B, "fb")):
        area = path(level) + f" L{x(F_HI):.1f},{TOP + plot_h} L{x(F_LO):.1f},{TOP + plot_h} Z"
        s.append(f'<path d="{area}" fill="url(#{fill})"/>')
        s.append(f'<path d="{path(level)}" fill="none" stroke="{color}" stroke-width="2.8" stroke-linejoin="round"/>')
    # callouts in a lane above the band names, each with a leader line down to its region
    placed: list[float] = []
    for r in sorted(found, key=lambda r: r.peak_hz):
        target = x(np.sqrt(r.lo_hz * r.hi_hz))
        cx = min(max(target, LEFT + 92), WIDTH - RIGHT - 92)
        for p in placed:  # keep boxes from overlapping
            if abs(cx - p) < 190:
                cx = p + 190
        cx = min(cx, WIDTH - RIGHT - 92)
        placed.append(cx)
        cy = TOP - 46
        if r.gap_db == float("inf"):
            line2, color = f"was within {r.gap_before:g} dB, now clear", COLOR_OK
        elif r.gap_before is not None:
            better = r.gap_db > r.gap_before
            line2, color = f"within {r.gap_db:g} dB (was {r.gap_before:g} dB)", COLOR_OK if better else COLOR_HIT
        else:
            line2, color = f"within {r.gap_db:g} dB", COLOR_HIT
        s.append(f'<path d="M{cx:.1f},{cy + 24:.1f} L{target:.1f},{TOP + 4:.1f}" stroke="{color}" '
                 f'stroke-opacity="0.6" stroke-width="1.5" fill="none"/>')
        s.append(f'<rect x="{cx - 90:.1f}" y="{cy - 18:.1f}" width="180" height="42" rx="8" fill="{BG}" '
                 f'stroke="{color}" stroke-opacity="0.8"/>')
        s.append(f'<text x="{cx:.1f}" y="{cy:.1f}" fill="{TEXT}" font-size="14" font-weight="600" '
                 f'text-anchor="middle">{_hz(r.lo_hz)} to {_hz(r.hi_hz)}</text>')
        s.append(f'<text x="{cx:.1f}" y="{cy + 17:.1f}" fill="{color}" font-size="13" text-anchor="middle">'
                 f'{line2}</text>')
    s.append(f'<text x="{LEFT}" y="{HEIGHT - 26}" fill="{MUTED}" font-size="13">Measured by Marco: Welch spectrum, '
             f'sixth-octave smoothing; a collision is both tracks within {COLLISION_DB:g} dB and both strong.</text>')
    s.append("</svg>")
    Path(out).write_text("\n".join(s))
    return found

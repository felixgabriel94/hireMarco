"""Where the 1 is: the beat grid from the whole song, then which beat of the bar starts the bar.

The first sound in a beat file is often not the 1 (a riser, a reverse cymbal, a pickup), so the grid comes from the
body of the song, and the bar's first beat from where the steady part begins:

* the grid: the offset where the kicks fall on the beats, checked against the sixteenth and triplet grid, then moved
  onto the kicks' attacks;
* the start: the first beat whose bars repeat in the bars after it, and whose own hit sounds like the 1 a bar later
  (a riser, a reverse cymbal, a lone pickup or silence does not repeat).

Owner 2026-10-30: line the 1 up with the grid, and say so when the cues disagree rather than guess quietly.

Measured, not yet trusted: on 40 real drum loops behind made-up intros (scripts/measure_downbeat.py, 2026-10-30)
the grid lands within 15 ms of the truth most of the time, but which beat is the 1 was right on 13 of 40 (33%).
Session setup does not use ``find`` until a measured version clears the bar; it lines up the first sound.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

HOP_S = 0.002          # 2 ms frames for the grid
WINDOW = 3             # frames either side of a grid line where a hit still counts (6 ms)
SEARCH_BARS = 32       # the stretch after the first hit the grid is fitted on
REPEATS = 0.8          # two bars this alike to the two after them: the steady part has begun


@dataclass(frozen=True)
class Downbeat:
    first: float        # seconds into the file of the first 1 at or after the first hit
    grid: float         # seconds into the file of a beat on the fitted grid
    on_grid: float      # share of strong hits in the fitted stretch within 20 ms of a beat or an eighth
    alike: float        # how closely the two bars from the 1 repeat in the next two (cosine, 0 to 1)
    sure: bool          # the grid holds and the music repeats from the 1


def _bands(mono: np.ndarray, rate: int) -> list[np.ndarray]:
    from scipy.signal import butter, sosfilt

    return [sosfilt(butter(4, 120, "lowpass", fs=rate, output="sos"), mono),
            sosfilt(butter(4, [120, 2500], "bandpass", fs=rate, output="sos"), mono),
            sosfilt(butter(4, 2500, "highpass", fs=rate, output="sos"), mono)]


def _flux(x: np.ndarray, hop: int) -> np.ndarray:
    n = len(x) // hop
    if n < 2:
        return np.zeros(max(n, 1))
    e = np.sqrt(np.add.reduceat(x[: n * hop] ** 2, np.arange(0, n * hop, hop)) / hop)
    d = np.diff(e, prepend=e[0])
    d[d < 0] = 0
    return d


def _at(signal: np.ndarray, frames: np.ndarray) -> np.ndarray:
    frames = frames[(frames >= 0) & (frames < len(signal))]
    if frames.size == 0:
        return np.zeros(0)
    return np.array([signal[max(0, f - WINDOW): f + WINDOW + 1].max() for f in frames])


def _attack_shift(mono: np.ndarray, rate: int, grid: float, beat: float, count: int) -> float:
    """How far the grid sits from where the kicks actually begin: the energy rise the grid is fitted on peaks some
    25 ms after a kick's attack (measured live 2026-10-30 on two beats), so the grid is moved onto the attacks."""
    from scipy.signal import butter, sosfiltfilt

    from hiremarco.studio.beat_in import first_hit as attack

    low = sosfiltfilt(butter(4, 150, "lowpass", fs=rate, output="sos"), mono)  # zero phase: no filter delay
    loud = np.percentile(np.abs(low), 99.5)
    offsets = []
    for k in range(count):
        t = grid + k * beat
        a, b = int((t - 0.06) * rate), int((t + 0.12) * rate)
        if a < 0 or b > len(low) or np.abs(low[a:b]).max() < 0.5 * loud:
            continue
        found = a / rate + attack(low[a:b], rate) - t
        if found > -0.055:  # at the window's start: the low end was still ringing from before, not a new kick
            offsets.append(found)
    return float(np.median(offsets)) if len(offsets) >= 4 else 0.0


def find(mono: np.ndarray, rate: int, bpm: float, first_hit: float) -> Downbeat:
    hop = max(1, int(rate * HOP_S))
    fps = rate / hop
    low, mid, high = _bands(mono, rate)
    full, kick = _flux(mono, hop), _flux(low, hop)
    accent = 0.5 * full + 2 * kick  # the kick sets the grid; off-beat hats would pull it half a beat
    beat = 60.0 / bpm
    duration = len(mono) / rate
    a = int(first_hit * fps)
    b = min(len(accent), int((first_hit + SEARCH_BARS * 4 * beat) * fps))
    stretch = accent[a:b]
    count = int((b - a) / fps / beat)
    # the grid: the offset where the most weight falls on the beats
    phases = np.arange(0.0, beat, HOP_S)
    scores = [float(_at(stretch, ((ph + np.arange(count) * beat) * fps).astype(int)).sum()) for ph in phases]
    phase = float(phases[int(np.argmax(scores))])
    # on the beat or half a beat off: the kicks decide (hats and claps also sit on the off-beats)
    other = (phase + beat / 2) % beat
    kicks_at = lambda ph: float(_at(kick[a:b], ((ph + np.arange(count) * beat) * fps).astype(int)).sum())  # noqa: E731
    if kicks_at(other) > 1.15 * kicks_at(phase):
        phase = other
    grid = first_hit + phase  # on the energy rises; moved onto the attacks once the grid has been checked
    # does the grid hold: the strongest kicks of the stretch land within 25 ms of a sixteenth or a triplet
    kicks = kick[a:b]
    peaks = np.flatnonzero((kicks > np.percentile(kicks, 99.5)) & (kicks == np.maximum.reduce(
        [np.roll(kicks, k) for k in range(-25, 26)])))
    times = first_hit + peaks / fps
    near = np.minimum.reduce([np.abs(((times - grid) / step + 0.5) % 1 - 0.5) * step
                              for step in (beat / 4, beat / 6)])  # straight sixteenths or a triplet swing
    on_grid = float(np.mean(near < 0.025)) if times.size else 0.0
    grid += _attack_shift(mono, rate, grid, beat, count)
    beats = grid + np.arange(-int(grid / beat), int((duration - grid) / beat)) * beat
    beats = beats[(beats >= -0.03) & (beats + beat <= duration)]
    # where the steady part begins: the first beat whose next two bars repeat in the two bars after them (a riser,
    # a reverse cymbal, a lone pickup or silence does not repeat; a producer's bar does), counted on sixteenths
    step = beat / 4
    sixteenths = np.arange(beats[0], duration - step, step) if beats.size else np.zeros(0)
    profile = np.stack([_at(kick, (sixteenths * fps).astype(int)), _at(full, (sixteenths * fps).astype(int))], axis=1)
    loudness = profile.sum(axis=1)
    usual = np.median([loudness[i:i + 16].sum() for i in range(0, max(1, len(loudness) - 16), 16)]) or 1.0
    first_beat = int(np.argmin(np.abs(beats - first_hit)))
    best = None
    for k in range(max(0, first_beat - 4), min(len(beats), first_beat + 64)):
        i = int(round((beats[k] - beats[0]) / step))
        here, after = profile[i:i + 32].ravel(), profile[i + 16:i + 48].ravel()
        if after.size < here.size or here.size < 32 or loudness[i:i + 16].sum() < 0.1 * usual:
            continue
        alike = float(np.dot(here, after) / (np.linalg.norm(here) * np.linalg.norm(after) + 1e-12))
        # the 1 itself must sound like the 1 a bar later: a riser's or a pickup's beat does not
        one, later = profile[i:i + 4].ravel(), profile[i + 16:i + 20].ravel()
        same_one = float(np.dot(one, later) / (np.linalg.norm(one) * np.linalg.norm(later) + 1e-12))
        if alike >= REPEATS and same_one >= REPEATS and profile[i].sum() >= 0.3 * profile[i + 16].sum():
            best = (k, alike)
            break
    if best is None:
        k = first_beat
        alike = 0.0
    else:
        k, alike = best
    sure = bool(on_grid >= 0.5 and alike >= REPEATS)
    return Downbeat(float(beats[k]), grid, on_grid, alike, sure)


def attack_near(mono: np.ndarray, rate: int, at: float, within: float = 0.04) -> float:
    """The attack of the hit closest to ``at``, so a bar line meets the hit itself rather than the grid's estimate."""
    from hiremarco.studio.beat_in import first_hit

    a = max(0, int((at - within) * rate))
    b = min(len(mono), int((at + within + 0.06) * rate))  # past the window, so the hit's peak sets the threshold
    if b - a < rate * 0.005:
        return at
    found = a / rate + first_hit(mono[a:b], rate)
    return found if abs(found - at) <= within else at

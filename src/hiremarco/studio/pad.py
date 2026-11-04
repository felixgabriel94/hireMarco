"""Marco's arrival: a celestial pad on his pair while the halo is up and Logic opens (Owner 2026-11-04, "A, Aurora").

A dark saw pad on D major 9 that opens up as it swells, a second chord an octave above joining late, and a sub at D
underneath so it feels large. Synthesized here from wavetables, no file: it starts as the halo fades in, holds until
the session is open, and goes out over a second before he speaks. ``HIREMARCO_ALOUD=off`` keeps it silent like
everything else on the pair.
"""

from __future__ import annotations

import numpy as np

from hiremarco.studio import aloud

RATE = 48000
SECONDS = 40.0      # longer than any session takes to open; the booth fades it out when the session is up
ATTACK_S = 3.5
NOTES = (50, 57, 61, 64, 69)          # D2 major 9, the pad
HIGH = (62, 66, 69, 73)               # the chord above, joining late
SUB_HZ = 36.7                         # D1


def _table(harmonics: int, tilt: float = 1.3, size: int = 4096) -> np.ndarray:
    """One period of a band-limited saw, darker with fewer harmonics."""
    x = np.arange(size) / size
    table = np.zeros(size)
    for k in range(1, harmonics + 1):
        table += np.sin(2 * np.pi * k * x) / k ** tilt
    return table / np.max(np.abs(table))


def _voices(notes, t: np.ndarray, dark: np.ndarray, bright: np.ndarray, open_: np.ndarray, detune: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.zeros_like(t)
    size = len(dark)
    for midi in notes:
        f = 440.0 * 2 ** ((midi - 69) / 12)
        for d in (-detune, 0.0, detune):
            phase = (t * f * (1 + d) + rng.uniform(0, 1)) % 1.0
            idx = phase * size
            a = np.interp(idx, np.arange(size + 1), np.append(dark, dark[0]))
            b = np.interp(idx, np.arange(size + 1), np.append(bright, bright[0]))
            out += a * (1 - open_) + b * open_
    return out / (3 * len(notes))


def aurora(seconds: float = SECONDS, rate: int = RATE) -> np.ndarray:
    """The pad, stereo float32, peak at 0.85: a swell over ATTACK_S, a long hold with slow movement, a 2 s release."""
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    attack = np.clip(t / ATTACK_S, 0, 1) ** 2
    release = np.clip((seconds - t) / 2.0, 0, 1) ** 1.5
    env = attack * release
    open_ = np.clip((t - 1.0) / 6.0, 0, 1)                 # the filter opening over six seconds
    dark, bright = _table(6), _table(16)
    pad = _voices(NOTES, t, dark, bright, open_, 0.006, 7) * env
    sweep = _voices(HIGH, t, dark, bright, open_, 0.008, 11) * np.clip((t - 2.0) / 5.0, 0, 1) ** 2 * release * 0.5
    sub = np.sin(2 * np.pi * SUB_HZ * t) * (1 + 0.15 * np.sin(2 * np.pi * 0.5 * t)) * np.clip(t / 2.0, 0, 1) * release * 0.55
    mono = pad + sweep + sub
    sway = 0.04 * np.sin(2 * np.pi * 0.09 * t)
    stereo = np.stack([mono * (1 + sway), mono * (1 - sway)], axis=1)
    return (stereo / (np.max(np.abs(stereo)) + 1e-9) * 0.85).astype(np.float32)


def cache_path():
    from pathlib import Path

    from hiremarco import config

    return Path(config.STATE_DIR) / "pad-aurora.npy"


def prepare() -> np.ndarray:
    """The pad rendered once and kept in the state folder (six seconds to synthesize, 2026-11-04): the booth renders
    it as it starts, so his arrival never waits on the maths."""
    path = cache_path()
    if path.exists():
        try:
            pcm = np.load(path)
            if pcm.ndim == 2 and pcm.shape[1] == 2 and len(pcm) == int(RATE * SECONDS):
                return pcm
        except Exception:   # noqa: BLE001  a half-written file: rendered again below
            pass
    pcm = aurora()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part.npy")
    np.save(tmp, pcm)
    tmp.replace(path)
    return pcm


def start():
    """The pad on Marco's pair; None when the pair is off or out of reach, and nothing else changes."""
    if not aloud.on():
        return None
    return aloud.play(prepare(), RATE)


def stop(fade: float = 1.0) -> None:
    aloud.fade(fade)

"""The audit: Marco reads a track before he touches it.

Every number here is measured, none is modelled. On top of his ears
(``mix.ears``: integrated loudness, true peak, crest, the seven bands, stereo
correlation) the audit adds what a mastering engineer looks at first: the
loudness over time (short-term and momentary maxima, loudness range per EBU
Tech 3342), peak-to-loudness ratio, the spectrum's tilt, resonances that
stand out of the long-term spectrum, the problem bands (rumble, mud,
harshness, sibilance), width and correlation per band, what mono playback
loses, DC offset, clicks, and the silence at the head and the tail. Against
reference masters the artist owns it reports deltas, so the plan can say
"2 dB darker than its references above 6 kHz" instead of guessing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from hiremarco.mix.ears import BANDS, TrackReport, k_weighting, lufs, measure

PROBLEM_BANDS = [("rumble", 5, 30), ("mud", 200, 400), ("harsh", 2500, 5000), ("sibilance", 5000, 9000)]
TILT_RANGE = (50.0, 10000.0)      # Hz: the slope is fitted between these, away from the sub and the air
RESONANCE_RANGE = (60.0, 8000.0)  # Hz: where a sustained peak reads as a resonance, not as bass or air
RESONANCE_DB = 6.0                # a 1/12-octave bin this far above its octave's smoothed level stands out
SILENCE_DB = -60.0                # below this the head or tail counts as silence
CLICK_JUMP = 0.2                  # a sample-to-sample jump at least this large (full scale) can be a click...
CLICK_RATIO = 12.0                # ...when it is also this many times the mean jump around it
RUMBLE_DB = -15.0                 # energy under 30 Hz above this share of the whole is rumble, not sub bass
CEILING_DBTP = -1.0               # the true-peak ceiling a master is held to
ABSOLUTE_GATE = -70.0


@dataclass
class Resonance:
    hz: float
    above_db: float


@dataclass
class Audit:
    base: TrackReport
    short_term_max: float
    momentary_max: float
    loudness_range: float
    plr_db: float                               # true peak minus integrated loudness
    tilt_db_per_octave: float
    problem_bands_db: dict[str, float]          # each problem band's share of the energy, dB (0 = all of it)
    resonances: list[Resonance]
    band_correlation: dict[str, float | None]   # per mix band, stereo only
    band_width_db: dict[str, float | None]      # per mix band: side minus mid, dB; lower is narrower
    mono_loss_db: float | None                  # what folding to mono costs in loudness; 0 is fully compatible
    dc_offset: float
    clicks: int
    head_silence_s: float
    tail_silence_s: float
    sample_rate: int
    subtype: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Deltas:
    """This track against the references, positive means this track has more."""
    against: list[str]
    lufs: float
    loudness_range: float
    plr_db: float
    tilt_db_per_octave: float
    bands_db: dict[str, float]
    band_width_db: dict[str, float | None]
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _weighted(audio: np.ndarray, rate: int) -> np.ndarray:
    data = audio if audio.ndim > 1 else audio[:, None]
    return signal.sosfilt(k_weighting(rate), data, axis=0)


def block_loudness(weighted: np.ndarray, rate: int, block_s: float, hop_s: float) -> np.ndarray:
    """K-weighted loudness of every block, LUFS, the blocks ``hop_s`` apart."""
    block, hop = int(block_s * rate), max(1, int(hop_s * rate))
    if weighted.shape[0] < block:
        return np.array([])
    starts = range(0, weighted.shape[0] - block + 1, hop)
    powers = np.array([np.sum(np.mean(weighted[s:s + block] ** 2, axis=0)) for s in starts])
    return -0.691 + 10 * np.log10(np.maximum(powers, 1e-12))


def loudness_range(weighted: np.ndarray, rate: int) -> float:
    """EBU Tech 3342: short-term (3 s) loudness, absolute gate at -70, relative gate 20 LU under the gated
    mean, then the spread between the 10th and the 95th percentile."""
    short = block_loudness(weighted, rate, 3.0, 0.1)
    short = short[short > ABSOLUTE_GATE]
    if short.size < 2:
        return 0.0
    relative = -0.691 + 10 * np.log10(np.mean(10 ** ((short + 0.691) / 10))) - 20
    kept = short[short > relative]
    if kept.size < 2:
        return 0.0
    return round(float(np.percentile(kept, 95) - np.percentile(kept, 10)), 1)


def smoothed_spectrum(audio: np.ndarray, rate: int, per_octave: int = 12) -> tuple[np.ndarray, np.ndarray]:
    """The long-term spectrum in fractional-octave bins, dB (power per Hz, relative)."""
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    nperseg = min(32768, max(1024, mono.size))
    freqs, power = signal.welch(mono, rate, nperseg=nperseg)
    centers = 20.0 * 2 ** (np.arange(0, per_octave * 10 + 1) / per_octave)
    centers = centers[centers < min(20000.0, rate / 2)]
    half = 2 ** (1 / (2 * per_octave))
    levels = []
    for c in centers:
        inside = (freqs >= c / half) & (freqs < c * half)
        levels.append(10 * np.log10(max(float(np.mean(power[inside])) if np.any(inside) else 0.0, 1e-18)))
    return centers, np.array(levels)


def tilt(centers: np.ndarray, levels: np.ndarray, span: tuple[float, float] = TILT_RANGE) -> float:
    """The spectrum's slope in dB per octave between ``span``; pink noise reads about -3."""
    inside = (centers >= span[0]) & (centers <= span[1]) & (levels > -170)
    if np.sum(inside) < 4:
        return 0.0
    slope, _ = np.polyfit(np.log2(centers[inside]), levels[inside], 1)
    return round(float(slope), 2)


def resonances(centers: np.ndarray, levels: np.ndarray, per_octave: int = 12,
               above_db: float = RESONANCE_DB) -> list[Resonance]:
    """Bins that stand ``above_db`` over their own octave's smoothed level, and are a local peak."""
    if levels.size < per_octave + 2:
        return []
    kernel = np.ones(per_octave) / per_octave
    smooth = np.convolve(levels, kernel, mode="same")
    found = []
    for i in range(1, levels.size - 1):
        if not (RESONANCE_RANGE[0] <= centers[i] <= RESONANCE_RANGE[1]):
            continue
        over = levels[i] - smooth[i]
        if over >= above_db and levels[i] >= levels[i - 1] and levels[i] >= levels[i + 1]:
            found.append(Resonance(round(float(centers[i]), 1), round(float(over), 1)))
    return sorted(found, key=lambda r: -r.above_db)[:6]


def problem_shares(audio: np.ndarray, rate: int) -> dict[str, float]:
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    freqs, power = signal.welch(mono, rate, nperseg=min(8192, max(256, mono.size)))
    total = np.sum(power[(freqs >= 20) & (freqs <= 20000)]) or 1e-12
    return {name: round(float(10 * np.log10(max(np.sum(power[(freqs >= lo) & (freqs < hi)]) / total, 1e-12))), 1)
            for name, lo, hi in PROBLEM_BANDS}


def stereo_bands(audio: np.ndarray, rate: int) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """Per mix band: the correlation between the channels, and side against mid in dB."""
    corr: dict[str, float | None] = {}
    width: dict[str, float | None] = {}
    if audio.ndim < 2 or audio.shape[1] != 2:
        return {b: None for b, _, _ in BANDS}, {b: None for b, _, _ in BANDS}
    for name, lo, hi in BANDS:
        hi = min(hi, rate / 2 * 0.95)
        sos = signal.butter(4, [lo, hi], "band", fs=rate, output="sos")
        left, right = signal.sosfilt(sos, audio[:, 0]), signal.sosfilt(sos, audio[:, 1])
        if not (np.std(left) and np.std(right)):
            corr[name], width[name] = None, None
            continue
        corr[name] = round(float(np.corrcoef(left, right)[0, 1]), 2)
        mid, side = (left + right) / 2, (left - right) / 2
        width[name] = round(float(10 * np.log10(max(np.mean(side ** 2), 1e-18) / max(np.mean(mid ** 2), 1e-18))), 1)
    return corr, width


def mono_loss(audio: np.ndarray, rate: int) -> float | None:
    """Loudness lost when the mix is played in mono, as a listener's phone plays it: the fold-down on both
    channels, so identical channels lose nothing and out-of-phase content loses everything."""
    if audio.ndim < 2 or audio.shape[1] != 2:
        return None
    folded = np.repeat(audio.mean(axis=1, keepdims=True), 2, axis=1)
    return round(lufs(audio, rate) - lufs(folded, rate), 1)


def edges(audio: np.ndarray, rate: int, floor_db: float = SILENCE_DB) -> tuple[float, float]:
    level = np.max(np.abs(audio), axis=1) if audio.ndim > 1 else np.abs(audio)
    loud = np.flatnonzero(level > 10 ** (floor_db / 20))
    if loud.size == 0:
        return round(audio.shape[0] / rate, 2), 0.0
    return round(float(loud[0] / rate), 2), round(float((audio.shape[0] - 1 - loud[-1]) / rate), 2)


def clicks(audio: np.ndarray, rate: int = 48000, jump: float = CLICK_JUMP) -> int:
    """Sample-to-sample jumps far above what the music around them is doing: a click is many times the local
    mean jump (20 ms) and large on its own, so a loud transient in a loud mix is not one (live 2026-11-02: a
    plain threshold counted 15,935 clicks in a clean beat peaking over full scale)."""
    data = audio if audio.ndim > 1 else audio[:, None]
    steps = np.abs(np.diff(data, axis=0))
    if steps.shape[0] < 10:
        return 0
    window = max(3, int(0.02 * rate))
    local = np.apply_along_axis(lambda s: np.convolve(s, np.ones(window) / window, mode="same"), 0, steps)
    return int(np.sum((steps > CLICK_RATIO * np.maximum(local, 1e-6)) & (steps > jump)))


def audit_audio(audio: np.ndarray, rate: int, name: str, *, subtype: str = "") -> Audit:
    audio = np.asarray(audio, dtype=np.float64)
    base = measure(audio, rate, name)
    weighted = _weighted(audio, rate)
    short = block_loudness(weighted, rate, 3.0, 1.0)
    momentary = block_loudness(weighted, rate, 0.4, 0.1)
    centers, levels = smoothed_spectrum(audio, rate)
    corr, width = stereo_bands(audio, rate)
    head, tail = edges(audio, rate)
    return Audit(
        base=base,
        short_term_max=round(float(short.max()), 1) if short.size else -120.0,
        momentary_max=round(float(momentary.max()), 1) if momentary.size else -120.0,
        loudness_range=loudness_range(weighted, rate),
        plr_db=round(base.true_peak_db - base.lufs, 1),
        tilt_db_per_octave=tilt(centers, levels),
        problem_bands_db=problem_shares(audio, rate),
        resonances=resonances(centers, levels),
        band_correlation=corr, band_width_db=width,
        mono_loss_db=mono_loss(audio, rate),
        dc_offset=round(float(np.mean(audio)), 4),
        clicks=clicks(audio, rate),
        head_silence_s=head, tail_silence_s=tail,
        sample_rate=rate, subtype=subtype,
    )


def audit_file(path: Path) -> Audit:
    path = Path(path)
    audio, rate = sf.read(path, dtype="float32", always_2d=False)
    return audit_audio(audio, rate, path.stem, subtype=sf.info(path).subtype)


def references(folder: Path) -> list[Audit]:
    """Every WAV, AIFF or FLAC in the folder, audited; the artist's own files, never streams."""
    found = []
    for suffix in ("*.wav", "*.aif", "*.aiff", "*.flac"):
        found += sorted(Path(folder).glob(suffix))
    return [audit_file(p) for p in found]


def _mean(values: list[float | None]) -> float | None:
    kept = [v for v in values if v is not None]
    return float(np.mean(kept)) if kept else None


def compare(track: Audit, refs: list[Audit]) -> Deltas | None:
    """This track against the mean of the references; None without references."""
    if not refs:
        return None
    bands = {b: round(track.base.bands_db[b] - float(np.mean([r.base.bands_db[b] for r in refs])), 1)
             for b, _, _ in BANDS if b in track.base.bands_db}
    width = {}
    for b, _, _ in BANDS:
        mine, theirs = track.band_width_db.get(b), _mean([r.band_width_db.get(b) for r in refs])
        width[b] = round(mine - theirs, 1) if mine is not None and theirs is not None else None
    deltas = Deltas(
        against=[r.base.name for r in refs],
        lufs=round(track.base.lufs - float(np.mean([r.base.lufs for r in refs])), 1),
        loudness_range=round(track.loudness_range - float(np.mean([r.loudness_range for r in refs])), 1),
        plr_db=round(track.plr_db - float(np.mean([r.plr_db for r in refs])), 1),
        tilt_db_per_octave=round(track.tilt_db_per_octave - float(np.mean([r.tilt_db_per_octave for r in refs])), 2),
        bands_db=bands, band_width_db=width,
    )
    deltas.notes = delta_notes(deltas)
    return deltas


def delta_notes(d: Deltas) -> list[str]:
    notes = []
    if abs(d.lufs) >= 1:
        notes.append(f"{abs(d.lufs)} LU {'louder' if d.lufs > 0 else 'quieter'} than its references")
    if d.tilt_db_per_octave <= -0.5:
        notes.append(f"darker than its references (tilt {d.tilt_db_per_octave:+} dB/octave against them)")
    elif d.tilt_db_per_octave >= 0.5:
        notes.append(f"brighter than its references (tilt {d.tilt_db_per_octave:+} dB/octave against them)")
    for band, gap in d.bands_db.items():
        if abs(gap) >= 2:
            notes.append(f"{abs(gap)} dB {'more' if gap > 0 else 'less'} {band} than its references")
    if abs(d.loudness_range) >= 2:
        notes.append(f"{abs(d.loudness_range)} LU {'more' if d.loudness_range > 0 else 'less'} dynamic range than its references")
    for band, gap in d.band_width_db.items():
        if gap is not None and abs(gap) >= 3:
            notes.append(f"{'wider' if gap > 0 else 'narrower'} than its references in the {band} ({gap:+} dB side)")
    return notes


def findings(a: Audit) -> list[str]:
    """What stands out on its own, before any reference: the lines a mastering engineer would say first."""
    notes = []
    b = a.base
    if b.clipped:
        notes.append(f"{b.clipped} clipped samples")
    if a.clicks:
        notes.append(f"{a.clicks} clicks or dropouts")
    if abs(a.dc_offset) >= 0.001:
        notes.append(f"DC offset {a.dc_offset:+.4f}")
    if b.true_peak_db > CEILING_DBTP:
        notes.append(f"true peak {b.true_peak_db} dBTP, over the {CEILING_DBTP:g} dBTP ceiling")
    if a.problem_bands_db.get("rumble", -99) > RUMBLE_DB:
        notes.append(f"energy under 30 Hz at {a.problem_bands_db['rumble']} dB of the whole: rumble to high-pass")
    if a.mono_loss_db is not None and a.mono_loss_db >= 1.5:
        notes.append(f"mono playback loses {a.mono_loss_db} LU: something wide is out of phase")
    if b.low_mono is not None and b.low_mono < 0.8:
        notes.append(f"low end below 120 Hz is wide (correlation {b.low_mono})")
    for r in a.resonances[:3]:
        notes.append(f"resonance at {r.hz:g} Hz, {r.above_db} dB over its octave")
    if a.head_silence_s > 1.0:
        notes.append(f"{a.head_silence_s} s of silence at the head")
    if a.tail_silence_s > 3.0:
        notes.append(f"{a.tail_silence_s} s of silence at the tail")
    if a.plr_db < 8:
        notes.append(f"peak-to-loudness {a.plr_db} dB: already limited hard")
    if a.loudness_range < 4:
        notes.append(f"loudness range {a.loudness_range} LU: little dynamic movement")
    return notes


def summary(a: Audit, deltas: Deltas | None = None) -> str:
    b = a.base
    lines = [f"{b.name}: {b.seconds} s, {a.sample_rate} Hz {a.subtype or ''}".rstrip(),
             f"loudness {b.lufs} LUFS integrated, short-term max {a.short_term_max}, momentary max {a.momentary_max}, "
             f"range {a.loudness_range} LU",
             f"true peak {b.true_peak_db} dBTP, PLR {a.plr_db} dB, crest {b.crest_db} dB",
             f"tilt {a.tilt_db_per_octave:+} dB/octave; bands " + ", ".join(f"{k} {v}" for k, v in b.bands_db.items()),
             "problem bands " + ", ".join(f"{k} {v}" for k, v in a.problem_bands_db.items())]
    if b.correlation is not None:
        lines.append(f"correlation {b.correlation}, low end {b.low_mono}, mono loses {a.mono_loss_db} LU; width "
                     + ", ".join(f"{k} {v}" for k, v in a.band_width_db.items() if v is not None))
    lines += [f"finding: {n}" for n in findings(a)]
    if deltas:
        lines += [f"against {', '.join(deltas.against)}: {n}" for n in deltas.notes] or \
                 [f"against {', '.join(deltas.against)}: within range on loudness, tilt, bands and width"]
    return "\n".join(lines)

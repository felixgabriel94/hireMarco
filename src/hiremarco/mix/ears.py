"""Marco's mix ears: what each track and the mix actually sound like, as numbers.

Built here, no model: loudness by ITU-R BS.1770-4 (K-weighting, 400 ms blocks,
absolute and relative gates), sample and true peak (4x oversampled), crest
factor, the share of energy in seven mix bands, stereo correlation and how
mono the low end is. Between tracks, a collision is a band where two tracks
both put real energy within a few dB of each other: the kick and the bass
fighting at 60-250 Hz, a guitar sitting on the vocal at 2-4 kHz. The mix
check measures what a mastering engineer needs: headroom, no clipping, and
loudness left for mastering.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

BANDS = [
    ("sub", 20, 60), ("bass", 60, 250), ("low mids", 250, 500), ("mids", 500, 2000),
    ("upper mids", 2000, 4000), ("presence", 4000, 6000), ("air", 6000, 20000),
]
SILENT_LUFS = -60.0
COLLISION_DB = 6.0      # two tracks within this of each other in a band...
STRONG_SHARE_DB = -12.0  # ...where each has at least this share of its own energy
MASTER_PEAK_MAX = -3.0  # dBFS: headroom a mastering engineer expects at least
MASTER_LUFS_RANGE = (-23.0, -12.0)


@dataclass
class TrackReport:
    name: str
    seconds: float
    lufs: float
    peak_db: float
    true_peak_db: float
    crest_db: float
    bands_db: dict[str, float]          # each band's share of the track's energy, dB (0 = all of it)
    correlation: float | None = None    # stereo only: 1 mono, 0 wide, below 0 out of phase
    low_mono: float | None = None       # stereo only: correlation below 120 Hz
    clipped: int = 0

    @property
    def silent(self) -> bool:
        return self.lufs <= SILENT_LUFS


@dataclass
class Collision:
    a: str
    b: str
    band: str
    gap_db: float


@dataclass
class EarsReport:
    tracks: list[TrackReport] = field(default_factory=list)
    collisions: list[Collision] = field(default_factory=list)
    mix: TrackReport | None = None
    mix_notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _db(x: float) -> float:
    return float(10 * np.log10(max(x, 1e-12)))


def k_weighting(rate: int) -> np.ndarray:
    """The BS.1770 K filter (shelf plus high-pass) as second-order sections for any sample rate."""
    # Pre-filter: high shelf, about +4 dB above 1.5 kHz.
    f0, gain_db, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * f0 / rate)
    vh = 10 ** (gain_db / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    shelf = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0,
             1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    # RLB filter: high-pass at about 38 Hz.
    f0, q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * f0 / rate)
    a0 = 1 + k / q + k * k
    highpass = [1.0, -2.0, 1.0, 1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    return np.array([shelf, highpass])


def lufs(audio: np.ndarray, rate: int) -> float:
    data = audio if audio.ndim > 1 else audio[:, None]
    weighted = signal.sosfilt(k_weighting(rate), data, axis=0)
    block, hop = int(0.4 * rate), int(0.1 * rate)
    if weighted.shape[0] < block:
        return -120.0
    starts = range(0, weighted.shape[0] - block + 1, hop)
    powers = np.array([np.sum(np.mean(weighted[s:s + block] ** 2, axis=0)) for s in starts])
    loud = -0.691 + 10 * np.log10(np.maximum(powers, 1e-12))
    gated = powers[loud > -70]
    if gated.size == 0:
        return -120.0
    relative = -0.691 + 10 * np.log10(np.mean(gated)) - 10
    final = powers[(loud > -70) & (loud > relative)]
    return round(-0.691 + 10 * np.log10(np.mean(final)) if final.size else -120.0, 1)


BEAT_LUFS = -20.0       # where a beat sits at the start of a session (Owner 2026-10-29): room for every track after it
BEAT_TRUE_PEAK = -6.0   # and its peaks stay this far under full scale, whatever its loudness


def beat_gain(audio: np.ndarray, rate: int) -> tuple[float, float, float]:
    """The region gain, in dB to a tenth, that puts a beat at BEAT_LUFS with true peaks at or under
    BEAT_TRUE_PEAK, measured on the file itself (never the master meter, which carries the click):
    (gain, loudness before, true peak before)."""
    audio = np.asarray(audio, dtype=np.float64)
    loud = lufs(audio, rate)
    tp = 20 * np.log10(max(float(np.max(np.abs(signal.resample_poly(audio, 4, 1, axis=0)))), 1e-9))
    gain = min(BEAT_LUFS - loud, BEAT_TRUE_PEAK - tp)
    return round(max(min(gain, 30.0), -30.0), 1), round(loud, 1), round(tp, 1)


def band_shares(audio: np.ndarray, rate: int) -> dict[str, float]:
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    freqs, power = signal.welch(mono, rate, nperseg=min(8192, max(256, mono.size)))
    total = np.sum(power[(freqs >= 20) & (freqs <= 20000)]) or 1e-12
    return {name: round(_db(np.sum(power[(freqs >= lo) & (freqs < hi)]) / total), 1) for name, lo, hi in BANDS}


def measure(audio: np.ndarray, rate: int, name: str) -> TrackReport:
    audio = np.asarray(audio, dtype=np.float64)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
    upsampled = signal.resample_poly(audio, 4, 1, axis=0) if audio.size else audio
    true_peak = float(np.max(np.abs(upsampled))) if audio.size else 0.0
    correlation = low_mono = None
    if audio.ndim > 1 and audio.shape[1] == 2 and np.any(audio):
        left, right = audio[:, 0], audio[:, 1]
        correlation = round(float(np.corrcoef(left, right)[0, 1]), 2) if np.std(left) and np.std(right) else 1.0
        lp = signal.butter(4, 120, "low", fs=rate, output="sos")
        ll, rl = signal.sosfilt(lp, left), signal.sosfilt(lp, right)
        low_mono = round(float(np.corrcoef(ll, rl)[0, 1]), 2) if np.std(ll) and np.std(rl) else 1.0
    return TrackReport(
        name=name, seconds=round(audio.shape[0] / rate, 2), lufs=lufs(audio, rate),
        peak_db=round(20 * np.log10(max(peak, 1e-9)), 1), true_peak_db=round(20 * np.log10(max(true_peak, 1e-9)), 1),
        crest_db=round(20 * np.log10(max(peak, 1e-9) / max(rms, 1e-9)), 1) if rms else 0.0,
        bands_db=band_shares(audio, rate) if audio.size else {},
        correlation=correlation, low_mono=low_mono, clipped=int(np.sum(np.abs(audio) >= 0.9999)),
    )


def collisions(tracks: list[TrackReport]) -> list[Collision]:
    """Bands where two audible tracks both carry real energy at similar loudness."""
    live = [t for t in tracks if not t.silent]
    found = []
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            for band, _, _ in BANDS:
                share_a, share_b = a.bands_db.get(band, -99), b.bands_db.get(band, -99)
                if share_a < STRONG_SHARE_DB or share_b < STRONG_SHARE_DB:
                    continue
                level_a, level_b = a.lufs + share_a, b.lufs + share_b  # each track's energy in that band
                gap = abs(level_a - level_b)
                if gap <= COLLISION_DB:
                    found.append(Collision(a.name, b.name, band, round(gap, 1)))
    return sorted(found, key=lambda c: c.gap_db)


def mix_notes(mix: TrackReport) -> list[str]:
    """What stands between this mix and a mastering engineer's inbox."""
    notes = []
    if mix.true_peak_db > MASTER_PEAK_MAX:
        notes.append(f"true peak {mix.true_peak_db} dBFS: leave at least {abs(MASTER_PEAK_MAX):g} dB of headroom")
    if mix.clipped:
        notes.append(f"{mix.clipped} clipped samples")
    low, high = MASTER_LUFS_RANGE
    if mix.lufs > high:
        notes.append(f"{mix.lufs} LUFS is already loud: likely limited, leave loudness to mastering")
    elif mix.lufs < low:
        notes.append(f"{mix.lufs} LUFS is very quiet for a mix")
    if mix.low_mono is not None and mix.low_mono < 0.8:
        notes.append(f"low end below 120 Hz is wide (correlation {mix.low_mono}): keep the low end mono")
    if mix.correlation is not None and mix.correlation < 0:
        notes.append(f"stereo correlation {mix.correlation}: phase problem")
    return notes


def listen(folder: Path, mix_file: Path | None = None) -> EarsReport:
    report = EarsReport()
    for path in sorted(Path(folder).glob("*.wav")) + sorted(Path(folder).glob("*.aif*")):
        if mix_file and path.resolve() == Path(mix_file).resolve():
            continue
        audio, rate = sf.read(path, dtype="float32", always_2d=False)
        report.tracks.append(measure(audio, rate, path.stem))
    report.collisions = collisions(report.tracks)
    if mix_file:
        audio, rate = sf.read(mix_file, dtype="float32", always_2d=False)
        report.mix = measure(audio, rate, Path(mix_file).stem)
        report.mix_notes = mix_notes(report.mix)
    return report


def summary(report: EarsReport, top: int = 8) -> str:
    lines = []
    for t in report.tracks:
        if t.silent:
            lines.append(f"{t.name}: silent")
            continue
        loudest = max(t.bands_db, key=t.bands_db.get)
        lines.append(f"{t.name}: {t.lufs} LUFS, peak {t.true_peak_db} dBTP, crest {t.crest_db} dB, "
                     f"most energy in {loudest}" + (" , CLIPPING" if t.clipped else ""))
    for c in report.collisions[:top]:
        lines.append(f"collision: {c.a} and {c.b} in the {c.band} (within {c.gap_db} dB)")
    if report.mix:
        lines.append(f"mix: {report.mix.lufs} LUFS, true peak {report.mix.true_peak_db} dBTP")
        lines += [f"mix: {n}" for n in report.mix_notes] or ["mix: ready for mastering on headroom and loudness"]
    return "\n".join(lines)

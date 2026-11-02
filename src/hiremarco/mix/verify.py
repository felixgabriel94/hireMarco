"""Verification before "done": the master against the mix, the chain check against the mix, the strip's manifest.

The Owner's rule (2026-11-02): no step is done until its result is read back
and checked by a test that can fail. A stray Kickstart on the output ducked a
whole master until he heard it, so this module is what would have caught it:
the eight-bar chain check and the master are compared with the mix print,
loudness-matched, for new periodic modulation at the song's tempo (pumping),
for tonal change beyond the plan, and for a change in crest that a limiter
alone would not make; and every insert on the output is accounted for as the
artist's, planned, or a stray before any print starts. The delivery says what
was checked, with the numbers, and names what could not be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import time

import numpy as np
import soundfile as sf

from hiremarco.mix import audit as auditing
from hiremarco.mix.ears import BANDS

HOP_S = 0.02                 # the loudness envelope's step
BLOCK_S = 0.05
PUMP_LIMIT_DB = 1.5          # new modulation at the beat or bar rate beyond this fails
BAND_LIMIT_DB = 4.0          # a band moved beyond this, after loudness matching, fails
PLANNED_BAND_DB = 1.5        # a tonal move the plan asked for may be this big on top
CREST_LIMIT_DB = 8.0         # a crest drop beyond this is damage, not limiting
PLR_FLOOR_DB = 8.0           # peak-to-loudness under this is a master limited hard (the audit's own line)
WIDTH_LIMIT_DB = 1.5         # a band's side-against-mid moved beyond this is width lost or invented
MONO_LOSS_LIMIT_LU = 0.5     # mono playback losing this much more than the mix did is openness lost


@dataclass
class Verdict:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    numbers: dict = field(default_factory=dict)
    checked: list[str] = field(default_factory=list)
    not_checked: list[str] = field(default_factory=list)

    def text(self) -> str:
        head = "verified" if self.passed else "NOT VERIFIED"
        lines = [head + ": " + "; ".join(self.checked)]
        if self.reasons:
            lines.append("failed on: " + "; ".join(self.reasons))
        if self.not_checked:
            lines.append("not checked: " + "; ".join(self.not_checked))
        return "\n".join(lines)


def envelope(audio: np.ndarray, rate: int) -> np.ndarray:
    """Short-term loudness in dB every HOP_S, K-weighted, the slow trend (1 s) taken out."""
    env = auditing.block_loudness(auditing._weighted(audio, rate), rate, BLOCK_S, HOP_S)
    if env.size == 0:
        return env
    env = np.where(env < -80, -80, env)
    window = max(1, int(1.0 / HOP_S))
    kernel = np.ones(window) / window
    trend = np.convolve(env, kernel, mode="same")
    return env - trend


def beat_modulation(audio: np.ndarray, rate: int, bpm: float) -> dict[str, float]:
    """How much the loudness swings in step with the tempo: the envelope folded over the beat and over the bar, the
    peak-to-trough of the folded mean, in dB. A ducker on the output shows here; a limiter does not."""
    env = envelope(audio, rate)
    out = {}
    for name, beats in (("beat", 1.0), ("bar", 4.0)):
        period = beats * 60.0 / bpm / HOP_S
        if env.size < 4 * period or period < 2:
            out[name] = 0.0
            continue
        bins = 32
        phase = (np.arange(env.size) % period) / period
        folded = []
        for b in range(bins):
            picked = env[(phase >= b / bins) & (phase < (b + 1) / bins)]
            if picked.size:
                folded.append(float(picked.mean()))
        out[name] = float(max(folded) - min(folded)) if len(folded) > 1 else 0.0
    return out


def band_levels(audio: np.ndarray, rate: int) -> dict[str, float]:
    """Each mix band's level in dB from the smoothed spectrum, relative to the whole."""
    centers, levels = auditing.smoothed_spectrum(audio, rate)
    out = {}
    for name, lo, hi in BANDS:
        inside = (centers >= lo) & (centers < hi)
        out[name] = float(np.mean(levels[inside])) if inside.any() else float("nan")
    return out


def crest_db(audio: np.ndarray) -> float:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
    return 20 * np.log10(max(peak, 1e-9) / max(rms, 1e-9))


def _read(path: Path, start_s: float | None = None, length_s: float | None = None) -> tuple[np.ndarray, int]:
    info = sf.info(str(path))
    start = int((start_s or 0) * info.samplerate)
    frames = int(length_s * info.samplerate) if length_s else -1
    audio, rate = sf.read(str(path), dtype="float32", always_2d=True, start=start, frames=frames)
    return audio, rate


def compare(mix_path: Path, master_path: Path, bpm: float, *, start_s: float | None = None,
            length_s: float | None = None, planned_bands: dict[str, float] | None = None,
            tonal_only: bool = False, master_start_s: float | None = None) -> Verdict:
    """The master (or a chain check) against the mix over the same stretch, loudness-matched: fails on new
    tempo-locked modulation, on a band moved beyond the plan, or on a crest that collapsed. A short print that
    starts at the stretch's first bar is read from ``master_start_s`` (0), not from the mix's offset (run 35,
    2026-11-02: the loudest bars' offset sliced a nineteen-second print past its end)."""
    from hiremarco import events

    stretch = f"{length_s:.0f} s from {start_s:.0f} s" if start_s is not None and length_s else "the whole song"
    call_id = events.new_call_id()
    events.emit("verification_started", source="marco", operation="verification", status="running",
                summary=f"{Path(master_path).stem[:50]} against the mix, {stretch}", call_id=call_id)
    began = time.monotonic()
    v = Verdict(True)
    try:
        v = _compare(mix_path, master_path, bpm, start_s, length_s, planned_bands, tonal_only, master_start_s)
    finally:
        events.emit("verification_completed", source="marco", operation="verification",
                    status="ok" if v.passed else "failed",
                    summary=("verified" if v.passed else "not verified: " + (v.reasons[0] if v.reasons else "")),
                    metrics=_verdict_metrics(v), latency_ms=int((time.monotonic() - began) * 1000), call_id=call_id)
    return v


def _verdict_metrics(v: Verdict) -> list[tuple]:
    n = v.numbers
    out = []
    if "modulation_beat_new_db" in n:
        out.append(("Pumping at the beat", f"{n['modulation_beat_new_db']:+.1f}", "dB"))
    if "crest_master_db" in n:
        out.append(("Crest", f"{n['crest_mix_db']:.1f} to {n['crest_master_db']:.1f}", "dB"))
    if "plr_master_db" in n:
        out.append(("Peak to loudness", f"{n['plr_master_db']:.1f}", "dB"))
    if "master_lufs" in n:
        out.append(("Loudness", f"{n['master_lufs']:.1f}", "LUFS"))
    return out


def _compare(mix_path, master_path, bpm, start_s, length_s, planned_bands, tonal_only, master_start_s) -> Verdict:
    v = Verdict(True)
    try:
        mix, rate = _read(mix_path, start_s, length_s)
        master, rate2 = _read(master_path, start_s if master_start_s is None else master_start_s, length_s)
    except Exception as exc:  # noqa: BLE001
        v.passed = False
        v.reasons.append(f"could not read the prints: {type(exc).__name__}")
        return v
    if rate != rate2:
        v.not_checked.append(f"sample rates differ ({rate} and {rate2})")
        return v
    n = min(mix.shape[0], master.shape[0])
    if n < rate:
        v.passed = False
        v.reasons.append(f"the prints overlap for {n / rate:.1f} s only; nothing to compare")
        return v
    mix, master = mix[:n], master[:n]
    from hiremarco.mix.ears import lufs

    lm, ls = lufs(mix, rate), lufs(master, rate)
    v.numbers["mix_lufs"], v.numbers["master_lufs"] = round(lm, 1), round(ls, 1)
    master_raw = master
    if ls > -60 and lm > -60:
        master = master * 10 ** ((lm - ls) / 20)     # loudness-matched
    v.checked.append(f"loudness-matched the master ({ls:.1f} LUFS) to the mix ({lm:.1f} LUFS) over {n / rate:.0f} s")
    # pumping: new modulation in step with the tempo
    mm, ms = beat_modulation(mix, rate, bpm), beat_modulation(master, rate, bpm)
    for key in ("beat", "bar"):
        new = ms[key] - mm[key]
        v.numbers[f"modulation_{key}_new_db"] = round(new, 2)
        if new > PUMP_LIMIT_DB:
            v.passed = False
            v.reasons.append(f"the master pumps at the {key} rate: {ms[key]:.1f} dB of swing where the mix has {mm[key]:.1f} dB")
    v.checked.append(f"no new modulation at the beat or bar rate (beat {ms['beat'] - mm['beat']:+.1f} dB, bar {ms['bar'] - mm['bar']:+.1f} dB)")
    # tone: each band against the mix, beyond the plan
    bm, bs = band_levels(mix, rate), band_levels(master, rate)
    deltas = {k: round(bs[k] - bm[k], 1) for k in bm if not np.isnan(bm[k]) and not np.isnan(bs[k])}
    v.numbers["band_deltas_db"] = deltas
    for name, d in deltas.items():
        allowed = BAND_LIMIT_DB + abs((planned_bands or {}).get(name, 0.0)) + (PLANNED_BAND_DB if planned_bands else 0.0)
        if abs(d) > allowed:
            v.passed = False
            v.reasons.append(f"{name} moved {d:+.1f} dB against the mix, beyond the {allowed:.1f} dB the plan allows")
    v.checked.append("every band within the plan's reach of the mix (" + ", ".join(f"{k} {d:+.1f}" for k, d in deltas.items()) + ")")
    if not tonal_only:
        cm, cs = crest_db(mix), crest_db(master)
        v.numbers["crest_mix_db"], v.numbers["crest_master_db"] = round(cm, 1), round(cs, 1)
        if cm - cs > CREST_LIMIT_DB:
            v.passed = False
            v.reasons.append(f"the crest fell from {cm:.1f} to {cs:.1f} dB, more than a limiter takes")
        v.checked.append(f"crest {cm:.1f} to {cs:.1f} dB, within what a limiter takes")
        # transients kept: the master's own peak-to-loudness, before matching, stays over the floor; a mix that
        # arrived with less headroom than the floor sets its own, one dB under what it had
        plr = float(20 * np.log10(max(float(np.max(np.abs(master_raw))), 1e-9))) - ls if ls > -60 else 99.0
        plr_mix = float(20 * np.log10(max(float(np.max(np.abs(mix))), 1e-9))) - lm if lm > -60 else 99.0
        floor = min(PLR_FLOOR_DB, plr_mix - 1.0)
        v.numbers["plr_master_db"], v.numbers["plr_mix_db"] = round(plr, 1), round(plr_mix, 1)
        if plr < floor:
            v.passed = False
            v.reasons.append(f"peak-to-loudness {plr:.1f} dB: limited hard, under the {floor:.1f} dB floor")
        v.checked.append(f"peak-to-loudness {plr:.1f} dB, over the {floor:.1f} dB floor")
        # openness kept: width per band and what mono loses, against the mix
        if mix.ndim == 2 and mix.shape[1] == 2:
            from hiremarco.mix.audit import mono_loss, stereo_bands

            _, wm = stereo_bands(mix, rate)
            _, ws = stereo_bands(master, rate)
            width = {k: round(ws[k] - wm[k], 1) for k in wm if wm[k] is not None and ws[k] is not None}
            v.numbers["width_deltas_db"] = width
            for name, d in width.items():
                if abs(d) > WIDTH_LIMIT_DB:
                    v.passed = False
                    v.reasons.append(f"{name} width moved {d:+.1f} dB against the mix")
            lossm, losss = mono_loss(mix, rate), mono_loss(master, rate)
            if lossm is not None and losss is not None:
                v.numbers["mono_loss_new_lu"] = round(losss - lossm, 2)
                if losss - lossm > MONO_LOSS_LIMIT_LU:
                    v.passed = False
                    v.reasons.append(f"mono playback loses {losss:.1f} LU where the mix lost {lossm:.1f}")
            v.checked.append("width per band and the mono fold within reach of the mix ("
                             + ", ".join(f"{k} {d:+.1f}" for k, d in width.items()) + ")")
    return v


def manifest(inserts, ledger: list[dict], planned: set[str], same) -> list[dict]:
    """Every insert on the output accounted for: the artist's (not in Marco's ledger), planned (Marco's and in
    the plan's roles), or a stray (Marco's, in no role, or written down as a stray)."""
    marcos = {row["name"] for row in ledger}
    strays = {row["name"] for row in ledger if row.get("stray")}
    out = []
    counts: dict[str, int] = {}
    for i in sorted(inserts, key=lambda i: i.y):
        ordinal = counts.get(i.name, 0)
        counts[i.name] = ordinal + 1
        if i.name not in marcos:
            status = "yours"
        elif i.name in strays and not any(same(p, i.name) for p in planned):
            status = "stray"
        elif any(same(p, i.name) for p in planned):
            status = "planned"
        else:
            status = "stray"
        out.append({"name": i.name, "y": round(i.y), "ordinal": ordinal, "bypassed": i.bypassed, "status": status})
    return out

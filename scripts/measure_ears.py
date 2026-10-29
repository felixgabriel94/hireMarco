"""Measure the pitch ears on sung-like test lines with breath, reverb and beat bleed: uv run python scripts/measure_ears.py"""
import numpy as np, time
from scipy.signal import lfilter, fftconvolve
from hiremarco.studio import tune
rate = 48000
rng = np.random.default_rng(3)
def line(notes):
    f, truth = [], []
    prev = None
    for midi, secs, off, vib in notes:
        n = int(secs * rate); t = np.arange(n) / rate
        m = midi + off / 100 + (0.35 * np.sin(2 * np.pi * 5.5 * t) if vib else 0) + 0.15 * np.sin(2 * np.pi * 0.6 * t)
        if prev is not None:
            g = min(int(0.06 * rate), n); m[:g] = np.linspace(prev, m[g], g)
        prev = m[-1]; f.append(440 * 2 ** ((m - 69) / 12)); truth.append(m)
        gap = int(0.08 * rate); f.append(np.zeros(gap)); truth.append(np.full(gap, np.nan)); prev = None
    f = np.concatenate(f); truth = np.concatenate(truth)
    phase = 2 * np.pi * np.cumsum(f) / rate
    amp = (f > 0).astype(float)
    src = sum(np.sin(k * phase) / k ** 1.2 for k in range(1, 30)) * amp
    for fc, bw in ((650, 120), (1100, 140), (2600, 200)):
        r = np.exp(-np.pi * bw / rate); th = 2 * np.pi * fc / rate
        src = lfilter([1 - r], [1, -2 * r * np.cos(th), r * r], src)
    return src / np.max(np.abs(src)) * 0.4, truth
def beat(n):
    t = np.arange(n) / rate; out = np.zeros(n)
    for k in range(0, n, int(rate * 0.5)):  # 120 bpm kick
        seg = np.arange(min(int(rate * 0.25), n - k)) / rate
        out[k:k + seg.size] += np.sin(2 * np.pi * (50 + 80 * np.exp(-seg * 30)) * seg) * np.exp(-seg * 12)
    for k in range(int(rate * 0.25), n, int(rate * 0.25)):  # hats
        m = min(int(rate * 0.03), n - k); out[k:k + m] += rng.standard_normal(m) * 0.3 * np.exp(-np.arange(m) / rate * 150)
    out += 0.3 * np.sin(2 * np.pi * 55 * t)  # bass
    return out / np.max(np.abs(out))
notes = [(57, 0.7, 30, False), (60, 0.6, -35, False), (62, 1.0, 20, True), (64, 0.5, -25, False), (67, 0.9, 40, True), (65, 0.6, -15, False), (62, 0.8, 10, False)]
voice, truth = line(notes)
conditions = {
    "clean": voice,
    "breath": voice + rng.standard_normal(voice.size) * 0.02,
    "reverb": fftconvolve(voice, rng.standard_normal(int(rate * 0.6)) * np.exp(-np.arange(int(rate * 0.6)) / rate * 6) * 0.05)[:voice.size],
    "beat bleed": voice + beat(voice.size) * 0.12,
    "all three": fftconvolve(voice, rng.standard_normal(int(rate * 0.6)) * np.exp(-np.arange(int(rate * 0.6)) / rate * 6) * 0.05)[:voice.size] + rng.standard_normal(voice.size) * 0.02 + beat(voice.size) * 0.12,
}
frames = np.arange(int(np.ceil(voice.size / tune.HOP))) * tune.HOP
true_midi = truth[np.minimum(frames, truth.size - 1)]
print(f"{'condition':12} {'ear':6} {'within 50c':>10} {'mean |err| c':>12} {'false voiced':>12} {'time':>6}")
for cname, audio in conditions.items():
    for ear in ("pyin", "crepe", "both"):
        t = time.monotonic(); midi, voiced = tune.pitch_track(audio.astype(np.float32), rate, ear=ear); dt = time.monotonic() - t
        n = min(midi.size, true_midi.size); m, v, tr = midi[:n], voiced[:n], true_midi[:n]
        sung = ~np.isnan(tr); both = sung & v
        err = np.abs(m[both] - tr[both]) * 100
        within = (both & (np.abs(np.nan_to_num(m - tr, nan=99)) * 100 <= 50)).sum() / sung.sum()
        false = (v & ~sung).sum() / max(1, (~sung).sum())
        print(f"{cname:12} {ear:6} {within*100:9.1f}% {np.mean(err) if err.size else float('nan'):11.1f} {false*100:11.1f}% {dt:5.1f}s")

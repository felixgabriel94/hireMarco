"""Marco's first tuning pass: his own ear decides, a formant-keeping shifter renders.

The ear: probabilistic YIN (pYIN, Mauch and Dixon, ICASSP 2014; librosa's
implementation) gives the sung pitch frame by frame. Each voiced stretch is
cut into notes where the pitch settles on one scale degree of the song's key;
what lies between notes is a glide and is left as sung. Inside a note the
pitch is split three ways: its center (the median), its slow drift (what a
0.3 s moving average keeps), and the fast part, which is vibrato when it
swings at 4 to 8 Hz and is never touched.

The plan has two amounts, as in Melodyne's Correct Pitch: ``center`` moves
each note's center that far toward the scale note (100 is all the way), and
``drift`` takes that much of the slow wander out. A first pass that sounds
like the artist sits near 80 and 30.

The render: Rubber Band (R3 engine, formants preserved) follows a pitch map,
one offset per analysis hop; its realtime mode adds a little latency, which
is measured against the original and taken out, so the tuned take lines up
sample for sample with the take it came from. The original is not changed.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HOP = 512
EAR = "both"  # pYIN and CREPE together: on test lines with reverb, breath and beat bleed, 96.6% of sung frames within
# 50 cents against 90.8% (pYIN) and 95.8% (CREPE), at pYIN's precision on clean notes (2.8 cents), 2026-10-29
NOTE_MIN_S = 0.15  # shorter than this between two notes is the glide passing a note, left as sung
VIBRATO_HZ = (4.0, 8.0)


@dataclass
class Note:
    start: int          # analysis frame
    end: int            # exclusive
    center: float       # midi, the median sung pitch
    target: int         # midi, the scale note it belongs to
    vibrato: bool

    @property
    def cents_off(self) -> float:
        return (self.center - self.target) * 100


@dataclass
class Pass:
    notes: list[Note]
    offsets: np.ndarray   # semitones per frame, what the render applies
    rate: int
    hop: int = HOP

    def summary(self) -> dict:
        off = [abs(n.cents_off) for n in self.notes]
        return {"notes": len(self.notes), "vibrato_notes": sum(n.vibrato for n in self.notes),
                "median_cents_off": round(float(np.median(off)), 1) if off else 0.0,
                "worst_cents_off": round(float(np.max(off)), 1) if off else 0.0}


def pitch_track(audio: np.ndarray, rate: int, ear: str | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Midi pitch per hop (nan where unvoiced) and the voiced mask, from the chosen ear."""
    ear = ear or EAR
    if ear == "crepe":
        return crepe_track(audio, rate)
    if ear == "both":
        return both_track(audio, rate)
    return pyin_track(audio, rate)


def both_track(audio: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
    """Two ears: pYIN's value where the two agree within half a semitone (it is the finer of the two on a
    clean tone), CREPE's where pYIN loses the note (it holds on through reverb, breath and bleed)."""
    p_midi, p_voiced = pyin_track(audio, rate)
    c_midi, c_voiced = crepe_track(audio, rate)
    n = min(p_midi.size, c_midi.size)
    p_midi, p_voiced, c_midi, c_voiced = p_midi[:n], p_voiced[:n], c_midi[:n], c_voiced[:n]
    agree = p_voiced & c_voiced & (np.abs(np.nan_to_num(p_midi - c_midi, nan=9.0)) <= 0.5)
    midi = np.where(agree, p_midi, np.where(c_voiced, c_midi, np.where(p_voiced, p_midi, np.nan)))
    return midi, ~np.isnan(midi)


def crepe_track(audio: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
    """CREPE (Kim, Salamon, Li and Bello, ICASSP 2018), the full model, on the Mac's GPU when it has one: a
    neural pitch tracker trained on sung and played notes, steadier than pYIN on breath and bleed."""
    import torch
    import torchcrepe
    from scipy.signal import resample_poly

    mono = resample_poly(audio.astype(np.float64), 1, rate // 16000).astype(np.float32) if rate % 16000 == 0 else \
        np.interp(np.arange(int(audio.size * 16000 / rate)) * rate / 16000, np.arange(audio.size), audio).astype(np.float32)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    pitch, periodicity = torchcrepe.predict(torch.from_numpy(mono)[None], 16000, hop_length=160, fmin=65.0, fmax=1100.0,
                                            model="full", decoder=torchcrepe.decode.weighted_argmax, return_periodicity=True,
                                            batch_size=1024, device=device)
    periodicity = torchcrepe.filter.median(periodicity, 3)
    f0 = pitch[0].cpu().numpy()
    conf = periodicity[0].cpu().numpy()
    times = np.arange(f0.size) * 0.01
    ours = np.arange(int(np.ceil(audio.size / HOP))) * HOP / rate
    f0 = np.interp(ours, times, f0)
    voiced = np.interp(ours, times, conf) >= 0.45
    midi = np.where(voiced, 69 + 12 * np.log2(np.maximum(f0, 1.0) / 440.0), np.nan)
    return midi, voiced


def pyin_track(audio: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
    """pYIN (Mauch and Dixon, ICASSP 2014), librosa's implementation."""
    import librosa

    f0, voiced, _ = librosa.pyin(audio.astype(np.float32), fmin=65.0, fmax=1100.0, sr=rate,
                                 frame_length=2048, hop_length=HOP)
    midi = np.where(voiced, 69 + 12 * np.log2(np.where(f0 > 0, f0, 1.0) / 440.0), np.nan)
    return midi, voiced


def _smooth(x: np.ndarray, width: int) -> np.ndarray:
    if width <= 1:
        return x.copy()
    pad = width // 2
    padded = np.pad(x, (pad, width - pad - 1), mode="edge")
    return np.convolve(padded, np.ones(width) / width, mode="valid")


def nearest_in_key(midi: float, scale: tuple[int, ...], tonic: int) -> int:
    base = int(np.floor(midi)) - 2
    choices = [n for n in range(base, base + 6) if (n - tonic) % 12 in scale]
    return min(choices, key=lambda n: abs(n - midi))


def plan(audio: np.ndarray, rate: int, key: str, *, center: float = 80, drift: float = 30,
         track: tuple[np.ndarray, np.ndarray] | None = None, reference_cents: float = 0.0) -> Pass:
    """``reference_cents`` is the beat's tuning against A = 440 (+24 for a beat at 446 Hz): notes are judged
    and corrected on that grid, so a vocal is pulled to the beat, not to 440 (Owner 2026-10-29, standard)."""
    from hiremarco.studio.pitch import parse_key

    tonic, scale = parse_key(key)
    midi, voiced = track if track is not None else pitch_track(audio, rate)
    midi = midi - reference_cents / 100.0
    fps = rate / HOP
    min_frames = max(2, int(NOTE_MIN_S * fps))
    # which note is being sung is judged on the pitch with vibrato averaged out (a 0.2 s window spans one
    # swing at 5 Hz), and it sticks until the pitch is clearly nearer the next one: a wide vibrato or a sharp
    # note must not flip between two notes and split itself (it did, on the first test: 12 notes for 6)
    filled = np.where(voiced, np.nan_to_num(midi, nan=0.0), np.nan)
    filled = np.where(np.isnan(filled), np.interp(np.arange(filled.size), np.flatnonzero(voiced),
                                                  filled[voiced]) if voiced.any() else 0.0, filled)
    settled = _smooth(filled, max(1, int(0.2 * fps)))
    degree = np.full(midi.size, -1)
    current = None
    for idx, (m, v) in enumerate(zip(settled, voiced)):
        if not v:
            current = None
            continue
        nearest = nearest_in_key(m, scale, tonic)
        if current is None or abs(m - current) > 0.75:
            current = nearest
        degree[idx] = current

    notes: list[Note] = []
    i = 0
    while i < degree.size:
        if degree[i] < 0:
            i += 1
            continue
        j = i
        while j < degree.size and degree[j] == degree[i]:
            j += 1
        if j - i >= min_frames:
            sung = midi[i:j]
            sung = sung[~np.isnan(sung)]
            if sung.size:
                cents = sung - np.median(sung)
                notes.append(Note(i, j, float(np.median(sung)), int(degree[i]), _has_vibrato(cents, fps)))
        i = j

    offsets = np.zeros(midi.size)
    edge = max(1, int(0.03 * fps))
    slow_width = max(1, int(0.3 * fps))
    for note in notes:
        seg = np.nan_to_num(midi[note.start:note.end], nan=note.center)
        slow = _smooth(seg, slow_width) - note.center  # the wander; vibrato averages out of it
        move = (center / 100.0) * (note.target - note.center) - (drift / 100.0) * slow
        ramp = np.ones(seg.size)
        k = min(edge, seg.size // 2)
        if k:
            ramp[:k] = np.linspace(0, 1, k)
            ramp[-k:] = np.linspace(1, 0, k)
        offsets[note.start:note.end] = move * ramp
    return Pass(notes, offsets, rate)


def _has_vibrato(cents: np.ndarray, fps: float) -> bool:
    if cents.size < int(fps * 0.3):
        return False
    fast = cents - _smooth(cents, max(1, int(0.12 * fps)))
    if np.sqrt(np.mean(fast ** 2)) < 0.12:  # under 12 cents of swing is a steady note
        return False
    spectrum = np.abs(np.fft.rfft(fast * np.hanning(fast.size)))
    freqs = np.fft.rfftfreq(fast.size, 1 / fps)
    band = (freqs >= VIBRATO_HZ[0]) & (freqs <= VIBRATO_HZ[1])
    return bool(band.any() and spectrum[band].max() >= 0.5 * spectrum[1:].max())


def render(source: Path, target: Path, tuned: Pass) -> Path:
    """The take, retuned by the plan, written beside it; same length and alignment as the original."""
    import soundfile as sf

    if shutil.which("rubberband") is None:
        raise RuntimeError("Rubber Band is not installed (brew install rubberband)")
    audio, rate = sf.read(str(source), dtype="float32", always_2d=True)
    with tempfile.TemporaryDirectory() as tmp:
        pmap = Path(tmp) / "pitch.map"
        frames = np.arange(tuned.offsets.size) * tuned.hop * rate / tuned.rate
        pmap.write_text("".join(f"{int(f)} {o:.4f}\n" for f, o in zip(frames, tuned.offsets)))
        out = Path(tmp) / "out.wav"
        done = subprocess.run(["rubberband", "-3", "-F", "-q", "--pitchmap", str(pmap), str(source), str(out)],
                              capture_output=True, text=True, timeout=600)
        if done.returncode != 0:
            raise RuntimeError(f"Rubber Band failed: {done.stderr.strip()[-200:]}")
        shifted, _ = sf.read(str(out), dtype="float32", always_2d=True)
    shifted = align(audio, shifted)
    sf.write(str(target), shifted, rate, subtype="PCM_24")
    return target


def align(original: np.ndarray, shifted: np.ndarray, max_lag_s: float = 0.5, rate: int = 48000) -> np.ndarray:
    """Take out the shifter's latency: the lag where the two envelopes line up best, then the same length."""
    a = np.abs(original.mean(axis=1))
    b = np.abs(shifted.mean(axis=1))
    n = min(a.size, b.size, rate * 20)
    max_lag = int(max_lag_s * rate)
    step = 16
    best, lag = -1.0, 0
    for candidate in range(0, min(max_lag, b.size - 1), step):
        score = float(np.dot(a[:n - candidate:step], b[candidate:n:step]))
        if score > best:
            best, lag = score, candidate
    out = shifted[lag:]
    if out.shape[0] < original.shape[0]:
        out = np.vstack([out, np.zeros((original.shape[0] - out.shape[0], out.shape[1]), dtype=out.dtype)])
    return out[:original.shape[0]]


def first_pass(source: Path, key: str, *, center: float = 80, drift: float = 30,
               reference_cents: float = 0.0) -> tuple[Path, dict, dict]:
    """Plan, render, and measure again: the before and after are both heard by the same ear."""
    import soundfile as sf

    audio, rate = sf.read(str(source), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    tuned = plan(mono, rate, key, center=center, drift=drift, reference_cents=reference_cents)
    target = source.with_name(f"{source.stem} (Marco tuned){source.suffix}")
    render(source, target, tuned)
    after_audio, _ = sf.read(str(target), dtype="float32", always_2d=True)
    after = plan(after_audio.mean(axis=1), rate, key, center=0, drift=0, reference_cents=reference_cents)
    return target, tuned.summary(), after.summary()

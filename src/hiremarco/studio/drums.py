"""A drum pattern read from audio, as MIDI a drum machine can play.

Owner 2026-10-31: send Marco a song whose drums he likes, and Marco rebuilds the pattern in his Maschine, on his own
sounds. The song's drums come apart first (Logic's Stem Splitter); this module reads that drums stem. A small ear,
trained on beats built from his own Maschine library, hears each attack and names the drums in it (kick, snare
or clap, hat), and each is placed on the song's sixteenth grid from its 1 (the beat model finds the 1 and the
tempo). What comes out is the pattern, never the song's audio: the notes, rebuilt on his kit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

KINDS = ("kick", "snare", "hat")
NOTES = {"kick": 36, "snare": 38, "hat": 42}  # General MIDI's drum notes; a kit maps its pads to them
BANDS = {"kick": (30.0, 150.0), "snare": (180.0, 4000.0), "hat": (6000.0, 16000.0)}  # where each is loudest, in Hz
LIBRARY = Path("/Users/Shared/Maschine 2 Library/Samples/Drums")
MODEL = Path.home() / ".local" / "share" / "hiremarco" / "drums.joblib"
RATE = 48000
HOP = 256
MELS = 48


@dataclass(frozen=True)
class Hit:
    kind: str
    step: int          # sixteenths from the 1
    velocity: int      # 1 to 127


def _mel(y: np.ndarray, rate: int) -> np.ndarray:
    import librosa

    m = librosa.feature.melspectrogram(y=y, sr=rate, n_fft=2048, hop_length=HOP, n_mels=MELS, fmin=30, fmax=16000)
    return np.log1p(m * 100.0)


def attacks(y: np.ndarray, rate: int) -> list[int]:
    """Every attack in the stem, as spectrogram frames: sensitive on purpose, since the ear below decides what each
    one is (and that it is a drum at all). Two attacks closer than 40 ms are one (a hat roll's 32nds at 140 BPM are
    54 ms apart)."""
    import librosa

    return [int(f) for f in librosa.onset.onset_detect(y=y, sr=rate, hop_length=HOP, delta=0.03,
                                                       wait=max(1, int(0.04 * rate / HOP)), units="frames")]


def features(mel: np.ndarray, frame: int) -> np.ndarray:
    """What an attack sounds like: the spectrum's jump at the attack and over the next 50 ms, against the 20 ms
    before it, plus the attack's own spectrum, all on the stem's own loudness scale."""
    top = float(mel.max()) or 1.0
    n = mel.shape[1]
    window = lambda a, b: mel[:, max(0, min(n - 1, a)):max(1, min(n, b))].mean(axis=1)  # noqa: E731
    before = window(frame - 4, frame)
    hit = window(frame, frame + 3)
    tail = window(frame + 3, frame + 10)
    return np.concatenate([hit - before, tail - before, hit]) / top


def transcribe(audio: np.ndarray, rate: int, bpm: float, one: float = 0.0, *, per_beat: int = 4, model=None,
               threshold: float = 0.5) -> list[Hit]:
    """The pattern in a drums stem: each attack heard as kick, snare (or clap), hat, any of them or none, then placed
    on the grid from ``one`` (seconds into the audio)."""
    y = np.asarray(audio, dtype=np.float32)
    if y.ndim > 1:
        y = y.mean(axis=1)
    model = model or load_model()
    mel = _mel(y, rate)
    frames = attacks(y, rate)
    if not frames:
        return []
    chances = np.asarray(model.predict_proba(np.stack([features(mel, f) for f in frames])))
    # each drum's loudness in its own part of the spectrum: measured across the whole attack, a kick under a snare
    # read 120 and a kick alone 68 (live 2026-10-31, the Owner heard the 2 and 4 kicks drop out of the preview)
    import librosa

    centres = librosa.mel_frequencies(n_mels=MELS, fmin=30, fmax=16000)
    rows = {kind: (centres >= lo) & (centres < hi) for kind, (lo, hi) in BANDS.items()}
    loud = {kind: np.array([float(mel[rows[kind], f:f + 3].mean()) for f in frames]) for kind in KINDS}
    loud = {kind: (v - v.min()) / max(1e-9, float(v.max() - v.min())) for kind, v in loud.items()}
    step_s = 60.0 / bpm / per_beat
    hits: dict[tuple[str, int], float] = {}
    for i, (f, chance) in enumerate(zip(frames, chances)):
        step = round((f * HOP / rate - one) / step_s)
        if step < 0:
            continue
        for kind, c in zip(KINDS, chance):
            if c >= threshold:
                hits[(kind, step)] = max(hits.get((kind, step), 0.0), float(loud[kind][i]))
    return sorted((Hit(kind, step, max(1, min(127, round(50 + 77 * v)))) for (kind, step), v in hits.items()),
                  key=lambda h: (h.step, KINDS.index(h.kind)))


def load_model(path: Path = MODEL):
    import joblib

    if not path.exists():
        raise FileNotFoundError(f"no drum ear at {path}: run `marco drums train` once")
    return joblib.load(path)


def synth(rng, pools: dict[str, list[Path]], samples: dict, rate: int = RATE):
    """A two-bar beat built from his drum library, with what is in it: random kit, tempo, swing of a few ms, hat
    density from quarters to 32nd rolls, ghost notes, and other percussion that is none of the three (so the ear
    learns to say no). Returns (audio, attacks as (seconds, kind))."""
    import librosa

    def sample(path):
        if path not in samples:
            y, _ = librosa.load(str(path), sr=rate, mono=True)
            samples[path] = y[: rate] / (np.abs(y[: rate]).max() + 1e-9)
        return samples[path]

    kit = {k: sample(rng.choice(pools[k])) for k in pools}
    bpm, lead = rng.uniform(65, 160), rng.uniform(0.05, 0.6)
    step_s = 60.0 / bpm / 4
    out = np.zeros(int((32 * step_s + lead + 1.2) * rate), dtype=np.float32)
    truth = []
    hat_every = rng.choice([1, 2, 2, 4])
    for step in range(32):
        s = step % 16
        play = []
        if (s in (0, 8) and rng.random() < 0.9) or rng.random() < 0.12:
            play.append("kick")
        if (s in (4, 12) and rng.random() < 0.95) or rng.random() < 0.06:
            play.append("snare")
        if s % hat_every == 0 and rng.random() < 0.9:
            play.append("hat")
        if rng.random() < 0.08:
            play.append("other")
        for kind in play:
            gain = rng.uniform(0.35, 1.0) * {"kick": 1.0, "snare": 0.85, "hat": 0.4, "other": 0.5}[kind]
            at_s = lead + step * step_s + rng.uniform(-0.006, 0.006)
            sound = kit[kind]
            at = int(at_s * rate)
            out[at:at + len(sound)] += gain * sound[: len(out) - at]
            if kind != "other":
                truth.append((at_s, kind))
        if hat_every == 1 and rng.random() < 0.05:  # a 32nd roll between two hats
            at_s = lead + (step + 0.5) * step_s
            at = int(at_s * rate)
            out[at:at + len(kit["hat"])] += 0.3 * kit["hat"][: len(out) - at]
            truth.append((at_s, "hat"))
    out /= np.abs(out).max() + 1e-9
    return out * rng.uniform(0.3, 0.95), truth, bpm, lead


def library_pools(root: Path = LIBRARY) -> dict[str, list[Path]]:
    pick = lambda *globs: sorted(p for g in globs for p in root.glob(g))  # noqa: E731
    return {"kick": pick("Kick/*.wav"), "snare": pick("Snare/*.wav", "Clap/*.wav"),
            "hat": pick("Hihat/*Closed*.wav", "Hihat/*Hat C*.wav", "Shaker/*.wav") or pick("Hihat/*.wav"),
            "other": pick("Percussion/*.wav", "Tom/*.wav", "Cymbal/*.wav")}


def labelled(audio: np.ndarray, truth: list[tuple[float, str]], rate: int = RATE, near_s: float = 0.025):
    """Each attack in a built beat with the drums that really start there (within 25 ms)."""
    mel = _mel(audio, rate)
    xs, ys = [], []
    for f in attacks(audio, rate):
        t = f * HOP / rate
        xs.append(features(mel, f))
        ys.append([int(any(abs(t - s) <= near_s and k == kind for s, k in truth)) for kind in KINDS])
    return xs, ys


def train(beats: int = 600, seed: int = 1, path: Path = MODEL, pools: dict | None = None) -> str:
    """The ear, learned from beats built out of his own library; a few minutes once, kept on disk."""
    import random

    import joblib
    from sklearn.neural_network import MLPClassifier

    rng = random.Random(seed)
    pools = pools or library_pools()
    samples: dict = {}
    xs, ys = [], []
    for _ in range(beats):
        audio, truth, _, _ = synth(rng, pools, samples)
        x, y = labelled(audio, truth)
        xs += x
        ys += y
    model = MLPClassifier(hidden_layer_sizes=(96, 48), max_iter=300, early_stopping=True, random_state=seed)
    model.fit(np.stack(xs), np.asarray(ys))
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    return f"drum ear trained on {beats} beats, {len(xs)} attacks, kept at {path}"


def to_midi(hits: list[Hit], path: Path, bpm: float, *, per_beat: int = 4, notes: dict[str, int] | None = None,
            length_steps: int | None = None) -> Path:
    """One MIDI track of the pattern, at its tempo, a sixteenth per note, on channel 10 (drums)."""
    import mido

    notes = notes or NOTES
    ticks = 480
    step_ticks = ticks // per_beat
    midi = mido.MidiFile(ticks_per_beat=ticks)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    events = []
    for h in hits:
        at = h.step * step_ticks
        events.append((at, 1, mido.Message("note_on", channel=9, note=notes[h.kind], velocity=h.velocity)))
        events.append((at + step_ticks // 2, 0, mido.Message("note_off", channel=9, note=notes[h.kind], velocity=0)))
    events.sort(key=lambda e: (e[0], e[1]))
    now = 0
    for at, _, message in events:
        track.append(message.copy(time=at - now))
        now = at
    end = (length_steps or (max((h.step for h in hits), default=0) // 16 + 1) * 16) * step_ticks
    track.append(mido.MetaMessage("end_of_track", time=max(0, end - now)))
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.save(str(path))
    return path


def grid(hits: list[Hit], bars: int | None = None) -> str:
    """The pattern as a step grid he can read at a glance: one row per drum, x for a hit, . for a rest."""
    last = max((h.step for h in hits), default=0)
    steps = (bars or last // 16 + 1) * 16
    rows = []
    for kind in KINDS:
        on = {h.step for h in hits if h.kind == kind}
        cells = "".join("x" if s in on else "." for s in range(steps))
        rows.append(f"{kind:>5} " + " ".join(cells[i:i + 16] for i in range(0, steps, 16)))
    return "\n".join(rows)


def groove(hits: list[Hit], bars: int = 2) -> list[Hit]:
    """The song's main pattern, ``bars`` long, steps counted from its own first bar. Every stretch on the bar lines is
    compared with every other; the one most like the rest stands for the song's loop, the stretches close to it (an
    intro with no kick or a fill is not) vote step by step, and a step the majority of them play is in. Hats that
    vary a little from bar to bar still give one loop."""
    span = bars * 16
    windows: dict[int, set] = {}
    for h in hits:
        windows.setdefault(h.step // span, set()).add((h.kind, h.step % span))
    full = [w for w in windows.values() if len(w) >= bars * 4]
    if not full:
        return []
    like = lambda a, b: len(a & b) / max(1, len(a | b))  # noqa: E731
    centre = max(full, key=lambda w: sum(like(w, o) for o in full) + 1e-3 * len(w))
    close = [w for w in full if like(w, centre) >= 0.6]
    votes: dict[tuple[str, int], int] = {}
    for w in close:
        for cell in w:
            votes[cell] = votes.get(cell, 0) + 1
    kept = {cell for cell, n in votes.items() if n * 2 > len(close)}
    loudness: dict[tuple[str, int], list[int]] = {}
    starts = {b for b, w in windows.items() if w in close}
    for h in hits:
        cell = (h.kind, h.step % span)
        if cell in kept and h.step // span in starts:
            loudness.setdefault(cell, []).append(h.velocity)
    return sorted((Hit(k, s, round(sum(v) / len(v))) for (k, s), v in loudness.items()),
                  key=lambda h: (h.step, KINDS.index(h.kind)))


def render(hits: list[Hit], bpm: float, kit: dict[str, Path], *, loops: int = 2, bars: int = 2,
           rate: int = RATE) -> np.ndarray:
    """The pattern played on a kit, so it can be heard before it goes anywhere."""
    import librosa

    sounds = {k: librosa.load(str(p), sr=rate, mono=True)[0] for k, p in kit.items()}
    step_s = 60.0 / bpm / 4
    out = np.zeros(int((loops * bars * 16 * step_s + 1.0) * rate), dtype=np.float32)
    for loop in range(loops):
        for h in hits:
            sound = sounds[h.kind]
            at = int(((loop * bars * 16) + h.step) * step_s * rate)
            out[at:at + len(sound)] += (h.velocity / 127.0) * sound[: len(out) - at]
    return out / (np.abs(out).max() + 1e-9) * 0.9


KIT_WORDS = {"kick": ("kick", "bd", "bassdrum"), "snare": ("snare", "sd", "clap", "rim"),
             "hat": ("closedhh", "closed hh", "hihat c", "hat c", "chh", "closed", "hh", "hat", "shaker")}
PAD_ONE = 36  # Maschine's pad 1 answers C1 (note 36) and each pad after it the next note up, by default


def kit_notes(group: Path) -> dict[str, int]:
    """The notes that play a Maschine kit's kick, snare and hat, read from its group file: the sounds' sample paths
    are stored in pad order, so the first kick sample is the kick pad, and so on. A drum the kit has no pad for keeps
    the General MIDI note."""
    import re

    text = group.read_bytes().decode("latin-1")
    pads = [m.group(1) for m in re.finditer(r"Samples/[^\x00]*?/([^/\x00]+?)\.(?:wav|aif|aiff)", text, re.I)]
    notes = dict(NOTES)
    for kind, words in KIT_WORDS.items():
        for word in words:
            hit = next((i for i, name in enumerate(pads) if word in name.lower() and not
                        (kind == "hat" and "open" in name.lower())), None)
            if hit is not None and hit < 16:
                notes[kind] = PAD_ONE + hit
                break
    return notes

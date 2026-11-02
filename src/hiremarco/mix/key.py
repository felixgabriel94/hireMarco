"""The song's key, and every frequency named as a note against it.

The artist's rule (2026-11-02): a frequency is named by its note (254 Hz is
B3, nearly a quarter tone sharp), the song's key is known, and a resonance
is judged against the key: a ring on a chord tone can be tone, a ring off
the key is a problem. The key is read from the audio's chroma with the
Krumhansl-Schmuckler key profiles (Krumhansl 1990, the standard template
match, not a model call); the result carries its confidence so a weak read
is said to be weak.
"""

from __future__ import annotations

import numpy as np

from hiremarco.studio.pitch import MAJOR, MINOR, NOTE_NAMES, hz_to_midi, midi_name, parse_key

# Krumhansl-Kessler key profiles (Krumhansl, Cognitive Foundations of Musical Pitch, 1990)
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
CHORD_DEGREES = (0, 2, 4)   # scale steps of the tonic triad: 1, 3, 5


def note_of(hz: float) -> tuple[str, int]:
    """The nearest note and the cents off it: 440 -> ('A4', 0); 254 -> ('B3', 49)."""
    if hz <= 0:
        raise ValueError("a frequency above zero")
    midi = hz_to_midi(hz)
    nearest = int(round(midi))
    return midi_name(nearest), int(round((midi - nearest) * 100))


def relation(hz: float, key: str) -> str:
    """How a frequency's note sits in the key: tonic, chord tone, in the key, or off the key."""
    tonic, scale = parse_key(key)
    pitch_class = int(round(hz_to_midi(hz))) % 12
    degree = (pitch_class - tonic) % 12
    if degree == 0:
        return "the tonic"
    if degree in scale:
        return "a chord tone" if scale.index(degree) in CHORD_DEGREES else "in the key"
    return "off the key"


def chroma(audio: np.ndarray, rate: int) -> np.ndarray:
    """Twelve pitch-class energies, summed over the track (librosa's CQT chroma)."""
    import librosa

    mono = np.asarray(audio, dtype=np.float32)
    if mono.ndim > 1:
        mono = mono.mean(axis=1)
    if mono.size < rate:
        mono = np.pad(mono, (0, rate - mono.size))
    c = librosa.feature.chroma_cqt(y=mono, sr=rate)
    return c.sum(axis=1)


def detect(audio: np.ndarray, rate: int) -> tuple[str, float]:
    """The key and a confidence from 0 to 1: the best key profile's correlation against the chroma, scaled by
    its lead over the runner-up (a close race reads as a weak key)."""
    return from_chroma(chroma(audio, rate))


def from_chroma(vector: np.ndarray) -> tuple[str, float]:
    vector = np.asarray(vector, dtype=np.float64)
    if vector.sum() <= 0:
        return "", 0.0
    scores = []
    for tonic in range(12):
        for name, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            rolled = np.roll(profile, tonic)
            r = np.corrcoef(vector, rolled)[0, 1]
            scores.append((float(r), f"{NOTE_NAMES[tonic]} {name}"))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    lead = max(0.0, best[0] - second[0])
    confidence = max(0.0, min(1.0, best[0])) * min(1.0, lead / 0.1 + 0.3)
    return best[1], round(float(confidence), 2)


def describe(hz: float, key: str = "") -> str:
    """'254 Hz (B3 +49 cents, in the key of C major)'."""
    name, cents = note_of(hz)
    off = f" {cents:+d} cents" if cents else ""
    where = f", {relation(hz, key)} of {key}" if key else ""
    return f"{hz:g} Hz ({name}{off}{where})"

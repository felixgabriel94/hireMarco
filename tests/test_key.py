"""The song's key and every frequency as a note against it."""

import numpy as np

from hiremarco.mix import key


def tone(hz, seconds, rate):
    t = np.arange(int(seconds * rate)) / rate
    return 0.3 * np.sin(2 * np.pi * hz * t) + 0.15 * np.sin(2 * np.pi * 2 * hz * t)


def test_a_frequency_is_a_note_with_its_cents():
    assert key.note_of(440.0) == ("A4", 0)
    assert key.note_of(254.0) == ("B3", 49)
    assert key.note_of(261.63) == ("C4", 0)
    assert key.describe(254.0, "C major") == "254 Hz (B3 +49 cents, in the key of C major)"
    assert key.describe(440.0) == "440 Hz (A4)"


def test_relation_to_the_key_names_tonic_chord_tone_scale_or_off():
    assert key.relation(261.63, "C major") == "the tonic"
    assert key.relation(329.63, "C major") == "a chord tone"        # E
    assert key.relation(392.0, "E minor") == "a chord tone"         # G, the minor third of E minor
    assert key.relation(293.66, "C major") == "in the key"          # D
    assert key.relation(277.18, "C major") == "off the key"         # C#
    assert key.relation(246.94, "G major") == "a chord tone"        # B, the third of G major
    assert key.relation(246.94, "E minor") == "a chord tone"        # B, the fifth of E minor


def test_the_key_is_read_from_a_chord_progression():
    rate = 22050
    parts = []
    for chord in ((261.63, 329.63, 392.0), (349.23, 440.0, 523.25), (392.0, 493.88, 587.33), (261.63, 329.63, 392.0)):
        parts.append(sum(tone(h, 1.0, rate) for h in chord))
    audio = np.concatenate(parts)
    name, confidence = key.detect(audio, rate)
    assert name == "C major" and confidence > 0.3


def test_a_minor_progression_reads_minor():
    rate = 22050
    parts = []
    for chord in ((220.0, 261.63, 329.63), (293.66, 349.23, 440.0), (329.63, 415.30, 493.88), (220.0, 261.63, 329.63)):
        parts.append(sum(tone(h, 1.0, rate) for h in chord))
    name, confidence = key.detect(np.concatenate(parts), rate)
    assert name == "A minor" and confidence > 0.2


def test_silence_has_no_key():
    assert key.from_chroma(np.zeros(12)) == ("", 0.0)

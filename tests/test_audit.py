"""The audit reads a track as numbers: loudness over time, tilt, resonances, width, mono loss, defects."""

import numpy as np

from hiremarco.mix import audit

RATE = 48000


def pink(seconds: float, seed: int = 1) -> np.ndarray:
    """Pink noise by shaping white noise's spectrum, stereo, peaks near -3 dBFS."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    spectrum = np.fft.rfft(rng.standard_normal((n, 2)), axis=0)
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    spectrum[1:] /= np.sqrt(freqs[1:])[:, None]
    spectrum[0] = 0
    audio = np.fft.irfft(spectrum, n=n, axis=0)
    return audio / np.max(np.abs(audio)) * 0.7


def test_pink_noise_tilts_about_minus_three_db_per_octave():
    a = audit.audit_audio(pink(8), RATE, "pink")
    assert -4.0 < a.tilt_db_per_octave < -2.0
    assert a.resonances == []
    assert a.base.correlation is not None and a.base.correlation < 0.3   # independent channels read wide


def test_a_sustained_tone_reads_as_a_resonance():
    t = np.arange(8 * RATE) / RATE
    audio = pink(8) * 0.3
    audio += (0.4 * np.sin(2 * np.pi * 1000 * t))[:, None]
    a = audit.audit_audio(audio, RATE, "tone")
    assert a.resonances, "a 1 kHz tone over pink noise should stand out"
    assert abs(a.resonances[0].hz - 1000) < 60


def test_mono_loses_nothing_on_identical_channels_and_everything_out_of_phase():
    mono = pink(4)[:, 0]
    same = np.stack([mono, mono], axis=1)
    flipped = np.stack([mono, -mono], axis=1)
    assert abs(audit.mono_loss(same, RATE)) < 0.2
    assert audit.mono_loss(flipped, RATE) > 20
    assert audit.mono_loss(mono, RATE) is None


def test_width_per_band_is_lower_when_the_channels_match():
    mono = pink(4)[:, 0]
    narrow = np.stack([mono, mono * 0.98], axis=1)
    _, width_narrow = audit.stereo_bands(narrow, RATE)
    _, width_wide = audit.stereo_bands(pink(4, seed=3), RATE)
    assert width_narrow["mids"] < -20
    assert width_wide["mids"] > width_narrow["mids"] + 10


def test_loudness_range_grows_with_a_quiet_verse_and_a_loud_chorus():
    flat = pink(12)
    shaped = flat.copy()
    shaped[: 6 * RATE] *= 0.1   # the first half 20 dB down
    weighted_flat = audit._weighted(flat, RATE)
    weighted_shaped = audit._weighted(shaped, RATE)
    assert audit.loudness_range(weighted_flat, RATE) < 2
    assert audit.loudness_range(weighted_shaped, RATE) > 10


def test_defects_are_counted():
    audio = pink(3) * 0.2
    audio[RATE] = [0.9, 0.9]                 # one click
    audio += 0.01                            # a DC offset
    a = audit.audit_audio(audio, RATE, "defects")
    assert a.clicks >= 1
    assert a.dc_offset > 0.005
    notes = audit.findings(a)
    assert any("click" in n for n in notes) and any("DC offset" in n for n in notes)


def test_head_and_tail_silence():
    audio = np.zeros((6 * RATE, 2))
    audio[2 * RATE: 5 * RATE] = pink(3) * 0.5
    a = audit.audit_audio(audio, RATE, "edges")
    assert abs(a.head_silence_s - 2.0) < 0.05
    assert abs(a.tail_silence_s - 1.0) < 0.05
    assert any("silence at the head" in n for n in audit.findings(a))


def test_deltas_against_references_name_the_gaps():
    track = audit.audit_audio(pink(6) * 0.2, RATE, "mine")          # quieter, same tilt
    refs = [audit.audit_audio(pink(6, seed=s), RATE, f"ref{s}") for s in (2, 3)]
    d = audit.compare(track, refs)
    assert d is not None and d.against == ["ref2", "ref3"]
    assert d.lufs < -5
    assert any("quieter" in n for n in d.notes)
    assert audit.compare(track, []) is None
    text = audit.summary(track, d)
    assert "against ref2, ref3" in text and "LUFS integrated" in text


def test_a_resonance_is_named_by_its_note_and_the_key_is_read():
    rate = 22050
    t = np.arange(6 * rate) / rate
    rng = np.random.default_rng(5)
    chords = [(261.63, 329.63, 392.0), (349.23, 440.0, 523.25), (392.0, 493.88, 587.33)]
    bed = np.concatenate([sum(0.2 * np.sin(2 * np.pi * h * t[: 2 * rate]) for h in chord) for chord in chords])
    ring = 0.5 * np.sin(2 * np.pi * 1046.5 * t)
    a = audit.audit_audio((bed + ring + 0.01 * rng.standard_normal(t.size)).astype(np.float64), rate, "ring")
    assert a.key == "C major" and a.key_confidence > 0.2
    top = a.resonances[0]
    assert top.note == "C6" and top.relation == "the tonic"
    line = next(n for n in audit.findings(a) if n.startswith("resonance at"))
    assert "(C6, the tonic of C major)" in line
    assert "key C major" in audit.summary(a)


def test_two_notes_taking_turns_in_one_bin_are_named_as_the_part_not_a_ring():
    rate = 22050
    t = np.arange(rate) / rate
    b3 = 0.5 * np.sin(2 * np.pi * 246.94 * t)
    c4 = 0.5 * np.sin(2 * np.pi * 261.63 * t)
    rng = np.random.default_rng(7)
    bed = 0.02 * rng.standard_normal(8 * rate)
    audio = bed + np.concatenate([b3, c4, b3, c4, b3, c4, b3, c4])
    a = audit.audit_audio(audio, rate, "turns")
    top = a.resonances[0]
    assert set(top.notes.replace("%", "").split(", ")) >= {"B3 50", "C4 50"} or top.notes.count(",") == 1
    line = next(n for n in audit.findings(a) if n.startswith("resonance at"))
    assert "second by second" in line and "two notes of the part share this bin" in line

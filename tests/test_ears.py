import numpy as np
import pytest
import soundfile as sf

from hiremarco.mix.ears import collisions, listen, lufs, measure, mix_notes, summary

RATE = 48000


def tone(freqs, seconds=3.0, amp=0.1, stereo=False):
    t = np.arange(int(RATE * seconds)) / RATE
    x = sum(amp * np.sin(2 * np.pi * f * t) for f in freqs)
    return np.column_stack([x, x]) if stereo else x


def test_loudness_matches_the_bs1770_reference():
    # A 1 kHz sine at -20 dBFS reads -23.0 LUFS in mono and -20.0 LUFS on two channels.
    assert lufs(tone([1000]), RATE) == pytest.approx(-23.0, abs=0.1)
    assert lufs(tone([1000], stereo=True), RATE) == pytest.approx(-20.0, abs=0.1)
    assert lufs(np.zeros(RATE), RATE) == -120.0


def test_bands_peaks_and_stereo():
    r = measure(tone([80], stereo=True), RATE, "bass")
    assert max(r.bands_db, key=r.bands_db.get) == "bass"
    assert r.true_peak_db == pytest.approx(-20, abs=0.2) and r.correlation == 1.0 and r.low_mono == 1.0
    wide = np.column_stack([tone([70]), -tone([70])])
    assert measure(wide, RATE, "x").low_mono == -1.0


def test_kick_and_bass_collide_the_vocal_does_not():
    kick, bass, vocal = (measure(tone(f), RATE, n) for f, n in (([55, 90], "Kick"), ([70, 110], "Bass"),
                                                                ([1200, 2500], "Vocal")))
    found = collisions([kick, bass, vocal])
    assert any({c.a, c.b} == {"Kick", "Bass"} and c.band == "bass" for c in found)
    assert not any("Vocal" in (c.a, c.b) for c in found)


def test_a_silent_track_is_left_out_of_collisions():
    quiet = measure(np.zeros(RATE * 2), RATE, "Empty")
    assert quiet.silent and collisions([quiet, measure(tone([70]), RATE, "Bass")]) == []


def test_mix_notes_for_mastering():
    hot = measure(tone([100, 1000, 5000], amp=0.33, stereo=True), RATE, "mix")
    notes = mix_notes(hot)
    assert any("headroom" in n for n in notes)
    fine = measure(tone([100, 1000, 5000], amp=0.05, stereo=True), RATE, "mix")
    assert not any("headroom" in n for n in mix_notes(fine))


def test_listen_reads_a_folder_and_the_mix(tmp_path):
    sf.write(tmp_path / "01 Kick.wav", tone([55, 90]), RATE, subtype="PCM_24")
    sf.write(tmp_path / "02 Bass.wav", tone([70, 110]), RATE, subtype="PCM_24")
    sf.write(tmp_path / "Mix.wav", tone([55, 70, 1000], amp=0.05, stereo=True), RATE, subtype="PCM_24")
    report = listen(tmp_path, tmp_path / "Mix.wav")
    assert [t.name for t in report.tracks] == ["01 Kick", "02 Bass"]
    assert report.mix.name == "Mix"
    text = summary(report)
    assert "collision: 01 Kick and 02 Bass in the bass" in text and "mix:" in text

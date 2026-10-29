import zipfile
from datetime import date

import numpy as np
import pytest
import soundfile as sf

from hiremarco.mix.handoff import ready_for_mastering, ready_to_mix

RATE = 48000


def write(path, amp=0.12, seconds=40, subtype="PCM_24", stereo=True):
    t = np.arange(int(RATE * seconds)) / RATE
    x = amp * (np.sin(2 * np.pi * 100 * t) + np.sin(2 * np.pi * 1000 * t))
    sf.write(path, np.column_stack([x, x]) if stereo else x, RATE, subtype=subtype)


def test_a_mix_with_headroom_is_filed_with_its_notes(tmp_path):
    write(tmp_path / "bounce.wav")
    check = ready_for_mastering(tmp_path / "bounce.wav", tmp_path / "out", song="Let Me Love You",
                                today=date(2026, 10, 28))
    assert check.ready and check.folder.name.endswith("_for_mastering_2026-10-28")
    notes = (check.folder / "MASTERING_NOTES.md").read_text()
    assert "No limiter" in notes and "dB headroom" in notes
    assert len(list(check.folder.glob("*mix for mastering.wav"))) == 1


def test_a_hot_or_short_or_16_bit_mix_is_reported_not_filed(tmp_path):
    write(tmp_path / "hot.wav", amp=0.48)
    write(tmp_path / "short.wav", seconds=5)
    write(tmp_path / "cd.wav", subtype="PCM_16")
    for name, why in (("hot.wav", "headroom"), ("short.wav", "whole song"), ("cd.wav", "24-bit")):
        check = ready_for_mastering(tmp_path / name, tmp_path / "out", song="x")
        assert not check.ready and any(why in p for p in check.problems) and check.folder is None
    assert not (tmp_path / "out").exists()


def test_ready_to_mix_adds_the_measurements_to_the_folder_and_zip(tmp_path):
    src = tmp_path / "export"
    src.mkdir()
    write(src / "Vocal.wav", seconds=3, stereo=False)
    write(src / "Bass.wav", seconds=3, stereo=False)
    folder = ready_to_mix(src, tmp_path / "out", song="Let Me Love You")
    assert "LUFS" in (folder / "ANALYSIS.txt").read_text()
    zips = list((tmp_path / "out").rglob("*.zip"))
    assert zips and any(n.endswith("ANALYSIS.txt") for n in zipfile.ZipFile(zips[0]).namelist())


def test_a_quiet_mix_is_filed_with_a_note(tmp_path):
    write(tmp_path / "quiet.wav", amp=0.03)
    check = ready_for_mastering(tmp_path / "quiet.wav", tmp_path / "out", song="Quiet One")
    assert check.ready and "very quiet" in (check.folder / "MASTERING_NOTES.md").read_text()

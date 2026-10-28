import zipfile
from datetime import date

import numpy as np
import pytest
import soundfile as sf

from hiremarco.studio.export import clean_name, prepare

SR = 48000


def tone(path, seconds=1.0, amp=0.5, sr=SR, subtype="PCM_24"):
    t = np.arange(int(sr * seconds)) / sr
    sf.write(str(path), (amp * np.sin(2 * np.pi * 220 * t)).astype("float32"), sr, subtype=subtype)


def test_clean_name():
    assert clean_name("New Record_Lead Vox#02", "New Record") == "Lead_Vox_2"
    assert clean_name("Harmony 1 (high)") == "Harmony_1_high"
    assert clean_name("___") == "Track"


def test_clean_session_is_ready(tmp_path):
    src = tmp_path / "logic"
    src.mkdir()
    tone(src / "New Record_Beat.wav")
    tone(src / "New Record_Lead Vox.wav", amp=0.25)
    out = tmp_path / "out"
    out.mkdir()
    report = prepare(src, out, song="New Record", take_notes=["Take 3 of the chorus is the keeper"],
                     bpm=92, key="F minor", today=date(2026, 11, 2))
    assert [s.name for s in report.stems] == ["01_Beat.wav", "02_Lead_Vox.wav"]
    assert report.problems == []
    assert report.summary() == "2 stems, all clean. The folder is ready for mix."
    notes = (report.folder / "MIX_NOTES.md").read_text()
    assert "48000 Hz" in notes and "92 BPM" in notes and "Take 3 of the chorus" in notes
    assert abs(report.stems[1].peak_dbfs - 20 * np.log10(0.25)) < 0.1
    with zipfile.ZipFile(report.zip_path) as zf:
        names = zf.namelist()
    assert "New_Record_ready_to_mix_2026-11-02/stems/01_Beat.wav" in names
    assert (src / "New Record_Beat.wav").exists()  # originals untouched


def test_problems_are_flagged(tmp_path):
    src = tmp_path / "logic"
    src.mkdir()
    tone(src / "a.wav")
    tone(src / "b.wav", sr=44100)
    tone(src / "c.wav", seconds=0.5)
    sf.write(str(src / "d.wav"), np.zeros(SR, dtype="float32"), SR)
    hot = np.full(SR, 0.2, dtype="float32")
    hot[100:110] = 1.0
    sf.write(str(src / "e.wav"), hot, SR, subtype="FLOAT")
    report = prepare(src, tmp_path, song="Test", today=date(2026, 11, 2))
    text = " | ".join(report.problems)
    assert "sample rates differ" in text and "not the same length" in text
    assert "05_e.wav clips 1 time" in text and "04_d.wav is silent" in text
    assert report.summary().startswith("5 stems. 4 to look at")


def test_never_overwrites(tmp_path):
    src = tmp_path / "logic"
    src.mkdir()
    tone(src / "a.wav")
    prepare(src, tmp_path, song="S", today=date(2026, 11, 2))
    with pytest.raises(FileExistsError):
        prepare(src, tmp_path, song="S", today=date(2026, 11, 2))


def test_empty_folder_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        prepare(tmp_path, tmp_path, song="S")

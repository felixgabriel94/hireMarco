"""A sound from a description, in the song's key (Owner 2026-10-31)."""

import io

import httpx
import numpy as np
import pytest
import soundfile as sf

from hiremarco import gate
from hiremarco.joblog import JobLog
from hiremarco.studio import soundgen


def test_the_prompt_carries_the_session():
    p = soundgen.prompt("Moody, spacey pad", "A major", 99, 19.4)
    assert p.startswith("Moody, spacey pad. Key of A major, 99 BPM, 4/4, about 19 seconds.") and "no vocals" in p


def test_the_shortest_shift_lands_the_clip_in_the_song_key():
    assert soundgen.shift_to("D# major", "A major") in (6, -6)
    assert soundgen.shift_to("F# minor", "A major") == 0                # same notes: left alone
    assert soundgen.shift_to("G major", "A major") == 2
    assert soundgen.shift_to("B major", "A major") == -2


def test_making_a_sound_is_off_until_he_turns_it_on(tmp_path, monkeypatch):
    with pytest.raises(gate.Refused):
        soundgen.generate("a pad", 10, api_key="k", joblog=JobLog(tmp_path / "j.jsonl"))
    monkeypatch.setenv("HIREMARCO_SOUND_GEN", "on")
    buf = io.BytesIO()
    sf.write(buf, np.zeros((4800, 2), dtype="float32"), 48000, format="WAV")
    sent = {}
    transport = httpx.MockTransport(lambda r: sent.update(body=r.content) or
                                    httpx.Response(200, content=buf.getvalue(), headers={"content-type": "audio/wav"}))
    out = soundgen.generate("a pad", 500, api_key="k", joblog=JobLog(tmp_path / "j.jsonl"), transport=transport)
    assert out == buf.getvalue() and b'"music_length_ms":60000' in sent["body"]   # capped at a minute


def test_the_clip_is_moved_into_the_key_and_written_for_logic(tmp_path):
    rate = 22050
    t = np.arange(rate) / rate
    buf = io.BytesIO()
    sf.write(buf, np.stack([0.2 * np.sin(2 * np.pi * 392.0 * t)] * 2, axis=1).astype("float32"), rate, format="WAV")
    made = soundgen.fit(buf.getvalue(), "A major", tmp_path, "pad", read_key=lambda d, r: "G major")
    assert made.shift == 2 and made.path.exists() and sf.info(str(made.path)).subtype == "PCM_24"
    assert not list(tmp_path.glob(".*raw*"))


def test_raw_pcm_from_the_api_becomes_a_48k_stereo_wav(tmp_path):
    pcm = (np.stack([np.full(4800, 1000, dtype="<i2"), np.full(4800, -1000, dtype="<i2")], axis=1)).tobytes()
    made = soundgen.fit(pcm, "A major", tmp_path, "pad", read_key=lambda d, r: "A major")
    info = sf.info(str(made.path))
    assert (info.samplerate, info.channels, info.subtype) == (48000, 2, "PCM_24") and made.shift == 0
    data, _ = sf.read(str(made.path))
    assert data[0, 0] > 0 > data[0, 1]                                    # left and right kept apart


def test_a_vocal_comes_dry_and_a_cappella_and_an_instrument_stays_instrumental():
    choir = soundgen.prompt("a gospel choir singing ooh", "A major", 99, 20)
    assert "A cappella only" in choir and "no reverb" in choir and "instrumental only" not in choir
    assert "dry" in soundgen.prompt("female vocal chops", "A minor", 99, 14)
    pad = soundgen.prompt("moody spacey pad", "A major", 99, 19)
    assert "instrumental only" in pad and "A cappella" not in pad


def test_a_near_miss_on_tempo_is_stretched_and_a_far_one_is_left_alone():
    assert soundgen.stretch_ratio(96.0, 99.0) == pytest.approx(96 / 99)
    assert soundgen.stretch_ratio(99.1, 99.0) == 1.0            # already in time
    assert soundgen.stretch_ratio(0.0, 99.0) == 1.0             # tempo not read: nothing guessed
    assert soundgen.stretch_ratio(80.0, 99.0) == 1.0            # 19% off is not a near miss


def test_the_fitter_stretches_and_shifts_in_one_pass_with_formants_kept_on_a_voice(tmp_path):
    pcm = (np.sin(np.linspace(0, 2000, 48000 * 2)) * 8000).astype("<i2")
    calls = []

    def move(source, target, *, time_ratio, semitones, voice):
        calls.append((round(time_ratio, 4), semitones, voice))
        import shutil
        shutil.copy(source, target)

    made = soundgen.fit(np.stack([pcm, pcm], axis=1).tobytes(), "A major", tmp_path, "choir", wanted_bpm=99,
                        voice=True, read_key=lambda d, r: "A# major", tempo=lambda path, wanted: 96.0, move=move)
    assert calls == [(round(96 / 99, 4), -1, True)]
    assert (made.heard_bpm, made.wanted_bpm, made.shift) == (96.0, 99, -1)

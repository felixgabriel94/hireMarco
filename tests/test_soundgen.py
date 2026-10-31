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

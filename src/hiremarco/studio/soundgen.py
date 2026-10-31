"""A sound made from a description, in the song's key, laid where it is needed.

Owner 2026-10-31: "Marco, I need a pad for the bridge, moody and spacey." Marco writes the prompt from the words and
the session (key, tempo, how long the section is), ElevenLabs Music makes it (the Owner's pick by ear over Meta's
MusicGen: "light years ahead"), and Marco checks the result with his own ear before it reaches the session: the model
treats the key in a prompt as a suggestion (live: asked A major, got what reads as D# major), so the clip is moved
to the song's key by the shortest pitch shift, or left alone when its notes are already the song's (a relative key).
Each sound costs ElevenLabs credits: it runs only while HIREMARCO_SOUND_GEN is on, one sound per ask, at most a
minute long.
"""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from hiremarco import config, gate
from hiremarco.joblog import JobLog, JobRow

URL = "https://api.elevenlabs.io/v1/music"
MODEL = "music_v1"
TENANT = "owner"
MAX_SECONDS = 60.0


@dataclass(frozen=True)
class Made:
    path: Path
    asked_key: str
    heard_key: str
    shift: int          # semitones the clip was moved to land in the song's key
    seconds: float


def prompt(described: str, key: str, bpm: float, seconds: float) -> str:
    """His words plus what the session already knows, written the way the music model reads best."""
    return (f"{described.strip().rstrip('.')}. Key of {key}, {bpm:g} BPM, 4/4, about {seconds:.0f} seconds. "
            "A single instrument part for a song that is already playing: instrumental only, no vocals; no drums "
            "unless asked; it starts and ends cleanly so it can sit on a section of the song.")


def shift_to(heard: str, wanted: str) -> int:
    """Semitones from the heard key to the wanted one, the short way (-6 to +6); 0 when the clip's notes are already
    the song's (a relative major or minor)."""
    from hiremarco.studio.pitch import parse_key

    h_tonic, h_scale = parse_key(heard)
    w_tonic, w_scale = parse_key(wanted)
    notes = lambda tonic, scale: {(tonic + d) % 12 for d in scale}  # noqa: E731
    for s in range(0, 7):
        for sign in ((1,) if s in (0, 6) else (1, -1)):
            if notes(h_tonic + sign * s, h_scale) == notes(w_tonic, w_scale):
                return sign * s
    return (w_tonic - h_tonic + 6) % 12 - 6


def generate(text: str, seconds: float, *, api_key: str | None = None, joblog: JobLog | None = None,
             transport: httpx.BaseTransport | None = None) -> bytes:
    if (config.get("HIREMARCO_SOUND_GEN") or "off") != "on":
        raise gate.Refused("making sounds costs ElevenLabs credits and is off until the Owner turns it on")
    seconds = max(3.0, min(seconds, MAX_SECONDS))
    joblog = joblog or JobLog()
    gate.check_model_call(TENANT, model=MODEL, system="", prompt=text, joblog=joblog)
    key = api_key or config.require("ELEVENLABS_API_KEY")
    started = time.monotonic()
    with httpx.Client(timeout=240, transport=transport) as http:
        r = http.post(URL, headers={"xi-api-key": key},
                      json={"prompt": text, "music_length_ms": int(seconds * 1000), "model_id": MODEL})
    ms = int((time.monotonic() - started) * 1000)
    if r.status_code >= 400 or not r.headers.get("content-type", "").startswith("audio"):
        joblog.append(JobRow(job="sound", model=MODEL, ok=False, duration_ms=ms, note=f"http {r.status_code}"))
        raise RuntimeError(f"ElevenLabs Music returned HTTP {r.status_code}")
    from hiremarco.meta.pricing import audio_cost_usd

    joblog.append(JobRow(job="sound", model=MODEL, ok=True, duration_ms=ms,
                         cost_usd=audio_cost_usd(MODEL, int(seconds * 1000)),
                         note=f"{seconds:.0f} s of music; cost an estimate at 0.30 USD a minute"))
    return r.content


def fit(audio_bytes: bytes, wanted_key: str, folder: Path, name: str, *, read_key=None) -> Made:
    """The clip in the song's key, written as a 24-bit WAV the session can import."""
    import librosa
    import soundfile as sf

    data, rate = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=True)
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f".{name}.raw.wav"
    sf.write(str(raw), data, rate, subtype="PCM_24")
    if read_key is None:
        from hiremarco.studio.analyze import read

        heard = read(raw).key
    else:
        heard = read_key(data, rate)
    shift = shift_to(heard, wanted_key) if heard and wanted_key else 0
    if shift:
        data = np.stack([librosa.effects.pitch_shift(data[:, c], sr=rate, n_steps=shift)
                         for c in range(data.shape[1])], axis=1).astype("float32")
    target = folder / f"{name}.wav"
    sf.write(str(target), data, rate, subtype="PCM_24")
    raw.unlink(missing_ok=True)
    return Made(target, wanted_key, heard, shift, len(data) / rate)

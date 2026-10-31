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
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from hiremarco import config, gate
from hiremarco.joblog import JobLog, JobRow

URL = "https://api.elevenlabs.io/v1/music"
FORMAT = "pcm_48000"  # uncompressed: 16-bit stereo at 48 kHz (live 2026-10-31: 5 s came back as 962,976 bytes);
#                       the default is a 128 kbps MP3
RATE, CHANNELS = 48000, 2
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
    heard_bpm: float = 0.0   # the clip's own tempo as Marco read it; 0 when it could not be read
    wanted_bpm: float = 0.0


VOCAL = re.compile(r"\b(?:vocals?|voices?|choirs?|sing(?:s|ing|er)?|sung|chops?|hooks?|ad[- ]?libs?|harmon(?:y|ies)|"
                   r"a ?cappella|acapella|hum(?:s|ming)?|chant(?:s|ing)?|ooh|aah?)\b", re.IGNORECASE)


def prompt(described: str, key: str, bpm: float, seconds: float) -> str:
    """His words plus what the session already knows, written the way the music model reads best. A vocal comes
    dry, a cappella, with no effects, so Marco's own chain in Logic does the processing (Owner 2026-10-31, after a
    dry take measured 26 dB of fall in 300 ms where the same hook unprompted fell 13 dB)."""
    head = f"{described.strip().rstrip('.')}. Key of {key}, {bpm:g} BPM, 4/4, about {seconds:.0f} seconds. "
    if VOCAL.search(described):
        return head + ("A cappella only, no instruments, no drums. Completely dry vocal: no reverb, no delay, no echo, "
                       "no effects, close-mic'd in a dead vocal booth, like a raw unprocessed studio take.")
    return head + ("A single instrument part for a song that is already playing: instrumental only, no vocals; no "
                   "drums unless asked; it starts and ends cleanly so it can sit on a section of the song.")


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
        r = http.post(URL, params={"output_format": FORMAT}, headers={"xi-api-key": key},
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


STRETCH_MAX = 0.12      # a clip more than 12% off the song's tempo is not a near miss: it is left alone and said so
TEMPO_STEADY = 0.06     # beats whose spacing wanders more than this are not a tempo worth stretching to


def read_tempo(path: Path, wanted: float) -> float:
    """The clip's tempo from the beat model's beats (Day 4's Beat This!), folded to the octave nearest the song's
    (half or double time reads as the same tempo). 0 when the beats are too few or too uneven to trust: a held choir
    or a pad often has no beat to read, and a guess there would stretch a clip that was right."""
    from hiremarco.studio.the_one import beats

    found = beats(path)
    if not found or len(found) < 8:
        return 0.0
    times = np.asarray(found, dtype=float)
    gaps = np.diff(times)
    middle = float(np.median(gaps))
    if middle <= 0 or float(np.percentile(np.abs(gaps - middle), 75)) > TEMPO_STEADY * middle:
        return 0.0
    # the beat period is the slope of beat time against beat count, not the median gap: the model reports beats on
    # a 20 ms grid, so every gap of a 99 BPM clip reads 600 or 620 ms and the median says 100 (live 2026-10-31)
    count = np.concatenate([[0.0], np.cumsum(np.round(gaps / middle))])
    bpm = 60.0 / float(np.polyfit(count, times, 1)[0])
    if wanted > 0:
        bpm = min((bpm * f for f in (0.5, 1.0, 2.0)), key=lambda b: abs(b - wanted))
    return bpm


def stretch_ratio(heard: float, wanted: float) -> float:
    """How much longer the clip gets (rubberband's --time): 1.0 when it is already in time, unread, or too far off
    to be a near miss."""
    if heard <= 0 or wanted <= 0 or abs(heard - wanted) < 0.3:
        return 1.0
    ratio = heard / wanted
    return ratio if abs(ratio - 1.0) <= STRETCH_MAX else 1.0


def rubberband(source: Path, target: Path, *, time_ratio: float, semitones: int, voice: bool) -> None:
    """Rubber Band's finer engine for both moves at once, one pass; formants kept on a voice so a shifted vocal does
    not turn small and bright (librosa's shift, the fallback, does not keep them)."""
    import shutil
    import subprocess

    tool = shutil.which("rubberband")
    if tool is None:
        raise FileNotFoundError("rubberband")
    args = [tool, "-q", "--fine", "-t", f"{time_ratio:.6f}", "-p", str(semitones)]
    if voice:
        args.append("-F")
    subprocess.run(args + [str(source), str(target)], check=True, capture_output=True, timeout=300)


def fit(audio_bytes: bytes, wanted_key: str, folder: Path, name: str, *, wanted_bpm: float = 0.0,
        voice: bool = False, read_key=None, tempo=read_tempo, move=rubberband) -> Made:
    """The clip in the song's key and at its tempo, written as a 24-bit WAV the session can import. A near miss on
    tempo (Owner 2026-10-31: "a couple of BPMs faster or slower") is stretched to the song's; the key the short way."""
    import soundfile as sf

    if audio_bytes[:4] in (b"RIFF", b"ID3\x03") or audio_bytes[:2] == b"\xff\xfb":
        data, rate = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=True)
    else:  # raw PCM from the API: 16-bit little-endian, interleaved stereo
        pcm = np.frombuffer(audio_bytes[: len(audio_bytes) // (2 * CHANNELS) * 2 * CHANNELS], dtype="<i2")
        data, rate = pcm.reshape(-1, CHANNELS).astype("float32") / 32768.0, RATE
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f".{name}.raw.wav"
    sf.write(str(raw), data, rate, subtype="PCM_24")
    if read_key is None:
        from hiremarco.studio.analyze import read

        heard = read(raw).key
    else:
        heard = read_key(data, rate)
    shift = shift_to(heard, wanted_key) if heard and wanted_key else 0
    heard_bpm = tempo(raw, wanted_bpm) if wanted_bpm > 0 else 0.0
    ratio = stretch_ratio(heard_bpm, wanted_bpm)
    target = folder / f"{name}.wav"
    if shift or ratio != 1.0:
        try:
            move(raw, target, time_ratio=ratio, semitones=shift, voice=voice)
        except (FileNotFoundError, OSError):
            import librosa

            if ratio != 1.0:
                data = np.stack([librosa.effects.time_stretch(data[:, c], rate=1.0 / ratio)
                                 for c in range(data.shape[1])], axis=1)
            if shift:
                data = np.stack([librosa.effects.pitch_shift(data[:, c], sr=rate, n_steps=shift)
                                 for c in range(data.shape[1])], axis=1)
            sf.write(str(target), data.astype("float32"), rate, subtype="PCM_24")
    else:
        sf.write(str(target), data, rate, subtype="PCM_24")
    raw.unlink(missing_ok=True)
    seconds = sf.info(str(target)).duration
    return Made(target, wanted_key, heard, shift, seconds, heard_bpm, wanted_bpm)

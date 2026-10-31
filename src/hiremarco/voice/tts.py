"""Text to speech over the ElevenLabs API.

POST /v1/text-to-speech/{voice_id} with ``output_format=pcm_24000`` returns
raw mono 16-bit little-endian PCM at 24 kHz (ElevenLabs docs, read
2026-10-28). The same rate feeds talkback and the Opus voice note, so nothing
is resampled. Every call passes ``gate.check_model_call`` and lands in the job
log with its estimated cost.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import numpy as np

from hiremarco import config, gate
from hiremarco.joblog import JobLog, JobRow
from hiremarco.meta.pricing import speech_cost_usd

BASE_URL = "https://api.elevenlabs.io/v1"
MODEL = "eleven_flash_v2_5"
RATE = 24000
TENANT = "owner"
MAX_CHARS = 1000
# Delivery, from the ElevenLabs voice settings: higher stability is calmer and steadier, lower style is less
# dramatic, speed below 1 is slower. Each can be set in the env file; these are the calm defaults.
VOICE_SETTINGS = {
    "stability": ("HIREMARCO_VOICE_STABILITY", 0.65),
    "similarity_boost": ("HIREMARCO_VOICE_SIMILARITY", 0.75),
    "style": ("HIREMARCO_VOICE_STYLE", 0.0),
    "speed": ("HIREMARCO_VOICE_SPEED", 0.95),
}


def voice_settings() -> dict[str, float]:
    settings = {}
    for field, (key, default) in VOICE_SETTINGS.items():
        value = float(config.get(key) or default)
        low, high = (0.7, 1.2) if field == "speed" else (0.0, 1.0)
        settings[field] = min(max(value, low), high)
    return settings


class SpeechError(RuntimeError):
    pass


@dataclass(frozen=True)
class Speech:
    text: str
    pcm: np.ndarray  # mono int16 at RATE

    @property
    def seconds(self) -> float:
        return self.pcm.size / RATE


def speakable(text: str) -> str:
    """Music written the way it is said: "A major" is "Eigh major" (live 2026-10-31 the voice said "uh major"), "F#" is
    "F sharp", "Bb" is "B flat", "Am" is "Eigh minor". A capital A that is a word ("A beat arrived") stays as it is."""
    import re

    # no "Hmm" or "Mm" to open a line (Owner 2026-10-31), whoever wrote it
    t = re.sub(r"^\s*(?:h?m{2,}|uh+|um+)(?:[,.!?…]+|\s)\s*", "", text, flags=re.I) or text
    t = re.sub(r"\b([A-G])(?:#|♯)", r"\1 sharp", t)
    t = re.sub(r"\b([A-G])(?:b|♭)(?=m\b|\s|[.,;:!?]|$)", r"\1 flat", t)
    t = re.sub(r"\b([A-G])m\b", r"\1 minor", t)
    note = r"A(?=\s+(?:sharp|flat|major|minor|natural)\b)"
    t = re.sub(rf"\b{note}", "Eigh", t)
    t = re.sub(r"\b(key of) A\b", r"\1 Eigh", t)
    t = re.sub(r"(?<=\b[A-G] )A\b|\bA(?= [A-G]\b)", "Eigh", t)  # in a run of note names: "G A B"
    return t


def synthesize(text: str, *, voice_id: str | None = None, api_key: str | None = None,
               joblog: JobLog | None = None, transport: httpx.BaseTransport | None = None,
               timeout: float = 30.0) -> Speech:
    text = text.strip()
    if not text:
        raise ValueError("nothing to say")
    if len(text) > MAX_CHARS:
        raise ValueError(f"{len(text)} characters is more than one line of talk ({MAX_CHARS})")
    joblog = joblog or JobLog()
    gate.check_model_call(TENANT, model=MODEL, system="", prompt=text, joblog=joblog)
    voice_id = voice_id or config.require("ELEVENLABS_VOICE_ID")
    api_key = api_key or config.require("ELEVENLABS_API_KEY")
    started = time.monotonic()
    ok, note = False, ""
    try:
        with httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport) as http:
            response = http.post(
                f"/text-to-speech/{voice_id}",
                params={"output_format": f"pcm_{RATE}"},
                headers={"xi-api-key": api_key, "accept": "audio/pcm"},
                json={"text": speakable(text), "model_id": MODEL, "voice_settings": voice_settings()},
            )
        if response.status_code >= 400:
            note = f"HTTP {response.status_code}"
            raise SpeechError(f"ElevenLabs returned {note}")
        body = response.content
        if len(body) < 2 or len(body) % 2:
            note = f"{len(body)} bytes is not 16-bit PCM"
            raise SpeechError(note)
        ok = True
        return Speech(text, np.frombuffer(body, dtype="<i2").copy())
    except httpx.HTTPError as exc:
        note = type(exc).__name__
        raise SpeechError(f"request failed: {note}") from exc
    finally:
        joblog.append(JobRow(job="speech", model=MODEL, cost_usd=speech_cost_usd(MODEL, len(text)),
                             duration_ms=int((time.monotonic() - started) * 1000), ok=ok,
                             note=note or f"{len(text)} characters"))

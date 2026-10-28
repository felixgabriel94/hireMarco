"""Marco's ears: Muse Voice Transcribe.

Two ways in, both from the Meta Model API docs (read 2026-10-28):

- ``Listener`` streams the booth mic over the realtime WebSocket in
  ENDPOINTING mode, so the model itself decides when Felix has finished a
  sentence, with keyword biasing toward the words Marco must not miss.
- ``transcribe`` sends a finished recording (the call) in DIARIZATION mode,
  so the transcript comes back in turns with speaker labels.

Audio goes in as mono 16-bit PCM at 24 kHz, the model's native rate.
"""

from __future__ import annotations

import io
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx
import numpy as np
import soundfile as sf

from hiremarco import config, gate
from hiremarco.joblog import JobLog, JobRow
from hiremarco.meta.client import BASE_URL
from hiremarco.meta.pricing import audio_cost_usd

MODEL = "muse-voice-transcribe-1.0"
REALTIME_URL = "wss://api.meta.ai/v1/asr/realtime"
RATE = 24000
TENANT = "owner"
STUDIO_KEYWORDS = ["Marco", "punch", "chorus", "verse", "intro", "bridge", "hook", "harmony", "reverb", "delay",
                   "auto-tune", "tuning", "bar", "track", "take", "mix", "record"]


@dataclass(frozen=True)
class Turn:
    start_ms: int
    end_ms: int
    text: str
    speaker: str = ""


def to_pcm24k(data: np.ndarray, rate: int) -> np.ndarray:
    """Mono int16 at 24 kHz from any float or int array at any rate."""
    if data.ndim > 1:
        data = data.mean(axis=1)
    integer = np.issubdtype(data.dtype, np.integer)
    data = data.astype(np.float64)
    if integer:
        data = data / 32768.0
    if rate != RATE and data.size:
        duration = data.size / rate
        target = np.linspace(0, duration, int(round(duration * RATE)), endpoint=False)
        data = np.interp(target, np.arange(data.size) / rate, data)
    return (np.clip(data, -1, 1) * 32767).astype("<i2")


def wav_bytes(pcm: np.ndarray) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, pcm, RATE, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _log(joblog: JobLog, job: str, audio_ms: int, started: float, ok: bool, note: str = "") -> None:
    joblog.append(JobRow(job=job, model=MODEL, cost_usd=audio_cost_usd(MODEL, audio_ms),
                         duration_ms=int((time.monotonic() - started) * 1000), ok=ok,
                         note=note or f"{audio_ms} ms of audio"))


def transcribe(audio: np.ndarray, rate: int, *, diarize: bool = True, keywords: list[str] | None = None,
               joblog: JobLog | None = None, transport: httpx.BaseTransport | None = None) -> list[Turn]:
    joblog = joblog or JobLog()
    gate.check_model_call(TENANT, model=MODEL, system="", prompt="", joblog=joblog)
    pcm = to_pcm24k(audio, rate)
    request = {"model": MODEL, "audioEncoding": "WAV", "mode": "DIARIZATION" if diarize else "ENDPOINTING"}
    if keywords:
        request["keywords"] = keywords
    started = time.monotonic()
    with httpx.Client(base_url=BASE_URL, timeout=120, transport=transport) as http:
        response = http.post("/asr/transcribe", headers={"Authorization": f"Bearer {config.require('MODEL_API_KEY')}",
                                                          "Accept": "application/json"},
                             files={"request": (None, json.dumps(request), "application/json"),
                                    "audio": ("audio.wav", wav_bytes(pcm), "audio/wav")})
    audio_ms = int(len(pcm) / RATE * 1000)
    if response.status_code >= 400:
        _log(joblog, "transcribe", audio_ms, started, False, f"http {response.status_code}")
        raise RuntimeError(f"Voice Transcribe returned HTTP {response.status_code}")
    data = response.json()
    _log(joblog, "transcribe", int(data.get("audioDurationMs", audio_ms)), started, True)
    turns = [Turn(t["startMs"], t["endMs"], t["transcript"].strip(), t.get("speaker", "")) for t in data.get("turns") or []]
    if not turns and data.get("transcript"):
        turns = [Turn(0, audio_ms, data["transcript"].strip())]
    return turns


class Listener:
    """One realtime session: feed it PCM chunks, get finished sentences back."""

    def __init__(self, *, keywords: list[str] | None = None, joblog: JobLog | None = None,
                 connect: Callable | None = None):
        self.keywords = keywords if keywords is not None else STUDIO_KEYWORDS
        self.joblog = joblog or JobLog()
        self._connect = connect

    def handshake(self) -> dict:
        return {
            "authorization": {"accessToken": f"Bearer {config.require('MODEL_API_KEY')}"},
            "audioEncoding": "PCM_24KHZ",
            "model": MODEL,
            "mode": "ENDPOINTING",
            "partialMode": "CUMULATIVE",
            "emitAudioProgress": False,
            "keywords": self.keywords,
            "languageBias": ["English"],
        }

    async def sentences(self, chunks: AsyncIterator[bytes]) -> AsyncIterator[str]:
        """Yield each finished sentence as the model closes the turn."""
        import asyncio

        gate.check_model_call(TENANT, model=MODEL, system="", prompt="", joblog=self.joblog)
        if self._connect is None:
            import websockets

            self._connect = websockets.connect
        started = time.monotonic()
        sent_bytes = 0
        async with self._connect(REALTIME_URL) as ws:
            await ws.send(json.dumps(self.handshake()))
            json.loads(await ws.recv())  # {"sessionId": ...}

            async def pump() -> None:
                nonlocal sent_bytes
                async for chunk in chunks:
                    await ws.send(chunk)
                    sent_bytes += len(chunk)
                await ws.send(json.dumps({"type": "endStream"}))

            sender = asyncio.create_task(pump())
            try:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == "speechComplete" and event.get("transcript", "").strip():
                        yield event["transcript"].strip()
                    elif kind == "error":
                        raise RuntimeError(f"Voice Transcribe error: {event.get('errorType') or 'unknown'}")
            finally:
                sender.cancel()
                _log(self.joblog, "listen", int(sent_bytes / 2 / RATE * 1000), started, True)

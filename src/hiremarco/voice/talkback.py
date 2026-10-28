"""Talkback: Marco speaks in the Owner's headphones, between takes only.

The line is spoken only while the transport is stopped. It is checked twice,
before the speech is made and again just before it plays, because a take can
start in the second or two that synthesis takes. Every line is kept as a
timestamped WAV in the capture folder, exactly what played, with one JSON
line beside it, so the film can lay Marco's voice in on the same clock.

The output goes to an Apollo virtual channel pair, set by two settings (read
like the secrets, process environment first, then the env file):

    HIREMARCO_TALKBACK_DEVICE    the output device name, e.g. "Universal Audio Thunderbolt"
    HIREMARCO_TALKBACK_CHANNELS  the 1-based channel pair, e.g. "3,4"

Unset, it plays on the Mac's default output, which is how a dry run sounds.
Every line passes the gate on the ``talkback`` channel, so a ``send:
talkback -> *`` line in RULES.md must be live.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from hiremarco import config, gate
from hiremarco.voice.tts import MODEL, RATE, Speech, synthesize, voice_settings

TENANT = "owner"

Player = Callable[[np.ndarray, int], None]


class TakeRolling(gate.Refused):
    """A take is rolling, so Marco holds the line."""


def capture_dir() -> Path:
    return Path(config.get("HIREMARCO_CAPTURE") or config.STATE_DIR / "capture")


def channel_pair(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    pair = [int(part) for part in raw.replace(" ", "").split(",") if part]
    if len(pair) != 2 or min(pair) < 1:
        raise ValueError("HIREMARCO_TALKBACK_CHANNELS takes two 1-based channels, e.g. 3,4")
    return pair


def device_player() -> Player:
    """Play through PortAudio on the configured device and channel pair."""
    device = config.get("HIREMARCO_TALKBACK_DEVICE") or None
    mapping = channel_pair(config.get("HIREMARCO_TALKBACK_CHANNELS"))

    def play(pcm: np.ndarray, rate: int) -> None:
        import sounddevice as sd

        stereo = np.column_stack([pcm, pcm])
        sd.play(stereo, rate, device=device, mapping=mapping, blocking=True)

    return play


class Talkback:
    def __init__(
        self,
        is_rolling: Callable[[], bool],
        *,
        speak: Callable[[str], Speech] = synthesize,
        play: Player | None = None,
        folder: Path | None = None,
        conn=None,
        rules_path: Path | None = None,
        cache_dir: Path | None = None,
    ):
        self.is_rolling = is_rolling
        self.speak = speak
        self.play = play or device_player()
        self.folder = folder or capture_dir()
        self.conn = conn or gate.connect()
        self.rules_path = rules_path
        state = Path(os.environ.get("HIREMARCO_STATE", config.STATE_DIR))
        self.cache_dir = cache_dir if cache_dir is not None else state / "voice-cache"

    def _cache_path(self, text: str) -> Path:
        voice = config.get("ELEVENLABS_VOICE_ID") or "default"
        delivery = ",".join(f"{v:.2f}" for v in voice_settings().values())
        key = hashlib.sha256(f"{voice}|{MODEL}|{delivery}|{text}".encode()).hexdigest()[:24]
        return self.cache_dir / f"{key}.wav"

    def _ready(self, text: str) -> Speech:
        """The line's audio: from the cache when Marco has said it before, made and kept otherwise."""
        path = self._cache_path(text)
        if path.exists():
            pcm, _ = sf.read(path, dtype="int16")
            return Speech(text, pcm)
        speech = self.speak(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, speech.pcm, RATE, subtype="PCM_16")
        return speech

    def warm(self, lines: list[str]) -> int:
        """Make the session's stock lines ahead, so "Rolling" plays the instant it is needed."""
        made = 0
        for line in lines:
            if not self._cache_path(line).exists():
                self._ready(line)
                made += 1
        return made

    def say(self, text: str) -> Path:
        """Speak one line. Returns the WAV that played. Raises ``TakeRolling`` or ``gate.Refused``."""
        if self.is_rolling():
            raise TakeRolling("a take is rolling")
        stamp = datetime.now().astimezone()
        return gate.execute_effect(
            self.conn, lambda: self._speak_and_play(text, stamp),
            tenant_id=TENANT, idempotency_key=f"talkback:{time.time_ns()}", capability="speak",
            channel="talkback", target="*", message=text, department="studio", rules_path=self.rules_path,
        )

    def play_clip(self, pcm: np.ndarray, label: str) -> Path:
        """Play a clip Marco made himself (the guide melody), held to the same rules as speech."""
        if self.is_rolling():
            raise TakeRolling("a take is rolling")
        stamp = datetime.now().astimezone()
        return gate.execute_effect(
            self.conn, lambda: self._play_and_keep(Speech(label, pcm), stamp, 0, "_guide.wav"),
            tenant_id=TENANT, idempotency_key=f"talkback:{time.time_ns()}", capability="play_guide",
            channel="talkback", target="*", message=label, department="studio", rules_path=self.rules_path,
        )

    def _speak_and_play(self, text: str, stamp: datetime) -> Path:
        began = time.monotonic()
        speech = self._ready(text)
        ready_ms = int((time.monotonic() - began) * 1000)
        return self._play_and_keep(speech, stamp, ready_ms, "_marco.wav")

    def _play_and_keep(self, speech: Speech, stamp: datetime, ready_ms: int, suffix: str) -> Path:
        if self.is_rolling():
            raise TakeRolling("a take started while Marco was getting the line ready")
        self.folder.mkdir(parents=True, exist_ok=True)
        name = stamp.strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + suffix
        path = self.folder / name
        sf.write(path, speech.pcm, RATE, subtype="PCM_16")
        started = datetime.now().astimezone()
        self.play(speech.pcm, RATE)
        with (self.folder / "talkback.jsonl").open("a") as log:
            log.write(json.dumps({"played_at": started.isoformat(timespec="milliseconds"), "file": name,
                                  "seconds": round(speech.seconds, 3), "ready_ms": ready_ms,
                                  "text": speech.text}) + "\n")
        return path

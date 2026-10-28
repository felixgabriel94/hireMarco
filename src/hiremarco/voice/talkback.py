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

import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from hiremarco import config, gate
from hiremarco.voice.tts import RATE, Speech, synthesize

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
    ):
        self.is_rolling = is_rolling
        self.speak = speak
        self.play = play or device_player()
        self.folder = folder or capture_dir()
        self.conn = conn or gate.connect()
        self.rules_path = rules_path

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

    def _speak_and_play(self, text: str, stamp: datetime) -> Path:
        speech = self.speak(text)
        if self.is_rolling():
            raise TakeRolling("a take started while Marco was getting the line ready")
        self.folder.mkdir(parents=True, exist_ok=True)
        name = stamp.strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3] + "_marco.wav"
        path = self.folder / name
        sf.write(path, speech.pcm, RATE, subtype="PCM_16")
        started = datetime.now().astimezone()
        self.play(speech.pcm, RATE)
        with (self.folder / "talkback.jsonl").open("a") as log:
            log.write(json.dumps({"played_at": started.isoformat(timespec="milliseconds"), "file": name,
                                  "seconds": round(speech.seconds, 3), "text": speech.text}) + "\n")
        return path

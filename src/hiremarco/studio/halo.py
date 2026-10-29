"""Marco's halo over Logic: the orb that shows when he listens, thinks and speaks.

The halo is its own small Mac app (``halo/MarcoHalo.swift``), built once with
the Mac's Swift compiler into the state folder and rebuilt when the source
changes. The booth starts it and tells it what Marco is doing over UDP on
127.0.0.1:8789, thirty times a second: "listening" with the artist's level,
"thinking" while a command runs, "speaking" with Marco's own level.
"""

from __future__ import annotations

import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from hiremarco import config

PORT = 8789
SOURCE = Path(__file__).resolve().parents[3] / "halo" / "MarcoHalo.swift"


def binary() -> Path:
    return config.STATE_DIR / "bin" / "MarcoHalo"


def build(source: Path = SOURCE, target: Path | None = None) -> Path:
    """Compile the halo when it is missing or older than its source."""
    target = target or binary()
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["swiftc", "-O", "-swift-version", "5", str(source), "-o", str(target)],
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(f"the halo did not build: {done.stderr.strip()[-300:]}")
    return target


def level_of(rms: float, gain: float) -> float:
    return max(0.0, min(1.0, rms * gain))


def booth_state(booth, audio) -> tuple[str, float]:
    """What the halo shows for the booth right now: away for a take, and his voice, his thinking or yours otherwise."""
    if booth.rolling:  # the take belongs to the artist: the halo steps out of the way
        return "recording", 0.0
    if audio.speaking:
        return "speaking", level_of(audio.out_level, 10)
    if booth.busy or time.monotonic() - getattr(booth, "called_at", 0.0) < 3.0:
        return "thinking", 0.0  # his name was just heard: he rises before the sentence is even finished
    return "listening", level_of(audio.in_level, 8)


class Halo:
    """The link to the running halo. ``state`` reads the booth's audio and mode; a thread sends it 30 times a second."""

    def __init__(self, state: Callable[[], tuple[str, float]], *, send: Callable[[bytes], None] | None = None,
                 rate: float = 30.0):
        self.state = state
        self.interval = 1.0 / rate
        self._sock = None
        self._send = send or self._udp
        self._process: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _udp(self, data: bytes) -> None:
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.sendto(data, ("127.0.0.1", PORT))

    def tick(self) -> bytes:
        mode, level = self.state()
        message = f"{mode} {level:.3f}".encode()
        try:
            self._send(message)
        except OSError:
            pass  # the halo is not up yet, or has gone; the booth carries on
        return message

    def _run(self) -> None:
        while not self._stop.is_set():
            self.tick()
            time.sleep(self.interval)

    def start(self, *, launch: bool = True) -> None:
        if launch:
            self._process = subprocess.Popen([str(build())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._send(b"quit")
        except OSError:
            pass
        if self._process is not None:
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.terminate()

"""The film recorder: the booth on one clock, the whole session long.

Logic records the song only while it rolls. The film needs everything: the
mic between takes, what the Owner hears, and Marco's talkback. This reads the
interface's inputs continuously, the mic dry plus the Apollo virtual channels
that carry Logic's output and Marco's voice, and writes them as one
multichannel file per segment.

Segments are 15 minutes of 24-bit WAV each, so a crash loses at most the
segment being written, and each file stays far below the WAV size limit.
``film.jsonl`` beside them records every segment's first sample on the
session clock and the wall-clock time it began, so the edit can line the
segments up without a gap; a clap per take checks it.

Settings, read like the secrets (process environment first, then the env file):

    HIREMARCO_FILM_DEVICE    the input device name, e.g. "Universal Audio Thunderbolt"
    HIREMARCO_FILM_CHANNELS  1-based input channels in file order; on the Apollo Twin X
                             "1,3,4,5,6": the mic dry, the headphone mix (MON L/R), Logic alone (Virtual 1-2)
    HIREMARCO_FILM_RATE      the interface's sample rate, 48000 unless set
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from hiremarco import config

SEGMENT_SECONDS = 15 * 60


def film_dir() -> Path:
    return Path(config.get("HIREMARCO_CAPTURE") or config.STATE_DIR / "capture") / "film"


def channel_list(raw: str | None) -> list[int]:
    if not raw:
        raise ValueError("set HIREMARCO_FILM_CHANNELS, e.g. 1,9,10,11,12")
    channels = [int(part) for part in raw.replace(" ", "").split(",") if part]
    if not channels or min(channels) < 1 or len(set(channels)) != len(channels):
        raise ValueError("HIREMARCO_FILM_CHANNELS takes distinct 1-based channels")
    return channels


class Segmenter:
    """Writes blocks of frames into segment files on one running sample clock."""

    def __init__(self, folder: Path, rate: int, channels: int, segment_seconds: int = SEGMENT_SECONDS,
                 clock: Callable[[], datetime] = lambda: datetime.now().astimezone()):
        self.folder = folder
        self.rate = rate
        self.channels = channels
        self.segment_frames = segment_seconds * rate
        self.clock = clock
        self.frames = 0  # samples written since the session started, per channel
        self.files: list[Path] = []
        self._file: sf.SoundFile | None = None
        self._in_segment = 0

    def _open(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        began = self.clock()
        path = self.folder / (began.strftime("%Y-%m-%dT%H-%M-%S") + f"_film_{len(self.files) + 1:03d}.wav")
        self._file = sf.SoundFile(path, "w", samplerate=self.rate, channels=self.channels, subtype="PCM_24")
        self._in_segment = 0
        self.files.append(path)
        with (self.folder / "film.jsonl").open("a") as log:
            log.write(json.dumps({"file": path.name, "first_sample": self.frames, "rate": self.rate,
                                  "channels": self.channels, "began": began.isoformat(timespec="milliseconds")})
                      + "\n")

    def write(self, block: np.ndarray) -> None:
        if block.ndim != 2 or block.shape[1] != self.channels:
            raise ValueError(f"expected frames x {self.channels} channels, got {block.shape}")
        while block.shape[0]:
            if self._file is None or self._in_segment >= self.segment_frames:
                self.close()
                self._open()
            room = self.segment_frames - self._in_segment
            part, block = block[:room], block[room:]
            self._file.write(part)
            self._in_segment += part.shape[0]
            self.frames += part.shape[0]

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


class FilmRecorder:
    """Reads the interface in a PortAudio callback; a writer thread does the disk."""

    def __init__(self, *, device: str | None = None, channels: list[int] | None = None, rate: int | None = None,
                 folder: Path | None = None, segment_seconds: int = SEGMENT_SECONDS, stream_factory=None):
        self.device = device or config.get("HIREMARCO_FILM_DEVICE") or None
        self.channels = channels or channel_list(config.get("HIREMARCO_FILM_CHANNELS"))
        self.rate = rate or int(config.get("HIREMARCO_FILM_RATE") or 48000)
        self.segmenter = Segmenter(folder or film_dir(), self.rate, len(self.channels), segment_seconds)
        self.stream_factory = stream_factory or self._portaudio_stream
        self.dropped = 0
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._writer: threading.Thread | None = None
        self._stream = None

    def _portaudio_stream(self, callback):
        import sounddevice as sd

        # Open enough channels to reach the highest one asked for, then keep only those.
        return sd.InputStream(device=self.device, channels=max(self.channels), samplerate=self.rate,
                              dtype="float32", callback=callback)

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            self.dropped += 1  # an overflow is reported, not hidden
        self._queue.put(np.asarray(indata)[:, [c - 1 for c in self.channels]].copy())

    def _drain(self) -> None:
        while True:
            block = self._queue.get()
            if block is None:
                break
            self.segmenter.write(block)
        self.segmenter.close()

    def start(self) -> None:
        self._writer = threading.Thread(target=self._drain, name="film-writer", daemon=True)
        self._writer.start()
        self._stream = self.stream_factory(self._callback)
        self._stream.start()

    def stop(self) -> list[Path]:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._queue.put(None)
        if self._writer is not None:
            self._writer.join()
        return self.segmenter.files

    @property
    def seconds(self) -> float:
        return self.segmenter.frames / self.rate

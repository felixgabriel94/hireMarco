"""One audio stream for the interface: the mic in and Marco out, together.

Opening a second stream on the Apollo for Marco's voice while the mic stream
runs made the mic stall ("ingress audio slower than real-time", live
2026-10-28), and Voice Transcribe dropped the session. A single duplex stream
reads the mic and writes Marco's voice in the same callback, so neither
blocks the other. Marco's lines arrive at 24 kHz, are resampled to the
device's rate, and are mixed onto the configured output pair; ``play``
blocks until the line has been written, so talkback keeps its timing.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

import numpy as np

from hiremarco import config


def resample(pcm: np.ndarray, rate_in: int, rate_out: int) -> np.ndarray:
    """Mono int16 at one rate to float32 at another."""
    data = pcm.astype(np.float32) / 32768.0
    if rate_in == rate_out or data.size == 0:
        return data
    duration = data.size / rate_in
    target = np.linspace(0, duration, int(round(duration * rate_out)), endpoint=False)
    return np.interp(target, np.arange(data.size) / rate_in, data).astype(np.float32)


class DuplexAudio:
    def __init__(self, *, device: str | None, rate: int, mic_channel: int, out_pair: tuple[int, int],
                 in_channels: int, out_channels: int, on_input: Callable[[np.ndarray], None],
                 blocksize: int | None = None):
        self.device = device
        self.rate = rate
        self.mic_channel = mic_channel
        self.out_pair = out_pair
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.on_input = on_input
        self.blocksize = blocksize or rate // 10
        self._pending: queue.Queue[np.ndarray] = queue.Queue()
        self._current: np.ndarray | None = None
        self._offset = 0
        self._drained = threading.Event()
        self._drained.set()
        self._stream = None
        self.overflows = 0
        self.in_level = 0.0   # RMS of the last mic block, for the halo
        self.out_level = 0.0  # RMS of Marco's voice in the last block

    @classmethod
    def from_config(cls, on_input: Callable[[np.ndarray], None]) -> "DuplexAudio":
        import sounddevice as sd

        device = config.get("HIREMARCO_MIC_DEVICE") or config.get("HIREMARCO_TALKBACK_DEVICE") or None
        info = sd.query_devices(device) if device else sd.query_devices(kind="input")
        rate = int(config.get("HIREMARCO_MIC_RATE") or info.get("default_samplerate") or 48000)
        pair_raw = config.get("HIREMARCO_TALKBACK_CHANNELS") or "1,2"
        pair = tuple(int(p) for p in pair_raw.replace(" ", "").split(",")[:2])
        return cls(device=device, rate=rate, mic_channel=int(config.get("HIREMARCO_MIC_CHANNEL") or 1),
                   out_pair=(pair[0], pair[1] if len(pair) > 1 else pair[0]),
                   in_channels=int(info.get("max_input_channels") or 1),
                   out_channels=int(info.get("max_output_channels") or 2), on_input=on_input)

    def callback(self, indata, outdata, frames, time_info, status) -> None:
        if status and getattr(status, "input_overflow", False):
            self.overflows += 1
        if frames > 0:
            mic = np.asarray(indata)[:, self.mic_channel - 1].copy()
            self.in_level = float(np.sqrt(np.mean(mic * mic))) if mic.size else 0.0
            self.on_input(mic)
        out = np.asarray(outdata)
        out[:] = 0
        written = 0
        voice = 0.0
        while written < frames:
            if self._current is None or self._offset >= self._current.size:
                try:
                    self._current = self._pending.get_nowait()
                    self._offset = 0
                except queue.Empty:
                    self._current = None
                    self._drained.set()
                    break
            take = min(frames - written, self._current.size - self._offset)
            chunk = self._current[self._offset:self._offset + take]
            voice += float(np.sum(chunk * chunk))
            for ch in self.out_pair:
                if 1 <= ch <= self.out_channels:
                    out[written:written + take, ch - 1] += chunk
            self._offset += take
            written += take
        self.out_level = float(np.sqrt(voice / frames)) if frames > 0 else 0.0

    @property
    def speaking(self) -> bool:
        return not self._drained.is_set()

    def play(self, pcm: np.ndarray, rate: int) -> None:
        """Queue one line for the next callbacks and wait until it has gone out."""
        data = resample(np.asarray(pcm), rate, self.rate)
        if data.size == 0:
            return
        self._drained.clear()
        self._pending.put(data)
        self._drained.wait(timeout=data.size / self.rate + 2.0)

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.Stream(device=(self.device, self.device), channels=(self.in_channels, self.out_channels),
                                 samplerate=self.rate, dtype="float32", blocksize=self.blocksize,
                                 callback=self.callback)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self) -> "DuplexAudio":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

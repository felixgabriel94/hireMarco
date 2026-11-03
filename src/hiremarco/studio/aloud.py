"""What Marco listens to, heard by the room's recording (Owner 2026-11-03: in the studio you hear what the mastering
engineer hears).

Each clip a model is given plays on Marco's own channel pair on the Apollo, the pair the film records and the Owner's
headphones carry, beside the model call and never ahead of it: the clip starts as the call goes out and stops when the
next clip or Logic's own playback starts, so Marco never waits for the room. The room's speakers are not on this path.
With no Apollo in reach, or ``HIREMARCO_ALOUD=off``, the work goes on in silence as before.
"""

from __future__ import annotations

import threading

import numpy as np

from hiremarco import config

_lock = threading.Lock()
_current: Clip | None = None
BLOCK_S = 0.1


def where() -> tuple[str | None, list[int] | None]:
    """Marco's channel pair on the Apollo, the same one his voice and the count-in take (crew.outputs)."""
    from hiremarco.crew import outputs

    return outputs()[1]


class Clip:
    """One clip on its way out, stoppable between blocks."""

    def __init__(self, pcm: np.ndarray, rate: int, device: str | None, mapping: list[int] | None, stream=None):
        stereo = pcm if pcm.ndim == 2 else np.column_stack([pcm, pcm])
        stereo = stereo[:, :2] if stereo.shape[1] >= 2 else np.column_stack([stereo[:, 0], stereo[:, 0]])
        width = max(mapping) if mapping else 2
        self.block = np.zeros((len(stereo), width), dtype=np.float32)
        for i, channel in enumerate(mapping or [1, 2]):
            self.block[:, channel - 1] = stereo[:, i]
        self.rate, self.device, self.width, self._stream = rate, device, width, stream
        self.seconds = len(stereo) / float(rate)
        self.played = 0
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="aloud", daemon=True)

    def _run(self) -> None:
        stream = self._stream
        if stream is None:
            import sounddevice as sd

            stream = sd.OutputStream(device=self.device, channels=self.width, samplerate=self.rate, dtype="float32")
        step = max(int(self.rate * BLOCK_S), 1)
        with stream as out:
            for i in range(0, len(self.block), step):
                if self._stop.is_set():
                    break
                out.write(self.block[i:i + step])
                self.played = min(i + step, len(self.block))

    def stop(self) -> None:
        self._stop.set()

    @property
    def done(self) -> bool:
        return not self.thread.is_alive()


def on() -> bool:
    return (config.get("HIREMARCO_ALOUD") or "on").lower() != "off"


def play(pcm: np.ndarray, rate: int, *, stream=None) -> Clip | None:
    """Start the clip on Marco's pair; whatever was playing stops. None when playback is off or the pair is out of
    reach, and the caller carries on either way."""
    global _current
    if not on():
        return None
    with _lock:
        if _current is not None:
            _current.stop()
            _current = None
        try:
            device, mapping = where()
            clip = Clip(np.asarray(pcm, dtype="float32"), int(rate), device, mapping, stream=stream)
            clip.thread.start()
        except Exception:   # noqa: BLE001  (no device, no sounddevice): silence, never a stopped job
            return None
        _current = clip
        return clip


def stop() -> None:
    """Before Logic's own playback or at the end of a job: the room hears one thing at a time."""
    global _current
    with _lock:
        if _current is not None:
            _current.stop()
            _current = None

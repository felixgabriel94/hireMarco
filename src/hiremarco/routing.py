"""The routing test: does the interface carry what the film and talkback need?

Plays a quiet tone (-30 dBFS, one second) on one output pair and records
every input at the same time, then names the inputs that heard it. On an
Apollo, a virtual output pair should come back on the matching virtual input
pair, and on MON L/R if Console sends it to the monitors. The mic check
records a few seconds of every input while Felix speaks and reports levels,
so the Manley's input is found rather than assumed.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

QUIET = 0.03  # about -30 dBFS
HEARD_DB = -60.0


def levels_db(recording: np.ndarray) -> list[float]:
    rms = np.sqrt((recording.astype(np.float64) ** 2).mean(axis=0))
    return [round(20 * float(np.log10(max(r, 1e-9))), 1) for r in rms]


def probe(device: str, out_pair: tuple[int, int], outputs: int, inputs: int, *, rate: int = 48000,
          playrec: Callable | None = None) -> dict[int, float]:
    """Inputs (1-based) that heard a tone on ``out_pair``, with their level in dBFS."""
    if playrec is None:
        import sounddevice as sd

        playrec = sd.playrec
    t = np.arange(rate) / rate
    tone = (np.sin(2 * np.pi * 440 * t) * QUIET).astype("float32")
    out = np.zeros((rate, outputs), dtype="float32")
    for ch in out_pair:
        out[:, ch - 1] = tone
    rec = playrec(out, rate, device=(device, device), input_mapping=list(range(1, inputs + 1)),
                  output_mapping=list(range(1, outputs + 1)), blocking=True)
    rec = np.asarray(rec)[rate // 4:]  # skip the round-trip latency at the start
    return {i + 1: db for i, db in enumerate(levels_db(rec)) if db > HEARD_DB}


def mic_levels(device: str, inputs: int, seconds: float = 3.0, *, rate: int = 48000,
               rec: Callable | None = None, threshold: float = HEARD_DB) -> dict[int, float]:
    if rec is None:
        import sounddevice as sd

        def rec(frames, samplerate, device, mapping):
            data = sd.rec(frames, samplerate=samplerate, device=device, mapping=mapping)
            sd.wait()
            return data

    data = rec(int(seconds * rate), rate, device, list(range(1, inputs + 1)))
    return {i + 1: db for i, db in enumerate(levels_db(np.asarray(data))) if db > threshold}

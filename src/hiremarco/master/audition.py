"""Hearing the part of the sound a move would touch, on its own: what Pro-Q's solo does for an engineer.

From the mix print, not from the Solo button, so a solo can never reach a master. The slice is shaped by the same
frequency and width a band would have, on the channel it would act on, measured against the whole, and heard by a Meta
model that listens. Only what the audit named gets auditioned: a part of the sound with no finding is left alone.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from hiremarco import events, gate
from hiremarco.meta.client import MuseSpark
from hiremarco.studio.feedback import MODEL, TENANT, take_wav

MOST = 3
LOW_END_HZ = 120.0
WIDE_BELOW = 0.8     # the rulebook's low-end correlation (handbook M-05)
INSTRUCTIONS = (
    "You are a mastering engineer listening to one part of the sound on its own, the way an equalizer's solo button "
    "plays it. Say what you hear in it and whether it sounds like part of the music or a problem to fix. Answer as asked.")
SCHEMA = {"type": "object", "properties": {
    "hears": {"type": "string", "description": "what is in this slice, for the engineer, one sentence"},
    "note": {"type": "string", "description": "the same for someone who has never been in a studio: one short everyday sentence, first person, no numbers, no music or audio terms"},
    "is_a_problem": {"type": "boolean"}}, "required": ["hears", "note", "is_a_problem"], "additionalProperties": False}


@dataclass(frozen=True)
class Target:
    what: str
    hz: float | None = None      # a bell at this frequency, or everything below ``below``
    q: float = 4.0
    below: float | None = None
    placement: str = "Stereo"


@dataclass(frozen=True)
class Heard:
    what: str
    level_db: float
    note: str
    is_a_problem: bool


def targets(audit) -> list[Target]:
    """What the audit named: a wide low end on its side channel, then the worst resonances."""
    out = []
    low = audit.base.low_mono
    if low is not None and low < WIDE_BELOW:
        out.append(Target(f"the sides below {LOW_END_HZ:g} Hz", below=LOW_END_HZ, placement="Side"))
    for r in audit.resonances[:MOST]:
        out.append(Target(f"{r.hz:g} Hz" + (f" ({r.note})" if r.note else ""), hz=float(r.hz)))
    return out[:MOST]


def channel(audio: np.ndarray, placement: str) -> np.ndarray:
    left, right = audio[:, 0], audio[:, -1]
    return {"Left": left, "Right": right, "Mid": (left + right) / 2, "Side": (left - right) / 2}.get(placement, (left + right) / 2)


def slice_of(audio: np.ndarray, rate: int, target: Target) -> np.ndarray:
    """The part of the sound that band would touch: a bell's shape at its frequency and width, or all below a cut."""
    signal = channel(audio, target.placement)
    spectrum = np.fft.rfft(signal)
    freqs = np.maximum(np.fft.rfftfreq(signal.size, 1 / rate), 1e-6)
    if target.below is not None:
        mask = (freqs <= target.below).astype(float)
    else:
        mask = 1.0 / np.sqrt(1.0 + (target.q * (freqs / target.hz - target.hz / freqs)) ** 2)
    return np.fft.irfft(spectrum * mask, signal.size)


def level_against(part: np.ndarray, audio: np.ndarray) -> float:
    whole = float(np.sqrt(np.mean(np.square(audio)))) or 1e-9
    return round(20 * float(np.log10(max(float(np.sqrt(np.mean(np.square(part)))), 1e-9) / whole)), 1)


def run(mix: Path, audit, bars: tuple[int, int] | None = None, *, client: MuseSpark | None = None, seconds: float = 20.0,
        bar_s: float | None = None) -> list[Heard]:
    """Each named part of the sound, alone, heard once. ``seconds`` of the loudest stretch keep the call short."""
    found = targets(audit)
    if not found:
        return []
    audio, rate = sf.read(str(mix), dtype="float32", always_2d=True)
    hop = int(rate * 0.5)
    energy = np.convolve(np.square(audio).mean(axis=1)[::hop], np.ones(max(int(seconds * 2), 1)), mode="valid")
    start = int(np.argmax(energy)) * hop if energy.size else 0
    stretch = audio[start:start + int(rate * seconds)]
    client = client or MuseSpark()
    heard = []
    for target in found:
        part = slice_of(stretch, rate, target)
        level = level_against(part, stretch)
        peak = float(np.max(np.abs(part))) or 1.0
        wav = base64.b64encode(take_wav((part / peak * 0.5).astype("float32"), rate)).decode()
        question = f"This is {target.what} of the song, on its own, turned up so you can hear it. What is in it?"
        gate.check_model_call(TENANT, model=MODEL, system=INSTRUCTIONS, prompt=question, joblog=client.joblog)
        reply = client.chat(
            [{"role": "developer", "content": INSTRUCTIONS},
             {"role": "user", "content": [{"type": "text", "text": question},
                                          {"type": "input_audio", "input_audio": {"data": wav, "format": "wav"}}]}],
            job="band_audition", model=MODEL, max_completion_tokens=2000, summarize=_line,
            response_format={"type": "json_schema", "json_schema": {"name": "audition", "schema": SCHEMA, "strict": True}})
        try:
            data = json.loads(reply.text)
        except ValueError:
            continue
        heard.append(Heard(target.what, level, str(data.get("hears", "")).strip(), bool(data.get("is_a_problem"))))
        words = events.readable(str(data.get("note", "")))
        if words:
            events.thought(words)
    return heard


def _line(text: str) -> str:
    return events.readable(str(json.loads(text).get("note", ""))) or "Listened."

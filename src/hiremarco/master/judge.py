"""Knowledge and wisdom on every decision that changes the master (Owner 2026-11-03).

Marco's meters and the playbook are the knowledge: they measure and they set
the limits. Muse Spark 1.2 is the ears: it hears two clips of the same part of
the song at the same level and says what differs. Muse Wonder is the wisdom: it
gets the numbers, the rule and what the ears heard, and judges inside the
limits. Marco applies the call. A limit is never argued past: a verdict outside
one is overruled by the caller and the log says so.

Every call here is a model call on the live view, so a model is lit for as long
as it is really at work; nothing here is written for the screen.
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
from hiremarco.studio.feedback import MODEL as EARS
from hiremarco.studio.feedback import TENANT, take_wav

BRAIN = "muse-wonder-1.0"
EFFORT = "medium"      # a verdict on one decision, not a plan: medium effort answers in seconds, not minutes
TOKENS = 6000
SECONDS = 20.0         # of the loudest stretch, enough to hear a tool's absence and short enough for one call

EAR_INSTRUCTIONS = (
    "You are a mastering engineer at the console, hearing two short clips of the same part of a song, matched in "
    "level. The first is one version, the second another. Say what differs between them, plainly, and whether the "
    "difference helps the song, hurts it, or is too small to matter. Answer as asked.")
EAR_SCHEMA = {"type": "object", "properties": {
    "hears": {"type": "string", "description": "what differs between the two, for the engineer, one or two sentences"},
    "note": {"type": "string", "description": "the same for someone who has never been in a studio: one short everyday sentence, first person, no numbers, no music or audio terms"},
    "difference": {"type": "string", "enum": ["helps", "hurts", "none"]}},
    "required": ["hears", "note", "difference"], "additionalProperties": False}

BRAIN_INSTRUCTIONS = (
    "You are Marco, a mastering engineer, deciding one thing. You get the numbers Marco measured on this song, the "
    "playbook's rule with its limits, and what the ears heard. Judge inside the limits: a limit is not yours to move, "
    "and a verdict past one is thrown out. Choose one of the choices given. Give the technical reason in one sentence "
    "that quotes a number you were given, and a plain line for someone who has never been in a studio: one short "
    "everyday sentence, first person, no numbers, no music or audio terms.")

# the playbook, as the brain reads it (knowledge); the numbers ride in the payload
BENCH_RULE = ("Every tool on the master must earn its place. A tool whose absence the measurements cannot see and the ears "
              "cannot hear is taken off; a tool that hurts the song comes off even when it measures. The limits: a move counts "
              "as measured at or past earn_db on level, crest or the widest band, or earn_tilt on tilt.")
LADDER_RULE = ("The master is as loud as this song stays clean, and not one step past it. A step that breaks a floor is "
               "already refused by the meters; the question is whether the next step up is still worth taking, given how "
               "close the last step sits to the floors and the cap, and what the ears said.")
CHECK_RULE = ("Done means the master still sounds like the same song, louder and clearer, with nothing new that hurts it. "
              "The marks (loudness within tolerance of the target, the true peak at or under the ceiling, the check against "
              "the mix) are given as facts under marks_met, measured by Marco; do not re-judge them, judge the sound. Not "
              "yet means one more pass with a named correction to the sound.")


@dataclass
class Call:
    decision: str
    why: str
    plain: str


def _ear_line(text: str) -> str:
    return events.readable(str(json.loads(text).get("note", ""))) or "Listened."


def _call_line(text: str) -> str:
    data = json.loads(text)
    return events.readable(str(data.get("plain", ""))) or str(data.get("decision", "")).capitalize() + "."


def _brain_schema(choices: tuple[str, ...]) -> dict:
    return {"type": "object", "properties": {"decision": {"type": "string", "enum": list(choices)}, "why": {"type": "string"},
                                             "plain": {"type": "string"}},
            "required": ["decision", "why", "plain"], "additionalProperties": False}


def matched_clips(a: Path, b: Path, seconds: float = SECONDS) -> tuple[np.ndarray, np.ndarray, int]:
    """The loudest ``seconds`` of ``a`` and the same stretch of ``b``, the second scaled to the first's level, both
    under a safe peak: louder wins by level, not by quality, so the ears get them matched (rulebook, the listening
    protocol)."""
    audio_a, rate = sf.read(str(a), dtype="float32", always_2d=True)
    audio_b, rate_b = sf.read(str(b), dtype="float32", always_2d=True)
    if rate_b != rate:
        raise ValueError(f"{a.name} is {rate} Hz and {b.name} is {rate_b} Hz")
    hop = int(rate * 0.5)
    energy = np.convolve(np.square(audio_a).mean(axis=1)[::hop], np.ones(max(int(seconds * 2), 1)), mode="valid")
    start = int(np.argmax(energy)) * hop if energy.size else 0
    span = int(rate * seconds)
    clip_a, clip_b = audio_a[start:start + span], audio_b[start:start + span]
    rms_a, rms_b = float(np.sqrt(np.mean(np.square(clip_a)))) or 1e-9, float(np.sqrt(np.mean(np.square(clip_b)))) or 1e-9
    clip_b = clip_b * (rms_a / rms_b)
    peak = max(float(np.max(np.abs(clip_a))) if clip_a.size else 0.0, float(np.max(np.abs(clip_b))) if clip_b.size else 0.0) or 1.0
    return (clip_a / peak * 0.5).astype("float32"), (clip_b / peak * 0.5).astype("float32"), rate


class Judge:
    def __init__(self, client: MuseSpark | None = None):
        self.client = client or MuseSpark()

    def hear(self, a: Path, b: Path, *, job: str, what: str, retried: bool = False) -> dict:
        """Spark 1.2 on two matched clips: what differs, in the engineer's words and in plain words, and whether it
        helps, hurts or is nothing. Unreadable comes back as unknown, never as a verdict; an answer too thin to be a
        hearing (run 39, 2026-11-03: "no audio?") is asked once more, then counts as unknown."""
        clip_a, clip_b, rate = matched_clips(a, b)
        from hiremarco.studio import aloud

        aloud.play(np.concatenate([clip_a, clip_b]), rate)   # the room hears the pair as the ears get it, beside the call
        question = f"Two clips of the same part of the song: first {what[0]}, then {what[1]}. What differs, and does it help?"
        gate.check_model_call(TENANT, model=EARS, system=EAR_INSTRUCTIONS, prompt=question, joblog=self.client.joblog)
        content = [{"type": "text", "text": question}]
        for clip in (clip_a, clip_b):
            wav = base64.b64encode(take_wav(clip, rate)).decode()
            content.append({"type": "input_audio", "input_audio": {"data": wav, "format": "wav"}})
        reply = self.client.chat(
            [{"role": "developer", "content": EAR_INSTRUCTIONS}, {"role": "user", "content": content}],
            job=job, model=EARS, max_completion_tokens=2000, summarize=_ear_line,
            response_format={"type": "json_schema", "json_schema": {"name": "ears", "schema": EAR_SCHEMA, "strict": True}})
        try:
            data = json.loads(reply.text)
            heard = {"hears": str(data.get("hears", "")).strip(), "note": str(data.get("note", "")).strip(),
                     "difference": str(data.get("difference", "")).strip() or "unknown"}
        except ValueError:
            heard = {"hears": "", "note": "", "difference": "unknown"}
        if len(heard["hears"].split()) < 4:
            if not retried:
                return self.hear(a, b, job=job, what=what, retried=True)
            return {"hears": "", "note": "", "difference": "unknown"}
        return heard

    def decide(self, job: str, choices: tuple[str, ...], *, rule: str, numbers: dict, heard: dict | None = None) -> Call:
        """Wonder on one decision: the rule, the numbers and what the ears heard in, one of the choices out."""
        payload = {"rule": rule, "choices": list(choices), "numbers": numbers, "heard": heard or {}}
        prompt = json.dumps(payload)
        gate.check_model_call(TENANT, model=BRAIN, system=BRAIN_INSTRUCTIONS, prompt=prompt, joblog=self.client.joblog)
        reply = self.client.ask(prompt, developer=BRAIN_INSTRUCTIONS, job=job, model=BRAIN, max_completion_tokens=TOKENS,
                                reasoning_effort=EFFORT, summarize=_call_line,
                                response_format={"type": "json_schema",
                                                 "json_schema": {"name": job, "schema": _brain_schema(choices), "strict": True}})
        if reply.finish_reason == "length":
            raise RuntimeError(f"the {job} ran out of room before it answered")
        try:
            data = json.loads(reply.text)
        except ValueError as exc:
            raise RuntimeError(f"the {job} came back unreadable") from exc
        decision = str(data.get("decision", "")).strip()
        if decision not in choices:
            raise RuntimeError(f"the {job} answered {decision!r}, not one of {', '.join(choices)}")
        return Call(decision, str(data.get("why", "")).strip(), str(data.get("plain", "")).strip())

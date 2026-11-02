"""What Marco learns about the artist from a real session: his sound, part by part.

The Owner asked (2026-11-02) what Marco learns by auditing a session of his:
how he likes his lead, his harmonies, his ad-libs, his effects. Marco reads
it from the session itself, not from a questionnaire: for one track of each
part he selects the track, reads the signal flow it rides (the Mixer's Single
view: track, its stacks and buses, the output), and reads every insert with
its settings in the plug-in's own units; he adds the audit of the mix print
and what the hearing stack hears. The deepest brain then writes the profile
with its evidence, and the profile is kept beside the song and in Marco's
taste notes for the next session.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hiremarco import gate
from hiremarco.meta.client import MuseSpark

SCRIPTS = Path(__file__).parent / "scripts"
TENANT = "owner"
MODEL = "muse-wonder-1.0"
EFFORT = "high"
TOKENS = 32000
THINK_TIMEOUT = 900.0

INSTRUCTIONS = (
    "You are Marco, the house engineer, reading one artist's real session to learn his sound. You get, for one "
    "track of each part (lead, double, harmony, background vocal, ad-lib, effect, the vocal bus, the output), the "
    "signal flow it rides, every insert in order with its settings in the plug-in's own units, plus the measured "
    "audit of the mix print and what a listener hears. Write what you learned, part by part: how he likes his lead "
    "to sit (tuning, dynamics, tone, de-essing, space, width), his doubles and harmonies, his background vocals, "
    "his ad-libs, his effects, his bus and output, and the mix as a whole. Every claim names the plug-in and the "
    "setting or the measurement it rests on; where a chain is read but a setting is a bare number with no unit, "
    "say what it likely means and label it as inferred. Then list the habits worth keeping as his signature, the "
    "ones that cost him clarity or loudness with the number that shows it, and three questions you would ask him. "
    "Plain words, as one engineer to another; no jargon he would not use himself."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "parts": {"type": "array", "items": {"type": "object", "properties": {
            "part": {"type": "string"}, "learned": {"type": "string"}, "evidence": {"type": "string"}},
            "required": ["part", "learned", "evidence"], "additionalProperties": False}},
        "signature": {"type": "array", "items": {"type": "string"}},
        "costs": {"type": "array", "items": {"type": "string"}},
        "questions": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["parts", "signature", "costs", "questions", "summary"],
    "additionalProperties": False,
}


@dataclass
class PartRead:
    part: str
    number: int
    name: str
    flow: list[str] = field(default_factory=list)          # the strips in the Mixer's Single view, track to output
    inserts: list[dict] = field(default_factory=list)      # [{"slot", "plugin", "bypassed", "settings": {control: shown}}]
    error: str = ""


@dataclass
class Profile:
    parts: list[dict]
    signature: list[str]
    costs: list[str]
    questions: list[str]
    summary: str

    def as_dict(self) -> dict:
        return asdict(self)

    def markdown(self, title: str) -> str:
        out = [f"# {title}", "", self.summary, "", "## Part by part", ""]
        for p in self.parts:
            out += [f"**{p['part']}.** {p['learned']}", f"Evidence: {p['evidence']}", ""]
        out += ["## Worth keeping as his signature", ""] + [f"- {s}" for s in self.signature]
        out += ["", "## What costs him, with the number", ""] + [f"- {c}" for c in self.costs]
        out += ["", "## Three questions for him", ""] + [f"- {q}" for q in self.questions]
        return "\n".join(out).replace("—", ",").replace("–", " to ") + "\n"


def _flow() -> list[str]:
    done = subprocess.run(["osascript", "-l", "JavaScript", str(SCRIPTS / "mixer_single.js")], capture_output=True,
                          text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:] or f"osascript exit {done.returncode}")
    return [str(n) for n in json.loads(done.stdout or "[]")]


def read_parts(parts: list[tuple[str, int, str]], *, select: Callable[[int], None], flow: Callable[[], list[str]] = _flow,
               chain: Callable[[], list[dict]], log: Callable[[str], None] = print) -> list[PartRead]:
    """One read per part: the track selected by its number, its signal flow and every insert with its settings.
    A part whose read fails is kept with its error, so one stuck window does not lose the rest."""
    out = []
    for part, number, name in parts:
        row = PartRead(part, number, name)
        try:
            select(number)
            row.flow = flow()
            row.inserts = chain()
            log(f"   {part}: {name} rides {' > '.join(row.flow)}; {len(row.inserts)} inserts")
        except Exception as exc:   # noqa: BLE001
            row.error = f"{type(exc).__name__}: {str(exc)[-160:]}"
            log(f"   {part}: {name}: {row.error}")
        out.append(row)
    return out


def chain_for_model(chain) -> list[dict]:
    """The selected track's inserts as the brain reads them: the plug-in, bypassed or not, each movable control
    as the plug-in shows it (units) with percent of range for the rest."""
    rows = []
    for s in chain.slots:
        row = {"slot": s.number, "plugin": s.name, "bypassed": s.bypassed, "settings": {}}
        if s.state is not None:
            view = s.state.for_model()
            shown = view.get("in_units", {})
            row["settings"] = {n: shown.get(n, f"{v:g} percent") for n, v in view.get("parameters", {}).items()}
            row["fixed"] = view.get("fixed", {})
        rows.append(row)
    return rows


def profile(reads: list[PartRead], audit: dict | None, hearing: dict | None, *, artist: str = "the artist",
            client: MuseSpark | None = None) -> Profile:
    if not any(r.inserts or r.flow for r in reads):
        # with nothing read the brain answered placeholders (live 2026-11-02: "bye", "hello"); a profile needs reads
        raise RuntimeError("no part was read from Logic; nothing to learn from: " + "; ".join(r.error for r in reads if r.error)[:300])
    client = client or MuseSpark(timeout=THINK_TIMEOUT)
    from hiremarco.mix import listen as listening

    payload = {"artist": artist, "parts": [asdict(r) for r in reads], "audit_of_the_mix_print": audit,
               "hearing": listening.for_model(hearing)}
    prompt = json.dumps(payload, default=str)
    gate.check_model_call(TENANT, model=MODEL, system=INSTRUCTIONS, prompt=prompt, joblog=client.joblog)
    reply = client.ask(prompt, developer=INSTRUCTIONS, job="taste", model=MODEL, max_completion_tokens=TOKENS,
                       reasoning_effort=EFFORT,
                       response_format={"type": "json_schema", "json_schema": {"name": "taste", "schema": SCHEMA,
                                                                               "strict": True}})
    if reply.finish_reason == "length":
        raise RuntimeError("the taste profile ran out of room before it finished")
    try:
        data = json.loads(reply.text)
    except ValueError as exc:
        raise RuntimeError("the taste profile came back unreadable") from exc
    return Profile([{"part": str(p.get("part", "")), "learned": str(p.get("learned", "")), "evidence": str(p.get("evidence", ""))}
                    for p in data.get("parts", [])],
                   [str(s) for s in data.get("signature", [])], [str(c) for c in data.get("costs", [])],
                   [str(q) for q in data.get("questions", [])], str(data.get("summary", "")).strip())


def run_live(parts: list[tuple[str, int, str]], mix_print: Path | None, *, artist: str, out: Path,
             log: Callable[[str], None] = print, conn=None) -> tuple[Profile, Path]:
    """The whole job with Marco's real hands: the reads in Logic, the audit and the ears on the print, the profile
    written beside the song and into Marco's taste notes."""
    from hiremarco.mix import audit as auditing
    from hiremarco.mix import listen as listening
    from hiremarco.master.plan import audit_for_model
    from hiremarco.studio.beat_in import BeatLoader
    from hiremarco.studio.chain import Channel

    loader, channel = BeatLoader(conn=conn), Channel(conn=conn)

    def select(number: int) -> None:
        subprocess.run(["osascript", "-e", 'tell application "Logic Pro" to activate'], check=False, timeout=10)
        time.sleep(0.3)
        subprocess.run(["osascript", "-e", 'tell application "System Events" to tell process "Logic Pro"\n'
                        'repeat with w in (every window)\nif (name of w) ends with " - Tracks" then perform action '
                        '"AXRaise" of w\nend repeat\nend tell'], check=False, timeout=15)
        time.sleep(0.4)
        loader.select(f"Track {number}")

    log("1. the parts, read from Logic")
    reads = read_parts(parts, select=select, chain=lambda: chain_for_model(channel.read()), log=log)
    audit = hearing = None
    if mix_print is not None and Path(mix_print).exists():
        log("2. the mix print")
        a = auditing.audit_file(Path(mix_print))
        audit = audit_for_model(a, None)
        for line in auditing.summary(a, None).splitlines():
            log(f"   {line}")
        hearing = listening.listen(Path(mix_print))
        for line in listening.highlights(hearing):
            log(f"   {line}")
    log("3. what Marco learned")
    prof = profile(reads, audit, hearing, artist=artist)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    path = out / f"what Marco learned {stamp}.md"
    path.write_text(prof.markdown(f"What Marco learned about {artist}'s sound ({stamp})"))
    (out / f"taste reads {stamp}.json").write_text(json.dumps({"parts": [asdict(r) for r in reads], "audit": audit,
                                                               "hearing": hearing, "profile": prof.as_dict()},
                                                              indent=1, default=str))
    return prof, path

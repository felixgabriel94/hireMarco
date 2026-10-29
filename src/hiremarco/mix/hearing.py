"""The mix hearing: Marco reads the whole session first, talks it through, asks, and keeps the answers.

The artist is the CEO; Marco is the COO. On a developed session he does a
full read (the session view) before anything moves, says what he hears in a
few sentences, and asks how the artist feels about it. What comes back
("the lead's right, the harmonies need to sit differently, the 808 should
hit harder") becomes the song's **preferences**: tracks to keep as they are,
wishes per track, and a reference sound. They are saved with the song and
every later pass plans inside them; a move on a kept track is dropped
before it reaches Logic.

A reference by name ("I want to sound like Travis Scott") becomes a
**signature**: what Muse Wonder knows of that sound as chain choices and
targets, labelled as his understanding, never a copy. A reference file is
measured with Marco's ears and its numbers ride along, so the proof is
measured even when the direction is knowledge.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hiremarco import config, gate
from hiremarco.meta.client import MuseSpark
from hiremarco.mix.ears import EarsReport, measure
from hiremarco.mix.session import SessionView, build

MODEL = "muse-wonder-1.0"
TENANT = "owner"

HEARING_INSTRUCTIONS = (
    "You are Marco, the mix engineer, and the artist is in charge. You have just read their whole session: each "
    "track's role and reading, the fights between tracks, what is masked, how each track sits against its "
    "role's target, and the mix's headroom. Say what you hear in three or four plain spoken sentences an artist "
    "would follow: what is working, the two or three things that stand out, nothing about what you would do "
    "yet. Then ask one open question about how they feel about it right now. No lists, no numbers unless one "
    "matters, no jargon the artist did not use."
)
PREFERENCE_INSTRUCTIONS = (
    "The artist just answered how they feel about their mix. Turn it into their preferences, exactly as said, "
    "using only track names from the session list. keep: tracks they are happy with, to leave alone. wishes: "
    "for each track they want changed, what they want in their own words. reference: an artist, record or "
    "sound they named as the target, else empty. overall: one sentence of the general direction, else empty. "
    "Never invent a wish they did not say."
)
SIGNATURE_INSTRUCTIONS = (
    "The artist named a reference sound. Describe its signature as a mix engineer would brief an assistant: "
    "vocal (tuning character, air, compression, doubles and ad-libs, space), low end, drums, overall tone and "
    "loudness feel, and the three moves that get closest with a typical vocal chain. Plain language, specific, "
    "and honest about what is a generalization. This is your understanding of a style, not instructions to copy "
    "a recording."
)
PREFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "keep": {"type": "array", "items": {"type": "string"}},
        "wishes": {"type": "array", "items": {"type": "object", "properties": {
            "track": {"type": "string"}, "wish": {"type": "string"}},
            "required": ["track", "wish"], "additionalProperties": False}},
        "reference": {"type": "string"},
        "overall": {"type": "string"},
    },
    "required": ["keep", "wishes", "reference", "overall"],
    "additionalProperties": False,
}


@dataclass
class Preferences:
    song: str
    keep: list[str] = field(default_factory=list)
    wishes: dict[str, str] = field(default_factory=dict)
    reference: str = ""
    overall: str = ""
    signature: str = ""                    # Marco's understanding of the reference, from the model
    reference_numbers: dict = field(default_factory=dict)  # measured from a reference file, when given
    heard: str = ""                        # what Marco said at the hearing
    updated: str = ""

    def guardrails(self) -> dict:
        return {"keep_as_is": self.keep, "wishes": self.wishes, "reference": self.reference,
                "signature": self.signature, "reference_numbers": self.reference_numbers, "overall": self.overall}


def prefs_path(song: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", song.lower()).strip("-") or "song"
    return Path(config.STATE_DIR) / "prefs" / f"{slug}.json"


def load(song: str) -> Preferences:
    path = prefs_path(song)
    if not path.exists():
        return Preferences(song)
    data = json.loads(path.read_text())
    return Preferences(**{k: v for k, v in data.items() if k in Preferences.__dataclass_fields__})


def save(prefs: Preferences) -> Path:
    prefs.updated = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    path = prefs_path(prefs.song)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(prefs), indent=1))
    return path


def _ask(client: MuseSpark, instructions: str, prompt: str, *, job: str, schema: dict | None = None,
         tokens: int = 1500) -> str:
    gate.check_model_call(TENANT, model=MODEL, system=instructions, prompt=prompt, joblog=client.joblog)
    kwargs = {}
    if schema is not None:
        kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": job, "schema": schema, "strict": True}}
    reply = client.ask(prompt, developer=instructions, job=job, model=MODEL, max_completion_tokens=tokens,
                       reasoning_effort="low", **kwargs)
    if reply.finish_reason == "length":
        raise RuntimeError(f"the {job} ran out of room before it finished")
    return reply.text


def hear(report: EarsReport, song: str, *, client: MuseSpark | None = None) -> tuple[SessionView, Preferences]:
    """The full read, then Marco's spoken take and his question. Nothing moves."""
    view = build(report)
    client = client or MuseSpark()
    said = _ask(client, HEARING_INSTRUCTIONS, json.dumps(view.as_dict()), job="mix_hearing").strip()
    prefs = load(song)
    prefs.heard = said
    save(prefs)
    return view, prefs


def answer(song: str, words: str, track_names: list[str], *, client: MuseSpark | None = None) -> Preferences:
    """The artist's answer becomes the song's preferences, merged with what was already kept."""
    client = client or MuseSpark()
    prompt = json.dumps({"tracks": track_names, "artist_said": words})
    data = json.loads(_ask(client, PREFERENCE_INSTRUCTIONS, prompt, job="mix_preferences",
                           schema=PREFERENCE_SCHEMA, tokens=800))
    prefs = load(song)
    known = set(track_names)
    for name in data.get("keep", []):
        if name in known and name not in prefs.keep:
            prefs.keep.append(name)
    for item in data.get("wishes", []):
        track = str(item.get("track", ""))
        if track in known and item.get("wish"):
            prefs.wishes[track] = str(item["wish"]).strip()
            if track in prefs.keep:
                prefs.keep.remove(track)  # a new wish outranks an older keep
    if data.get("reference"):
        prefs.reference = str(data["reference"]).strip()
    if data.get("overall"):
        prefs.overall = str(data["overall"]).strip()
    save(prefs)
    return prefs


def reference(song: str, name: str, *, reference_file: Path | None = None,
              client: MuseSpark | None = None) -> Preferences:
    """A named sound becomes a signature; a file, when given, becomes measured numbers."""
    client = client or MuseSpark()
    prefs = load(song)
    prefs.reference = name.strip()
    prefs.signature = _ask(client, SIGNATURE_INSTRUCTIONS, json.dumps({"reference": name}),
                           job="mix_signature", tokens=1200).strip()
    if reference_file is not None:
        import soundfile as sf

        audio, rate = sf.read(reference_file, dtype="float32", always_2d=False)
        r = measure(audio, rate, Path(reference_file).stem)
        prefs.reference_numbers = {"lufs": r.lufs, "true_peak_db": r.true_peak_db, "crest_db": r.crest_db,
                                   "bands_db": r.bands_db, "low_mono": r.low_mono, "correlation": r.correlation}
    save(prefs)
    return prefs

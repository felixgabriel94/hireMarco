"""Organizing a session the way the house does: Marco surveys every track and region, decides, and renames.

The Owner records fast and labels later (2026-11-02: "this session is a good
example of how I usually record"); a session arrives with stacks named by
feel, a dozen tracks called after the channel strip preset, and leads for
two sections on one track. Marco reads the whole layout (``survey``: every
header, every region with its bar and length, the stacks), hands it with the
house standard to the deepest brain (``propose``) and gets back the sections
he inferred, a name and color for every track with the reason in bars, and
what he would not touch. Nothing moves until the Owner says go; then
``apply`` renames track by track through the Tracks hands and reads each
name back. Colors and track order wait on their hands being mapped.
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
EFFORT = "high"   # at max the brain spent 38000 tokens and answered an empty plan (live 2026-11-02); high answers
TOKENS = 64000   # the plan reasons through forty tracks at max effort; 32000 ran out live (2026-11-02)
THINK_TIMEOUT = 900.0

STANDARD = {
    "names": "Plain words, capitalized, the role first and the section second when a track serves one section: "
             "Beat, Lead Vox, Lead Intro, Lead V1, Lead Chorus, Double V1, Harmony Chorus 1, BGV Chorus 1, "
             "Ad-lib Chorus 1, Robo 1, Reference. Numbered from 1 within a kind. No channel strip names, no "
             "trailing punctuation, no all caps. A stack is named for what it sums: LEAD, DOUBLES, HARMONIES, BGVS, "
             "AD-LIBS, FX, in caps so a stack reads apart from a track.",
    "order": "Beat first, then the vocal stacks in this order: LEAD, DOUBLES, HARMONIES, BGVS, AD-LIBS, FX. Inside a "
             "stack, by section in song order.",
    "colors": {"beat": "orange", "lead": "blue", "double": "blue", "harmony": "light blue", "bgv": "purple",
               "ad-lib": "teal", "fx": "green", "reference": "gray", "empty": "gray"},
    "rules": [
        "A section kind repeated through the song (every chorus, every verse) is one role for naming: a track that "
        "sings all the choruses is Lead Chorus, not a split. A track is flagged for a split only when it carries "
        "two different kinds of section (an intro and a verse), with the bars (Marco does not move regions in this "
        "pass).",
        "Tracks in one stack that hold the same regions in the same bars are layers of a stacked part (BGV layers, "
        "harmony layers), each its own performance, never duplicates: number them 1 to N in order (BGV Chorus 1, "
        "BGV Chorus 2). Flag only a layer whose regions differ from its siblings', saying how.",
        "An empty plain track is flagged, not deleted (a delete needs the Owner's line). An open stack shows no "
        "regions of its own; its children follow it in the list, so it is never empty by that reading.",
        "A stack that already carries a house-style name keeps it; one that does not is renamed in the house style "
        "for what it sums (the stack of every vocal stack is VOCALS).",
        "Sections are inferred from where the leads and the doubles sit; name them Intro, V1, Chorus 1, V2, Chorus 2, "
        "Bridge, Chorus 3, Outro as the bars suggest, each with its start and end bar.",
    ],
}

INSTRUCTIONS = (
    "You are Marco, the house engineer, organizing the artist's recording session before mixing. You get the "
    "session's layout as read from Logic: every track in order with its number, current name, whether it is a "
    "stack (open or closed) and its regions as [name, start bar, length in bars]. A closed stack shows its "
    "children's regions on its own lane and hides the children. You also get the house standard. Decide: the "
    "sections of the song with their bars; for every track its new name, its color and its role; and what you "
    "flag rather than change. Every reason names bars from the layout. Keep names short and consistent; a stack "
    "keeps its stack name style. Give every track exactly one entry, in the order given, including the ones you "
    "leave as they are (then proposed equals current and the reason says why). Then two short sentences for the "
    "artist on what you did and what you want him to look at."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "start_bar": {"type": "number"}, "end_bar": {"type": "number"},
            "evidence": {"type": "string"}},
            "required": ["name", "start_bar", "end_bar", "evidence"], "additionalProperties": False}},
        "tracks": {"type": "array", "items": {"type": "object", "properties": {
            "number": {"type": "integer"}, "current": {"type": "string"}, "proposed": {"type": "string"},
            "color": {"type": "string"}, "role": {"type": "string"},
            "flag": {"type": "string", "description": "empty, or what the Owner should look at (split, duplicate, empty)"},
            "reason": {"type": "string"}},
            "required": ["number", "current", "proposed", "color", "role", "flag", "reason"], "additionalProperties": False}},
        "said": {"type": "string"},
    },
    "required": ["sections", "tracks", "said"],
    "additionalProperties": False,
}


@dataclass
class Region:
    name: str
    bar: float
    bars: float


@dataclass
class Track:
    number: int
    name: str
    stack: str              # "open", "closed" or "" for a plain track
    regions: list[Region] = field(default_factory=list)


@dataclass
class Survey:
    tracks: list[Track]
    px_per_bar: float
    bar1_x: float

    def as_dict(self) -> dict:
        return asdict(self)

    def compact(self) -> list[dict]:
        """What the brain reads: one row per track, regions rounded to a tenth of a bar; a track with many
        regions shows them as spans (a gap over two bars starts a new span), so thirteen BGV tracks with twelve
        regions each do not drown the plan (live 2026-11-02: the first plan ran out of room)."""
        rows = []
        for t in self.tracks:
            row = {"number": t.number, "name": t.name, "stack": t.stack or "no", "regions": len(t.regions)}
            if len(t.regions) <= 6:
                row["each"] = [[r.name, round(r.bar, 1), round(r.bars, 1)] for r in t.regions]
            else:
                row["spans"] = [[round(a, 1), round(b, 1)] for a, b in spans(t.regions)]
                row["names"] = sorted({r.name.split("#")[0].strip() for r in t.regions})
            rows.append(row)
        return rows


def spans(regions: list[Region], gap: float = 2.0) -> list[tuple[float, float]]:
    """Regions merged into the stretches they cover, bar to bar."""
    out: list[list[float]] = []
    for r in sorted(regions, key=lambda r: r.bar):
        if out and r.bar - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], r.bar + r.bars)
        else:
            out.append([r.bar, r.bar + r.bars])
    return [(a, b) for a, b in out]


def _survey_js() -> dict:
    done = subprocess.run(["osascript", "-l", "JavaScript", str(SCRIPTS / "survey.js")], capture_output=True,
                          text=True, timeout=400)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:] or f"osascript exit {done.returncode}")
    return json.loads(done.stdout)


def parse_survey(raw: dict, raw_at_other_bar: dict, bar_a: int, bar_b: int) -> Survey:
    """Two reads of the layout with the playhead at two bars give the scale; the first read's regions are kept."""
    xa, xb = raw.get("thumb_x"), raw_at_other_bar.get("thumb_x")
    if xa is None or xb is None or xb == xa:
        raise RuntimeError("the playhead thumb was not read at both bars; the scale is unknown")
    ppb = (xb - xa) / (bar_b - bar_a)
    x1 = xa - (bar_a - 1) * ppb
    lanes = {lane["desc"]: lane for lane in raw.get("lanes", [])}
    tracks = []
    for h in raw.get("headers", []):
        desc = str(h.get("desc", ""))
        if not desc.startswith("Track "):
            continue
        number = int(desc.split()[1])
        name = desc.split("“", 1)[-1].split("”", 1)[0] if "“" in desc else desc
        tri = h.get("triangle")
        stack = "" if tri in (None, "") else ("open" if str(tri) == "1" else "closed")
        regions = [Region(str(r[0]), 1 + (float(r[1]) - x1) / ppb, float(r[2]) / ppb)
                   for r in lanes.get(desc, {}).get("regions", [])]
        regions.sort(key=lambda r: r.bar)
        tracks.append(Track(number, name, stack, regions))
    return Survey(tracks, ppb, x1)


def survey(*, read: Callable[[], dict] = _survey_js, go: Callable[[int], object] | None = None,
           bars: tuple[int, int] = (1, 65)) -> Survey:
    """The session's layout from Logic: the playhead jumped to two bars so screen x reads as bars."""
    if go is None:
        from hiremarco.studio.arrange import _run

        go = lambda bar: _run(["goto", str(bar)])   # noqa: E731
    go(bars[0])
    first = read()
    go(bars[1])
    second = read()
    return parse_survey(first, second, bars[0], bars[1])


def nesting(layout: Survey) -> list[str]:
    """What holds what, as far as the list order shows it: a stack's members are the tracks after it up to the next
    stack header; a stack that opens right after another open stack sits inside it (the vocal stack holding the
    part stacks, as the Mixer's signal flow showed live 2026-11-02)."""
    lines, open_parent = [], None
    for i, t in enumerate(layout.tracks):
        if t.stack == "open":
            if open_parent is not None and i > 0 and layout.tracks[i - 1].stack == "open":
                lines.append(f"{t.name} (stack) is inside {open_parent.name} (stack)")
            else:
                open_parent = t
                lines.append(f"{t.name} (stack) holds the tracks after it up to the next stack")
        elif t.stack == "closed":
            lines.append(f"{t.name} (stack, closed) hides its member tracks; its lane shows their regions")
    return lines


def keep_reply(text: str) -> Path | None:
    """The brain's raw answer kept on disk, so an empty or odd plan can be read after the fact."""
    try:
        from hiremarco import config

        folder = Path(config.STATE_DIR) / "capture"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{time.strftime('%Y-%m-%dT%H-%M-%S')}_organize.json"
        path.write_text(text)
        return path
    except Exception:
        return None


@dataclass
class Plan:
    sections: list[dict]
    tracks: list[dict]
    said: str

    def as_dict(self) -> dict:
        return asdict(self)

    def changes(self) -> list[dict]:
        return [t for t in self.tracks if t["proposed"] != t["current"]]

    def table(self) -> str:
        lines = ["| # | now | proposed | color | role | flag | why |", "|---|---|---|---|---|---|---|"]
        for t in self.tracks:
            lines.append(f"| {t['number']} | {t['current']} | {t['proposed']} | {t['color']} | {t['role']} | "
                         f"{t['flag']} | {t['reason']} |")
        return "\n".join(lines)


def propose(layout: Survey, *, client: MuseSpark | None = None, direction: str = "", tokens: int = TOKENS) -> Plan:
    client = client or MuseSpark(timeout=THINK_TIMEOUT)
    payload = {"direction": direction, "standard": STANDARD, "session": layout.compact(), "nesting": nesting(layout)}
    reply = None
    for note in ("", "the room is short: one sentence of reason per track, the bars and the role, nothing more"):
        prompt = json.dumps({**payload, **({"note": note} if note else {})})
        gate.check_model_call(TENANT, model=MODEL, system=INSTRUCTIONS, prompt=prompt, joblog=client.joblog)
        reply = client.ask(prompt, developer=INSTRUCTIONS, job="organize", model=MODEL, max_completion_tokens=tokens,
                           reasoning_effort=EFFORT,
                           response_format={"type": "json_schema", "json_schema": {"name": "organize", "schema": SCHEMA,
                                                                                   "strict": True}})
        if reply.finish_reason != "length":
            break
    if reply is None or reply.finish_reason == "length":
        raise RuntimeError("the organizing plan ran out of room before it finished, twice")
    keep_reply(reply.text)
    try:
        data = json.loads(reply.text)
    except ValueError as exc:
        raise RuntimeError("the organizing plan came back unreadable") from exc
    if not data.get("tracks"):
        raise RuntimeError("the organizing plan named no track (the raw reply is in the capture folder)")
    known = {t.number: t.name for t in layout.tracks}
    tracks = []
    for row in data.get("tracks", []):
        number = int(row.get("number", 0))
        if number not in known:
            continue
        tracks.append({"number": number, "current": known[number], "proposed": str(row.get("proposed", "")).strip()[:60]
                       or known[number], "color": str(row.get("color", "")).strip(), "role": str(row.get("role", "")).strip(),
                       "flag": str(row.get("flag", "")).strip(), "reason": str(row.get("reason", "")).strip()})
    answered = {t["number"] for t in tracks}
    for number, name in known.items():   # a track the brain skipped stays as it is, and says so
        if number not in answered:
            tracks.append({"number": number, "current": name, "proposed": name, "color": "", "role": "",
                           "flag": "not answered", "reason": "the plan gave no entry for this track"})
    tracks.sort(key=lambda t: [x.number for x in layout.tracks].index(t["number"]))
    return Plan([{"name": str(s.get("name", "")), "start_bar": float(s.get("start_bar", 0)),
                  "end_bar": float(s.get("end_bar", 0)), "evidence": str(s.get("evidence", ""))}
                 for s in data.get("sections", [])], tracks, str(data.get("said", "")).strip())


def apply(plan: Plan, *, select: Callable[[str, int], None], rename: Callable[[str], str],
          read_names: Callable[[], dict[int, str]], log: Callable[[str], None] = print) -> list[tuple[int, str, str]]:
    """Every proposed rename made on the Owner's go: the track selected by its current name and number, renamed,
    and the whole list read back once at the end. Returns (number, before, after) for each change."""
    done = []
    for t in plan.changes():
        select(t["current"], t["number"])
        said = rename(t["proposed"])
        log(f"   {t['number']} {t['current']!r} -> {t['proposed']!r}: {said}")
        done.append((t["number"], t["current"], t["proposed"]))
    after = read_names()
    off = [(n, b, a) for n, b, a in done if after.get(n) != a]
    if off:
        raise RuntimeError("renames did not take: " + ", ".join(f"{n} reads {after.get(n)!r}" for n, _, _ in off))
    return done


def live_apply(plan: Plan, *, log: Callable[[str], None] = print, conn=None) -> list[tuple[int, str, str]]:
    """The plan's renames made in Logic with Marco's real hands: each track selected by its number (names repeat),
    renamed through the track's name editor, and the whole list read back at the end."""
    import subprocess

    from hiremarco.studio.beat_in import BeatLoader
    from hiremarco.studio.tracks import Tracks, parse_list

    loader, hands = BeatLoader(conn=conn), Tracks(conn=conn)

    def select(name: str, number: int) -> None:
        # the Tracks window to the front: the tall Mixer window sits over the headers (live 2026-11-02)
        subprocess.run(["osascript", "-e", 'tell application "Logic Pro" to activate'], check=False, timeout=10)
        time.sleep(0.3)
        subprocess.run(["osascript", "-e", 'tell application "System Events" to tell process "Logic Pro"\n'
                        'repeat with w in (every window)\nif (name of w) ends with " - Tracks" then perform action '
                        '"AXRaise" of w\nend repeat\nend tell'], check=False, timeout=15)
        time.sleep(0.4)
        loader.select(f"Track {number}")

    def read_names() -> dict[int, str]:
        # keyed by Logic's own track number ("Track 14"), the number the survey and the plan use; the list's row
        # index is not it once a track is hidden or inside a closed stack (live 2026-11-02: every name read one off)
        return names_by_track_number(hands.run(["list"]))

    return apply(plan, select=select, rename=hands.rename, read_names=read_names, log=log)


def open_stacks() -> dict:
    """Every closed stack opened before the survey, so the tracks inside are seen and named (live 2026-11-04)."""
    done = subprocess.run(["osascript", "-l", "JavaScript", str(SCRIPTS / "open_stacks.js")], capture_output=True,
                          text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:] or f"osascript exit {done.returncode}")
    return json.loads(done.stdout)


def organize_now(*, direction: str = "", log: Callable[[str], None] = print, conn=None,
                 survey_of=None, propose_for=None, apply_plan=None, unstack=None) -> str:
    """Asked aloud or by text, the asking is the go (Owner 2026-11-04: "organize my session"): every stack opened,
    survey, plan, rename, read back. Only on the copy Marco opened; the booth checks that. One line of what was
    done; a stack that would not open is said, never hidden behind "labeled" (live 2026-11-04)."""
    stacks = {"opened": 0, "still_closed": 0}
    if unstack is not None or survey_of is None:
        try:
            stacks = (unstack or open_stacks)()
            log(f"   stacks opened: {stacks.get('opened', 0)}, still closed: {stacks.get('still_closed', 0)}")
        except Exception as exc:
            log(f"   (stacks not opened: {type(exc).__name__}: {str(exc)[-120:]})")
            stacks = {"opened": 0, "still_closed": -1}
    layout = (survey_of or survey)()
    closed = sum(1 for t in layout.tracks if getattr(t, "stack", "") == "closed")
    plan = (propose_for or (lambda l: propose(l, direction=direction)))(layout)
    done = (apply_plan or (lambda p: live_apply(p, log=log, conn=conn)))(plan)
    line = f"{len(done)} of {len(layout.tracks)} tracks renamed and read back"
    return line + (f"; {closed} stack{'s' if closed != 1 else ''} stayed closed" if closed else "")


def names_by_track_number(listing: str) -> dict[int, str]:
    """'3<TAB>Track 6 “intro lead”<TAB>19' lines read as {6: "intro lead"}: Logic's track number, not the row."""
    import re

    out = {}
    for line in listing.splitlines():
        m = re.match(r"\s*\d+\t(?:Track (\d+))?\s*[\u201c\"](.*?)[\u201d\"]", line)
        if m and m.group(1):
            out[int(m.group(1))] = m.group(2)
    return out


def load_plan(path: Path) -> Plan:
    data = json.loads(Path(path).read_text())
    return Plan(list(data.get("sections", [])), list(data.get("tracks", [])), str(data.get("said", "")))

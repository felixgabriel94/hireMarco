"""The master job, end to end: audit, plan, chain, print, read back, deliver.

Owner 2026-11-02: Marco mixes, masters, exports and texts the WAV. The job
prints the mix as it stands (his chain bypassed, 32-bit float), audits it
against the references the artist owns, asks the deepest brain what the track
needs, puts that chain on the Stereo Out, reads every control, sets them with
their reasons, prints the master (24-bit), audits that too, and if the print
misses its loudness target or its ceiling by more than a tolerance, adjusts
once and prints again. Both files and the audit go wherever ``deliver`` points
(the Owner's WhatsApp from the server, the terminal from the CLI). Every
number in the record was measured on a file; a step that cannot be verified
stops the job and says so.
"""

from __future__ import annotations

import json
import re
import os
import math
import time

import soundfile as sf
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from hiremarco import events
from hiremarco.master import plan as planning
from hiremarco.master import roles
from hiremarco.master.judge import BENCH_RULE, CHECK_RULE, LADDER_RULE, Judge
from hiremarco.master.rules import PURPOSES
from hiremarco.mix import audit as auditing
from hiremarco.mix import listen as listening
from hiremarco.mix import verify as verifying
from hiremarco.studio import bounce as bouncing
from hiremarco.studio.chain import Channel
from hiremarco.studio.stereo_out import StereoOut, same_plugin

LUFS_TOLERANCE = 1.0      # LU: a print this close to its target is done
CEILING_TOLERANCE = 0.1   # dB over the true-peak ceiling that still passes (the meter's own rounding)
LOCK_FRESH_S = 2 * 3600   # a master lock older than this is a dead run's, not a running one
MAX_ROUNDS = 3   # a second pass under-asked the limiter by 3 dB (run 25, 2026-11-02); a third, told the exact figure, closes it


@dataclass
class Job:
    song: str
    end_bar: int
    bounces: Path
    purpose: str = "demo"
    direction: str = ""
    stock_only: bool = False
    references: Path | None = None
    today: str = field(default_factory=lambda: date.today().isoformat())
    bpm: float | None = None          # the song's tempo, for the pumping check (a ducker shows at the beat rate)
    check_range: tuple[int, int] | None = None   # the loudest eight bars of the mix print, once it is read
    budget_s: float = 45 * 60.0       # past this, no more tests or passes: Marco prints what he has and says so (Owner 2026-11-03)

    @property
    def bar_s(self) -> float | None:
        return 4 * 60.0 / self.bpm if self.bpm else None


@dataclass
class Result:
    mix: Path | None = None
    master: Path | None = None
    plan: planning.MasterPlan | None = None
    audit_mix: auditing.Audit | None = None
    audit_master: auditing.Audit | None = None
    settings: list[dict] = field(default_factory=list)
    rounds: int = 0
    stopped: str = ""
    record: Path | None = None
    dead: list[str] = field(default_factory=list)   # inserts that passed silence, left bypassed
    hearing: dict | None = None                     # the hearing stack on the mix print, when installed
    hearing_master: dict | None = None
    manifest: list[dict] = field(default_factory=list)   # every insert on the output: yours, planned or stray
    verdict: object | None = None                   # the master against the mix (mix.verify.Verdict)
    bench: list[dict] = field(default_factory=list)      # each insert with and without, measured; what earned its place
    ladder: dict | None = None                            # the loudness ladder on the loudest bars: steps, ceiling, what gave
    judged: list[dict] = field(default_factory=list)      # the ears and the brain on each finished print, against the goal
    meter: dict | None = None                             # the meter on screen against Marco's ears on the same stretch
    trimmed_s: float = 0.0                                # seconds of silent tail cut off the master

    @property
    def caption(self) -> str:
        if self.stopped:
            return f"Stopped: {self.stopped}"
        am, p = self.audit_master, self.plan
        if am is None or p is None:
            return "No master printed."
        verified = (self.verdict.text().splitlines()[0] if self.verdict is not None
                    else "not verified against the mix (no tempo to check the pumping)")
        if self.bench:
            kept = [b["name"] for b in self.bench if b["earned"]]
            gone = [b["name"] for b in self.bench if not b["earned"]]
            verified += (f". Each insert earned its place with and without it: kept {', '.join(kept) or 'none'}"
                         + (f"; taken off {', '.join(gone)}" if gone else ""))
        return (f"Master, {p.purpose}: {am.base.lufs} LUFS integrated, true peak {am.base.true_peak_db} dBTP, "
                f"loudness range {am.loudness_range} LU, {am.sample_rate} Hz {am.subtype}. "
                f"Target was {p.target_lufs} LUFS under {p.ceiling_dbtp} dBTP. {verified[0].upper() + verified[1:]}.")


def end_bar_for(seconds: float, bpm: float, beats_per_bar: int = 4, lead_in_bars: int = 1, tail_bars: int = 1) -> int:
    """The bar the bounce ends on: the song's bars after the lead-in, plus a bar for the tail."""
    bars = math.ceil(seconds * bpm / 60.0 / beats_per_bar)
    return lead_in_bars + bars + tail_bars + 1


def _plain(name: str) -> str:
    """A plugin name as the strip or the search may spell it: no maker prefix, no case, letters and digits only."""
    text = name.lower()
    for prefix in ("uad ", "uadx ", "the "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return "".join(ch for ch in text if ch.isalnum())


def on_strip(plugin: str, names: list[str]) -> bool:
    """The strip shows short names ("Shadow Hills Mastering Compress" for the compressor, "UAD Shadow" for the UAD
    one that the search lands first): the names are compared plain, one a prefix of the other, eight characters
    or more."""
    wanted = _plain(plugin)
    for n in names:
        shown = _plain(n)
        if not shown or not wanted:
            continue
        head = min(len(shown), len(wanted))
        if head >= 6 and shown[:head] == wanted[:head]:   # the strip can show as little as "UAD Shadow"
            return True
        if shown == wanted:
            return True
    return False


CHECK_RANGE = (2, 10)   # bars, until the mix print is read: then the loudest eight bars (Owner 2026-11-02)
CHECK_BARS = 8
_SPEAKER: list = []   # the booth's voice while it runs this job (Owner 2026-11-04: a few spoken checkpoints, not commentary)


class speaking:
    """``with speaking(booth._say):`` the job's checkpoints are said aloud through the booth for the job's length."""

    def __init__(self, say: Callable[[str, dict, str], None]):
        self.say = say

    def __enter__(self):
        _SPEAKER.append(self.say)
        return self

    def __exit__(self, *exc) -> None:
        if self.say in _SPEAKER:
            _SPEAKER.remove(self.say)


def checkpoint(moment: str, facts: dict, plain: str) -> None:
    """One spoken line at a checkpoint, written from this run's facts, the plain line if the writer is late; silent
    when no booth is speaking for the job. The voice is the look, not the work: a failure here changes nothing."""
    if not _SPEAKER:
        return
    try:
        _SPEAKER[-1](moment, facts, plain)
    except Exception:   # noqa: BLE001
        pass


STAGES = ["Balance", "Think", "Build", "Test", "Print", "Check", "Deliver"]   # the path on the live view; the mix is checked, then mastered (Owner 2026-11-04: two jobs, shown as two, in everyday words)


def check_range_of(job: Job) -> tuple[int, int]:
    return job.check_range or CHECK_RANGE


def prove_chain(strip: StereoOut, bouncer: bouncing.Bouncer, locators, toggle_cycle, job: Job, log,
                plugin_of: dict[str, str] | None = None, mark=None, mix_path: Path | None = None) -> list[str]:
    """The chain proves it passes audio: eight bars printed with everything in. A silent print means an insert is
    eating the sound (Owner 2026-11-02: a plug-in whose subscription lapsed loads, says so on its face, and passes
    silence; Marco has to know the difference). Marco's active inserts are bypassed one at a time, from the last,
    and the first bypass that brings the sound back names the dead one, which stays bypassed and is written to the
    license ledger. The names of the dead inserts come back; the range is put back to the song."""
    folder = Path(job.bounces).expanduser() / "checks"
    folder.mkdir(parents=True, exist_ok=True)
    dead: list[str] = []

    last_print: list[Path] = []

    def short_print(label: str) -> auditing.Audit:
        name = bouncing.free_name(folder, bouncing.print_name(job.song, label, job.today))
        printed = bouncer.print(bouncing.CHECK, folder, name)
        last_print[:] = [printed.path]
        return auditing.audit_file(printed.path)

    bars = check_range_of(job)
    locators(*bars)
    ensure_range(bouncer, bars[1], toggle_cycle, log)
    try:
        for _ in range(4):
            heard = short_print("chain check")
            if not heard.base.silent:
                log(f"   the chain passes audio ({heard.base.lufs} LUFS over bars {bars[0]} to {bars[1]})")
                if mix_path is not None and job.bar_s and last_print:
                    # the same eight bars of the mix against the check, loudness-matched: a ducker on the output
                    # shows as new modulation at the beat rate here, before a full print (Owner 2026-11-02)
                    v = verifying.compare(mix_path, last_print[0], job.bpm, start_s=(bars[0] - 1) * job.bar_s,
                                          length_s=(bars[1] - bars[0]) * job.bar_s, tonal_only=True, master_start_s=0.0)
                    for line in v.text().splitlines():
                        log(f"   chain check {line}")
                    pumping = [r for r in v.reasons if "pumps" in r]
                    if pumping:
                        raise RuntimeError("the chain pumps against the mix: " + "; ".join(pumping))
                return dead
            log("   the chain prints silence: looking for the insert that eats the sound")
            culprit = None
            for ins in reversed([i for i in strip.read().inserts if i.marcos and not i.bypassed]):
                strip.bypass(True, rows=[ins.y])
                if not short_print(f"chain check without {ins.name}").base.silent:
                    culprit = ins
                    break
                strip.bypass(False, rows=[ins.y])
            if culprit is None:
                raise RuntimeError("the chain prints silence and no single insert explains it")
            plugin = (plugin_of or {}).get(culprit.name, culprit.name)
            dead.append(plugin)
            log(f"   {plugin} passes silence: left bypassed and written to the ledger as inactive")
            if mark is not None:
                mark(plugin, "inactive", f"printed silence on the Stereo Out {job.today}")
        raise RuntimeError("the chain still prints silence after four tries")
    finally:
        locators(1, job.end_bar)
        ensure_range(bouncer, job.end_bar, toggle_cycle, log)


EARN_DB = 0.3            # an insert earns its place when its absence moves level, crest or a band this much
EARN_TILT = 0.1          # or the tilt this much, dB per octave


def run_bench(strip: StereoOut, bouncer: bouncing.Bouncer, locators, toggle_cycle, job: Job, log,
              ledger: list[dict], judge=None) -> list[dict]:
    """Every one of Marco's inserts on the output printed with and without over the check range, after the
    settings: the full chain once, then each insert bypassed in turn. The difference its absence makes (level,
    crest, tilt, the widest band move) is the measured reason; with a ``judge`` (master.judge), the ears hear both
    prints and the brain gives the verdict inside the playbook's limits (Owner 2026-11-03: knowledge and wisdom).
    One that earns nothing is taken off and the record says so. Returns one row per insert."""
    folder = Path(job.bounces).expanduser() / "checks"
    folder.mkdir(parents=True, exist_ok=True)
    marcos = {row["name"] for row in ledger}

    def short_print(label: str) -> Path:
        name = bouncing.free_name(folder, bouncing.print_name(job.song, label, job.today))
        return bouncer.print(bouncing.CHECK, folder, name).path

    def measure(path: Path) -> dict:
        audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
        a = auditing.audit_audio(audio, rate, path.stem)
        return {"lufs": a.base.lufs, "crest": a.base.crest_db, "tilt": a.tilt_db_per_octave,
                "bands": verifying.band_levels(audio, rate)}

    rows: list[dict] = []
    bars = check_range_of(job)
    locators(*bars)
    ensure_range(bouncer, bars[1], toggle_cycle, log)
    try:
        full_path = short_print("bench full chain")
        full = measure(full_path)
        on_bench = [i for i in strip.read().inserts if i.marcos and i.name in marcos and not i.bypassed]
        seen: dict[str, int] = {}
        for ins in on_bench:
            # two of one plugin on the strip (run 37: Pro-Q 3 twice) are told apart on the screen by their order
            seen[ins.name] = seen.get(ins.name, 0) + 1
            label = ins.name if sum(i.name == ins.name for i in on_bench) == 1 \
                else f"{ins.name}, the {('first', 'second', 'third', 'fourth')[min(seen[ins.name], 4) - 1]} one"
            strip.bypass(True, rows=[ins.y])
            try:
                # the verdict is the test's own line, not a second thought under it (Owner 2026-11-03: one line per task)
                with events.step(f"Try the song without {label}", motif="rec", word="tested") as line:
                    without_path = short_print(f"bench without {ins.name}")
                    without = measure(without_path)
                    band_moves = {k: round(full["bands"][k] - without["bands"][k], 1) for k in full["bands"]
                                  if not math.isnan(full["bands"][k]) and not math.isnan(without["bands"][k])}
                    widest = max(band_moves.items(), key=lambda kv: abs(kv[1])) if band_moves else ("", 0.0)
                    effect = {"level_db": round(full["lufs"] - without["lufs"], 1), "crest_db": round(full["crest"] - without["crest"], 1),
                              "tilt_db_per_octave": round(full["tilt"] - without["tilt"], 2), "widest_band": widest[0], "band_db": widest[1]}
                    measured = bool(abs(effect["level_db"]) >= EARN_DB or abs(effect["crest_db"]) >= EARN_DB
                                    or abs(effect["tilt_db_per_octave"]) >= EARN_TILT or abs(effect["band_db"]) >= EARN_DB)
                    earned, heard, call = measured, {}, None
                    if judge is not None:
                        # the ears on both prints, then the brain inside the rule; the rule's floor still holds
                        try:
                            heard = judge.hear(full_path, without_path, job="bench_ear", what=(f"with {ins.name}", f"without {ins.name}"))
                            call = judge.decide("bench_verdict", ("keep", "remove"), rule=BENCH_RULE,
                                                numbers={"tool": ins.name, "without_it": effect, "earn_db": EARN_DB, "earn_tilt": EARN_TILT,
                                                         "measured": measured}, heard=heard)
                            earned = call.decision == "keep"
                            if earned and not measured and heard.get("difference") in ("none", "unknown"):
                                earned = False
                                log(f"   the playbook overrules the brain on {ins.name}: nothing measured and nothing heard")
                        except Exception as exc:   # noqa: BLE001
                            log(f"   the judge sat {ins.name} out ({type(exc).__name__}: {str(exc)[-100:]}); the meters decide")
                    line["summary"] = (events.readable(call.plain) if call is not None else "") or \
                        (f"{label} stays. It makes a real difference." if earned else f"Without {label}, nothing changes.")
            finally:
                strip.bypass(False, rows=[ins.y])
            rows.append({"name": ins.name, "y": round(ins.y), "earned": earned, "measured": measured, **effect,
                         "heard": heard.get("hears", ""), "verdict": call.why if call is not None else ""})
            if earned:
                log(f"   {ins.name} earns its place: without it level {-effect['level_db']:+.1f} dB, crest "
                    f"{-effect['crest_db']:+.1f} dB, tilt {-effect['tilt_db_per_octave']:+.2f}, {widest[0]} {-widest[1]:+.1f} dB")
            else:
                log(f"   {ins.name} changes nothing measurable here (level {effect['level_db']:+.1f}, crest "
                    f"{effect['crest_db']:+.1f}, {widest[0]} {widest[1]:+.1f} dB): taken off")
                events.emit("tool_skipped", source="marco", status="refused", tool="Logic Pro", summary=f"{ins.name} taken off.",
                            detail="It changed nothing he could measure.", plain=f"Marco removed {ins.name}. It made no difference.")
                try:
                    strip.remove(ins.name, ins.y)
                except Exception as exc:   # noqa: BLE001
                    log(f"   could not remove {ins.name} ({str(exc)[-100:]}); bypassed instead")
                    strip.bypass(True, rows=[ins.y])
    finally:
        locators(1, job.end_bar)
        ensure_range(bouncer, job.end_bar, toggle_cycle, log)
    return rows


def row_keys(inserts) -> dict[int, tuple[str, int]]:
    """Each insert keyed by its name and its place among the inserts of that name, top first: a key that survives
    the strip scrolling when a new insert lands (live 2026-11-02, run 29: keys by screen row stopped matching and
    two inserts stayed bypassed)."""
    counts: dict[str, int] = {}
    out = {}
    for i in sorted(inserts, key=lambda i: i.y):
        n = counts.get(i.name, 0)
        counts[i.name] = n + 1
        out[id(i)] = (i.name, n)
    return out


def key_of(inserts, insert) -> tuple[str, int]:
    return row_keys(inserts)[id(insert)]


def role_filled(role: str, names: list[str], claimed: set[str] | None = None, room: set[str] | None = None) -> str | None:
    """The strip name of a plugin already there that can fill the role (a run that stopped after its insert), not
    one another role has claimed: Pro-Q 3 counts once, for the EQ role it was put in for. A candidate outside the
    room (a plug-in the ledger holds inactive) never counts, however it got on the strip."""
    for candidate in roles.CANDIDATES.get(role, []):
        if room is not None and candidate not in room:
            continue
        for shown in names:
            if shown in (claimed or set()):
                continue
            if on_strip(candidate, [shown]):
                return shown
    return None


def ensure_range(bouncer: bouncing.Bouncer, end_bar: int, toggle_cycle: Callable[[], None], log=print) -> None:
    """The Bounce dialog takes the cycle range when Cycle is on (live 2026-11-02): open it, read its end bar, and
    turn Cycle on when the dialog shows the project end instead. Closed again before the print."""
    for attempt in range(2):
        opened = bouncer.open(bouncing.MIX)
        bouncer.cancel()
        shown = int(opened.end.split()[0]) if opened.end.split() and opened.end.split()[0].isdigit() else None
        if shown == end_bar:
            return
        log(f"   bounce range ends at bar {shown}, wanted {end_bar}: toggling Cycle")
        toggle_cycle()
    raise RuntimeError(f"the Bounce dialog would not take bars 1 to {end_bar}")


def emit_analysis(audit, hearing) -> None:
    """The audit as the trace shows it: what stands out, then the whole-song numbers."""
    try:
        a, b = audit, audit.base
        stands = []
        if a.resonances:
            r = a.resonances[0]
            stands.append(("Resonance", f"{r.hz:g} Hz {r.note}".strip(), ""))
        if a.key:
            stands.append(("Key", a.key, ""))
        if b.low_mono is not None:
            stands.append(("Low-end correlation", f"{b.low_mono:.2f}", ""))
        stems = (hearing or {}).get("stems") if isinstance(hearing, dict) else None
        if isinstance(stems, dict) and isinstance(stems.get("lufs"), dict) and "vocals" in stems["lufs"]:
            rest = [v for k, v in stems["lufs"].items() if k != "vocals"]
            if rest:
                stands.append(("Vocal balance", f"{stems['lufs']['vocals'] - max(rest):+.1f}", "dB"))
        events.emit("analysis_generated", source="marco", operation="mastering analysis", status="ok",
                    summary="Measured.",
                    metrics=stands[:4], confidence=a.key_confidence if a.key else None)
    except Exception:   # noqa: BLE001  (the trace never stops the work)
        pass


TAIL_FLOOR_DB = -45.0    # below this, over TAIL_HOLD_S, the tail is room hiss lifted by the chain, not music (Owner 2026-11-03)
TAIL_HOLD_S = 2.0
TAIL_FADE_S = 2.0


def trim_tail(path: Path, *, floor_db: float = TAIL_FLOOR_DB, hold_s: float = TAIL_HOLD_S, fade_s: float = TAIL_FADE_S) -> float:
    """The silent tail cut off a print, in place: a mix that runs past the song's end carries the room's hiss, and the
    chain lifts it to where a listener hears a fan for a minute (run 39, 2026-11-03). The last tenth of a second that
    rises above the floor is found; the file ends ``hold_s`` after it with a fade of ``fade_s``. Returns the seconds
    removed, 0.0 when the tail was already short."""
    import numpy as np

    info = sf.info(str(path))
    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    window = max(int(rate * 0.1), 1)
    n = len(audio) // window
    if n < 2:
        return 0.0
    levels = np.sqrt(np.mean(np.square(audio[: n * window].reshape(n, window, -1)), axis=(1, 2)))
    loud = np.flatnonzero(20 * np.log10(np.maximum(levels, 1e-9)) > floor_db)
    if not loud.size:
        return 0.0
    end = min(len(audio), (int(loud[-1]) + 1) * window + int(hold_s * rate))
    if len(audio) - end < rate * 0.5:
        return 0.0
    fade = min(int(fade_s * rate), end)
    kept = audio[:end].copy()
    kept[end - fade:end] *= np.linspace(1.0, 0.0, fade, dtype="float32")[:, None]
    sf.write(str(path), kept, rate, subtype=info.subtype, format=info.format)
    return round((len(audio) - end) / rate, 2)


PAYOFF_SECONDS = 40.0    # the finished song plays this long through the meter on screen; the file's same stretch is the check
METER_AGREE_LU = 0.5     # the meter and the file within this much of each other count as one reading


def play_through_meter(strip: StereoOut, master: Path, result: Result, payoff, client, log, room: set[str] = frozenset()) -> dict | None:
    """The chain's meter opened, the song played from the top through it, its window read by the eyes, and the same
    stretch of the file measured by the ears (Owner 2026-11-03: the audience sees the marks hit). ``payoff(name, row,
    seconds)`` does the Logic side and returns the meter window's picture; None when there is no meter to play through."""
    from hiremarco.studio import face as faces

    # the plan's meter when it named one, else the best meter the room owns (run 39: the plan named none and the payoff
    # was skipped); the payoff is the audience's proof, not the plan's call
    meter_name = (result.plan.chain.get("meter") if result.plan else None) or roles.fill("meter", room)
    if not meter_name:
        log("   no meter in the room to play through; no payoff on screen")
        return None
    events.stage("Check", "Marco plays the finished song through the meter so you can see the marks.")
    with events.step("Play the finished song through the meter", motif="vu", word="checked") as line:
        # the prints never carry a meter (the audit reads the file); for the payoff it goes on now, after the master is
        # printed, and comes off after, so the next run finds no stray on the strip
        before = strip.read()
        was_there = {(i.name, round(i.y)) for i in before.inserts}
        row = next((i for i in before.inserts if same_plugin(meter_name, i.name) and not i.bypassed), None)
        added = False
        if row is None:
            after = strip.insert(meter_name)
            row = next((i for i in after.inserts if same_plugin(meter_name, i.name) and (i.name, round(i.y)) not in was_there), None)
            added = row is not None
            if row is None:
                log(f"   {meter_name} did not land on the output; no payoff on screen")
                line["summary"] = "The meter could not be opened."
                return None
        try:
            try:
                from hiremarco.studio import aloud

                aloud.stop()   # Logic's own playback is the one thing the room hears now
                png = payoff(row.name, row.y, PAYOFF_SECONDS)
                read = faces.read_meter(png, client=client)
            except Exception as exc:   # noqa: BLE001
                log(f"   the meter could not be read ({type(exc).__name__}: {str(exc)[-100:]})")
                line["summary"] = "The meter could not be read."
                return None
            audio, rate = sf.read(str(master), dtype="float32", always_2d=True, frames=int(PAYOFF_SECONDS * rate_of(master)))
            stretch = auditing.audit_audio(audio, rate, master.stem)
            meter_lufs, file_lufs = read.get("integrated_lufs"), float(stretch.base.lufs)
            agree = bool(meter_lufs is not None and abs(meter_lufs - file_lufs) <= METER_AGREE_LU)
            out = {"plugin": read.get("plugin", ""), "meter_lufs": meter_lufs, "meter_peak": read.get("true_peak_dbtp"),
                   "meter_range": read.get("range_lu"), "file_lufs": file_lufs, "file_peak": stretch.base.true_peak_db,
                   "seconds": PAYOFF_SECONDS, "agree": agree}
            log(f"   the meter reads {meter_lufs} LUFS, {out['meter_peak']} dBTP; the file's first {PAYOFF_SECONDS:.0f} s measure "
                f"{file_lufs} LUFS, {out['file_peak']} dBTP: {'agree' if agree else 'DISAGREE'}")
            line["summary"] = "The meter and the ears agree." if agree else "The meter and the ears disagree."
            line["metrics"] = [("Meter", str(meter_lufs), "LUFS"), ("Ears", str(file_lufs), "LUFS")]
            return out
        finally:
            if added:
                try:
                    strip.remove(row.name, row.y)
                except Exception as exc:   # noqa: BLE001
                    log(f"   could not take {row.name} back off ({type(exc).__name__}); it stays on the output, bypassed is not possible here")


def rate_of(path: Path) -> int:
    return int(sf.info(str(path)).samplerate)


def climb_ladder(strip: StereoOut, bouncer: bouncing.Bouncer, locators, toggle_cycle, channel, job: Job, result: Result,
                 listen, log, judge=None) -> dict | None:
    """The limiter's gain up one dB at a time on the loudest bars until a clean bar breaks (master.ladder)."""
    from hiremarco.master import ladder as ladders

    limiter_name = result.plan.chain.get("limiter") if result.plan else None
    if not limiter_name:
        log("   no limiter in the chain; no ladder")
        return None
    chain = channel.read(fresh=True)
    slot = next((s for s in chain.active() if s.state and same_plugin(limiter_name, s.name)), None)
    if slot is None or not slot.state or "Gain" not in (slot.state.shown or {}):
        log(f"   the limiter {limiter_name} shows no Gain control to climb; no ladder")
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(slot.state.shown["Gain"]))
    if not m:
        log(f"   the limiter's Gain reads {slot.state.shown['Gain']!r}; no ladder")
        return None
    start = float(m.group(0))
    bars = check_range_of(job)
    folder = Path(job.bounces).expanduser() / "ladder"
    folder.mkdir(parents=True, exist_ok=True)
    start_s, length_s = (bars[0] - 1) * job.bar_s, (bars[1] - bars[0]) * job.bar_s

    def set_gain(value: float) -> float:
        states = channel.apply_changes([{"slot": slot.number, "parameter": "Gain", "value": value, "unit": "dB",
                                         "why": "the loudness ladder, one dB at a time"}], chain=chain)
        shown = (states.get(slot.number).shown or {}).get("Gain", "") if states.get(slot.number) else ""
        found = re.search(r"-?\d+(?:\.\d+)?", str(shown))
        return float(found.group(0)) if found else value

    def print_bars(label: str) -> Path:
        locators(*bars)
        ensure_range(bouncer, bars[1], toggle_cycle, log)
        name = bouncing.free_name(folder, bouncing.print_name(job.song, label, job.today))
        with events.step("Try the loudest part, one step louder", motif="fader", word="tested"):
            return bouncer.print(bouncing.CHECK, folder, name).path

    def compare(path: Path):
        return verifying.compare(result.mix, path, job.bpm, start_s=start_s, length_s=length_s, master_start_s=0.0)

    def lufs_of(path: Path) -> float:
        return auditing.audit_file(path).base.lufs

    hear = mix_hearing = None
    if listen is not None:
        try:
            import soundfile as sf

            audio, rate = sf.read(str(result.mix), start=int(start_s * 0), always_2d=True)
            lo, hi = int(start_s * rate), int((start_s + length_s) * rate)
            bars_path = folder / f"{bouncing.print_name(job.song, 'mix bars', job.today)}.wav"
            sf.write(str(bars_path), audio[lo:hi], rate, subtype="FLOAT")
            mix_hearing = listen(bars_path)
            hear = lambda path: listen(path, bars_path)   # noqa: E731
        except Exception as exc:   # noqa: BLE001
            log(f"   the ears sit this ladder out ({type(exc).__name__})")
    ask_next = None
    if judge is not None:
        def ask_next(step) -> tuple[bool, str]:
            # the brain's say after a clean step, inside the rule: it can stop short of the floors, not pass them
            call = judge.decide("ladder_verdict", ("louder", "stop"), rule=LADDER_RULE,
                                numbers={"limiter_gain_db": step.gain_db, "lufs_on_loudest_bars": step.lufs, "cap_lufs": ladders.CAP_LUFS,
                                         "target_lufs": result.plan.target_lufs, "floors": "peak-to-loudness 8 dB, no new pumping, "
                                         "the mono fold and width unchanged, roughness and likeness within the ears' lines",
                                         "this_step": "clean"})
            return call.decision == "louder", call.why

    try:
        out = ladders.climb(start_gain_db=start, set_gain=set_gain, print_bars=print_bars, compare=compare, lufs_of=lufs_of,
                            hear=hear, mix_hearing=mix_hearing, ask_next=ask_next, log=log)
    finally:
        locators(1, job.end_bar)
        ensure_range(bouncer, job.end_bar, toggle_cycle, log)
    if out.ceiling_gain_db is not None:
        events.emit("decision_made", source="marco", operation="loudness ceiling", status="ok",
                    summary="As loud as it goes before it suffers.",
                    detail=f"what gave first: {out.gave_first}" if out.gave_first else "nothing gave within the ladder",
                    thought="That is as loud as this song goes before it suffers.",
                    metrics=[("Steps", str(len(out.steps)), ""), ("Ceiling", f"{out.ceiling_lufs:.1f}", "LUFS")])
    return out.as_dict()


def mark_in_ledger(plugin: str, status: str, why: str) -> None:
    """A finding about a plug-in written to the license ledger, as Logic names it."""
    from hiremarco.studio.ledger import mark

    mark(roles.MAPS / "license_ledger.json", f"{plugin} (s/s)", status, why)


def run(job: Job, *, strip: StereoOut, bouncer: bouncing.Bouncer, channel: Channel, locators: Callable[[int, int], None],
        toggle_cycle: Callable[[], None], select_track: Callable[[], None], room: set[str] | None = None,
        client=None, critic=None, deliver: Callable[[Path, str], str] | None = None, log: Callable[[str], None] = print,
        sleep=time.sleep, mark_plugin: Callable[[str, str, str], None] | None = mark_in_ledger,
        look_at_face: Callable[[], object] | None = None,
        listen: Callable[..., dict | None] | None = None, bench: bool = False, ladder: bool = False,
        audition: Callable[..., list] | None = None, payoff: Callable[[str, float, float], bytes] | None = None) -> Result:
    result = Result()
    bounces = Path(job.bounces).expanduser()
    bounces.mkdir(parents=True, exist_ok=True)
    room = room if room is not None else roles.in_the_room()
    lock = hold_lock(job)
    try:
        return _run(job, result, bounces, room, strip=strip, bouncer=bouncer, channel=channel, locators=locators,
                    toggle_cycle=toggle_cycle, select_track=select_track, client=client, critic=critic, deliver=deliver,
                    log=log, sleep=sleep, mark_plugin=mark_plugin, look_at_face=look_at_face, listen=listen, bench=bench,
                    ladder=ladder, audition=audition, payoff=payoff)
    except Exception as exc:
        # the page says the job stopped, not the last thing it was doing, and the beat stops with it
        events.emit("job_ended", source="marco", status="failed", summary=f"{type(exc).__name__}: {str(exc)[-100:]}",
                    plain="Marco hits a wall and stops rather than guess.")   # Owner 2026-11-03: no "says so" without a real message
        raise
    finally:
        release_lock(lock)


def inserts_ledger(song: str) -> Path:
    from hiremarco import config, events

    folder = Path(config.STATE_DIR) / "inserts"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in " -_" else "-" for c in song).strip() or "song"
    return folder / f"{safe}.json"


def marcos_inserts(song: str) -> list[dict]:
    """What Marco has put on this song's output strip, run after run: name as the strip shows it, the plan's
    plugin, when, and whether it was a stray (a menu misfire). The artist's own inserts are never in here."""
    path = inserts_ledger(song)
    try:
        return list(json.loads(path.read_text())) if path.exists() else []
    except ValueError:
        return []


def remember_insert(song: str, name: str, plugin: str, *, stray: bool = False) -> None:
    rows = marcos_inserts(song)
    rows.append({"name": name, "plugin": plugin, "at": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "stray": stray})
    inserts_ledger(song).write_text(json.dumps(rows, indent=1))


def hold_lock(job: Job) -> Path | None:
    """One master job at a time on this Mac, whichever path started it (the CLI, the booth, WhatsApp, the nightly):
    a lock file in the state folder with the job's name and time; a lock under two hours old refuses the job."""
    try:
        from hiremarco import config

        path = Path(config.STATE_DIR) / "master.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and time.time() - path.stat().st_mtime < LOCK_FRESH_S:
            raise RuntimeError(f"another master job holds the lock ({path.read_text().strip()})")
        path.write_text(f"{job.song} started {time.strftime('%Y-%m-%d %H:%M:%S %Z')} pid {os.getpid()}")
        return path
    except OSError:
        return None


def release_lock(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink()
        except OSError:
            pass


def _run(job: Job, result: Result, bounces: Path, room: set[str], *, strip, bouncer, channel, locators, toggle_cycle,
         select_track, client, critic, deliver, log, sleep, mark_plugin, look_at_face, listen, bench, ladder=False, audition=None,
         payoff=None) -> Result:

    # 1. the mix as it stands: Marco's own inserts bypassed, the artist's untouched
    log("1. the mix print")
    began = time.monotonic()
    # knowledge and wisdom (Owner 2026-11-03): with a client, the ears and the brain sit on every test, the ladder and
    # the final check; without one (the suite's fakes), the meters decide alone as before
    judge = Judge(client) if client is not None else None

    def out_of_time(what: str) -> bool:
        """Past the budget, a test or a pass is skipped and the screen says so; the goal is a finished song, not a long night."""
        if time.monotonic() - began <= job.budget_s:
            return False
        log(f"   out of time for {what}: {int((time.monotonic() - began) / 60)} minutes in, the budget is {int(job.budget_s / 60)}")
        events.emit("tool_skipped", source="marco", status="refused", tool="Logic Pro", summary=f"No time left for {what}.",
                    detail=f"{int((time.monotonic() - began) / 60)} minutes in; the budget is {int(job.budget_s / 60)}.",
                    plain="Marco is out of time for more tests. He goes with what he has.")
        return True

    events.emit("job_started", source="marco", operation="Mastering the song", status="ok", stages=STAGES, stage="Balance",
                plain="Marco is finishing this song so it is ready for release.", pid=os.getpid())
    select_track()   # a plain track first: a stack selected makes the Mixer's Single view too wide to click
    strip.open_mixer()
    before = strip.read()
    # what was in and what was out before the job: an insert the artist or an earlier run left bypassed stays so
    before_keys = row_keys(before.inserts)
    was_in = {before_keys[id(i)] for i in before.inserts if i.marcos and not i.bypassed}
    seen = set(before_keys.values())
    if any(i.marcos for i in before.inserts):
        strip.bypass(True)
    mix_name = bouncing.print_name(job.song, "mix", job.today)
    if (bounces / f"{mix_name}.wav").exists():
        # today's mix print of this song already landed (a run that stopped after it): the same file is the mix
        mix = bouncing.read_back(bounces / f"{mix_name}.wav")
        log(f"   {mix.path.name} is already printed today: reading it back instead of printing again")
    else:
        locators(1, job.end_bar)
        ensure_range(bouncer, job.end_bar, toggle_cycle, log)
        with events.step("Save the song as it stands", motif="rec") as line:
            mix = bouncer.print(bouncing.MIX, bounces, mix_name)
            line["summary"] = "Saved."
            line["metrics"] = [("Length", f"{mix.seconds:.0f}", "s")]
        log(f"   {mix.path.name}: {mix.seconds} s, {mix.rate} Hz {mix.subtype}, {mix.took_s} s to print")
    result.mix = mix.path
    if job.bpm and job.check_range is None:
        # the loudest eight bars of the song are where the chain is checked, benched and compared (Owner 2026-11-02:
        # the loudest section first, since that is the peak; the intro said nothing about the Imager in run 34)
        try:
            import soundfile as sf

            audio, rate = sf.read(str(mix.path), always_2d=True)
            start, end, lufs = auditing.loudest_bars(audio, rate, job.bpm, CHECK_BARS)
            job.check_range = (max(start, 1), min(end, job.end_bar))
            log(f"   the loudest {CHECK_BARS} bars: {job.check_range[0]} to {job.check_range[1]} ({lufs} LUFS); "
                "the chain is checked and benched there")
        except Exception as exc:   # noqa: BLE001
            log(f"   the loudest bars could not be read ({type(exc).__name__}); bars {CHECK_RANGE[0]} to {CHECK_RANGE[1]} stand")

    # 2. the audit, against the references the artist owns
    log("2. the audit")
    events.stage("Balance", "Marco checks the balance of your song before he finishes it.")
    with events.step("Measure volume, tone and width", tool="Marco's ears", motif="vu") as line:
        result.audit_mix = auditing.audit_file(mix.path)
        line["summary"] = "Measured."
        line["metrics"] = [("Loudness", str(result.audit_mix.base.lufs), "LUFS"), ("Crest", str(result.audit_mix.base.crest_db), "dB")]
    if result.audit_mix.base.silent:
        result.stopped = f"the mix print is silent ({mix.path.name}); nothing to master"
        log(f"   {result.stopped}")
        return result
    refs = auditing.references(job.references) if job.references and Path(job.references).exists() else []
    deltas = auditing.compare(result.audit_mix, refs)
    for line in auditing.summary(result.audit_mix, deltas).splitlines():
        log(f"   {line}")
    if listen is not None:
        # the ears beyond the meters, against the first reference when there is one
        first_ref = next(iter(sorted(p for p in Path(job.references).iterdir() if p.suffix.lower() in (".wav", ".aiff", ".aif", ".flac"))), None) \
            if job.references and Path(job.references).is_dir() else None
        with events.step("Listen for what the meters miss", tool="Marco's ears", motif="wave"):
            result.hearing = listen(mix.path, reference=first_ref)
        for line in listening.highlights(result.hearing):
            log(f"   {line}")

    emit_analysis(result.audit_mix, result.hearing)
    found = events.plain_findings(auditing.findings(result.audit_mix))
    for words in found:
        events.thought(words)
    checkpoint("the artist's mix is measured and heard, before any of your work on it; say in one short sentence what "
               "stands out and that the finish comes next; no numbers", {"what_stands_out": found[:2]},
               "I've checked your balance. Now I'll finish it.")

    # 3. the plan, from the deepest brain, judged by the critic
    log("3. the plan")
    events.stage("Think", "Balance checked. Marco plans the finish.")
    result.plan = planning.roles_for(result.audit_mix, deltas, room, purpose=job.purpose, direction=job.direction,
                                     stock_only=job.stock_only, client=client, critic=critic, hearing=result.hearing)
    for r in result.plan.roles:
        as_model = getattr(log, "as_model", None)   # the running log names the brain that reasoned the line
        if as_model:
            as_model(planning.MODEL)
        log(f"   {r['role']}: {r['plugin']}. {r['why']}")
        if as_model:
            as_model("")
        events.emit("decision_made", source="marco", operation=r["role"].replace("_", " "), status="ok",
                    summary=f"{r['role'].replace('_', ' ')}: {r['plugin']}", detail=str(r.get("why", "")),
                    thought=events.plain_whole(str(r.get("plain", ""))),
                    metrics=[("Measured", str(r.get("measured", ""))[:24], "")] if r.get("measured") else None)
    log(f"   target {result.plan.target_lufs} LUFS, ceiling {result.plan.ceiling_dbtp} dBTP")
    # the goal, said before any tool moves, so what follows reads against it and done means it was met (Owner 2026-11-03)
    events.stage("Think", "Marco's goal: as loud as today's records, under the limit, still breathing.", motif="vu")
    events.emit("decision_made", source="marco", operation="the goal", status="ok",
                summary="The goal is set.", thought="The goal is set. Every step from here is measured against it.",
                detail=f"{result.plan.target_lufs} LUFS integrated, true peak under {result.plan.ceiling_dbtp} dBTP, the song still moving.",
                metrics=[("Loudness", str(result.plan.target_lufs), "LUFS"), ("Ceiling", str(result.plan.ceiling_dbtp), "dBTP")])
    if result.plan.critic:
        log(f"   critic: {'approved' if result.plan.critic[0] else 'held'}: {result.plan.critic[1]}")
    if result.plan.critic and not result.plan.critic[0]:
        result.stopped = f"the critic held the plan: {result.plan.critic[1]}"
        log(f"   {result.stopped}")
        events.emit("job_ended", source="marco", status="refused", summary="Held", plain="A second opinion held the plan. Marco stops here.")
        return result
    if job.purpose == "mix" or not PURPOSES[job.purpose]["limiter"]:
        result.stopped = "a mix for mastering takes no chain; the mix print is the delivery"
        return result

    # 4. the chain on the Stereo Out, in the rulebook's order
    log("4. the chain")
    events.stage("Build", "Marco is setting up his tools in the studio software.")
    strip.open_mixer()   # the Mixer window was gone once by this step (live 2026-11-02, run 13); it comes back
    # what counts as on the strip: every insert that was there before the job, bypassed or not. A run that died
    # mid-way leaves the whole chain bypassed, and counting only what was in doubled the chain (runs 14 and 23,
    # live 2026-11-02); a plug-in the ledger holds inactive is kept out by the room, whatever its state
    names = [i.name for i in before.inserts]
    claimed: set[str] = set()
    claimed_rows: set[tuple[str, int]] = set()   # the exact rows that fill a role: a third Pro-Q 3 is not one of them
    plugin_of: dict[str, str] = {}   # the strip's short name -> the plan's plugin, for the ledger
    kept_out: set[tuple[str, int]] = set()   # rows a face notice put out: never brought back in
    faced: set[tuple[str, int]] = set()      # rows whose face was read at insert time this run
    for role, plugin in result.plan.chain.items():
        if role == "meter":
            continue  # meters are read by the audit, not by eye; nothing to insert for the print
        there = role_filled(role, names, set(), room)
        if there is not None:
            names.remove(there)   # that one row is taken; a second Pro-Q 3 on the strip can fill the next EQ role
            claimed.add(there)
            row = next((i for i in before.inserts if i.name == there and before_keys[id(i)] not in claimed_rows), None)
            if row is not None:
                claimed_rows.add(before_keys[id(row)])
            plugin_of[there] = plugin
            log(f"   {role} is already on the strip ({there})")
            continue
        # the plug-in the plan named, then the room's next candidates for the role when a face says it is not
        # licensed (Owner 2026-11-02): out of the room, in the ledger, bypassed here; the audio check is the second line
        candidates = [plugin] + [c for c in roles.CANDIDATES.get(role, ()) if c in room and c != plugin and c not in result.dead]
        for candidate in candidates:
            seen_face: list = []
            try:
                after = strip.insert(candidate, look=(lambda: seen_face.append(look_at_face())) if look_at_face else None)
            except RuntimeError as exc:
                # a misfire: the strip was read and whatever landed is bypassed (studio.stereo_out); it is written
                # down as a stray so no later run takes it for the artist's and brings it back in
                log(f"   {candidate} did not go in: {str(exc)[-160:]}")
                if "landed" in str(exc):
                    stray_name = str(exc).split(" landed", 1)[0].split("; ")[-1].strip()
                    remember_insert(job.song, stray_name, candidate, stray=True)
                continue
            landed = [i.name for i in after.inserts if i.name not in names] or [candidate]
            remember_insert(job.song, landed[-1], candidate)
            names = [i.name for i in after.inserts]
            claimed.add(landed[-1])
            after_keys = row_keys(after.inserts)
            new_rows = [i for i in after.inserts if after_keys[id(i)] not in seen]
            if new_rows:
                claimed_rows.add(after_keys[id(new_rows[-1])])
            plugin_of[landed[-1]] = candidate
            face = seen_face[0] if seen_face else None
            if face is not None:
                for i in after.inserts:
                    if after_keys[id(i)] not in seen:
                        faced.add(after_keys[id(i)])
            if face is None or face.licensed:
                if candidate != plugin:
                    for entry in result.plan.roles:   # the record names what landed, not what was planned
                        if entry["role"] == role:
                            entry["plugin"] = candidate
                log(f"   {landed[-1]} in ({role})" + ("; its face reads licensed" if face is not None else ""))
                break
            log(f"   {landed[-1]} shows a notice on its face: {face.notice!r}; left out")
            events.emit("tool_skipped", source="marco", status="refused", tool="Logic Pro", summary=f"{candidate} left out.",
                        detail=f"Its window says: {face.notice}", plain=f"Marco left {candidate} out. Its license is not active.")
            row = [i for i in after.inserts if i.name == landed[-1]][-1]
            strip.bypass(True, rows=[row.y])
            if mark_plugin is not None:
                mark_plugin(candidate, "inactive", f"its window said {face.notice!r} on {job.today}")
            result.dead.append(candidate)
            seen.add(after_keys[id(row)])   # not to be brought back in after the chain
            kept_out.add(after_keys[id(row)])
        else:
            log(f"   nothing licensed in the room for {role}; the chain goes on without it")
    # an insert Marco put there himself that fills no role in this plan, or a stray, stays out; the artist's own
    # inserts (never in the ledger) come back exactly as they were
    marcos = {row["name"] for row in marcos_inserts(job.song)}
    now = strip.read().inserts
    now_keys = row_keys(now)
    back_in = [i.y for i in now
               if i.marcos and now_keys[id(i)] not in kept_out
               and not (i.name in marcos and now_keys[id(i)] not in claimed_rows)
               and (now_keys[id(i)] in was_in or now_keys[id(i)] not in seen or now_keys[id(i)] in claimed_rows)]
    if back_in:
        strip.bypass(False, rows=back_in)

    # 4a. the manifest: every insert on the output accounted for before any print (Owner 2026-11-02: a stray
    # Kickstart pumped a whole master); a stray that is in is bypassed here and named
    log("4a. the manifest")
    planned = set(plugin_of.values()) | set(result.plan.chain.values())
    result.manifest = verifying.manifest(strip.read().inserts, marcos_inserts(job.song), planned, same_plugin)
    stray_rows = [row["y"] for row in result.manifest if row["status"] == "stray" and not row["bypassed"]]
    if stray_rows:
        strip.bypass(True, rows=stray_rows)
        for row in result.manifest:
            if row["y"] in stray_rows:
                row["bypassed"] = True
    for row in result.manifest:
        log(f"   {row['name']}: {row['status']}" + (" (bypassed)" if row["bypassed"] else ""))
        if row["status"] == "stray":
            # the catch goes on the screen, not only in the log (Owner 2026-11-03: an unowned Shadow Hills sat on the
            # strip with START DEMO on its window; Marco had put it out and nobody saw him do it)
            events.emit("tool_skipped", source="marco", status="refused", tool="Logic Pro", summary=f"{row['name']} left out.",
                        detail="On the output from before, and not in this plan.", plain="This one is not his to use. Marco leaves it out.")
    # every planned insert that was already on the strip gets its face read too (Owner 2026-11-02: an unowned
    # Shadow Hills sat in the chain with START DEMO on its window because only new inserts were faced)
    if look_at_face is not None and hasattr(strip, "open_insert"):
        for row in [r for r in result.manifest if r["status"] == "planned" and (r["name"], r["ordinal"]) not in faced]:
            try:
                strip.open_insert(row["name"], row["y"])
                face = look_at_face()
            except Exception as exc:   # noqa: BLE001
                log(f"   {row['name']}: its face could not be read ({type(exc).__name__}); the audio check stands")
                continue
            finally:
                strip.close_windows()
            if face is None:
                continue
            if face.licensed:
                log(f"   {row['name']}: its face reads licensed")
                continue
            plugin = plugin_of.get(row["name"], row["name"])
            log(f"   {row['name']} shows {face.notice!r} on its face: not owned, taken off the strip")
            events.emit("tool_skipped", source="marco", status="refused", tool="Logic Pro", summary=f"{plugin} taken off.",
                        detail=f"Its window says: {face.notice}", plain=f"Marco removed {plugin}. It is not licensed here.")
            try:
                strip.remove(row["name"], row["y"])
            except Exception as exc:   # noqa: BLE001
                log(f"   could not remove it ({str(exc)[-100:]}); bypassed instead")
                strip.bypass(True, rows=[row["y"]])
            if mark_plugin is not None:
                mark_plugin(plugin, "not_owned", f"its window said {face.notice!r} on {job.today}")
            room.discard(plugin)
            result.dead.append(plugin)
            row["status"] = "not owned, removed"
        result.manifest = verifying.manifest(strip.read().inserts, marcos_inserts(job.song), planned, same_plugin)

    # 4b. the chain proves it passes audio before anything is set or printed for real
    log("4b. the chain check")
    events.stage("Build", "Marco is checking the sound gets through his tools.")
    with events.step("Play a short test through the tools", motif="wave", word="tested"):
        result.dead += [d for d in prove_chain(strip, bouncer, locators, toggle_cycle, job, log, plugin_of=plugin_of, mark=mark_plugin,
                                               mix_path=result.mix)
                        if d not in result.dead]

    # 5. the settings, read and set through the Inspector's output strip
    log("5. the settings")
    direction = job.direction
    if audition is not None:
        # the part of the sound a move would touch, on its own (Owner 2026-11-02; Pro-Q's solo, done from the file so a
        # solo can never reach a print): only what the audit named, and the note goes to the settings
        events.stage("Build", "Marco listens to just the part he might change.")
        try:
            heard = audition(result.mix, result.audit_mix, job.check_range, client=client)
        except Exception as exc:   # noqa: BLE001
            log(f"   the audition did not run ({type(exc).__name__}: {str(exc)[-100:]}); the settings go on the measurements")
            heard = []
        for note in heard:
            log(f"   heard alone: {note.what}: {note.note}")
        if heard:
            direction = " ".join(filter(None, [direction, "Auditioned on their own, each part of the sound a move would touch: "
                                               + " ".join(f"{n.what} ({n.level_db} dB against the whole): {n.note}" for n in heard)]))
    events.stage("Build", "Marco is setting every control, and writing down why.")
    select_track()
    chain = channel.read(fresh=True)
    for round_no in range(1, MAX_ROUNDS + 1):
        if round_no > 1 and out_of_time("a corrected version"):
            result.rounds = round_no - 1
            break
        result.rounds = round_no
        settings = planning.settings_for(chain, result.audit_mix, deltas, result.plan, direction=direction,
                                         client=client, hearing=result.hearing)
        for c in settings.changes:
            log(f"   slot {c['slot']} {c['parameter']} = {c.get('choice') or format(c['value'], 'g') + ' ' + c['unit']}: {c['why']}")
        try:
            channel.apply_changes(settings.changes, chain=chain)
        except Exception as exc:
            if round_no == 1:
                raise
            log(f"   the second pass gave nothing usable ({str(exc)[-120:]}); the first print stands")
            result.rounds = round_no - 1
            break
        # the record carries what reached the plugins, not what was asked (run 37: eleven changes were dropped unsaid and
        # the record listed them as set); what was dropped is logged with its reason
        landed = getattr(channel, "landed", None)
        result.settings += settings.changes if landed is None else landed
        for reason in getattr(channel, "dropped", None) or []:
            log(f"   not applied: {reason}")
        log(f"   {settings.said}")
        if events.readable(settings.said):
            events.thought(events.readable(settings.said))

        if bench and round_no == 1 and not out_of_time("the tests"):
            # 5b. the bench: each insert printed with and without over the same bars, now that it is set; what
            # changes nothing comes off (Owner 2026-11-02: every decision earns its place with a measured reason)
            log("5b. the bench")
            events.stage("Test", "Every tool must earn its place. Marco tests each one.")
            result.bench = run_bench(strip, bouncer, locators, toggle_cycle, job, log, marcos_inserts(job.song), judge=judge)
            if any(not row["earned"] for row in result.bench):
                chain = channel.read(fresh=True)

        if ladder and round_no == 1 and job.bpm and job.bar_s and not out_of_time("the loudness ladder"):
            # 5c. the loudness ladder: as loud as this mix stays clean, on its loudest bars (Owner 2026-11-02)
            log("5c. the loudness ladder")
            events.stage("Test", "Marco turns it up, one step at a time, until it suffers.")
            try:
                result.ladder = climb_ladder(strip, bouncer, locators, toggle_cycle, channel, job, result, listen, log, judge=judge)
            except Exception as exc:   # noqa: BLE001
                log(f"   the ladder could not run ({type(exc).__name__}: {str(exc)[-120:]}); the plan's level stands")

        # 6. the master print, read back
        log(f"6. the master print (round {round_no})")
        events.stage("Print", "Marco is saving the final version." if round_no == 1 else "Marco is saving the corrected version.")
        name = bouncing.free_name(bounces, bouncing.print_name(job.song, "master" if round_no == 1 else f"master v{round_no}",
                                                               job.today))
        with events.step("Save the final version" if round_no == 1 else "Save the corrected version", motif="rec") as line:
            master = bouncer.print(bouncing.MASTER, bounces, name)
            line["summary"] = "Saved."
            line["metrics"] = [("Length", f"{master.seconds:.0f}", "s")]
        result.master = master.path
        with events.step("Trim the silent tail", motif="rec") as line:
            cut = trim_tail(master.path)
            result.trimmed_s = cut
            line["summary"] = f"Cut {cut:.0f} seconds of hiss off the end." if cut else "The end was already clean."
            if cut:
                line["metrics"] = [("Cut", f"{cut:.1f}", "s")]
        log(f"   the tail: {cut:.1f} s trimmed" if cut else "   the tail: nothing to trim")
        events.stage("Check", "Marco is checking what actually came out.")
        with events.step("Measure what came out", tool="Marco's ears", motif="vu", word="checked") as line:
            result.audit_master = auditing.audit_file(master.path)
            gap = result.plan.target_lufs - result.audit_master.base.lufs
            over = result.audit_master.base.true_peak_db - result.plan.ceiling_dbtp
            line["summary"] = ("On the mark." if abs(gap) <= LUFS_TOLERANCE and over <= CEILING_TOLERANCE
                               else "Off the mark." if over > CEILING_TOLERANCE else "Too quiet." if gap > 0 else "Too loud.")
            line["metrics"] = [("Loudness", str(result.audit_master.base.lufs), "LUFS"), ("True peak", str(result.audit_master.base.true_peak_db), "dBTP"),
                               ("Range", str(result.audit_master.loudness_range), "LU")]
        am = result.audit_master
        if listen is not None:
            with events.step("Listen to what came out", tool="Marco's ears", motif="wave", word="checked"):
                result.hearing_master = listen(master.path)
        if judge is not None:
            # the ears on the original and the result at matched level, then the brain against the goal; the numbers
            # below still decide whether a second pass runs, so the brain's word is the verdict a judge reads
            with events.step("Judge the finished song against the goal", tool="Marco's ears", motif="vu", word="checked") as line:
                try:
                    # before and after for the room (Owner 2026-11-04): his mix with Marco's tools off, then the master,
                    # the same stretch at the same level, so louder cannot pass for better
                    events.stage("Check", "Marco plays your song before his work, then after, at the same level.")
                    checkpoint("about to play the loudest part of the song before your work and then after it, at the "
                               "same level; one short sentence inviting the room to listen", {},
                               "Here's your song before my work, then after, at the same level.")
                    heard = judge.hear(result.mix, master.path, job="check_ear", what=("the original", "the finished version"))
                    # the marks are Marco's arithmetic, handed over as facts (run 39: the brain read a peak of exactly the
                    # ceiling as over it); the brain judges the sound
                    gap_now, over_now = result.plan.target_lufs - am.base.lufs, am.base.true_peak_db - result.plan.ceiling_dbtp
                    call = judge.decide("check_verdict", ("done", "not yet"), rule=CHECK_RULE,
                                        numbers={"target_lufs": result.plan.target_lufs, "ceiling_dbtp": result.plan.ceiling_dbtp,
                                                 "tolerance_lu": LUFS_TOLERANCE, "master_lufs": am.base.lufs, "true_peak_dbtp": am.base.true_peak_db,
                                                 "loudness_range_lu": am.loudness_range, "mix_lufs": result.audit_mix.base.lufs,
                                                 "marks_met": {"loudness_on_target": bool(abs(gap_now) <= LUFS_TOLERANCE),
                                                               "true_peak_at_or_under_ceiling": bool(over_now <= CEILING_TOLERANCE)}},
                                        heard=heard)
                    result.judged.append({"round": round_no, "heard": heard, "decision": call.decision, "why": call.why})
                    line["summary"] = events.readable(call.plain) or ("Done." if call.decision == "done" else "Not yet.")
                except Exception as exc:   # noqa: BLE001
                    log(f"   the judge sat the check out ({type(exc).__name__}: {str(exc)[-100:]}); the meters decide")
                    line["summary"] = "The meters decide."
        if payoff is not None and client is not None:
            # the payoff on screen (Owner 2026-11-03): the finished song plays through the chain's meter, the meter's own
            # figures are read off its window, and they are set beside Marco's measurement of the same stretch of the
            # file; agreement is the proof a viewer can see, not a claim
            result.meter = play_through_meter(strip, master.path, result, payoff, client, log, room=room)
            if result.meter is not None:
                events.emit("decision_made", source="marco", operation="the meter", status="ok" if result.meter["agree"] else "low_confidence",
                            summary="The meter and the ears agree." if result.meter["agree"] else "The meter and the ears disagree.",
                            thought="The meter on screen says what I measured. The marks are hit." if result.meter["agree"]
                            else "The meter on screen does not say what I measured. I say so rather than hide it.",
                            detail=f"meter {result.meter['meter_lufs']} LUFS against the file's {result.meter['file_lufs']} LUFS over the first "
                                   f"{result.meter['seconds']:.0f} s",
                            metrics=[("Meter", str(result.meter["meter_lufs"]), "LUFS"), ("Ears", str(result.meter["file_lufs"]), "LUFS"),
                                     ("True peak", str(result.meter["meter_peak"]), "dBTP")])
            for line in listening.highlights(result.hearing_master):
                log(f"   {line}")
        log(f"   {master.path.name}: {am.base.lufs} LUFS, {am.base.true_peak_db} dBTP, range {am.loudness_range} LU")
        if job.bpm:
            result.verdict = verifying.compare(result.mix, master.path, job.bpm)
            for line in result.verdict.text().splitlines():
                log(f"   {line}")
            if not result.verdict.passed:
                result.stopped = "the master failed verification against the mix: " + "; ".join(result.verdict.reasons)
                log(f"   {result.stopped}")
                events.emit("job_ended", source="marco", status="failed", summary="Not verified",
                            plain="The final version failed its check. Marco stops rather than guess.")
                break
        gap = result.plan.target_lufs - am.base.lufs
        over = am.base.true_peak_db - result.plan.ceiling_dbtp
        if result.ladder and result.ladder.get("ceiling_gain_db") is not None and over <= CEILING_TOLERANCE:
            log(f"   the ladder set the level: {result.ladder['ceiling_lufs']} LUFS on the loudest bars, "
                f"{am.base.lufs} LUFS integrated; no second round")
            break
        if abs(gap) <= LUFS_TOLERANCE and over <= CEILING_TOLERANCE:
            break
        # the exact figure, not a description: loudness before the limiter moves one for one with the gain stages, so
        # the whole gap goes on the limiter's gain this time (a pass that asked for less than the gap landed short)
        direction = (f"the print came out {abs(gap):.1f} LU {'under' if gap > 0 else 'over'} the target of "
                     f"{result.plan.target_lufs} LUFS" + (f" and {over:.1f} dB over the {result.plan.ceiling_dbtp} dBTP "
                     f"ceiling" if over > CEILING_TOLERANCE else "")
                     + f"; move the limiter's gain by {gap:+.1f} dB from where it stands now, the whole gap, keep every "
                     f"other control where it is, and hold the ceiling at {result.plan.ceiling_dbtp} dBTP")
        log(f"   {direction}")
        events.emit("verification_completed", source="marco", operation="the master against its target", status="failed",
                    summary="It missed the target.",
                    plain=(f"It came out too {'quiet' if gap > 0 else 'loud'}" + (" and over the safe limit" if over > CEILING_TOLERANCE else "")
                           if abs(gap) > LUFS_TOLERANCE else "It came out over the safe limit") + ". Marco goes back to fix it.", stage="Build",
                    metrics=[("Loudness", str(am.base.lufs), "LUFS"), ("True peak", str(am.base.true_peak_db), "dBTP")])
        chain = channel.read(fresh=False)

    # 7. the record, then the delivery
    result.record = bounces / f"{bouncing.print_name(job.song, 'record', job.today)}.json"
    result.record.write_text(json.dumps({
        "song": job.song, "purpose": job.purpose, "stock_only": job.stock_only, "direction": job.direction,
        "mix": str(result.mix), "master": str(result.master), "plan": result.plan.as_dict(),
        "settings": result.settings, "rounds": result.rounds, "dead": result.dead,
        "audit_mix": result.audit_mix.as_dict(), "audit_master": result.audit_master.as_dict() if result.audit_master else None,
        "deltas": deltas.as_dict() if deltas else None, "references": [r.base.name for r in refs],
        "hearing": result.hearing, "hearing_master": result.hearing_master,
        "manifest": result.manifest, "verdict": (result.verdict.__dict__ if result.verdict is not None else None),
        "bench": result.bench, "ladder": result.ladder, "judged": result.judged, "meter": result.meter, "trimmed_s": result.trimmed_s,
    }, indent=1, default=str))
    if deliver is not None and result.master is not None and not result.stopped:
        if result.audit_master is not None and result.plan is not None:
            met = bool(abs(result.plan.target_lufs - result.audit_master.base.lufs) <= LUFS_TOLERANCE
                       and result.audit_master.base.true_peak_db - result.plan.ceiling_dbtp <= CEILING_TOLERANCE)
            checkpoint("the finished song is measured and checked; say where it landed against the goal in plain words "
                       "and that you are sending it now", {"loudness_lufs": result.audit_master.base.lufs,
                                                          "true_peak_dbtp": result.audit_master.base.true_peak_db,
                                                          "goal_lufs": result.plan.target_lufs,
                                                          "ceiling_dbtp": result.plan.ceiling_dbtp, "marks_met": met},
                       "It hits the marks. Sending it to you now." if met else "It's done. Sending it to you now.")
        log("7. the delivery")
        events.stage("Deliver", "Done. It hits every mark.")
        went = deliver(result.master, result.caption)
        log("   " + went)
        # the screen says texted only when a text went out: a delivery that only names the file is not a send (run 37)
        if went.startswith("sent"):
            events.emit("message_sent", source="marco", status="ok", via="WhatsApp", text=result.caption,
                        plain="Marco is sending the song to the artist.")
        log("   " + deliver(result.mix, f"The mix as it stands, no master: {result.audit_mix.base.lufs} LUFS, "
                                        f"{result.audit_mix.base.true_peak_db} dBTP, 32-bit float."))
    from hiremarco.studio import aloud

    aloud.stop()
    events.emit("job_ended", source="marco", status="ok", summary="Done")
    return result

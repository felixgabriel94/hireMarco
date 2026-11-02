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
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from hiremarco.master import plan as planning
from hiremarco.master import roles
from hiremarco.master.rules import PURPOSES
from hiremarco.mix import audit as auditing
from hiremarco.studio import bounce as bouncing
from hiremarco.studio.chain import Channel
from hiremarco.studio.stereo_out import StereoOut

LUFS_TOLERANCE = 1.0      # LU: a print this close to its target is done
CEILING_TOLERANCE = 0.1   # dB over the true-peak ceiling that still passes (the meter's own rounding)
MAX_ROUNDS = 2


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

    @property
    def caption(self) -> str:
        if self.stopped:
            return f"Stopped: {self.stopped}"
        am, p = self.audit_master, self.plan
        if am is None or p is None:
            return "No master printed."
        return (f"Master, {p.purpose}: {am.base.lufs} LUFS integrated, true peak {am.base.true_peak_db} dBTP, "
                f"loudness range {am.loudness_range} LU, {am.sample_rate} Hz {am.subtype}. "
                f"Target was {p.target_lufs} LUFS under {p.ceiling_dbtp} dBTP.")


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
        if head >= 8 and shown[:head] == wanted[:head]:
            return True
        if shown == wanted:
            return True
    return False


def role_filled(role: str, names: list[str]) -> bool:
    """Any plugin that can fill the role is on the strip already (a run that stopped after its insert)."""
    return any(on_strip(c, names) for c in roles.CANDIDATES.get(role, []))


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


def run(job: Job, *, strip: StereoOut, bouncer: bouncing.Bouncer, channel: Channel, locators: Callable[[int, int], None],
        toggle_cycle: Callable[[], None], select_track: Callable[[], None], room: set[str] | None = None,
        client=None, critic=None, deliver: Callable[[Path, str], str] | None = None, log: Callable[[str], None] = print,
        sleep=time.sleep) -> Result:
    result = Result()
    bounces = Path(job.bounces).expanduser()
    bounces.mkdir(parents=True, exist_ok=True)
    room = room if room is not None else roles.in_the_room()

    # 1. the mix as it stands: Marco's own inserts bypassed, the artist's untouched
    log("1. the mix print")
    strip.open_mixer()
    before = strip.read()
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
        mix = bouncer.print(bouncing.MIX, bounces, mix_name)
        log(f"   {mix.path.name}: {mix.seconds} s, {mix.rate} Hz {mix.subtype}, {mix.took_s} s to print")
    result.mix = mix.path

    # 2. the audit, against the references the artist owns
    log("2. the audit")
    result.audit_mix = auditing.audit_file(mix.path)
    if result.audit_mix.base.silent:
        result.stopped = f"the mix print is silent ({mix.path.name}); nothing to master"
        log(f"   {result.stopped}")
        return result
    refs = auditing.references(job.references) if job.references and Path(job.references).exists() else []
    deltas = auditing.compare(result.audit_mix, refs)
    for line in auditing.summary(result.audit_mix, deltas).splitlines():
        log(f"   {line}")

    # 3. the plan, from the deepest brain, judged by the critic
    log("3. the plan")
    result.plan = planning.roles_for(result.audit_mix, deltas, room, purpose=job.purpose, direction=job.direction,
                                     stock_only=job.stock_only, client=client, critic=critic)
    for r in result.plan.roles:
        log(f"   {r['role']}: {r['plugin']}. {r['why']}")
    log(f"   target {result.plan.target_lufs} LUFS, ceiling {result.plan.ceiling_dbtp} dBTP")
    if result.plan.critic:
        log(f"   critic: {'approved' if result.plan.critic[0] else 'held'}: {result.plan.critic[1]}")
    if result.plan.critic and not result.plan.critic[0]:
        result.stopped = f"the critic held the plan: {result.plan.critic[1]}"
        log(f"   {result.stopped}")
        return result
    if job.purpose == "mix" or not PURPOSES[job.purpose]["limiter"]:
        result.stopped = "a mix for mastering takes no chain; the mix print is the delivery"
        return result

    # 4. the chain on the Stereo Out, in the rulebook's order
    log("4. the chain")
    names = [i.name for i in strip.read().inserts]
    for role, plugin in result.plan.chain.items():
        if role == "meter":
            continue  # meters are read by the audit, not by eye; nothing to insert for the print
        if on_strip(plugin, names) or role_filled(role, names):
            log(f"   {role} is already on the strip ({plugin})")
            continue
        after = strip.insert(plugin)
        names = [i.name for i in after.inserts]
        log(f"   {plugin} in ({role})")
    strip.bypass(False)

    # 5. the settings, read and set through the Inspector's output strip
    log("5. the settings")
    select_track()
    chain = channel.read(fresh=True)
    direction = job.direction
    for round_no in range(1, MAX_ROUNDS + 1):
        result.rounds = round_no
        settings = planning.settings_for(chain, result.audit_mix, deltas, result.plan, direction=direction,
                                         client=client)
        for c in settings.changes:
            log(f"   slot {c['slot']} {c['parameter']} = {c['value']:g} {c['unit']}: {c['why']}")
        channel.apply_changes(settings.changes, chain=chain)
        result.settings += settings.changes
        log(f"   {settings.said}")

        # 6. the master print, read back
        log(f"6. the master print (round {round_no})")
        name = bouncing.free_name(bounces, bouncing.print_name(job.song, "master" if round_no == 1 else f"master v{round_no}",
                                                               job.today))
        master = bouncer.print(bouncing.MASTER, bounces, name)
        result.master = master.path
        result.audit_master = auditing.audit_file(master.path)
        am = result.audit_master
        log(f"   {master.path.name}: {am.base.lufs} LUFS, {am.base.true_peak_db} dBTP, range {am.loudness_range} LU")
        gap = result.plan.target_lufs - am.base.lufs
        over = am.base.true_peak_db - result.plan.ceiling_dbtp
        if abs(gap) <= LUFS_TOLERANCE and over <= CEILING_TOLERANCE:
            break
        direction = (f"the print came out {abs(gap):.1f} LU {'under' if gap > 0 else 'over'} the target of "
                     f"{result.plan.target_lufs} LUFS" + (f" and {over:.1f} dB over the {result.plan.ceiling_dbtp} dBTP "
                     f"ceiling" if over > CEILING_TOLERANCE else "") + "; adjust the limiter and the gain stages only")
        log(f"   {direction}")
        chain = channel.read(fresh=False)

    # 7. the record, then the delivery
    result.record = bounces / f"{bouncing.print_name(job.song, 'record', job.today)}.json"
    result.record.write_text(json.dumps({
        "song": job.song, "purpose": job.purpose, "stock_only": job.stock_only, "direction": job.direction,
        "mix": str(result.mix), "master": str(result.master), "plan": result.plan.as_dict(),
        "settings": result.settings, "rounds": result.rounds,
        "audit_mix": result.audit_mix.as_dict(), "audit_master": result.audit_master.as_dict() if result.audit_master else None,
        "deltas": deltas.as_dict() if deltas else None, "references": [r.base.name for r in refs],
    }, indent=1, default=str))
    if deliver is not None and result.master is not None:
        log("7. the delivery")
        log("   " + deliver(result.master, result.caption))
        log("   " + deliver(result.mix, f"The mix as it stands, no master: {result.audit_mix.base.lufs} LUFS, "
                                        f"{result.audit_mix.base.true_peak_db} dBTP, 32-bit float."))
    return result

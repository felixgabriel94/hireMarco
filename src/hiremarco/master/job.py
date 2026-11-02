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
import os
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

    @property
    def caption(self) -> str:
        if self.stopped:
            return f"Stopped: {self.stopped}"
        am, p = self.audit_master, self.plan
        if am is None or p is None:
            return "No master printed."
        verified = (self.verdict.text().splitlines()[0] if self.verdict is not None
                    else "not verified against the mix (no tempo to check the pumping)")
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


CHECK_RANGE = (2, 10)   # bars: a short print that proves the chain passes audio before the master is printed


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
        printed = bouncer.print(bouncing.MASTER, folder, name)
        last_print[:] = [printed.path]
        return auditing.audit_file(printed.path)

    locators(*CHECK_RANGE)
    ensure_range(bouncer, CHECK_RANGE[1], toggle_cycle, log)
    try:
        for _ in range(4):
            heard = short_print("chain check")
            if not heard.base.silent:
                log(f"   the chain passes audio ({heard.base.lufs} LUFS over bars {CHECK_RANGE[0]} to {CHECK_RANGE[1]})")
                if mix_path is not None and job.bar_s and last_print:
                    # the same eight bars of the mix against the check, loudness-matched: a ducker on the output
                    # shows as new modulation at the beat rate here, before a full print (Owner 2026-11-02)
                    v = verifying.compare(mix_path, last_print[0], job.bpm, start_s=(CHECK_RANGE[0] - 1) * job.bar_s,
                                          length_s=(CHECK_RANGE[1] - CHECK_RANGE[0]) * job.bar_s, tonal_only=True)
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


def mark_in_ledger(plugin: str, status: str, why: str) -> None:
    """A finding about a plug-in written to the license ledger, as Logic names it."""
    from hiremarco.studio.ledger import mark

    mark(roles.MAPS / "license_ledger.json", f"{plugin} (s/s)", status, why)


def run(job: Job, *, strip: StereoOut, bouncer: bouncing.Bouncer, channel: Channel, locators: Callable[[int, int], None],
        toggle_cycle: Callable[[], None], select_track: Callable[[], None], room: set[str] | None = None,
        client=None, critic=None, deliver: Callable[[Path, str], str] | None = None, log: Callable[[str], None] = print,
        sleep=time.sleep, mark_plugin: Callable[[str, str, str], None] | None = mark_in_ledger,
        look_at_face: Callable[[], object] | None = None,
        listen: Callable[..., dict | None] | None = None) -> Result:
    result = Result()
    bounces = Path(job.bounces).expanduser()
    bounces.mkdir(parents=True, exist_ok=True)
    room = room if room is not None else roles.in_the_room()
    lock = hold_lock(job)
    try:
        return _run(job, result, bounces, room, strip=strip, bouncer=bouncer, channel=channel, locators=locators,
                    toggle_cycle=toggle_cycle, select_track=select_track, client=client, critic=critic, deliver=deliver,
                    log=log, sleep=sleep, mark_plugin=mark_plugin, look_at_face=look_at_face, listen=listen)
    finally:
        release_lock(lock)


def inserts_ledger(song: str) -> Path:
    from hiremarco import config

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
         select_track, client, critic, deliver, log, sleep, mark_plugin, look_at_face, listen) -> Result:

    # 1. the mix as it stands: Marco's own inserts bypassed, the artist's untouched
    log("1. the mix print")
    strip.open_mixer()
    before = strip.read()
    # what was in and what was out before the job: an insert the artist or an earlier run left bypassed stays so
    was_in = {(i.name, round(i.y)) for i in before.inserts if i.marcos and not i.bypassed}
    seen = {(i.name, round(i.y)) for i in before.inserts}
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
    if listen is not None:
        # the ears beyond the meters, against the first reference when there is one
        first_ref = next(iter(sorted(p for p in Path(job.references).iterdir() if p.suffix.lower() in (".wav", ".aiff", ".aif", ".flac"))), None) \
            if job.references and Path(job.references).is_dir() else None
        result.hearing = listen(mix.path, reference=first_ref)
        for line in listening.highlights(result.hearing):
            log(f"   {line}")

    # 3. the plan, from the deepest brain, judged by the critic
    log("3. the plan")
    result.plan = planning.roles_for(result.audit_mix, deltas, room, purpose=job.purpose, direction=job.direction,
                                     stock_only=job.stock_only, client=client, critic=critic, hearing=result.hearing)
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
    strip.open_mixer()   # the Mixer window was gone once by this step (live 2026-11-02, run 13); it comes back
    # what counts as on the strip: every insert that was there before the job, bypassed or not. A run that died
    # mid-way leaves the whole chain bypassed, and counting only what was in doubled the chain (runs 14 and 23,
    # live 2026-11-02); a plug-in the ledger holds inactive is kept out by the room, whatever its state
    names = [i.name for i in before.inserts]
    claimed: set[str] = set()
    claimed_rows: set[tuple[str, int]] = set()   # the exact rows that fill a role: a third Pro-Q 3 is not one of them
    plugin_of: dict[str, str] = {}   # the strip's short name -> the plan's plugin, for the ledger
    kept_out: set[tuple[str, int]] = set()   # rows a face notice put out: never brought back in
    for role, plugin in result.plan.chain.items():
        if role == "meter":
            continue  # meters are read by the audit, not by eye; nothing to insert for the print
        there = role_filled(role, names, set(), room)
        if there is not None:
            names.remove(there)   # that one row is taken; a second Pro-Q 3 on the strip can fill the next EQ role
            claimed.add(there)
            row = next((i for i in before.inserts if i.name == there and (i.name, round(i.y)) not in claimed_rows), None)
            if row is not None:
                claimed_rows.add((row.name, round(row.y)))
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
            new_rows = [i for i in after.inserts if (i.name, round(i.y)) not in seen]
            if new_rows:
                claimed_rows.add((new_rows[-1].name, round(new_rows[-1].y)))
            plugin_of[landed[-1]] = candidate
            face = seen_face[0] if seen_face else None
            if face is None or face.licensed:
                if candidate != plugin:
                    for entry in result.plan.roles:   # the record names what landed, not what was planned
                        if entry["role"] == role:
                            entry["plugin"] = candidate
                log(f"   {landed[-1]} in ({role})" + ("; its face reads licensed" if face is not None else ""))
                break
            log(f"   {landed[-1]} shows a notice on its face: {face.notice!r}; left out")
            row = [i for i in after.inserts if i.name == landed[-1]][-1]
            strip.bypass(True, rows=[row.y])
            if mark_plugin is not None:
                mark_plugin(candidate, "inactive", f"its window said {face.notice!r} on {job.today}")
            result.dead.append(candidate)
            seen.add((landed[-1], round(row.y)))   # not to be brought back in after the chain
            kept_out.add((landed[-1], round(row.y)))
        else:
            log(f"   nothing licensed in the room for {role}; the chain goes on without it")
    # an insert Marco put there himself that fills no role in this plan, or a stray, stays out; the artist's own
    # inserts (never in the ledger) come back exactly as they were
    marcos = {row["name"] for row in marcos_inserts(job.song)}
    back_in = [i.y for i in strip.read().inserts
               if i.marcos and (i.name, round(i.y)) not in kept_out
               and not (i.name in marcos and (i.name, round(i.y)) not in claimed_rows)
               and ((i.name, round(i.y)) in was_in or (i.name, round(i.y)) not in seen or (i.name, round(i.y)) in claimed_rows)]
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

    # 4b. the chain proves it passes audio before anything is set or printed for real
    log("4b. the chain check")
    result.dead += [d for d in prove_chain(strip, bouncer, locators, toggle_cycle, job, log, plugin_of=plugin_of, mark=mark_plugin,
                                           mix_path=result.mix)
                    if d not in result.dead]

    # 5. the settings, read and set through the Inspector's output strip
    log("5. the settings")
    select_track()
    chain = channel.read(fresh=True)
    direction = job.direction
    for round_no in range(1, MAX_ROUNDS + 1):
        result.rounds = round_no
        settings = planning.settings_for(chain, result.audit_mix, deltas, result.plan, direction=direction,
                                         client=client, hearing=result.hearing)
        for c in settings.changes:
            log(f"   slot {c['slot']} {c['parameter']} = {c['value']:g} {c['unit']}: {c['why']}")
        try:
            channel.apply_changes(settings.changes, chain=chain)
        except Exception as exc:
            if round_no == 1:
                raise
            log(f"   the second pass gave nothing usable ({str(exc)[-120:]}); the first print stands")
            result.rounds = round_no - 1
            break
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
        if listen is not None:
            result.hearing_master = listen(master.path)
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
                break
        gap = result.plan.target_lufs - am.base.lufs
        over = am.base.true_peak_db - result.plan.ceiling_dbtp
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
    }, indent=1, default=str))
    if deliver is not None and result.master is not None and not result.stopped:
        log("7. the delivery")
        log("   " + deliver(result.master, result.caption))
        log("   " + deliver(result.mix, f"The mix as it stands, no master: {result.audit_mix.base.lufs} LUFS, "
                                        f"{result.audit_mix.base.true_peak_db} dBTP, 32-bit float."))
    return result

"""The master job through fakes: both prints, the audit, the plan, the chain, the settings, the record, the delivery."""

import json

import pytest
from pathlib import Path

import numpy as np
import soundfile as sf

from hiremarco.master import job as jobs
from hiremarco.master import plan as planning
from hiremarco.master.plan import MasterPlan, Settings
from hiremarco.studio import bounce as bouncing
from hiremarco.studio.chain import Chain, Slot
from hiremarco.studio.plugins import PluginState
from hiremarco.studio.stereo_out import Insert, Strip

RATE = 48000


def test_end_bar_counts_the_lead_in_and_the_tail():
    assert jobs.end_bar_for(208.48, 99) == 1 + 86 + 1 + 1
    assert jobs.end_bar_for(60, 120) == 33


def test_on_strip_matches_logics_short_names():
    assert jobs.on_strip("Shadow Hills Mastering Compressor", ["Console Re", "Shadow Hills Mastering Compress"])
    assert jobs.on_strip("Pro-L 2", ["Pro-L 2"]) and not jobs.on_strip("Pro-L 2", ["Pro-Q 3"])


class FakeStrip:
    def __init__(self):
        self.inserts = [Insert("Console Re", False, 585, 163)]
        self.log = []

    def open_mixer(self):
        self.log.append("mixer")

    def read(self):
        return Strip((585, 196, 58, 9), list(self.inserts), None)

    def bypass(self, on, names=None, rows=None):
        self.log.append(("bypass", on))
        for i in self.inserts:
            if i.marcos and (rows is None or any(abs(i.y - r) < 4 for r in rows)):
                i.bypassed = on
        return self.read()

    def insert(self, name, look=None):
        self.log.append(("insert", name))
        self.inserts.append(Insert(name[:30], False, 585, 180 + 17 * len(self.inserts)))
        if look is not None:
            look()
        return self.read()

    def remove(self, name, row):
        self.log.append(("remove", name))
        self.inserts = [i for i in self.inserts if not (i.name == name and abs(i.y - row) < 4)]
        return self.read()

    def close_windows(self):
        return 0


class FakeBouncer:
    def __init__(self, folder, lufs_per_print):
        self.folder, self.levels, self.prints, self.opened = folder, iter(lufs_per_print), [], 0
        self.end = None   # the right locator the job last set; the dialog shows it once Cycle is on

    def open(self, spec):
        self.opened += 1
        shown = self.end if self.opened > 1 and self.end is not None else 257
        return bouncing.Opened("Requires 1 MB (Time 0:10)", " 1 1 1 1", f" {shown} 1 1 1")

    def cancel(self):
        return "cancelled"

    def print(self, spec, folder, name, timeout_s=None):
        from hiremarco.mix.ears import lufs

        rng = np.random.default_rng(1)   # the same noise every print, as an offline bounce of the same bars is the same
        level = next(self.levels)
        audio = rng.standard_normal((4 * RATE, 2)) * 0.05
        audio *= 10 ** ((level - lufs(audio, RATE)) / 20)      # lands exactly on the loudness asked for
        audio = np.clip(audio, -0.95, 0.95)
        path = Path(folder) / f"{name}.wav"
        sf.write(path, audio.astype("float32"), RATE, subtype="FLOAT" if spec.bits.startswith("32") else "PCM_24")
        self.prints.append((spec.bits, path.name))
        return bouncing.Printed(path, 4.0, RATE, "FLOAT", 2, 1.0)


class FakeChannel:
    def __init__(self):
        self.applied = []

    def read(self, fresh=True):
        return Chain([Slot(1, "Pro-L 2", False, PluginState("Pro-L 2", {"Gain": 0.0}, {"Gain": (0, 100)}, {}))])

    def apply_changes(self, changes, chain=None):
        self.applied.append(changes)
        return {}


def test_the_job_prints_audits_plans_sets_and_delivers(tmp_path, monkeypatch):
    # prints: the mix, the chain check, the master
    strip, bouncer, channel = FakeStrip(), FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB short"}], -12.0, -1.0, "A clean mix.", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings(
        [{"slot": 1, "parameter": "Gain", "value": 6, "unit": "dB", "why": "6 dB in stages"}], "Up 6 dB."))
    toggled, delivered, lines = [], [], []
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: (setattr(bouncer, "end", b), lines.append(f"locators {a} {b}")),
                      toggle_cycle=lambda: toggled.append(1), select_track=lambda: lines.append("selected"),
                      room={"Pro-L 2"}, deliver=lambda p, c: delivered.append((p.name, c)) or "sent", log=lines.append)
    assert toggled == [1]                                                       # the first open showed the project end
    assert [p[0] for p in bouncer.prints] == ["32-bit float", "24-bit", "24-bit"]
    assert "chain check" in bouncer.prints[1][1] and result.dead == []
    assert "locators 2 10" in lines                                             # the chain check's short range...
    assert max(i for i, l in enumerate(lines) if l == "locators 1 90") > lines.index("locators 2 10")   # ...put back
    assert result.mix.name == "song - mix 2026-11-02.wav" and result.master.name == "song - master 2026-11-02.wav"
    assert strip.log[:2] == ["mixer", ("insert", "Pro-L 2")] or ("insert", "Pro-L 2") in strip.log
    assert channel.applied[0][0]["parameter"] == "Gain" and result.rounds == 1
    assert result.audit_master is not None and abs(result.audit_master.base.lufs - plan.target_lufs) <= 1.5
    assert [d[0] for d in delivered] == ["song - master 2026-11-02.wav", "song - mix 2026-11-02.wav"]
    assert "LUFS integrated" in delivered[0][1]
    record = json.loads(result.record.read_text())
    assert record["plan"]["roles"][0]["plugin"] == "Pro-L 2" and record["rounds"] == 1


def test_a_held_plan_stops_before_the_chain(tmp_path, monkeypatch):
    strip, bouncer, channel = FakeStrip(), FakeBouncer(tmp_path, [-30.0]), FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": ""}], -12.0, -1.0, "", "demo",
                      critic=(False, "the rules say no"))
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2"}, log=lambda s: None)
    assert result.stopped.startswith("the critic held") and result.master is None
    assert not any(isinstance(e, tuple) and e[0] == "insert" for e in strip.log)


def test_a_silent_chain_names_the_insert_that_eats_the_sound(tmp_path, monkeypatch):
    # prints: the mix, a silent chain check, silent again without the last insert, sound without the one before, the
    # check again with the dead one out, the master
    strip = FakeStrip()
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -150.0, -150.0, -20.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "glue", "plugin": "Shadow Hills Mastering Compress", "why": "2 dB"},
                       {"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings(
        [{"slot": 1, "parameter": "Gain", "value": 6, "unit": "dB", "why": "6 dB"}], "Up."))
    marked = []
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2", "Shadow Hills Mastering Compress"},
                      log=lambda s: None, mark_plugin=lambda p, s, w: marked.append((p, s)))
    assert result.dead == ["Shadow Hills Mastering Compress"]
    assert marked == [("Shadow Hills Mastering Compress", "inactive")]
    states = {i.name: i.bypassed for i in strip.inserts}
    assert states["Shadow Hills Mastering Compress"[:30]] is True and states["Pro-L 2"] is False
    assert result.master is not None and result.audit_master.base.lufs > -60


def test_a_face_with_a_notice_puts_the_plugin_out_before_any_print(tmp_path, monkeypatch):
    from types import SimpleNamespace

    strip = FakeStrip()
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()   # mix, chain check, master
    plan = MasterPlan([{"role": "glue", "plugin": "Shadow Hills Mastering Compress", "why": "2 dB"},
                       {"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings(
        [{"slot": 1, "parameter": "Gain", "value": 6, "unit": "dB", "why": "6 dB"}], "Up."))
    faces = iter([SimpleNamespace(licensed=False, notice="SUBSCRIPTION NOT ACTIVE", plugin="Shadow Hills"),
                  SimpleNamespace(licensed=True, notice="", plugin="Pro-L 2")])
    marked = []
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2", "Shadow Hills Mastering Compress"},
                      log=lambda s: None, mark_plugin=lambda p, s, w: marked.append((p, s, w)),
                      look_at_face=lambda: next(faces))
    assert marked[0][:2] == ("Shadow Hills Mastering Compress", "inactive") and "SUBSCRIPTION NOT ACTIVE" in marked[0][2]
    assert result.dead == ["Shadow Hills Mastering Compress"]
    states = {i.name: i.bypassed for i in strip.inserts}
    assert states["Shadow Hills Mastering Compress"[:30]] is True and states["Pro-L 2"] is False
    assert result.master is not None


def test_a_print_off_target_gets_one_more_round(tmp_path, monkeypatch):
    # prints: the mix, the chain check, a master under target, the second master
    strip, bouncer, channel = FakeStrip(), FakeBouncer(tmp_path, [-30.0, -20.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": ""}], -12.0, -1.0, "", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    seen = []
    monkeypatch.setattr(planning, "settings_for", lambda chain, a, d, p, direction="", client=None, **kw: seen.append(direction) or Settings(
        [{"slot": 1, "parameter": "Gain", "value": 6, "unit": "dB", "why": ""}], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2"}, log=lambda s: None)
    assert result.rounds == 2 and "under the target" in seen[1] and "move the limiter's gain by +8.0 dB" in seen[1]
    assert result.master.name == "song - master v2 2026-11-02.wav"


def test_a_notice_sends_in_the_rooms_next_candidate_for_the_role(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from hiremarco.master import roles

    fallback = roles.CANDIDATES["glue"][-1]
    strip = FakeStrip()
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "glue", "plugin": "Shadow Hills Mastering Compress", "why": "2 dB"},
                       {"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], "Nothing."))
    faces = iter([SimpleNamespace(licensed=False, notice="DEMO MODE", plugin="Shadow Hills"),
                  SimpleNamespace(licensed=True, notice="", plugin=fallback),
                  SimpleNamespace(licensed=True, notice="", plugin="Pro-L 2")])
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None,
                      room={"Pro-L 2", "Shadow Hills Mastering Compress", fallback}, log=lambda s: None,
                      mark_plugin=lambda p, s, w: None, look_at_face=lambda: next(faces))
    inserted = [e[1] for e in strip.log if isinstance(e, tuple) and e[0] == "insert"]
    assert inserted == ["Shadow Hills Mastering Compress", fallback, "Pro-L 2"]
    assert result.plan.chain["glue"] == fallback and result.dead == ["Shadow Hills Mastering Compress"]
    assert json.loads(result.record.read_text())["plan"]["roles"][0]["plugin"] == fallback


def test_the_ears_ride_with_the_audit_into_the_plan_and_the_record(tmp_path, monkeypatch):
    strip, bouncer, channel = FakeStrip(), FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")
    got = {}
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: (got.__setitem__("plan", k.get("hearing")), plan)[1])
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: (got.__setitem__("settings", k.get("hearing")), Settings([], ""))[1])
    heard = {"audiobox_aesthetics": {"mix": {"CE": 6.0, "CU": 7.0, "PC": 5.0, "PQ": 6.5}}}
    listened = []
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2"}, log=lambda s: None,
                      listen=lambda p, reference=None: listened.append((p.name, reference)) or heard)
    assert result.hearing == heard and got["plan"] == heard and got["settings"] == heard
    assert listened[0] == ("song - mix 2026-11-02.wav", None) and listened[1][0].startswith("song - master")
    assert json.loads(result.record.read_text())["hearing"]["audiobox_aesthetics"]["mix"]["PQ"] == 6.5


def test_a_chain_left_bypassed_by_a_dead_run_is_reused_not_doubled(tmp_path, monkeypatch):
    strip = FakeStrip()
    strip.inserts += [Insert("Gain", True, 585, 180), Insert("Pro-L 2", True, 585, 197)]   # the last run died mid-way
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "gain", "plugin": "Gain", "why": "8 dB"}, {"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}],
                      -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Gain", "Pro-L 2"}, log=lambda s: None)
    assert not any(isinstance(e, tuple) and e[0] == "insert" for e in strip.log)          # nothing inserted twice
    assert [i.bypassed for i in strip.inserts if i.name in ("Gain", "Pro-L 2")] == [False, False]   # back in for the master
    assert result.master is not None


def test_a_plugin_outside_the_room_never_fills_a_role():
    assert jobs.role_filled("glue", ["Shadow Hil"], set(), room={"Pro-L 2"}) is None
    assert jobs.role_filled("glue", ["UAD Shadow"], set(), room={"UAD Shadow Hills Mastering Comp"}) == "UAD Shadow"


def test_two_of_the_same_eq_on_the_strip_fill_two_eq_roles(tmp_path, monkeypatch):
    strip = FakeStrip()
    strip.inserts += [Insert("Pro-Q 3", False, 585, 180), Insert("Pro-Q 3", False, 585, 197), Insert("Pro-L 2", False, 585, 214)]
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "corrective_eq", "plugin": "Pro-Q 3", "why": "254 Hz"}, {"role": "tonal_eq", "plugin": "Pro-Q 3", "why": "tilt"},
                       {"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
             toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-Q 3", "Pro-L 2"}, log=lambda s: None)
    assert not any(isinstance(e, tuple) and e[0] == "insert" for e in strip.log)   # a third Pro-Q 3 was not added


def test_one_master_job_at_a_time_on_this_mac(tmp_path, monkeypatch):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    lock = jobs.hold_lock(job)
    assert lock is not None and "song started" in lock.read_text()
    with pytest.raises(RuntimeError, match="another master job holds the lock"):
        jobs.hold_lock(job)
    jobs.release_lock(lock)
    assert not lock.exists() and jobs.hold_lock(job) is not None


def test_a_stray_insert_marco_made_stays_out_and_the_artists_come_back(tmp_path, monkeypatch):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    jobs.remember_insert("song", "Kickstart ", "Gain", stray=True)
    strip = FakeStrip()
    strip.inserts += [Insert("Ozone 11 Ma", False, 585, 180),   # the artist's own, not in the ledger
                      Insert("Kickstart ", True, 585, 197), Insert("Pro-L 2", False, 585, 214)]
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
             toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2"}, log=lambda s: None)
    states = {i.name: i.bypassed for i in strip.inserts}
    assert states["Kickstart "] is True and states["Ozone 11 Ma"] is False and states["Pro-L 2"] is False
    assert [r["name"] for r in jobs.marcos_inserts("song")] == ["Kickstart "]


def test_a_stray_with_a_claimed_name_stays_out_by_its_row(tmp_path, monkeypatch):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    for name, plugin, stray in (("Pro-Q 3", "Pro-Q 3", False), ("Pro-L 2", "Pro-L 2", False), ("Pro-Q 3", "Pro-Q 3", True)):
        jobs.remember_insert("song", name, plugin, stray=stray)
    strip = FakeStrip()
    strip.inserts += [Insert("Pro-Q 3", False, 585, 180), Insert("Pro-L 2", False, 585, 197), Insert("Pro-Q 3", True, 585, 214)]
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "corrective_eq", "plugin": "Pro-Q 3", "why": "254 Hz"}, {"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}],
                      -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
             toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-Q 3", "Pro-L 2"}, log=lambda s: None)
    rows = {round(i.y): i.bypassed for i in strip.inserts}
    assert rows[180] is False and rows[197] is False and rows[214] is True   # the third Pro-Q 3 stays out


def test_a_master_that_fails_verification_is_not_delivered(tmp_path, monkeypatch):
    from hiremarco.mix import verify

    strip, bouncer, channel = FakeStrip(), FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    calls = []

    def compare(mix, master, bpm, **kw):
        calls.append((mix.name, master.name, kw.get("tonal_only", False)))
        if kw.get("tonal_only"):
            return verify.Verdict(True, checked=["eight bars clean"])
        return verify.Verdict(False, reasons=["the master pumps at the beat rate: 4.0 dB of swing where the mix has 0.3 dB"],
                              checked=["loudness-matched"])
    monkeypatch.setattr(verify, "compare", compare)
    delivered = []
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02", bpm=100.0)
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2"}, log=lambda s: None,
                      deliver=lambda p, c: delivered.append(p.name) or "sent")
    assert calls[0][2] is True and calls[1][2] is False                   # the chain check first, then the master
    assert result.stopped.startswith("the master failed verification") and delivered == []
    assert "NOT VERIFIED" in result.verdict.text() and json.loads(result.record.read_text())["verdict"]["passed"] is False
    assert result.caption.startswith("Stopped: the master failed verification")
    assert [m["status"] for m in result.manifest] == ["yours", "planned"]   # Console Recall is the artist's; Pro-L 2 is Marco's from this run


def test_the_caption_says_verified_when_the_master_passes(tmp_path, monkeypatch):
    from hiremarco.mix import verify

    strip, bouncer, channel = FakeStrip(), FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    monkeypatch.setattr(verify, "compare", lambda *a, **k: verify.Verdict(True, checked=["no new modulation", "every band within reach"]))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02", bpm=100.0)
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2"}, log=lambda s: None)
    assert result.master is not None and "Verified: no new modulation; every band within reach." in result.caption


def test_the_bench_keeps_what_moves_the_sound_and_takes_off_what_does_not(tmp_path, monkeypatch):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    strip = FakeStrip()
    # prints: mix, chain check, bench full, bench without Gain (6 dB lower: Gain earns its place), bench without
    # Pro-L 2 (the same: it changes nothing), the master
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -20.0, -26.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "gain", "plugin": "Gain", "why": "8 dB"}, {"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}],
                      -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Gain", "Pro-L 2"}, log=lambda s: None,
                      bench=True)
    assert [(b["name"], b["earned"]) for b in result.bench] == [("Gain", True), ("Pro-L 2", False)]
    assert ("remove", "Pro-L 2") in strip.log and [i.name for i in strip.inserts] == ["Console Re", "Gain"]
    assert "kept Gain; taken off Pro-L 2" in result.caption and json.loads(result.record.read_text())["bench"][1]["earned"] is False


def test_inserts_come_back_in_even_when_a_new_insert_shifts_the_rows(tmp_path, monkeypatch):
    class ShiftingStrip(FakeStrip):
        def insert(self, name, look=None):
            for i in self.inserts:            # the strip scrolls: every row moves up when a new one lands
                i.y -= 17
            return super().insert(name, look)

    strip = ShiftingStrip()
    strip.inserts += [Insert("Gain", False, 585, 180), Insert("Ozone 11 I", False, 585, 197)]
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "gain", "plugin": "Gain", "why": "8 dB"}, {"role": "glue", "plugin": "UAD Manley Variable Mu", "why": "glue"},
                       {"role": "width", "plugin": "Ozone 11 Imager", "why": "wide low end"}], -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
             toggle_cycle=lambda: None, select_track=lambda: None, room={"Gain", "UAD Manley Variable Mu", "Ozone 11 Imager"},
             log=lambda s: None)
    states = {i.name: i.bypassed for i in strip.inserts}
    assert states["Gain"] is False and states["Ozone 11 I"] is False and states["UAD Manley Variable Mu"[:30]] is False


def _events(tmp_path):
    from hiremarco import events

    return [json.loads(l) for l in (tmp_path / "state" / events.NAME).read_text().splitlines()]


def _plain_run(tmp_path, monkeypatch, *, deliver, channel=None, job=None, bench=False):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    strip, bouncer, channel = FakeStrip(), FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), channel or FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB short"}], -12.0, -1.0, "A clean mix.", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings(
        [{"slot": 1, "parameter": "Gain", "value": 6, "unit": "dB", "why": "6 dB in stages"},
         {"slot": 1, "parameter": "Band 1 Shape", "value": 0, "unit": "", "choice": "gain", "why": "junk"}], "Up 6 dB."))
    lines = []
    job = job or jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2"}, deliver=deliver, log=lines.append,
                      bench=bench)
    return result, lines, strip


def test_the_screen_says_texted_only_when_a_text_went_out(tmp_path, monkeypatch):
    # run 37 (2026-11-03): the delivery only named the file, and the screen showed a green bubble with ticks
    _plain_run(tmp_path, monkeypatch, deliver=lambda p, c: f"{p} ({c})")
    kinds = [r["kind"] for r in _events(tmp_path)]
    assert "message_sent" not in kinds and any(r.get("plain") == "Done. It hits every mark." for r in _events(tmp_path))
    _plain_run(tmp_path, monkeypatch, deliver=lambda p, c: "sent to the Owner")
    sent = [r for r in _events(tmp_path) if r["kind"] == "message_sent"]
    assert len(sent) == 1 and sent[0]["via"] == "WhatsApp" and sent[0]["plain"] == "Marco is sending the song to the artist."


def test_the_record_carries_what_landed_and_the_log_names_what_did_not(tmp_path, monkeypatch):
    class Channel(FakeChannel):
        def apply_changes(self, changes, chain=None):
            self.landed = [changes[0]]
            self.dropped = ["slot 1 Band 1 Shape: 'gain' is not one of its options"]
            return {}

    result, lines, _ = _plain_run(tmp_path, monkeypatch, deliver=lambda p, c: "sent", channel=Channel())
    assert [c["parameter"] for c in result.settings] == ["Gain"]
    assert json.loads(result.record.read_text())["settings"] == result.settings
    assert any(l.startswith("   not applied: slot 1 Band 1 Shape") for l in lines)


def test_the_goal_is_said_before_any_tool_moves_and_the_check_reads_against_it(tmp_path, monkeypatch):
    _plain_run(tmp_path, monkeypatch, deliver=lambda p, c: "sent")
    rows = _events(tmp_path)
    goal = next(i for i, r in enumerate(rows) if r.get("plain", "").startswith("Marco's goal:"))
    first_build = next(i for i, r in enumerate(rows) if r.get("stage") == "Build")
    assert goal < first_build and rows[goal + 1]["metrics"][0] == {"label": "Loudness", "value": "-12.0", "unit": "LUFS"}
    check = next(r for r in rows if r["kind"] == "tool_completed" and r.get("task") is None and r.get("word") == "checked")
    assert check["summary"] == "On the mark." and [m["label"] for m in check["metrics"]] == ["Loudness", "True peak", "Range"]


def test_past_the_budget_the_tests_are_skipped_and_the_screen_says_so(tmp_path, monkeypatch):
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02", budget_s=0)
    result, lines, strip = _plain_run(tmp_path, monkeypatch, deliver=lambda p, c: "sent", job=job, bench=True)
    assert ("bypass", True) not in strip.log and result.master is not None
    skipped = [r for r in _events(tmp_path) if r["kind"] == "tool_skipped"]
    assert skipped and skipped[0]["summary"] == "No time left for the tests." and any("out of time for the tests" in l for l in lines)


class FakeJudge:
    """The ears and the brain as the test scripts them: one answer per tool, and one for the finished song."""

    def __init__(self, verdicts, heard="none", check=("done", "It hits the mark.")):
        self.verdicts, self.heard, self.check, self.asked = verdicts, heard, check, []

    def hear(self, a, b, *, job, what):
        self.asked.append((job, what))
        return {"hears": "scripted", "note": "I hear it.", "difference": self.heard}

    def decide(self, job, choices, *, rule, numbers, heard=None):
        self.asked.append((job, numbers.get("tool")))
        from hiremarco.master.judge import Call

        if job == "check_verdict":
            return Call(self.check[0], "why", self.check[1])
        decision, plain = self.verdicts[numbers["tool"]]
        return Call(decision, "why", plain)


def _judged_run(tmp_path, monkeypatch, judge):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(jobs, "Judge", lambda client: judge)
    strip = FakeStrip()
    # prints: mix, chain check, bench full, bench without Gain (6 dB lower), bench without Pro-L 2 (the same), the master
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -20.0, -26.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "gain", "plugin": "Gain", "why": "8 dB"}, {"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}],
                      -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    lines = []
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Gain", "Pro-L 2"}, log=lines.append,
                      bench=True, client=object())
    return result, lines, strip


def test_the_brain_judges_each_tool_inside_the_rule_and_the_record_says_who_decided(tmp_path, monkeypatch):
    # Gain measures 6 dB and the brain removes it anyway (it hurts); Pro-L 2 measures nothing, the ears hear nothing,
    # the brain says keep, and the playbook overrules: knowledge bounds, wisdom judges inside (Owner 2026-11-03)
    judge = FakeJudge({"Gain": ("remove", "I take it off. It pushes too hard."), "Pro-L 2": ("keep", "I keep it.")})
    result, lines, strip = _judged_run(tmp_path, monkeypatch, judge)
    assert [(b["name"], b["measured"], b["earned"]) for b in result.bench] == [("Gain", True, False), ("Pro-L 2", False, False)]
    assert ("remove", "Gain") in strip.log and ("remove", "Pro-L 2") in strip.log
    assert any("the playbook overrules the brain on Pro-L 2" in l for l in lines)
    assert [a[0] for a in judge.asked] == ["bench_ear", "bench_verdict", "bench_ear", "bench_verdict", "check_ear", "check_verdict"]
    assert result.judged == [{"round": 1, "heard": {"hears": "scripted", "note": "I hear it.", "difference": "none"}, "decision": "done", "why": "why"}]
    rows = _events(tmp_path)
    tested = [r for r in rows if r["kind"] == "tool_completed" and r.get("word") == "tested"][1:]   # after the short test through the tools
    assert tested[0]["summary"] == "I take it off." and tested[1]["summary"] == "I keep it."   # the first plain sentence
    checked = [r for r in rows if r["kind"] == "tool_completed" and r.get("word") == "checked"]
    assert checked[-1]["summary"] == "It hits the mark." and json.loads(result.record.read_text())["judged"] == result.judged


def test_the_finished_song_plays_through_the_meter_and_the_meter_is_set_beside_the_ears(tmp_path, monkeypatch):
    # Owner 2026-11-03: the audience sees the marks hit; the proof is the meter on screen agreeing with the file
    from hiremarco.studio import face as faces

    played = []
    monkeypatch.setattr(faces, "read_meter", lambda png, client=None: played.append(png) or
                        {"integrated_lufs": -12.1, "true_peak_dbtp": -1.0, "range_lu": 5.0, "plugin": "Loudness Meter"})
    judge = FakeJudge({"Gain": ("keep", "I keep it."), "Pro-L 2": ("keep", "I keep it.")}, heard="helps")
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(jobs, "Judge", lambda client: judge)
    strip, channel = FakeStrip(), FakeChannel()
    bouncer = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0])
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}, {"role": "meter", "plugin": "Loudness Meter", "why": "the marks"}],
                      -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2", "Loudness Meter"}, log=lambda s: None,
                      client=object(), payoff=lambda name, row, seconds: played.append((name, seconds)) or b"png")
    assert played[0] == ("Loudness Meter", jobs.PAYOFF_SECONDS) and played[1] == b"png"
    assert result.meter["agree"] is True and result.meter["meter_lufs"] == -12.1 and abs(result.meter["file_lufs"] - -12.0) <= 1.5
    rows = _events(tmp_path)
    assert any(r.get("plain", "").startswith("Marco plays the finished song through the meter") for r in rows)
    shown = next(r for r in rows if r["kind"] == "decision_made" and r.get("operation") == "the meter")
    assert shown["summary"] == "The meter and the ears agree." and [m["label"] for m in shown["metrics"]] == ["Meter", "Ears", "True peak"]
    assert json.loads(result.record.read_text())["meter"]["plugin"] == "Loudness Meter"


def test_a_meter_that_cannot_be_read_says_so_and_the_master_still_ships(tmp_path, monkeypatch):
    from hiremarco.studio import face as faces

    monkeypatch.setattr(faces, "read_meter", lambda png, client=None: (_ for _ in ()).throw(ValueError("unreadable")))
    judge = FakeJudge({}, heard="helps")
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(jobs, "Judge", lambda client: judge)
    strip, channel = FakeStrip(), FakeChannel()
    bouncer = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0])
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}, {"role": "meter", "plugin": "Loudness Meter", "why": "the marks"}],
                      -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2", "Loudness Meter"}, log=lambda s: None,
                      client=object(), payoff=lambda name, row, seconds: b"png")
    assert result.meter is None and result.master is not None and not result.stopped
    assert any(r["kind"] == "tool_completed" and r.get("summary") == "The meter could not be read." for r in _events(tmp_path))


def test_the_payoff_takes_the_rooms_meter_when_the_plan_named_none(tmp_path, monkeypatch):
    # run 39 (2026-11-03): the plan named no meter and the payoff was skipped; the audience's proof is not the plan's call
    from hiremarco import config
    from hiremarco.studio import face as faces

    monkeypatch.setattr(faces, "read_meter", lambda png, client=None: {"integrated_lufs": -12.0, "true_peak_dbtp": -1.0, "range_lu": 5.0, "plugin": "Loudness Meter"})
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(jobs, "Judge", lambda client: FakeJudge({"Pro-L 2": ("keep", "I keep it.")}, heard="helps"))
    strip, channel = FakeStrip(), FakeChannel()
    bouncer = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0])
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")   # no meter named
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    played = []
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2", "Loudness Meter"}, log=lambda s: None,
                      client=object(), payoff=lambda name, row, seconds: played.append(name) or b"png")
    assert played == ["Loudness Meter"] and result.meter["agree"] is True
    assert ("remove", "Loudness Meter") in strip.log   # on for the payoff, off after: no stray for the next run
    assert result.judged[0]["decision"] == "done"


def test_the_silent_tail_is_cut_off_the_master_with_a_fade(tmp_path):
    # run 39 (2026-11-03): the print ran 77 s past the song and the chain lifted the room's hiss into a fan sound
    import numpy as np
    import soundfile as sf

    rate = 48000
    t = np.linspace(0, 10, rate * 10, dtype="float32")
    music = 0.3 * np.sin(2 * np.pi * 220 * t[: rate * 4])          # four seconds of tone
    hiss = 0.002 * np.random.default_rng(1).standard_normal(rate * 6).astype("float32")   # six seconds of hiss, about -54 dBFS
    path = tmp_path / "m.wav"
    sf.write(str(path), np.column_stack([np.concatenate([music, hiss])] * 2), rate, subtype="PCM_24")
    cut = jobs.trim_tail(path)
    audio, _ = sf.read(str(path), dtype="float32", always_2d=True)
    assert 3.5 < cut < 4.5 and abs(len(audio) / rate - (4.0 + jobs.TAIL_HOLD_S)) < 0.15
    assert abs(float(audio[-1, 0])) < 1e-3 and sf.info(str(path)).subtype == "PCM_24"   # faded to nothing, still 24-bit
    assert jobs.trim_tail(path) == 0.0   # already clean: left alone
    sf.write(str(path), np.column_stack([music] * 2), rate, subtype="PCM_24")
    assert jobs.trim_tail(path) == 0.0   # no tail at all


def test_the_job_trims_the_tail_before_it_measures_the_master(tmp_path, monkeypatch):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    trimmed = []
    monkeypatch.setattr(jobs, "trim_tail", lambda path, **k: trimmed.append(path.name) or 3.0)
    strip, bouncer, channel = FakeStrip(), FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB short"}], -12.0, -1.0, "A clean mix.", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2"}, log=lambda s: None)
    assert trimmed == ["song - master 2026-11-02.wav"] and result.trimmed_s == 3.0
    rows = _events(tmp_path)
    trim = next(r for r in rows if r["kind"] == "tool_completed" and r.get("summary", "").startswith("Cut 3 seconds"))
    check = next(i for i, r in enumerate(rows) if r.get("plain") == "Marco is checking what actually came out.")
    assert rows.index(trim) < check and json.loads(result.record.read_text())["trimmed_s"] == 3.0


def test_a_stray_left_out_is_a_catch_on_the_screen(tmp_path, monkeypatch):
    # Owner 2026-11-03: an unowned plug-in sat on the strip with START DEMO showing; Marco had put it out, in the log only
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(jobs, "LEDGER", tmp_path / "ledger.json", raising=False)
    jobs.remember_insert("song", "Kickstart ", "Gain", stray=True)
    strip = FakeStrip()
    strip.inserts.append(Insert("Kickstart ", False, 585, 180, marcos=True) if "marcos" in Insert.__dataclass_fields__ else Insert("Kickstart ", False, 585, 180))
    bouncer, channel = FakeBouncer(tmp_path, [-30.0, -20.0, -12.0]), FakeChannel()
    plan = MasterPlan([{"role": "limiter", "plugin": "Pro-L 2", "why": "6 dB"}], -12.0, -1.0, "ok", "demo")
    monkeypatch.setattr(planning, "roles_for", lambda *a, **k: plan)
    monkeypatch.setattr(planning, "settings_for", lambda *a, **k: Settings([], ""))
    job = jobs.Job("song", 90, tmp_path, today="2026-11-02")
    result = jobs.run(job, strip=strip, bouncer=bouncer, channel=channel, locators=lambda a, b: setattr(bouncer, "end", b),
                      toggle_cycle=lambda: None, select_track=lambda: None, room={"Pro-L 2"}, log=lambda s: None)
    strays = [r for r in result.manifest if r["status"] == "stray"]
    catches = [r for r in _events(tmp_path) if r["kind"] == "tool_skipped" and r.get("summary", "").endswith("left out.")]
    assert strays and catches and catches[0]["plain"] == "This one is not his to use. Marco leaves it out."

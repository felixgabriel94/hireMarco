"""The master job through fakes: both prints, the audit, the plan, the chain, the settings, the record, the delivery."""

import json
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

        rng = np.random.default_rng(len(self.prints))
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
    assert result.rounds == 2 and "under the target" in seen[1]
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

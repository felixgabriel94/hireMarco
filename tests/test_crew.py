"""Roll, Action, Cut on set: exact words, the LaCie or nothing, the count-in only once every stream is live, the
monitors given back only if Marco took them, and nothing on Marco Live."""

import json
import time

from hiremarco import config, crew, events, server
from hiremarco.studio import monitor


def test_only_the_whole_word_is_a_crew_word():
    assert crew.words("Roll") == "roll" and crew.words("roll.") == "roll" and crew.words("ROLL TEST") == "roll test"
    assert crew.words("Action!") == "action" and crew.words(" cut ") == "cut"
    assert crew.words("roll the beat back") is None and crew.words("cut the intro") is None
    assert crew.words("lower it") is None and crew.words("") is None


def test_spoken_crew_words_and_slates_are_set_talk():
    for said in ("Roll.", "Cut!", "Action", "Session, take 2", "Cold open, take three", "Balcony take 4",
                 "B-roll, the keys", "B roll the window", "Long night, take one."):
        assert crew.set_talk(said), said
    for said in ("Marco, record", "take it from the top", "cut the second verse", "play it back", "Marco, roll it back"):
        assert not crew.set_talk(said), said


class Hand:
    def __init__(self, already=False):
        self.already, self.muted_by_me, self.calls = already, False, []

    def mute(self):
        self.calls.append("mute")
        self.muted_by_me = not self.already
        return self.muted_by_me

    def unmute(self):
        self.calls.append("unmute" if self.muted_by_me else "left")
        return self.muted_by_me


class Fakes:
    """The recorder as the crew sees it: a status file, a process that is alive until it is killed."""

    def __init__(self, ready=True, audio=True, pid=4242):
        self.pid, self.living, self.kills, self.spawned, self.played, self.told = pid, {pid}, [], [], [], []
        self.status = {"pid": pid, "ready": ready, "audio_live": audio, "files": 9,
                       "streams": {"tv": {"live": True}, "logic-main": {"live": ready}}}

    def kill(self, pid, sig):
        self.kills.append((pid, sig))
        self.living.discard(pid)


def make(tmp_path, monkeypatch, *, ready=True, audio=True, root=None):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    root = root or (tmp_path / "13-footage")
    root.mkdir(parents=True, exist_ok=True)
    f = Fakes(ready=ready, audio=audio)
    clock = iter(range(1_800_000_000, 1_800_009_999, 10))
    c = crew.Crew(root=root, tell=f.told.append, hand=Hand(),
                  play_cue=lambda name: (f.played.append(name), (1_800_000_000.0, []))[1],
                  spawn=f.spawned.append, status=lambda: f.status, is_alive=lambda pid: pid in f.living,
                  kill=f.kill, sleep=lambda s: None, clock=lambda: float(next(clock)), panel=lambda: None,
                  ready_timeout=1.0)
    return c, f.played, f.told, f, root


def slates(folder):
    return [json.loads(line) for line in (folder / "screen" / "slate.jsonl").read_text().splitlines()]


def test_roll_waits_for_every_stream_then_counts_in_marks_and_mutes(tmp_path, monkeypatch):
    c, played, told, proc, root = make(tmp_path, monkeypatch)
    assert c.do("roll").startswith("crew: rolling into ")
    assert played == [crew.ROLL_SOUND] and told == []
    assert c.hand.calls == ["mute"]
    assert (tmp_path / "state" / monitor.ROLLING_FLAG).exists()          # the speakers' level is held from Roll
    day = next(root.iterdir())
    row = slates(day)[0]
    assert row["file"] == "slate" and row["kind"] == "roll"
    assert row["at"] == crew.local_iso(1_800_000_001.5)                 # the long fourth beep's onset
    assert c.do("roll") == "crew: already rolling, left alone"


def test_action_marks_and_cut_stops_reports_and_gives_the_monitors_back(tmp_path, monkeypatch):
    c, played, told, proc, root = make(tmp_path, monkeypatch)
    c.do("roll")
    assert c.do("action") == "crew: action"
    result = c.do("cut")
    assert result.startswith("crew: cut after ") and "9 files" in result
    assert proc.kills == [(4242, 2)] and proc.spawned and played == [crew.ROLL_SOUND, crew.CUT_SOUND]
    assert c.hand.calls == ["mute", "unmute"]
    assert not (tmp_path / "state" / monitor.ROLLING_FLAG).exists()
    day = next(root.iterdir())
    kinds = [r["kind"] for r in slates(day)]
    assert kinds == ["roll", "action", "cut"] and slates(day)[-1]["files"] == 9


def test_monitors_muted_by_the_owner_stay_muted_after_cut(tmp_path, monkeypatch):
    c, *_ = make(tmp_path, monkeypatch)
    c._hand = Hand(already=True)
    c.do("roll")
    c.do("cut")
    assert c.hand.calls == ["mute", "left"]


def test_roll_test_goes_to_the_clap_test_folder(tmp_path, monkeypatch):
    c, played, told, proc, root = make(tmp_path, monkeypatch)
    c.do("roll test")
    assert (root / "clap-test" / "screen" / "slate.jsonl").exists()


def test_no_lacie_means_the_problem_sound_and_a_text_never_a_fallback(tmp_path, monkeypatch):
    c, played, told, proc, root = make(tmp_path, monkeypatch)
    c.root = tmp_path / "not-mounted"
    assert c.do("roll") == "crew: no LaCie, not rolling"
    assert played == [crew.PROBLEM_SOUND] and "LaCie" in told[0] and proc.spawned == []
    assert not c.rolling()


def test_a_stream_that_did_not_start_is_said_and_no_count_in_plays(tmp_path, monkeypatch):
    c, played, told, proc, root = make(tmp_path, monkeypatch, ready=False)
    c.do("roll")
    assert played == [crew.PROBLEM_SOUND]
    assert "logic-main" in told[0] and "rolling" in told[0] and told[0].endswith("m)")   # the time: no two texts alike


def test_a_recorder_that_died_at_the_start_is_said(tmp_path, monkeypatch):
    c, played, told, proc, root = make(tmp_path, monkeypatch, ready=False)
    proc.living.clear()
    c.do("roll")
    assert played == [crew.PROBLEM_SOUND] and not c.rolling() and "didn't start" in told[0]
    assert not (tmp_path / "state" / monitor.ROLLING_FLAG).exists()


def test_the_recorder_opens_through_a_hidden_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    script = crew.recorder_script(tmp_path / "2026-11-04")
    body = script.read_text()
    assert body.startswith("#!/bin/zsh") and "set visible of process \"Terminal\" to false" in body
    assert "film roll" in body and "2026-11-04" in body and "screenrec.log" in body
    assert script.stat().st_mode & 0o111


def test_crew_words_in_whatsapp_get_blue_ticks_no_typing_no_reply_no_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "path", lambda: tmp_path / "events.jsonl")

    class WA:
        def __init__(self):
            self.read, self.sent = [], []

        def mark_read(self, message_id, *, typing=False):
            self.read.append((message_id, typing))

        def send_text(self, *a, **k):
            self.sent.append(a)

    wa, taken = WA(), []
    assert server.crew_words("lower it", "1555", "m0", wa, take=lambda *a: taken.append(a)) is None
    out = server.crew_words("Roll", "1555", "m1", wa, take=lambda said, mid, tell: (taken.append(said), "crew: roll queued")[1])
    assert out == "crew: roll queued" and taken == ["Roll"]
    assert wa.read == [("m1", False)] and wa.sent == []
    assert not (tmp_path / "events.jsonl").exists()


def test_take_queues_in_order_and_handles_a_message_once(monkeypatch):
    done = []
    crew._SEEN.clear()
    assert crew.take("Roll", "a1", print, run=lambda w: done.append(w) or "ok") == "crew: roll queued"
    assert crew.take("Roll", "a1", print, run=lambda w: done.append(w) or "ok").endswith("(already handled)")
    assert crew.take("Cut", "a2", print, run=lambda w: done.append(w) or "ok") == "crew: cut queued"
    for _ in range(100):
        if len(done) == 2:
            break
        time.sleep(0.01)
    assert done == ["roll", "cut"]

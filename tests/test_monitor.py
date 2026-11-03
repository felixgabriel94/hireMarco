"""The Apollo monitor on the Owner's word: a slow fade under the apartment's cap, a plain mute for a take."""

import json
import threading

import pytest

from hiremarco.studio import monitor
from hiremarco.studio.console import Console, ConsoleError


class Engine:
    """The monitor section of the UA Mixer Engine as read live on 2026-11-03: MONITOR at -55, not muted."""

    def __init__(self, level=-55.0, mute=False, fail_after=None, name="MONITOR"):
        self.level, self.mute, self.name, self.writes, self.fail_after = level, mute, name, [], fail_after

    def __call__(self, command):
        if command.startswith("get "):
            p = command[4:]
            if p.endswith("/CRMonitorLevel/value"):
                return json.dumps({"path": p, "data": self.level})
            if p.endswith("/Mute/value"):
                return json.dumps({"path": p, "data": self.mute})
            if p.endswith("/Name/value"):
                return json.dumps({"path": p, "data": self.name})
            return json.dumps({"error": "no such path"})
        p, value = command[4:].rsplit(" ", 1)
        if self.fail_after is not None and len(self.writes) >= self.fail_after:
            return json.dumps({"error": "engine gone"})
        self.writes.append((p, value))
        if p.endswith("/CRMonitorLevel/value"):
            self.level = float(value)
            return json.dumps({"path": p, "data": self.level})
        if p.endswith("/Mute/value"):
            self.mute = value == "true"
            return json.dumps({"path": p, "data": self.mute})
        return json.dumps({"error": "no such path"})


@pytest.fixture
def engine():
    return Engine()


@pytest.fixture
def console(engine):
    return Console(send=engine, settle=0)


def test_level_and_mute_read_the_monitor_output(console):
    assert monitor.level(console) == -55.0
    assert monitor.muted(console) is False


def test_words_take_the_owners_phrases_whole_and_leave_the_rest_to_the_brain():
    assert monitor.words("lower it") == monitor.Request("step", -3.0)
    assert monitor.words("Turn it up") == monitor.Request("step", 3.0)
    assert monitor.words("Marco, turn it down a lot") == monitor.Request("step", -6.0)
    assert monitor.words("turn the speakers up a lot please") == monitor.Request("step", 6.0)
    assert monitor.words("set it to -50") == monitor.Request("level", -50.0)
    assert monitor.words("put the volume at -48.") == monitor.Request("level", -48.0)
    assert monitor.words("can you set it to -52 dB") == monitor.Request("level", -52.0)
    assert monitor.words("Stop") is None                       # nothing moving: not ours
    assert monitor.words("Stop", fading=True) == monitor.Request("stop")
    assert monitor.words("set up my session") is None
    assert monitor.words("lower the vocal in the chorus") is None
    assert monitor.words("turn it up on the second verse") is None
    assert monitor.words("set it to -30 and send it to mix") is None
    assert monitor.words("") is None


def test_a_fade_moves_in_small_steps_at_one_db_a_second(console, engine):
    slept = []
    done = monitor.fade(console, -52.0, sleep=slept.append)
    assert done == monitor.Fade(-52.0, "arrived")
    levels = [float(v) for p, v in engine.writes]
    assert len(levels) == 30 and sum(slept) == pytest.approx(3.0)
    assert all(abs(b - a) <= 0.1 + 1e-9 for a, b in zip([-55.0] + levels, levels))   # never a jump
    assert levels == sorted(levels)                                                  # one way, no wobble


def test_a_fade_never_passes_the_cap(console, engine):
    assert monitor.fade(console, -20.0, sleep=lambda s: None).ended == monitor.CAP_DB
    assert max(float(v) for p, v in engine.writes) == monitor.CAP_DB
    with pytest.raises(ConsoleError):
        monitor.write_level(console, -39.9)


def test_stop_halts_the_fade_where_it_is(console, engine):
    stop = threading.Event()

    def sleep(s):
        if len(engine.writes) == 7:
            stop.set()

    done = monitor.fade(console, -45.0, stop=stop, sleep=sleep)
    assert done.ended == pytest.approx(-54.3) and done.reason == "stopped" and len(engine.writes) == 7


def test_a_hand_on_the_knob_ends_the_fade(console, engine):
    def sleep(s):
        if len(engine.writes) == 5:
            engine.level = -60.0           # the Owner turned it himself

    done = monitor.fade(console, -45.0, sleep=sleep)
    assert done == monitor.Fade(-60.0, "hand") and len(engine.writes) == 5


def test_the_mute_coming_on_ends_the_fade(console, engine):
    def sleep(s):
        if len(engine.writes) == 3:
            engine.mute = True

    done = monitor.fade(console, -45.0, sleep=sleep)
    assert done.reason == "muted" and len(engine.writes) == 3


def test_a_failed_write_leaves_the_level_where_the_last_write_landed():
    engine = Engine(fail_after=4)
    console = Console(send=engine, settle=0)
    done = monitor.fade(console, -50.0, sleep=lambda s: None)
    assert done.ended == pytest.approx(-54.6) and done.reason == "lost" and len(engine.writes) == 4


def test_an_output_that_is_not_the_monitor_is_never_written():
    engine = Engine(name="LINE 3-4")
    console = Console(send=engine, settle=0)
    assert monitor.fade(console, -50.0, sleep=lambda s: None).reason == "lost"
    with pytest.raises(ConsoleError):
        monitor.Hand(console).mute()
    assert engine.writes == []


class Said:
    def __init__(self):
        self.lines = []

    def __call__(self, text):
        self.lines.append(text)


def hand_for(engine, rolling=False):
    return monitor.Hand(Console(send=engine, settle=0), start=lambda f: f(), sleep=lambda s: None,
                        rolling=lambda: rolling)


def test_lower_it_fades_three_db_and_reads_back(engine):
    said = Said()
    assert hand_for(engine).answer(monitor.Request("step", -3.0), said) == "fading -55 to -58"
    assert said.lines == ["Down to -58."] and engine.level == -58.0


def test_a_named_level_above_the_cap_stops_at_the_cap_and_says_so(engine):
    said = Said()
    hand_for(engine).answer(monitor.Request("level", -30.0), said)
    assert said.lines == ["Up to -40, the top for the apartment."] and engine.level == -40.0


def test_at_the_cap_up_is_refused_with_the_reason():
    engine, said = Engine(level=-40.0), Said()
    assert hand_for(engine).answer(monitor.Request("step", 3.0), said) == "refused: at the cap -40"
    assert said.lines == ["That's the top, -40. I won't go past it in the apartment."] and engine.writes == []


def test_between_roll_and_cut_the_level_stays(engine):
    said = Said()
    assert hand_for(engine, rolling=True).answer(monitor.Request("step", -3.0), said) == "held: rolling"
    assert engine.writes == [] and "rolling" in said.lines[0].lower()


def test_console_unreachable_leaves_it_and_says_so():
    def gone(command):
        raise OSError("connection refused")

    said = Said()
    hand = monitor.Hand(Console(send=gone, settle=0), start=lambda f: f(), sleep=lambda s: None, rolling=lambda: False)
    assert hand.answer(monitor.Request("step", -3.0), said).startswith("held: OSError")
    assert said.lines == ["I can't reach Console right now, so the speakers stay where they are."]


def test_mute_for_a_take_is_given_back_only_when_marco_took_it(engine):
    hand = hand_for(engine)
    assert hand.mute() is True and engine.mute is True
    assert hand.unmute() is True and engine.mute is False
    engine.mute = True                                   # the Owner muted it himself
    assert hand.mute() is False
    assert hand.unmute() is False and engine.mute is True
    assert all(p.endswith("/outputs/4/Mute/value") for p, v in engine.writes)   # the level is never touched


def test_a_second_ask_during_a_fade_is_held_and_stop_takes_it(engine):
    said = Said()
    hand = monitor.Hand(Console(send=engine, settle=0), start=lambda f: None, sleep=lambda s: None,
                        rolling=lambda: False)
    hand.answer(monitor.Request("step", -3.0), said)      # started, never run: the fade is "on"
    assert hand.answer(monitor.Request("step", -3.0), said) == "held: a fade is on"
    assert hand.answer(monitor.Request("stop"), said) == "stopping the fade"
    assert hand.stop.is_set()

import numpy as np

from hiremarco import gate
from hiremarco.studio.booth import NOTED, Booth, Tape
from hiremarco.studio.commands import Command, fast_match, strip_wake
from hiremarco.studio.feedback import TakeNote

RATE = 1000


def understand(line):
    said = strip_wake(line)
    if said is None:
        return None
    if said == "how was that take":
        return Command("take_feedback")
    if said == "punch it":
        return Command("punch")
    if said.startswith("note "):
        return Command("note", text=said[5:])
    if said == "more reverb":
        return Command("knob", knob="reverb", direction="up", steps=1)
    return fast_match(said) or Command("unknown")


def booth(note=TakeNote("Pitch dips on the last chorus line.", True, "chorus"), rolling_seen=None):
    said, did, fed = [], [], []

    def say(text):
        if b.rolling:
            raise gate.Refused("a take is rolling")
        said.append(text)

    def feedback(take, rate):
        fed.append((take.size, rate))
        return note

    b = Booth(understand=understand, logic=lambda c: did.append(c) or c.describe(), say=say,
              feedback=feedback, tape=Tape(RATE, seconds=5), log=lambda line: None)
    return b, said, did, fed


def test_a_take_then_its_note_then_the_punch():
    b, said, did, fed = booth()
    b.hear("Marco, record.")
    assert said == ["Rolling"] and b.rolling
    b.tape.write(np.ones(1500))
    b.hear("Marco, how was that take?")
    assert fed == []  # holds while rolling
    b.hear("Marco, stop.")
    assert not b.rolling
    b.hear("Marco, how was that take?")
    assert fed == [(1500, RATE)]
    assert said[-2:] == ["Let me listen.", "Pitch dips on the last chorus line. Want to punch it?"]
    b.hear("Marco, punch it.")
    assert did[-1] == Command("punch", section="chorus") and b.rolling and b.pending_punch == ""
    assert said[-1] == "Rolling"


def test_knobs_are_silent_and_notes_are_kept():
    b, said, did, _ = booth()
    b.hear("Marco, more reverb.")
    assert did == [Command("knob", knob="reverb", direction="up", steps=1)] and said == []
    b.hear("Marco, note second verse needs a double.")
    assert b.notes == ["second verse needs a double"] and said == [NOTED]


def test_lines_not_for_marco_do_nothing():
    b, said, did, _ = booth()
    assert b.hear("that was a good one") is None
    assert said == [] and did == []


def test_punch_with_nothing_pending_asks():
    b, _, did, _ = booth()
    assert "punch where" in b.hear("Marco, punch it.")
    assert did == []


def test_a_refused_logic_action_is_logged_not_raised():
    b, said, _, _ = booth()

    def refuse(command):
        raise gate.Refused("no send switch for logic -> *")

    b.logic = refuse
    assert "held: no send switch" in b.hear("Marco, play.")
    assert not b.rolling


def test_tape_keeps_only_the_take_and_wraps():
    tape = Tape(RATE, seconds=2)
    tape.write(np.zeros(1700))
    tape.mark_start()
    tape.write(np.arange(1, 1201, dtype="float32"))
    tape.mark_stop()
    take = tape.last_take()
    assert take.size == 1200 and take[0] == 1 and take[-1] == 1200


def test_run_check_measures_the_take_and_plays_the_guide():
    from hiremarco.hearing import Turn
    from tests.test_pitch import sung

    b, said, _, _ = booth()
    rate = 24000
    b.tape = Tape(rate, seconds=5)
    clips = []
    b.play_clip = lambda pcm, label: clips.append(label)
    b.transcribe = lambda audio, r: [Turn(0, 1200, "let me love you")]
    b.understand = lambda line: Command("run_check", text="love you") if "run" in line else (
        Command("set_key", text="A minor") if "minor" in line else understand(line))
    b.hear("Marco, record.")
    b.tape.write(sung([(None, 0.5), (69, 0.3), (71.7, 0.3), (None, 0.1)], rate))
    b.hear("Marco, stop.")
    assert "asked for the key" in b.hear("Marco, how's the run on love you")
    assert said[-1] == "What key are we in?"
    b.hear("Marco, we're in A minor")
    result = b.hear("Marco, how's the run on love you")
    assert "estimate" in result
    assert said[-2].startswith("The second note is") and said[-1] == "Here's how it goes."
    assert clips == ["guide: A4 C5"]


def test_spoken_key_and_run_commands_skip_the_model():
    from hiremarco.studio.commands import understand as real

    assert real("Marco, we're in F sharp minor", client=None) == Command("set_key", text="f sharp minor")
    assert real("Marco, how's the run on love you", client=None) == Command("run_check", text="love you")
    assert real("Marco, check the pitch", client=None) == Command("run_check", text="")


def test_sound_works_the_chain_and_puts_it_back():
    from hiremarco.studio.plugins import PluginState

    b, said, _, _ = booth()
    calls = []

    class FakeChannel:
        def design(self, words):
            calls.append(words)
            return {1: PluginState("Pro-Q 3"), 2: PluginState("CLA-76")}, "More air, softer attack."

        def put_back(self):
            calls.append("back")

    b.plugin = FakeChannel()
    b.understand = lambda line: Command("sound", text="brighter") if "brighter" in line else Command("put_back")
    assert "2 plugin(s)" in b.hear("Marco, make it brighter")
    assert said[-2:] == ["Let me dial that in.", "More air, softer attack."]
    b.hear("Marco, put it back")
    assert calls == ["brighter", "back"] and said[-1] == "Put it back."

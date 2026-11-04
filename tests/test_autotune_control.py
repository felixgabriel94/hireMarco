"""Every control on the Console's Auto-Tune by voice, Retune Speed first (Owner 2026-11-04)."""

import pytest

from hiremarco.studio.booth import Booth, Tape, control_named
from hiremarco.studio.commands import Command, understand
from hiremarco.studio.console import Console
from tests.test_console import Engine


@pytest.mark.parametrize("line, command", [
    ("Marco, retune speed 20", Command("autotune", text="retune speed=20", direction="set")),
    ("Marco, set the retune speed to ten", Command("autotune", text="retune speed=10", direction="set")),
    ("Marco, set the retune speed to 15 milliseconds", Command("autotune", text="retune speed=15", direction="set")),
    ("Marco, put the auto-tune's retune speed at 0", Command("autotune", text="retune speed=0", direction="set")),
    ("Marco, humanize 30", Command("autotune", text="humanize=30", direction="set")),
    ("Marco, flex tune off", Command("autotune", text="flex tune=off", direction="set")),
    ("Marco, set the detune to minus 10", Command("autotune", text="detune=-10", direction="set")),
    ("Marco, set the auto-tune scale to chromatic", Command("autotune", text="scale=chromatic", direction="set")),
    ("Marco, faster retune", Command("autotune", text="retune", direction="down", steps=1)),
    ("Marco, a lot faster retune speed", Command("autotune", text="retune speed", direction="down", steps=3)),
    ("Marco, slower retune", Command("autotune", text="retune", direction="up", steps=1)),
    ("Marco, speed up the retune", Command("autotune", text="retune speed", direction="down", steps=1)),
    ("Marco, more humanize", Command("autotune", text="humanize", direction="up", steps=1)),
    ("Marco, less natural vibrato", Command("autotune", text="natural vibrato", direction="down", steps=1)),
    ("Marco, what's the retune speed", Command("autotune", text="retune speed", direction="read")),
    ("Marco, what's the auto-tune on", Command("autotune", direction="read")),
    ("Marco, read me the auto-tune", Command("autotune", direction="read")),
])
def test_the_auto_tune_controls_skip_the_model(line, command):
    assert understand(line, client=None) == command


@pytest.mark.parametrize("line, command", [
    ("Marco, put the auto-tune in F minor", Command("tune_console", text="f minor")),   # the key is still the key
    ("Marco, set the tune to the beat", Command("tune_console")),
    ("Marco, turn up the tune", Command("knob", knob="tuning", direction="up", steps=1)),
    ("Marco, more verb", Command("knob", knob="reverb", direction="up", steps=1)),
])
def test_older_lines_keep_their_meaning(line, command):
    assert understand(line, client=None) == command


@pytest.mark.parametrize("said, name", [
    ("retune speed", "Retune Speed"), ("retune", "Retune Speed"), ("flex tune", "Flex-Tune"),
    ("vibrato", "Natural Vibrato"), ("humanize", "Humanize"), ("formant", None),
])
def test_control_named(said, name):
    assert control_named(said, ["Key", "Scale", "Retune Speed", "Flex-Tune", "Humanize", "Natural Vibrato", "Detune"]) == name


def booth(**parts):
    said = []
    engine = Engine()
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(),
              say=said.append, feedback=None, tape=Tape(1000, seconds=1), log=lambda line: None,
              console=Console(send=engine, settle=0), **parts)
    return b, said, engine


def test_retune_speed_is_set_exactly_and_read_back():
    b, said, engine = booth()
    result = b.hear("Marco, retune speed 20")
    assert said == ["Retune Speed's at 20."] and "Retune Speed:" in result
    assert engine.shown("Retune Speed") == "20"


def test_faster_retune_steps_down_ten_milliseconds_from_where_it_is():
    b, said, engine = booth()
    b.hear("Marco, retune speed 40")
    b.hear("Marco, faster retune")
    assert engine.shown("Retune Speed") == "30" and said[-1] == "Retune Speed's at 30."
    b.hear("Marco, a lot slower retune")
    assert engine.shown("Retune Speed") == "60"


def test_past_the_end_lands_on_the_end():
    b, said, engine = booth()
    b.hear("Marco, retune speed 5")
    b.hear("Marco, a lot faster retune")
    assert engine.shown("Retune Speed") == "0" and said[-1] == "Retune Speed's at 0."


def test_any_control_by_name_and_off_is_zero():
    b, said, engine = booth()
    b.hear("Marco, humanize 30")
    b.hear("Marco, flex tune off")
    assert engine.shown("Humanize") == "30" and engine.shown("Flex-Tune") == "0"
    b.hear("Marco, set the auto-tune scale to dorian")
    assert engine.shown("Scale") == "DORIAN"


def test_a_control_it_lacks_is_said_not_guessed():
    b, said, engine = booth()
    before = dict(engine.norm)
    result = b.hear("Marco, set the formant to 3")
    assert said == ["Your Auto-Tune has no formant."] and "no Auto-Tune control" in result and engine.norm == before


def test_reading_back_changes_nothing():
    b, said, engine = booth()
    b.hear("Marco, retune speed 25")
    before = dict(engine.norm)
    b.hear("Marco, what's the retune speed")
    assert said[-1] == "Retune Speed's at 25." and engine.norm == before
    b.hear("Marco, read me the auto-tune")
    assert said[-1].startswith("Key C, Scale CHROMATIC, Retune Speed 25")


def test_nothing_moves_while_a_take_rolls():
    b, said, engine = booth()
    b.rolling = True
    before = dict(engine.norm)
    assert "holding the Auto-Tune change" in b.handle(Command("autotune", text="retune speed=10", direction="set"))
    assert engine.norm == before


def test_no_auto_tune_on_the_input_is_said():
    b, said, engine = booth()
    engine.slots[1] = ""
    result = b.hear("Marco, retune speed 20")
    assert "Auto-Tune not read" in result and said == ["I can't reach the Auto-Tune. Is Console open with it on your input?"]

"""Harmony voices from a sung line, in the key's own steps (Owner 2026-10-31)."""

from hiremarco.studio.harmony import Stack, ask, names, shift
from hiremarco.studio.pitch import Note


def line(*midis):
    return [Note(i * 0.5, i * 0.5 + 0.4, float(m), m) for i, m in enumerate(midis)]


def test_a_third_above_moves_two_scale_steps_in_the_key():
    sung = line(64, 65, 67)                                   # E F G in C major
    assert names(shift(sung, "C major", 2)) == "G A B"
    assert names(shift(sung, "C major", -2)) == "C D E"
    assert names(shift(line(69), "A minor", 2)) == "C"        # minor: A up a third is C
    assert names(shift(line(71), "C major", 4)) == "F"        # B up a fifth stays in key: F, not F#


def test_what_he_says_becomes_steps():
    assert ask("what's the third above") == (2, False)
    assert ask("give me a fifth") == (4, False)
    assert ask("the 6th below") == (-5, False)
    assert ask("what's the second voice that goes with this") == (2, True)
    assert ask("next voice") == (2, True)


def test_the_next_voice_stacks_a_third_over_the_top_so_a_line_grows_into_a_chord():
    stack = Stack(line(60), "C major")                        # C
    assert names(stack.add("what's the second voice")) == "E"
    assert names(stack.add("and the next voice")) == "G"
    assert names(stack.add("what could be a fifth")) == "G"   # a fifth over the line he sang
    assert names(stack.add("one more voice below")) == "A"    # under the lowest: C down a third


def test_the_booth_plays_the_next_voice_and_names_it():
    import numpy as np

    from hiremarco.studio.booth import Booth, Tape
    from hiremarco.studio.commands import Command

    rate, said, played = 24000, [], []
    t = np.arange(int(0.5 * rate)) / rate
    sung = np.concatenate([0.3 * np.sin(2 * np.pi * 261.63 * t), 0.3 * np.sin(2 * np.pi * 329.63 * t)])   # C then E
    tape = Tape(rate, seconds=4)
    b = Booth(understand=lambda line: None, logic=lambda c: c.describe(), say=said.append,
              feedback=lambda take, r: None, tape=tape, log=lambda line: None,
              play_clip=lambda pcm, label: played.append(label))
    b.key = "C major"
    tape.mark_start()
    tape.write(sung)
    tape.mark_stop()
    line = b.handle(Command("harmony", text="what's the third above"))
    assert line == "harmony (what's the third above): E G over C E" and said[-1] == "E G."
    assert played == ["harmony: E G"]
    assert b.handle(Command("harmony", text="next voice")).startswith("harmony (next voice): G B")

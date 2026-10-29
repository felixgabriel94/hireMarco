import time

from hiremarco.studio.booth import FAILED, Booth, Tape
from hiremarco.studio.commands import understand
from hiremarco.studio.words import Writer, usable


def test_a_usable_line_is_one_short_spoken_line():
    assert usable('  "Harmony 3 is up. Same chain as the lead?" ') == "Harmony 3 is up. Same chain as the lead?"
    assert usable("") is None and usable("**Sure!**") is None and usable("one\ntwo") is None
    assert usable(" ".join(["word"] * 30)) is None


def test_the_plain_line_is_said_when_the_words_are_late_wrong_or_refused():
    slow = Writer(wait=0.05, complete=lambda prompt: time.sleep(0.5) or "too late")
    assert slow.line("m", {}, "plain") == "plain"

    def refuse(prompt):
        raise RuntimeError("held")

    assert Writer(complete=refuse).line("m", {}, "plain") == "plain"
    assert Writer(complete=lambda p: "- a list\n- of things").line("m", {}, "plain") == "plain"


def test_he_writes_from_the_facts_and_the_last_exchanges():
    seen = []
    w = Writer(complete=lambda prompt: seen.append(prompt) or "Harmony 3's up. Want the lead's chain on it?")
    w.heard("Marco, record", "Rolling")
    assert w.line("made a new track and named it", {"name": "Harmony 3"}, "Harmony 3. Rolling when you are.") \
        == "Harmony 3's up. Want the lead's chain on it?"
    assert '"Harmony 3"' in seen[0] and '"Rolling"' in seen[0] and "made a new track" in seen[0]


def test_the_booth_speaks_his_written_line_and_keeps_the_exchange():
    said, prompts = [], []
    writer = Writer(complete=lambda prompt: prompts.append(prompt) or "Still tracking. Mixing when you're ready.")
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(), say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None, writer=writer)
    b.hear("Marco, what mode are you in?")
    assert said[-1] == "Still tracking. Mixing when you're ready." and '"recording"' in prompts[0]
    assert writer.recent[-1] == ("Marco, what mode are you in?", "Still tracking. Mixing when you're ready.")


def test_a_failure_is_explained_in_his_words_with_the_plain_line_behind_it():
    def explode(command):
        raise RuntimeError("osascript exit 1: Invalid index")

    said = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=explode, say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None,
              writer=Writer(complete=lambda p: (_ for _ in ()).throw(RuntimeError("down"))))
    assert "failed" in b.hear("Marco, record.") and said[-1] == FAILED

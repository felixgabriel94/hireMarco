import pytest
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


def test_a_slow_answer_is_silent_until_his_line_is_ready():
    from hiremarco.studio.commands import Command

    said = []

    def slow(line):
        time.sleep(0.9)
        return Command("mode")

    b = Booth(understand=slow, logic=lambda c: c.describe(), say=said.append, feedback=lambda a, r: None,
              tape=Tape(1000, seconds=2), log=lambda line: None,
              writer=Writer(complete=lambda p: time.sleep(0.9) or "Still tracking."))
    b.hear("Marco, which mode")
    assert said == ["Still tracking."]  # no "One sec." or "Let me see.", however slow both steps were
    said.clear()
    quick = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(),
                  say=said.append, feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None)
    quick.hear("Marco, what mode are you in?")
    assert said == ["We're recording."]


def test_a_thinking_sound_is_not_a_line():
    from hiremarco.studio.words import PERSONA, usable

    assert usable("Hmm.") is None and usable("Uh, mm.") is None
    assert usable("Hmm, we're rolling.") == "Hmm, we're rolling."  # kept here; the voice drops the sound (speakable)
    assert "Never say hmm, mm, uh or um" in PERSONA and "wait until he has finished" in PERSONA


def test_no_filler_is_left_in_the_booth():
    import hiremarco.studio.booth as booth

    assert not hasattr(booth, "THINKING") and not hasattr(booth, "FILLER_AFTER")
    assert not any(line in booth.STOCK for line in ("One sec.", "Let me see."))


def test_he_holds_a_line_until_the_mic_is_quiet_and_only_so_long():
    levels = iter([0.2, 0.2, 0.0, 0.0, 0.0])
    said = []
    b = Booth(understand=lambda line: None, logic=lambda c: c.describe(), say=said.append, feedback=lambda a, r: None,
              tape=Tape(1000, seconds=2), log=lambda line: None, mic_level=lambda: next(levels, 0.0))
    b._speak("Rolling")
    assert said == ["Rolling"] and next(levels, "done") == "done"  # every read used: it waited through the talking

    b.mic_level = lambda: 0.5  # a loud room: late, never gagged
    started = time.monotonic()
    b._speak("Talk to me.")
    assert said[-1] == "Talk to me." and 1.0 <= time.monotonic() - started < 2.0


def test_a_fragment_with_no_name_gets_no_question_back():
    from hiremarco.studio.booth import MISSED
    from hiremarco.studio.commands import Command

    said = []
    b = Booth(understand=lambda line: Command("unknown"), logic=lambda c: c.describe(), say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None)
    b.hear("Marco, what's that")  # his name: he says he missed it
    assert said == [MISSED]
    b.hear("trying to")           # still awake, no name: someone talking, and he lets it go by
    assert said == [MISSED]
    b.hear("make the thing a bit more")  # a whole thought with no name still gets his question
    assert said == [MISSED, MISSED]


@pytest.mark.parametrize("moment, shown", [
    ("every track in his session is labeled; say the session is labeled and ready, in one short line",
     "Every track in FEGA's session is labeled."),
    ("asked to organize a session that is not a copy you opened; say you'll open his song first",
     "Asked to organize a session that is not a copy I opened."),
    ("the artist is done talking for now; sign off", "FEGA is done talking for now."),
    ("read the beat's key and tempo and its level; offer to set the session to it",
     "Read the beat's key and tempo and its level."),
])
def test_the_trace_shows_his_thought_not_the_line_he_says_to_the_artist(moment, shown):
    # Owner 2026-11-04: the Live trace is for the audience; "still sorting the rest out with you" was him talking to FEGA
    from hiremarco.studio.words import thought

    assert thought(moment) == shown

"""The song's structure and his bookmarks (Owner 2026-10-31): two kinds of marker, kept apart."""

import pytest

from hiremarco.studio.arrange import Arranger, Section, find, labelled, layout, parse_layout, parse_rows


def test_a_spoken_layout_becomes_sections_in_order_at_his_lengths():
    pairs = parse_layout("intro 4 bars, verse 8, chorus 8, then verse 8 and chorus 8, bridge 4, outro 4")
    assert pairs == [("Intro", 4), ("Verse", 8), ("Chorus", 8), ("Verse", 8), ("Chorus", 8), ("Bridge", 4),
                     ("Outro", 4)]
    sections = layout(pairs, start=2)
    assert [(s.name, s.bar, s.bars) for s in sections[:3]] == [("Intro", 2, 4), ("Verse", 6, 8), ("Chorus", 14, 8)]
    assert parse_layout("pre chorus 4, hook 8") == [("Pre-Chorus", 4), ("Hook", 8)]


def test_repeats_are_counted_because_logic_does_not_number_them():
    sections = layout([("Intro", 4), ("Verse", 8), ("Chorus", 8), ("Verse", 8), ("Chorus", 8), ("Outro", 4)])
    assert find(sections, "chorus 2").bar == 29 and find(sections, "the second chorus").bar == 29
    assert find(sections, "chorus").bar == 13 and find(sections, "last verse").bar == 21
    assert find(sections, "chorus 3") is None and find(sections, "bridge") is None
    assert labelled(sections)[2] == "Chorus 1: bars 13 to 20" and labelled(sections)[0] == "Intro: bars 1 to 4"


def test_marker_list_rows_are_read_as_marks_and_lengths():
    rows = parse_rows("1 1 1 1 \tIntro\t4 0 0 0\n5 1 1 1 \tVerse\t8 0 0 0\n13 3 1 1 \tChorus\t∞\nbad line")
    assert [(m.name, m.bar, m.beat, n) for m, n in rows] == [("Intro", 1, 1, 4), ("Verse", 5, 1, 8),
                                                              ("Chorus", 13, 3, 0)]


class FakeLogic:
    """The Marker List, the Marker track's menu and Logic's keys, as the script and the presses see them."""

    def __init__(self, arrangement=(), bookmarks=(), convert_leaves_markers=False):
        self.markers = list(bookmarks)  # (name, bar, bars)
        self.arrangement = list(arrangement)
        self.playhead = 1
        self.calls = []
        self.leaves = convert_leaves_markers
        self.undo_to = None

    def run(self, args):
        self.calls.append(args)
        cmd = args[0]
        if cmd == "clear":
            n = len(self.markers)
            self.markers = []
            return str(n)
        if cmd == "mark":
            self.markers.append((args[1], self.playhead, 0))
            return "marked"
        if cmd == "rows":
            return "\n".join(f"{bar} 1 1 1 \t{name}\t{bars} 0 0 0" for name, bar, bars in self.markers)
        if cmd == "undo":
            self.markers, self.undo_to = self.undo_to, None
            return "Undo"
        raise AssertionError(args)

    def menu(self, item):
        self.calls.append(["menu", item])
        if item == "from_arrangement":
            self.undo_to = list(self.markers)
            self.markers += [(s.name, s.bar, s.bars) for s in self.arrangement]
        if item == "to_arrangement":
            marks = sorted(self.markers, key=lambda m: m[1])
            self.arrangement = [Section(n, b, (marks[i + 1][1] - b) if i + 1 < len(marks) else 8)
                                for i, (n, b, _) in enumerate(marks)]
            if not self.leaves:
                self.markers = []

    def press(self, name):
        self.calls.append(["press", name])

    def go(self, bar, beat=1):
        self.calls.append(["go", bar])
        self.playhead = bar

    def locators(self, start, end):
        self.calls.append(["locators", start, end])


def arranger(logic):
    return Arranger(run=logic.run, menu=logic.menu, press=logic.press, go=logic.go, locators=logic.locators,
                    sleep=lambda s: None)


def test_the_structure_is_read_and_his_bookmarks_are_left_as_they_were():
    logic = FakeLogic([Section("Intro", 1, 4), Section("Chorus", 5, 8)], bookmarks=[("the high note", 7, 0)])
    assert arranger(logic).structure() == [Section("Intro", 1, 4), Section("Chorus", 5, 8)]
    assert logic.markers == [("the high note", 7, 0)] and ["undo"] in logic.calls
    empty = FakeLogic([Section("Intro", 1, 4)])
    assert arranger(empty).structure() == [Section("Intro", 1, 4)] and empty.markers == [] and ["clear"] in empty.calls


def test_a_restore_that_does_not_match_stops_loudly():
    logic = FakeLogic([Section("Intro", 1, 4)], bookmarks=[("keep", 3, 0)])
    logic.run = lambda args, real=logic.run: "Undo" if args[0] == "undo" else real(args)  # an undo that did nothing
    with pytest.raises(RuntimeError, match="did not go back"):
        arranger(logic).structure()


def test_a_built_layout_is_reported_from_what_logic_reads_back_and_bookmarks_come_back():
    logic = FakeLogic(bookmarks=[("fix the breath", 3, 0)], convert_leaves_markers=True)
    built = arranger(logic).build(layout([("Intro", 4), ("Verse", 8), ("Chorus", 8)]))
    assert [(s.name, s.bar, s.bars) for s in built] == [("Intro", 1, 4), ("Verse", 5, 8), ("Chorus", 13, 8)]
    assert logic.markers == [("fix the breath", 3, 0)]


def test_chorus_one_is_copied_into_chorus_two_by_its_bars():
    logic = FakeLogic()
    sections = layout([("Verse", 8), ("Chorus", 8), ("Verse", 8), ("Chorus", 8)])
    line = arranger(logic).copy_section(sections, "chorus 1", "chorus 2")
    assert line == "copied chorus 1 (bars 9 to 16) to bar 25"
    assert logic.calls == [["locators", 9, 17], ["press", "select_inside_locators"], ["press", "copy"], ["go", 25],
                           ["press", "paste"]]
    assert arranger(logic).copy_section(sections, "chorus 1", "chorus 3") == "no section called 'chorus 3' in this song"


def test_bookmarks_go_in_his_set_and_are_found_by_their_words():
    logic = FakeLogic(bookmarks=[("the high note", 7, 0), ("second harmony idea", 19, 0)])
    a = arranger(logic)
    logic.playhead = 23
    assert a.bookmark("fix the breath") == "marked fix the breath"
    assert a.find_bookmark("take me back to the harmony idea").bar == 19
    assert a.find_bookmark("go back to that").name == "fix the breath"
    assert a.find_bookmark("the bridge thing") is None


def booth_with(logic):
    from hiremarco.studio.booth import Booth, Tape

    said, did = [], []
    b = Booth(understand=lambda line: None, logic=lambda c: did.append(c) or c.describe(), say=said.append,
              feedback=lambda take, rate: None,
              tape=Tape(48000, seconds=1), log=lambda line: None, arranger=arranger(logic))
    return b, said, did


def test_the_booth_lays_out_the_song_and_says_what_logic_has():
    from hiremarco.studio.commands import Command

    logic = FakeLogic()
    b, said, did = booth_with(logic)
    line = b.handle(Command("arrange", text="intro 4 bars, verse 8, chorus 8, verse 8, chorus 8", bar=2))
    assert line == ("arranged: Intro: bars 2 to 5; Verse 1: bars 6 to 13; Chorus 1: bars 14 to 21; "
                    "Verse 2: bars 22 to 29; Chorus 2: bars 30 to 37")
    assert said == ["Laid out."]


def test_take_me_to_chorus_2_goes_to_its_real_bar_and_an_unknown_section_is_said_plainly():
    from hiremarco.studio.commands import Command

    logic = FakeLogic([Section("Verse", 1, 8), Section("Chorus", 9, 8), Section("Verse", 17, 8),
                       Section("Chorus", 25, 8)])
    b, said, did = booth_with(logic)
    assert b.handle(Command("go_to_section", section="chorus 2")) == "go to bar 25"
    assert did[-1] == Command("go_to_bar", bar=25)
    assert b.handle(Command("go_to_section", section="bridge")) == "no section 'bridge' in this song"
    assert said[-1] == "I don't see that section."


def test_the_booth_copies_a_section_and_holds_it_during_a_take():
    from hiremarco.studio.commands import Command

    logic = FakeLogic([Section("Chorus", 9, 8), Section("Chorus", 25, 8)])
    b, said, did = booth_with(logic)
    b.rolling = True
    assert b.handle(Command("copy_section", section="chorus 1", text="chorus 2")).startswith("holding")
    b.rolling = False
    assert b.handle(Command("copy_section", section="chorus 1", text="chorus 2")) == \
        "copied chorus 1 (bars 9 to 16) to bar 25"


def test_a_bookmark_is_dropped_and_found_again():
    from hiremarco.studio.commands import Command

    logic = FakeLogic()
    b, said, did = booth_with(logic)
    logic.playhead = 14
    assert b.handle(Command("bookmark", text="the high note")) == "marked the high note"
    assert b.handle(Command("go_to_bookmark", text="back to the high note")) == "go to bar 14 (the high note)"
    assert b.handle(Command("go_to_bookmark", text="the ad lib")) == "no bookmark for 'the ad lib'"


def test_take_me_back_to_a_bookmark_is_not_taken_for_a_lyric():
    from hiremarco.studio.commands import Command

    logic = FakeLogic(bookmarks=[("the high note", 14, 0)])
    b, said, did = booth_with(logic)
    assert b.handle(Command("play_from_lyric", text="high note")) == "go to bar 14 (the high note)"


def test_go_to_a_bar_moves_the_playhead_without_typing_a_position(tmp_path):
    # live 2026-10-31: "/" was Go to Marker Number in the Owner's Logic, and the typed spaces started playback
    from hiremarco import gate
    from hiremarco.studio.commands import Command
    from hiremarco.studio.logic import Logic
    from tests.test_beat_in import rules

    scripts, moved = [], []
    logic = Logic(conn=gate.connect(":memory:"), rules_path=rules(tmp_path), run_script=scripts.append,
                  move=moved.append)
    logic.do(Command("go_to_bar", bar=25))
    logic.do(Command("play_from", text="9 1 1 1"))
    assert moved == ["25", "9"]
    assert not any('keystroke "/"' in s for s in scripts) and len(scripts) == 1   # only the play press

"""One plug-in's face read on the strip and written to the ledger, the plug-in taken off again."""

from dataclasses import dataclass

from hiremarco.studio import facecheck
from hiremarco.studio.stereo_out import Insert, Strip


@dataclass
class Face:
    licensed: bool
    notice: str = ""
    plugin: str = ""


class FakeStrip:
    def __init__(self):
        self.inserts = [Insert("Gain", False, 10, 100), Insert("Pro-L 2", False, 10, 120)]
        self.removed = []
        self.closed = 0

    def read(self):
        return Strip(None, list(self.inserts), None, "FG Master")

    def insert(self, name, *, look=None):
        # the strip's rows move when an insert lands (live 2026-11-02): every y shifts, the new one goes last
        moved = [Insert(i.name, i.bypassed, i.x, i.y + 20) for i in self.inserts]
        self.inserts = moved + [Insert(name[:10], False, 10, max(i.y for i in moved) + 20)]
        if look:
            look()
        return self.read()

    def remove(self, name, row):
        self.inserts = [i for i in self.inserts if not (i.name == name and abs(i.y - row) < 4)]
        self.removed.append((name, row))
        return self.read()

    def close_windows(self):
        self.closed += 1
        return 0


def test_a_demo_face_marks_demo_and_the_plugin_comes_off():
    strip, marks, said = FakeStrip(), [], []
    status = facecheck.check("UAD Shadow Hills Class A Master", strip, lambda: Face(True, "DEMO: 14 days left"),
                             lambda n, s, w: marks.append((n, s, w)), said.append)
    assert status == "demo" and marks == [("UAD Shadow Hills Class A Master", "demo", "its window shows DEMO: 14 days left (read on the strip)")]
    assert strip.removed == [("UAD Shadow", 160)] and [i.name for i in strip.inserts] == ["Gain", "Pro-L 2"] and strip.closed == 1


def test_a_start_demo_face_marks_not_owned():
    strip, marks = FakeStrip(), []
    assert facecheck.check("UAD X", strip, lambda: Face(False, "START DEMO / BUY"), lambda n, s, w: marks.append(s), lambda s: None) == "not_owned"
    assert marks == ["not_owned"] and strip.removed


def test_an_unread_face_changes_nothing_but_still_takes_the_plugin_off():
    strip, marks = FakeStrip(), []
    assert facecheck.check("UAD X", strip, lambda: None, lambda n, s, w: marks.append(s), lambda s: None) == "unknown"
    assert marks == [] and strip.removed == [("UAD X", 160)]


def test_an_active_demo_notice_reads_as_a_demo_even_when_the_eye_said_unlicensed():
    strip, marks = FakeStrip(), []
    status = facecheck.check("UAD Shadow Hills Class A Master", strip, lambda: Face(False, "DEMO ACTIVE - 14 DAYS"),
                             lambda n, s, w: marks.append((s, w)), lambda s: None)
    assert status == "demo" and marks == [("demo", "its window shows DEMO ACTIVE - 14 DAYS (read on the strip)")]
    assert [i.name for i in strip.inserts] == ["Gain", "Pro-L 2"]


def test_a_second_copy_of_a_plugin_already_on_the_strip_is_the_one_taken_off():
    strip, marks = FakeStrip(), []
    strip.inserts.append(Insert("Pro-L 2", False, 10, 140))
    facecheck.check("Pro-L 2", strip, lambda: Face(True, ""), lambda n, s, w: marks.append(s), lambda s: None)
    assert marks == ["owned"] and [i.name for i in strip.inserts] == ["Gain", "Pro-L 2", "Pro-L 2"] and len(strip.removed) == 1

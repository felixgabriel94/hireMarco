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
        self.inserts.append(Insert(name[:10], False, 10, 140))
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
    assert strip.removed == [("UAD Shadow", 140)] and [i.name for i in strip.inserts] == ["Gain", "Pro-L 2"] and strip.closed == 1


def test_a_start_demo_face_marks_not_owned():
    strip, marks = FakeStrip(), []
    assert facecheck.check("UAD X", strip, lambda: Face(False, "START DEMO / BUY"), lambda n, s, w: marks.append(s), lambda s: None) == "not_owned"
    assert marks == ["not_owned"] and strip.removed


def test_an_unread_face_changes_nothing_but_still_takes_the_plugin_off():
    strip, marks = FakeStrip(), []
    assert facecheck.check("UAD X", strip, lambda: None, lambda n, s, w: marks.append(s), lambda s: None) == "unknown"
    assert marks == [] and strip.removed == [("UAD X", 140)]

import pytest

from hiremarco.studio.booth import Booth, Tape
from hiremarco.studio.commands import Command, understand
from hiremarco.studio.tracks import NotMapped, SessionState, TrackInfo


@pytest.mark.parametrize("line, command", [
    ("Marco, we're on the lead", Command("label_track", text="lead")),
    ("Marco, this is a harmony", Command("label_track", text="harmony")),
    ("Marco, this one's an ad-lib", Command("label_track", text="ad-lib")),
    ("Marco, name this track Hook Vox", Command("name_track", text="Hook Vox")),
    ("Marco, stack the harmonies", Command("stack", text="harmonies")),
    ("Marco, give me a quick mix pass", Command("mix_pass")),
    ("Marco, clean up what we have so far", Command("mix_pass")),
    ("Marco, keep it balanced as we go", Command("balanced_watch", text="on")),
    ("Marco, stop balancing", Command("balanced_watch", text="off")),
    ("Marco, what mode are you in?", Command("mode", text="")),
    ("Marco, let's do mixing now", Command("mode", text="mixing")),
])
def test_tidy_lines_skip_the_model(line, command):
    assert understand(line, client=None) == command


class FakeTracks:
    def __init__(self):
        self.calls = []

    def label(self, kind, state):
        self.calls.append(("label", kind))
        return ("Harmony 1" if kind == "harmony" else "Lead Vox"), "renamed"

    def rename(self, name):
        self.calls.append(("rename", name))
        return f"renamed to {name}"

    def stack(self, names, kind="summing"):
        self.calls.append(("stack", tuple(names)))
        raise NotMapped("track stacks are not mapped yet")


def booth():
    said = []
    tracks = FakeTracks()
    session = SessionState("recording", [TrackInfo(1, "Harmony 1", 2), TrackInfo(2, "Harmony 2", 2),
                                         TrackInfo(3, "Lead Vox", 5)])
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(), say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None,
              tracks=tracks, session=session, mix_pass=lambda brief: f"pass on: {brief}")
    return b, said, tracks


def test_labeling_names_the_track_and_marco_says_rolling_when_you_are():
    b, said, tracks = booth()
    b.hear("Marco, this is a harmony")
    assert tracks.calls == [("label", "harmony")] and said[-1] == "Harmony 1. Rolling when you are."


def test_stacking_the_harmonies_picks_the_harmony_tracks_and_notes_the_unmapped_step():
    b, said, tracks = booth()
    assert "not mapped yet" in b.hear("Marco, stack the harmonies")
    assert tracks.calls == [("stack", ("Harmony 1", "Harmony 2"))]
    assert said[-1] == "Noted. I'll do that one from the desk."


def test_mode_and_watch_and_mix_pass():
    b, said, _ = booth()
    assert "mode: recording" in b.hear("Marco, what mode are you in?")
    b.hear("Marco, keep it balanced as we go")
    assert b.session.balanced_watch and said[-1] == "I'll keep it balanced as we go."
    b.hear("Marco, record.")
    assert "holding the mix pass" in b.hear("Marco, give me a mix pass")
    b.hear("Marco, stop.")
    assert "pass on: baseline" in b.hear("Marco, give me a mix pass")
    b.hear("Marco, let's do mixing now")
    assert b.session.mode == "mixing" and said[-1] == "Mixing mode."

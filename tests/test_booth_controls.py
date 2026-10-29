"""Today's controls by voice: the Console's Auto-Tune, Flex Pitch's first pass, a plug-in through the surface."""

import pytest

from hiremarco.studio import flex
from hiremarco.studio.analyze import split_key
from hiremarco.studio.booth import Booth, Tape, start_surface
from hiremarco.studio.commands import Command, understand
from hiremarco.studio.tracks import SessionState, TrackInfo


@pytest.mark.parametrize("line, command", [
    ("Marco, set the tune to the beat", Command("tune_console")),
    ("Marco, put the auto-tune in F minor", Command("tune_console", text="f minor")),
    ("Marco, set autotune to e flat minor", Command("tune_console", text="e flat minor")),
    ("Marco, tune it to the beat", Command("tune_console")),
    ("Marco, first pass in Flex", Command("flex_pass")),
    ("Marco, flex the vocal", Command("flex_pass")),
    ("Marco, put an LA-2A on the vocal", Command("insert_plugin", text="la-2a")),
    ("Marco, throw a Pro-Q on the harmony in slot 4", Command("insert_plugin", text="pro-q", track="harmony", slot=4)),
    ("Marco, add a CLA-76 to my lead, insert three", Command("insert_plugin", text="cla-76", slot=3)),
])
def test_the_controls_skip_the_model(line, command):
    assert understand(line, client=None) == command


@pytest.mark.parametrize("line, command", [
    ("Marco, turn up the tune", Command("knob", knob="tuning", direction="up", steps=1)),  # a step, not the Console
    ("Marco, first pass", Command("tune_take")),                                           # his own file-based pass
    ("Marco, put it on my phone", Command("live_view")),                                   # not a plug-in
])
def test_older_lines_keep_their_meaning(line, command):
    assert understand(line, client=None) == command


@pytest.mark.parametrize("said, split", [
    ("E minor", ("E", "minor")), ("e flat minor", ("D#", "minor")), ("F#m", ("F#", "minor")),
    ("Bb", ("A#", "major")), ("c sharp major", ("C#", "major")), ("Ab minor", ("G#", "minor")),
])
def test_split_key_spells_roots_with_sharps(said, split):
    assert split_key(said) == split


def test_split_key_refuses_what_is_not_a_key():
    with pytest.raises(ValueError):
        split_key("the beat")


class FakeConsole:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def tune(self, channel, key, scale):
        if self.fail:
            raise self.fail
        self.calls.append((channel, key, scale))
        return {"Key": key, "Scale": scale.upper(), "Retune Speed": "40"}


def booth(**parts):
    said = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(),
              say=said.append, feedback=None, tape=Tape(1000, seconds=1), log=lambda line: None, fillers=False, **parts)
    return b, said


def test_tune_to_a_said_key_sets_the_console_and_the_session_key():
    console = FakeConsole()
    b, said = booth(console=console)
    result = b.hear("Marco, put the auto-tune in F minor")
    assert console.calls == [(0, "F", "minor")] and b.key == "f minor"
    assert "Auto-Tune on input 1" in result and said == ["Auto-Tune's on F minor."]


def test_tune_to_the_beat_uses_the_session_key_when_there_is_one():
    console = FakeConsole()
    b, _ = booth(console=console, key="E minor")
    b.hear("Marco, set the tune to the beat")
    assert console.calls == [(0, "E", "minor")]


def test_a_console_that_refuses_is_said_and_logged():
    b, said = booth(console=FakeConsole(fail=OSError("connection refused")), key="E minor")
    result = b.hear("Marco, set the tune to the beat")
    assert "Auto-Tune not set: OSError" in result and said == ["I couldn't set the Auto-Tune. Is Console open with it on your input?"]


def test_flex_asks_for_the_key_then_runs_with_it():
    ran = []
    b, said = booth(flex=lambda key: ran.append(key) or "root=E scale=Natural Minor (Aeolian) correction=80.0")
    assert "> asked for the key before Flex >" in b.hear("Marco, first pass in Flex") and said == ["What key are we in?"]
    b.key = "E minor"
    assert "correction=80.0" in b.hear("Marco, first pass in Flex") and ran == ["E minor"]


def test_flex_tries_the_flat_spelling_when_the_menu_lacks_the_sharp():
    tried = []

    def run(args):
        tried.append(args)
        if args[1] == "D#":
            raise RuntimeError("Can't get menu item \"D#\" of menu 1")
        return "root=Eb"

    assert flex.first_pass("Eb minor", run=run) == "root=Eb"
    assert [a[1] for a in tried] == ["D#", "Eb"] and tried[0] == ["apply", "D#", "minor", "80"]


def test_insert_goes_to_the_selected_track_first_empty_slot():
    sent = []
    b, said = booth(surface=lambda line: sent.append(line) or "UAD Teletronix LA-2A Silver in insert 12 (the strip reads LA2ASlv)\nx\ny\n")
    result = b.hear("Marco, put an LA-2A on the vocal")
    assert sent == ["insert selected 0 la-2a"] and "> UAD Teletronix LA-2A Silver in insert 12 (the strip reads LA2ASlv) >" in result
    assert said == ["la-2a's in."]


def test_insert_names_a_session_track_with_its_spaces_carried():
    sent = []
    session = SessionState("recording", [TrackInfo(1, "Lead Vox", 2), TrackInfo(2, "Harmony 1", 1)])
    b, _ = booth(surface=lambda line: sent.append(line) or "done\n", session=session)
    b.hear("Marco, throw a Pro-Q on the harmony in slot 4")
    assert sent == ["insert Harmony+1 4 pro-q"]


def test_a_refused_insert_is_said_not_claimed():
    b, said = booth(surface=lambda line: "bad command: insert 3 on that track already holds CLA-76\nx\ny\n")
    result = b.hear("Marco, add a pultec to the vocal, slot 3")
    assert "> insert refused: bad command" in result and said[-1].startswith("Couldn't get pultec in.")


def test_a_surface_that_is_down_is_said():
    def down(line):
        raise ConnectionRefusedError

    b, said = booth(surface=down)
    assert "> surface not running >" in b.hear("Marco, put an LA-2A on the vocal")
    assert said == ["My control surface isn't up. Give me a second."]


def test_the_booth_reuses_a_running_surface_and_starts_one_otherwise(tmp_path):
    spawned = []
    assert start_surface(tmp_path, ask=lambda: "ok", spawn=spawned.append) == "surface already up" and spawned == []
    answers = iter([OSError(), OSError(), "ok"])

    def ask():
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a

    assert start_surface(tmp_path, ask=ask, spawn=spawned.append) == "surface started"
    assert "mcu', 'serve" in spawned[0][-1]


def test_a_loop_of_whole_bars_snaps_to_its_tempo():
    from hiremarco.studio.analyze import loop_tempo

    assert loop_tempo(118.6, 8 * 240 / 117) == 117.0      # eight bars of 117 read slightly fast
    assert loop_tempo(118.6, 135.0) == 118.6              # a whole beat is not a loop
    assert loop_tempo(90.0, 8 * 240 / 117) == 90.0        # nothing within 3%: the ear stands


def test_relatives_share_their_notes():
    from hiremarco.studio.analyze import relative, same_notes

    assert relative("G major") == "E minor" and relative("E minor") == "G major"
    assert same_notes("E minor", "G major") and not same_notes("E minor", "A major")


class Heard:
    key, bpm, bpm_other = "G major", 117.0, 0.0


def test_a_producer_label_outranks_the_ear(tmp_path):
    session = SessionState("recording", [TrackInfo(1, "instrumental 117", 1), TrackInfo(3, "OS_6ix_149_vocal_remnants_Em", 1)])
    b, _ = booth(session=session)
    key, why = b._beat_key(Heard(), tmp_path / "instrumental 117.wav")
    assert key == "E minor" and "same notes" in why
    bare, _ = booth()
    key, why = bare._beat_key(Heard(), tmp_path / "instrumental 117.wav")
    assert key == "G major" and "E minor" in why


def test_settle_tempo_takes_the_whole_number_the_readers_agree_on():
    from hiremarco.studio.analyze import settle_tempo

    wobble = [117.88, 116.77, 117.22, 115.2, 118.47]   # Logic's Smart Tempo on a 117 beat
    assert settle_tempo(117.0, None, wobble)[0] == 117.0 and "agree" in settle_tempo(117.0, None, wobble)[1]
    assert settle_tempo(118.0, 117.0, wobble)[0] == 117.0      # the producer's label wins
    assert settle_tempo(117.6, None, [])[0] == 118.0           # no Logic reading: the ear, rounded
    assert "check it" in settle_tempo(117.0, None, [150.0, 150.2])[1]


class LogicTracks:
    def __init__(self):
        self.calls = []

    def regions(self):
        return ["instrumental 117"]

    def region_tempo(self, region):
        self.calls.append(("apply", region))
        return "117.2167"

    def tempo_map(self):
        return [117.88, 116.77, 117.22]

    def undo(self, step):
        self.calls.append(("undo", step))
        return "undone"

    def set_tempo(self, bpm):
        self.calls.append(("tempo", bpm))
        return f"tempo set to {bpm:g}"


def test_logic_reads_the_beat_then_its_map_is_undone_for_the_whole_tempo():
    tracks, sent = LogicTracks(), []
    b, _ = booth(tracks=tracks, surface=lambda line: sent.append(line) or "selected strip 0\n")
    events, note = b._logic_tempo("instrumental 117")
    assert sent == ["select instrumental+117"] and events == [117.88, 116.77, 117.22]
    assert tracks.calls == [("apply", "instrumental 117"), ("undo", "Apply Region Tempo to Project Tempo")]


def test_a_failed_logic_reading_leaves_his_own():
    class Broken(LogicTracks):
        def region_tempo(self, region):
            raise RuntimeError("the Apply Region Tempo dialog did not open")

    b, _ = booth(tracks=Broken(), surface=lambda line: "ok\n")
    events, note = b._logic_tempo("instrumental 117")
    assert events == [] and "not taken" in note

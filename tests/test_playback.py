import numpy as np

from hiremarco.studio.booth import Booth, Tape
from hiremarco.studio.commands import Command, understand
from hiremarco.studio.position import Position, parse_where


def test_positions_count_like_logic():
    start = Position(5)
    assert start.later(2.0, 120).typed() == "6 1 1 1"           # two seconds at 120 is one bar of 4/4
    assert start.later(0.25, 120).typed() == "5 1 3 1"          # an eighth note: two sixteenths
    assert Position(9, 2, 3, 121).later(0, 90).typed() == "9 2 3 121"
    assert parse_where("5 1 1 1 120 4") == (Position(5), 120.0, 4)


class FakeTracks:
    def __init__(self):
        self.calls = []

    def where(self):
        return Position(5), 120.0, 4

    def solo(self, on):
        self.calls.append(on)
        return f"solo {'on' if on else 'off'}: Harmony 1"


class Turn:
    def __init__(self, text, start_ms, end_ms):
        self.text, self.start_ms, self.end_ms = text, start_ms, end_ms


def booth():
    did, said = [], []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: did.append(c) or c.describe(),
              say=said.append, feedback=lambda a, r: None, tape=Tape(1000, seconds=30), log=lambda line: None,
              tracks=FakeTracks(), transcribe=lambda audio, rate: [Turn("you should let me love you", 4000, 8000)])
    return b, did, said


def test_play_it_back_goes_to_where_the_take_started_and_plays():
    b, did, said = booth()
    b.hear("Marco, record.")
    b.tape.write(np.ones(9000))
    b.hear("Marco, stop.")
    did.clear()
    assert "playing the take from 5 1 1 1" in b.hear("Marco, play it back")
    assert did == [Command("play_from", text="5 1 1 1")] and b.rolling


def test_take_me_back_to_a_line_jumps_to_just_before_it():
    b, did, said = booth()
    b.hear("Marco, record.")
    b.tape.write(np.ones(9000))
    b.hear("Marco, stop.")
    did.clear()
    result = b.hear("Marco, take me back to where I say let me love you")
    # "let me love you" sits from about 5.6 s in the turn; a second earlier at 120 bpm is about two bars in
    assert "estimate" in result and did[0].action == "play_from" and did[0].text.startswith("7 ")


def test_solo_and_unsolo_act_on_the_selected_track_without_a_word():
    b, did, said = booth()
    assert "solo on" in b.hear("Marco, solo my vocals") and "solo off" in b.hear("Marco, unsolo")
    assert b.tracks.calls == [True, False] and said == []


def test_the_solo_comes_off_by_itself_before_the_next_take_unless_it_is_a_cappella():
    b, did, said = booth()
    b.hear("Marco, solo my vocals")
    assert b.soloed and b.tracks.calls == [True]
    assert understand("Marco, all right, let's go again", client=None) == Command("go_again")
    b.hear("Marco, all right, let's go again")
    assert b.tracks.calls == [True, False] and not b.soloed and b.rolling  # unsoloed, then rolling
    b.hear("stop")
    b.hear("Marco, I'd like to record this a cappella")
    assert b.tracks.calls == [True, False, True] and b.rolling and b.soloed  # solo on for the a cappella take
    b.hear("stop")
    b.hear("Marco, one more")
    assert b.tracks.calls[-1] is False and not b.soloed  # the next normal take: off again


def test_moving_to_a_different_part_takes_the_solo_off_and_asks_where():
    b, did, said = booth()
    b.hear("Marco, solo it")
    assert "next part" in b.hear("Marco, let's record a different part")
    assert b.tracks.calls == [True, False] and said[-1] == "Where do you want to pick it up?"


def test_reading_the_beat_offers_the_key_and_tempo_and_a_yes_sets_them(monkeypatch, tmp_path):
    from hiremarco.studio import analyze

    b, did, said = booth()
    b.tracks.regions = lambda: ["Dreamy Keys 140BPM #01"]
    b.tracks.set_tempo = lambda bpm: f"tempo set to {bpm:g}"
    beat = tmp_path / "Dreamy Keys 140BPM.wav"
    monkeypatch.setattr(analyze, "find_audio", lambda region: beat)
    monkeypatch.setattr(analyze, "read", lambda path: analyze.Reading("F minor", 0.8, "G# major", 140.0, 70.0))
    assert understand("Marco, what key is the beat in?", client=None) == Command("read_beat")
    result = b.hear("Marco, what key is the beat in?")
    assert "F minor (" in result and "140 BPM (your file name" in result and "Want me to set the session" in said[-1]
    assert "tempo set to 140" in b.hear("Marco, yes") and b.key == "F minor"
    assert b.offer is None


def test_a_region_finds_its_file_without_logics_marks():
    from hiremarco.studio.analyze import find_audio, label

    hits = ["/x/Dreamy Keys 140BPM.wav", "/x/Dreamy Keys 140BPM.asd", "/y/Dreamy Keys 140BPM copy.wav"]
    assert str(find_audio("Dreamy Keys 140BPM #01", search=lambda name: hits)) == "/x/Dreamy Keys 140BPM.wav"
    assert label("BOI1DA_melodic_loop_piano_4bar_90_F#min") == ("F# minor", 90.0)
    assert label("SLS_CSP_92_electric_bass_soul_needyou_Bbmin") == ("A# minor", 92.0)

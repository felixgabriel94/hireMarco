"""The loudness ladder: up one dB at a time on the loudest bars until a bar breaks, back to the last clean step."""

from pathlib import Path

from hiremarco.master import ladder
from hiremarco.mix.verify import Verdict


class Limiter:
    """A fake limiter and printer: louder with gain, and pumping once the gain passes 4.5 dB."""

    def __init__(self):
        self.gain = 2.5
        self.sets = []

    def set_gain(self, value):
        self.gain = value
        self.sets.append(value)
        return value

    def print_bars(self, label):
        return Path(f"/prints/{label}.wav")

    def compare(self, path):
        gain = float(str(path).split("ladder ")[1].split(" dB")[0])
        if gain > 4.5:
            return Verdict(False, reasons=["the master pumps at the beat rate: 3.1 dB of swing where the mix has 0.4 dB"])
        return Verdict(True)

    def lufs_of(self, path):
        gain = float(str(path).split("ladder ")[1].split(" dB")[0])
        return -12.0 + (gain - 2.5)


def test_the_ladder_climbs_until_a_bar_breaks_and_goes_back():
    lim, said = Limiter(), []
    out = ladder.climb(start_gain_db=2.5, set_gain=lim.set_gain, print_bars=lim.print_bars, compare=lim.compare,
                       lufs_of=lim.lufs_of, log=said.append)
    assert [(s.gain_db, s.passed) for s in out.steps] == [(2.5, True), (3.5, True), (4.5, True), (5.5, False)]
    assert out.ceiling_gain_db == 4.5 and out.ceiling_lufs == -10.0 and out.gave_first.startswith("the master pumps")
    assert lim.sets == [3.5, 4.5, 5.5, 4.5] and lim.gain == 4.5
    assert out.lines()[-1].startswith("ceiling: limiter gain +4.5 dB, -10.0 LUFS on the loudest bars; what gave first: the master pumps")


def test_a_first_step_that_fails_leaves_the_gain_where_it_was():
    lim = Limiter()
    lim.compare = lambda path: Verdict(False, reasons=["peak-to-loudness 6.0 dB: limited hard, under the 8 dB floor"])
    out = ladder.climb(start_gain_db=2.5, set_gain=lim.set_gain, print_bars=lim.print_bars, compare=lim.compare, lufs_of=lim.lufs_of)
    assert out.ceiling_gain_db is None and lim.sets == [] and out.gave_first.startswith("peak-to-loudness")


def test_the_cap_stops_a_ladder_nothing_breaks():
    lim = Limiter()
    lim.compare = lambda path: Verdict(True)
    out = ladder.climb(start_gain_db=2.5, set_gain=lim.set_gain, print_bars=lim.print_bars, compare=lim.compare,
                       lufs_of=lambda p: -6.0 + (float(str(p).split("ladder ")[1].split(" dB")[0]) - 2.5), max_steps=4)
    assert len(out.steps) == 1 and out.ceiling_lufs == -6.0 and "nothing gave" in out.lines()[-1]


def test_the_ears_can_break_a_step():
    mix = {"psychoacoustics": {"roughness_asper_mean": 0.27}}
    assert ladder.hearing_bars(mix, {"psychoacoustics": {"roughness_asper_mean": 0.30}}) == []
    assert ladder.hearing_bars(mix, {"psychoacoustics": {"roughness_asper_mean": 0.50}}) == ["roughness rose +0.23 asper over the mix's bars"]
    assert ladder.hearing_bars(mix, {"zimtohrli": {"mos_mix_vs_reference": 3.1}}) == ["likeness to the mix 3.10 of 5, under the 3.5 floor"]
    assert ladder.hearing_bars(mix, {"error": "no stack"}) == [] and ladder.hearing_bars(None, None) == []


def test_the_brain_can_stop_the_ladder_short_of_the_floors_but_not_pass_them():
    lim, said = Limiter(), []
    asked = []

    def ask_next(step):
        asked.append(step.gain_db)
        return (step.gain_db < 3.5, "3.5 dB sits 1 dB under the pumping floor; the next step buys nothing the song needs")

    out = ladder.climb(start_gain_db=2.5, set_gain=lim.set_gain, print_bars=lim.print_bars, compare=lim.compare,
                       lufs_of=lim.lufs_of, ask_next=ask_next, log=said.append)
    assert [(s.gain_db, s.passed) for s in out.steps] == [(2.5, True), (3.5, True)] and asked == [2.5, 3.5]
    assert out.ceiling_gain_db == 3.5 and out.stopped_by.startswith("3.5 dB sits") and out.as_dict()["stopped_by"] == out.stopped_by
    # a brain that says louder past a floor changes nothing: the meters refuse the step as before
    out = ladder.climb(start_gain_db=2.5, set_gain=lim.set_gain, print_bars=lim.print_bars, compare=lim.compare,
                       lufs_of=lim.lufs_of, ask_next=lambda s: (True, "louder"), log=said.append)
    assert out.ceiling_gain_db == 4.5 and out.gave_first.startswith("the master pumps") and out.stopped_by == ""

"""A Logic plug-in's control set to an exact value by its name, Valhalla first (Owner 2026-11-04)."""

import pytest

from hiremarco import gate
from hiremarco.studio.booth import Booth, Tape
from hiremarco.studio.chain import Channel
from hiremarco.studio.commands import Command, understand


@pytest.mark.parametrize("line, command", [
    ("Marco, set the decay to 2 seconds", Command("plugin_set", text="decay=2 s", direction="set")),
    ("Marco, predelay 30", Command("plugin_set", text="predelay=30", direction="set")),
    ("Marco, predelay thirty milliseconds", Command("plugin_set", text="predelay=30 ms", direction="set")),
    ("Marco, mix 25 percent", Command("plugin_set", text="mix=25 %", direction="set")),
    ("Marco, mix 25%", Command("plugin_set", text="mix=25 %", direction="set")),
    ("Marco, set the high cut on the valhalla to 6k", Command("plugin_set", text="high cut=6 kHz@valhalla", direction="set")),
    ("Marco, set the high shelf to minus 12 dB", Command("plugin_set", text="high shelf=-12 dB", direction="set")),
    ("Marco, bass mult 1.2", Command("plugin_set", text="bass mult=1.2", direction="set")),
])
def test_exact_values_skip_the_model(line, command):
    assert understand(line, client=None) == command


@pytest.mark.parametrize("line, command", [
    ("Marco, retune speed 20", Command("autotune", text="retune speed=20", direction="set")),   # the Console's
    ("Marco, set the reverb to 60 percent", Command("knob", knob="reverb", direction="set", percent=60)),
    ("Marco, put the auto-tune in F minor", Command("tune_console", text="f minor")),
])
def test_older_lines_keep_their_meaning(line, command):
    assert understand(line, client=None) == command


@pytest.mark.parametrize("line", ["Marco, chorus 2", "Marco, take three", "Marco, harmony 2", "Marco, verse 2", "Marco, go to bar 5",
                                  "Marco, set the volume to -50", "Marco, bar 12"])
def test_sections_and_takes_are_not_controls(line):
    assert plugin_set_or_none(line) is None


def plugin_set_or_none(line):
    from hiremarco.studio.commands import plugin_set_said, strip_wake
    return plugin_set_said(strip_wake(line))


class Valhalla:
    """chain_io.applescript for one track: ValhallaVintageVerb on slot 1 with its own units, a bypassed Pro-Q on 2."""

    def __init__(self, *, second_mix=False):
        self.params = {"Mix": 100.0, "PreDelay": 20.0, "Decay": 40.0, "HighCut": 80.0, "Mode": "Concert Hall"}
        self.second_mix = second_mix
        self.calls = []

    def shown(self, k, v):
        return {"Mix": f"{v:.1f} %", "PreDelay": f"{v:.2f} ms", "Decay": f"{v / 10:.2f} s", "HighCut": f"{v * 100:.0f} Hz"}[k]

    def block(self):
        lines = ["plugin\tValhallaVintageVerb"]
        for k, v in self.params.items():
            lines.append(f"{k}\t~{v}" if isinstance(v, str) else f"{k}\t{v}\t0\t100\t{self.shown(k, v)}")
        return "\n".join(lines)

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "list":
            return "1\tValhallaVintageVerb\ton\n2\tPro-Q 3\tbypassed" + ("\n3\tChannel EQ\ton" if self.second_mix else "")
        if args[0] == "readall":
            out = "slot\t1\n" + self.block()
            if self.second_mix:
                out += "\nslot\t3\nplugin\tChannel EQ\nMix\t50\t0\t100\t50.0 %"
            return out
        if args[0] == "setmany":
            assert args[1] == "1" and args[-1] == ";"
            for k, v in zip(args[2:-1:2], args[3:-1:2]):
                if v.startswith("="):
                    number, unit = v[1:].split(" ", 1)
                    number = float(number)
                    self.params[k] = {"s": number * 10, "ms": number, "Hz": number / 100, "kHz": number * 10}[unit]
                else:
                    self.params[k] = float(v)
            return "slot\t1\n" + self.block()
        raise AssertionError(args)


@pytest.fixture
def rules(tmp_path):
    p = tmp_path / "RULES.md"
    p.write_text("send: logic -> * ; Logic ; until 2099-01-01\n")
    return p


def booth(rules, **fake):
    logic = Valhalla(**fake)
    said = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(),
              say=said.append, feedback=None, tape=Tape(1000, seconds=1), log=lambda line: None,
              plugin=Channel(run=logic, conn=gate.connect(":memory:"), rules_path=rules))
    return b, said, logic


def test_decay_in_seconds_lands_and_is_read_back(rules):
    b, said, logic = booth(rules)
    result = b.hear("Marco, set the decay to 2 seconds")
    assert logic.params["Decay"] == 20.0 and said == ["Decay's at 2.00 s."] and "Decay: 2.00 s" in result


def test_no_unit_means_the_one_it_shows(rules):
    b, said, logic = booth(rules)
    b.hear("Marco, predelay 30")
    assert logic.params["PreDelay"] == 30.0 and said == ["PreDelay's at 30.00 ms."]
    b.hear("Marco, set the high cut to 6k")
    assert logic.params["HighCut"] == 60.0 and said[-1] == "HighCut's at 6000 Hz."


def test_percent_is_of_the_range_and_put_back_undoes_it(rules):
    b, said, logic = booth(rules)
    b.hear("Marco, mix 25 percent")
    assert logic.params["Mix"] == 25.0 and said == ["Mix's at 25.0 %."]
    b.hear("Marco, put it back")
    assert logic.params["Mix"] == 100.0


def test_a_wrong_unit_is_said_not_guessed(rules):
    b, said, logic = booth(rules)
    b.hear("Marco, set the decay to 30 dB")
    assert logic.params["Decay"] == 40.0 and said == ["Decay reads in s. Give it to me in that."]


def test_mode_is_left_alone_and_a_missing_control_is_said(rules):
    b, said, logic = booth(rules)
    b.hear("Marco, set the mode to 2")
    assert said[-1].startswith("I leave mode as it is") and logic.params["Mode"] == "Concert Hall"
    b.hear("Marco, shimmer 40")
    assert said[-1] == "I don't see shimmer on this track's plug-ins."


def test_two_plugins_with_the_control_asks_which_then_the_name_picks(rules):
    b, said, logic = booth(rules, second_mix=True)
    b.hear("Marco, mix 30 percent")
    assert said[-1] == "Mix is on ValhallaVintageVerb and Channel EQ. Which one?" and logic.params["Mix"] == 100.0
    b.hear("Marco, set the mix on the valhalla to 30 percent")
    assert logic.params["Mix"] == 30.0


def test_nothing_moves_while_a_take_rolls(rules):
    b, said, logic = booth(rules)
    b.rolling = True
    assert "holding the plug-in change" in b.handle(Command("plugin_set", text="decay=2 s", direction="set"))
    assert logic.params["Decay"] == 40.0 and not any(c[0] == "setmany" for c in logic.calls)


@pytest.mark.parametrize("line, command", [
    ("Marco, set band 2 gain to minus 3 dB", Command("plugin_set", text="band 2 gain=-3 dB", direction="set")),
    ("Marco, band two frequency 300 hertz", Command("plugin_set", text="band 2 frequency=300 Hz", direction="set")),
    ("Marco, set the band 1 q to 1.5", Command("plugin_set", text="band 1 q=1.5", direction="set")),
])
def test_pro_q_bands_by_number(line, command):
    assert understand(line, client=None) == command


class ProQ(Valhalla):
    """Pro-Q 3 on slot 1, with its controls numbered by band and shown in dB, Hz and its Q."""

    def __init__(self):
        super().__init__()
        self.params = {"Band 1 Frequency": 100.0, "Band 1 Gain": 0.0, "Band 1 Q": 1.0, "Band 2 Frequency": 1000.0,
                       "Band 2 Gain": 0.0, "Band 2 Q": 1.0, "Band 2 Shape": "Bell"}

    def shown(self, k, v):
        return f"{v:.1f} Hz" if k.endswith("Frequency") else f"{v:+.2f} dB" if k.endswith("Gain") else f"{v:.2f}"

    def block(self):
        return super().block().replace("ValhallaVintageVerb", "Pro-Q 3")

    def __call__(self, args):
        if args[0] == "list":
            self.calls.append(args)
            return "1\tPro-Q 3\ton"
        if args[0] == "setmany":
            self.calls.append(args)
            for k, v in zip(args[2:-1:2], args[3:-1:2]):
                number = float(v[1:].split(" ", 1)[0]) if v.startswith("=") else float(v)
                self.params[k] = number
            return "slot\t1\n" + self.block()
        return super().__call__(args)



def test_pro_q_band_gain_and_frequency_land_in_its_units(rules):
    logic = ProQ()
    said = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(),
              say=said.append, feedback=None, tape=Tape(1000, seconds=1), log=lambda line: None,
              plugin=Channel(run=logic, conn=gate.connect(":memory:"), rules_path=rules))
    b.hear("Marco, set band 2 gain to minus 3 dB")
    assert logic.params["Band 2 Gain"] == -3.0 and said[-1] == "Band 2 Gain's at -3.00 dB."
    b.hear("Marco, band two frequency 300 hertz")
    assert logic.params["Band 2 Frequency"] == 300.0 and said[-1] == "Band 2 Frequency's at 300.0 Hz."
    b.hear("Marco, set band 2 shape to 3")
    assert said[-1].startswith("I leave band 2 shape as it is")


@pytest.mark.parametrize("line", [
    "Marco, cut some of the lows on this track", "Marco, clean up the low end", "Marco, less mud",
    "Marco, tame the harshness on my vocal", "Marco, add a little air", "Marco, cut some 300 hertz",
    "Marco, boost the highs a little", "Marco, roll off the bottom",
])
def test_eq_words_go_to_the_sound_on_the_track(line):
    from hiremarco.studio.commands import strip_wake
    assert understand(line, client=None) == Command("sound", text=strip_wake(line))


def test_older_sound_and_knob_lines_hold():
    assert understand("Marco, more verb", client=None) == Command("knob", knob="reverb", direction="up", steps=1)
    assert understand("Marco, make it darker", client=None) == Command("sound", text="darker")

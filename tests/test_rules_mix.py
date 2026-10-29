import pytest

from hiremarco.mix.rules import RULEBOOK, belongs_on, kind


@pytest.mark.parametrize("name, expected", [
    ("UAD Auto-Tune Realtime Advanced", "tuning"), ("Pro-Q 3", "eq"), ("Pro-G", "gate"), ("UAD Pultec EQP-1A", "eq"),
    ("CLA-76 (s)", "compressor"), ("F6-RTA (s)", "eq"), ("RVox (s)", "compressor"), ("Ghz Trem C", "modulation"),
    ("Pro-DS", "de-esser"), ("Pro-C 2", "compressor"), ("soothe2", "resonance control"),
    ("ValhallaVintageVerb", "reverb"), ("EchoBoy", "delay"),
])
def test_every_plugin_in_the_owners_chain_has_a_kind(name, expected):
    assert kind(name) == expected


def test_unknown_names_fall_back_to_their_controls():
    assert kind("Mystery FX", {"Decay": 1, "PreDelay": 2}) == "reverb"
    assert kind("Mystery FX", {"Ratio": 1, "Attack": 2}) == "compressor"
    assert kind("Mystery FX", {"Foo": 1}) == "unknown"


def test_space_goes_on_buses_and_character_on_inserts():
    assert belongs_on("reverb") == "bus" and belongs_on("delay") == "bus"
    assert belongs_on("eq") == "insert" and belongs_on("de-esser") == "insert"


def test_the_rulebook_holds_the_lines_marco_does_not_cross():
    for must in ("No limiter", "3 dB of true-peak headroom", "mono below about 120 Hz", "100 percent wet"):
        assert must in RULEBOOK

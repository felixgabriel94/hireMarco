import pytest

from hiremarco import gate
from hiremarco.studio.booth import MISSED, STOPPED, Booth, Tape
from hiremarco.studio.commands import Command, understand


@pytest.fixture(autouse=True)
def switch_off():
    gate.set_kill_switch(False)
    yield
    gate.set_kill_switch(False)


def booth(understand_fn):
    said, did = [], []
    b = Booth(understand=understand_fn, logic=lambda c: did.append(c) or c.describe(), say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None)
    return b, said, did


@pytest.mark.parametrize("line", ["Marco, stop everything", "Marco, kill it", "Marco, hands off", "Marco, freeze"])
def test_the_kill_line_is_matched_before_anything_else(line):
    assert understand(line, client=None) == Command("kill")


def test_stop_everything_turns_the_switch_on_stops_the_take_and_only_the_desk_clears_it():
    b, said, did = booth(lambda line: understand(line, client=None))
    b.hear("Marco, record.")
    assert b.rolling
    result = b.hear("Marco, stop everything")
    assert gate.kill_switch_on() and not b.rolling
    assert did[-1] == Command("stop") and said[-1] == STOPPED
    assert "marco gate kill off" in result
    # with the switch on, the gate refuses every action that goes through it
    with pytest.raises(gate.Refused, match="kill switch"):
        gate.check_outbound(gate.connect(":memory:"), tenant_id="owner", idempotency_key="x", capability="c",
                            channel="logic", target="*", message="m", department="studio")


def test_a_line_for_marco_he_cannot_place_gets_say_it_again_not_silence():
    b, said, did = booth(lambda line: Command("unknown"))
    result = b.hear("Marco, do the thing with the stuff")
    assert said == [MISSED] and did == [] and "nothing done" in result

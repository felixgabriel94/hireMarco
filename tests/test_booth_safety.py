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


def test_a_failing_action_is_said_and_logged_and_the_booth_keeps_listening():
    from hiremarco.studio.booth import FAILED

    def explode(command):
        raise RuntimeError("osascript exit 1: Invalid index")

    said = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=explode, say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None)
    result = b.hear("Marco, record.")
    assert "failed: RuntimeError" in result and said[-1] == FAILED
    assert "stop" in b.hear("Marco, stop.")  # still listening


def test_the_gate_record_works_across_threads(tmp_path):
    import threading

    conn = gate.connect(tmp_path / "gate.sqlite")
    errors = []

    def use():
        try:
            gate.check_outbound(conn, tenant_id="owner", idempotency_key="t", capability="c", channel="logic",
                                target="*", message="m", department="studio", rules_path=tmp_path / "none.md")
        except gate.Refused:
            pass  # no switch file: refused, but the record itself was readable
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=use)
    t.start()
    t.join()
    assert errors == []

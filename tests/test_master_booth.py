"""'Send it to mix' by voice: the booth's export action starts the master beside the booth and says when it is done."""

import time

from hiremarco.studio.booth import Booth, Tape
from hiremarco.studio.commands import Command

RATE = 48000


def booth_with(master):
    said = []
    b = Booth(understand=lambda line: Command("unknown"), logic=lambda c: c.describe(), say=said.append,
              feedback=lambda take, rate: None, tape=Tape(RATE, seconds=5), log=lambda line: None, master=master)
    return b, said


def wait_until_idle(b, seconds=5.0):
    deadline = time.monotonic() + seconds
    while b.busy and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.05)


def test_export_runs_the_master_and_reports():
    asked = []
    b, said = booth_with(lambda words: asked.append(words) or "Master, demo: -10.1 LUFS")
    assert b.handle(Command("export", text="a little warmer")) == "mastering started"
    wait_until_idle(b)
    assert asked == ["a little warmer"]
    assert said[0].startswith("On it") and said[-1].startswith("Master's done")
    assert not b.busy


def test_export_without_mastering_or_while_rolling_holds():
    b, said = booth_with(None)
    assert b.handle(Command("export")) == "no mastering in this booth"
    b, said = booth_with(lambda words: "ok")
    b.rolling = True
    assert b.handle(Command("export")) == "holding the master until the take stops"


def test_a_stopped_master_is_said_and_texted():
    texts = []
    b, said = booth_with(lambda words: (_ for _ in ()).throw(RuntimeError("the mix print is silent")))
    b.text_owner = texts.append
    b.handle(Command("export"))
    wait_until_idle(b)
    assert said[-1].startswith("The master stopped")
    assert texts == ["The master stopped: the mix print is silent"]

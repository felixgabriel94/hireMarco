import os

import numpy as np

from hiremarco.studio import halo
from hiremarco.studio.audio import DuplexAudio
from hiremarco.studio.booth import Booth, Tape
from hiremarco.studio.commands import understand


def test_the_halo_hears_the_state_as_one_line():
    sent = []
    link = halo.Halo(lambda: ("speaking", 0.61234), send=sent.append)
    assert link.tick() == b"speaking 0.612" and sent == [b"speaking 0.612"]


def test_a_halo_that_is_not_up_does_not_stop_the_booth():
    def refuse(data):
        raise ConnectionRefusedError()

    assert halo.Halo(lambda: ("listening", 0.1), send=refuse).tick() == b"listening 0.100"


def test_levels_are_clamped():
    assert halo.level_of(0.5, 10) == 1.0 and halo.level_of(0.01, 8) == 0.08 and halo.level_of(-1, 8) == 0.0


def test_the_build_is_skipped_when_the_binary_is_newer_than_the_source(tmp_path, monkeypatch):
    source, target = tmp_path / "MarcoHalo.swift", tmp_path / "bin" / "MarcoHalo"
    source.write_text("// halo")
    target.parent.mkdir()
    target.write_text("binary")
    os.utime(source, (1000, 1000))
    ran = []
    monkeypatch.setattr(halo.subprocess, "run", lambda *a, **k: ran.append(a))
    assert halo.build(source, target) == target and ran == []


def test_the_audio_reports_both_levels_and_whether_marco_is_speaking():
    audio = DuplexAudio(device=None, rate=1000, mic_channel=1, out_pair=(1, 2), in_channels=2, out_channels=2,
                        on_input=lambda block: None, blocksize=100)
    indata = np.full((100, 2), 0.25, dtype="float32")
    audio.callback(indata, np.zeros((100, 2), dtype="float32"), 100, None, None)
    assert abs(audio.in_level - 0.25) < 1e-6 and audio.out_level == 0.0 and not audio.speaking
    audio._drained.clear()
    audio._pending.put(np.full(100, 0.5, dtype="float32"))
    audio.callback(indata, np.zeros((100, 2), dtype="float32"), 100, None, None)
    assert abs(audio.out_level - 0.5) < 1e-6 and audio.speaking


def test_the_booth_is_busy_only_while_a_command_runs():
    seen = []
    b = Booth(understand=lambda line: understand(line, client=None),
              logic=lambda c: seen.append(b.busy) or c.describe(), say=lambda text: None,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None)
    b.hear("Marco, record.")
    assert seen == [True] and b.busy is False


def test_a_rolling_take_sends_the_halo_away_and_the_conversation_brings_it_back():
    from types import SimpleNamespace

    audio = SimpleNamespace(speaking=True, out_level=0.05, in_level=0.02)
    booth = SimpleNamespace(rolling=True, busy=False)
    assert halo.booth_state(booth, audio) == ("recording", 0.0)
    booth.rolling = False
    assert halo.booth_state(booth, audio) == ("speaking", 0.5)
    audio.speaking, booth.busy = False, True
    assert halo.booth_state(booth, audio) == ("thinking", 0.0)
    booth.busy = False
    assert halo.booth_state(booth, audio) == ("listening", 0.16)


def test_his_name_alone_gets_an_answer_and_his_name_mid_sentence_raises_the_halo():
    from types import SimpleNamespace
    import time as clock

    from hiremarco.studio.booth import HEARD
    from hiremarco.studio.commands import Command, calls_marco

    for line in ("Marco.", "Hey Marco", "hey marco?", "Marco, Marco"):
        assert understand(line, client=None) == Command("summon"), line
    assert understand("Marco, record.", client=None) == Command("record")
    assert calls_marco("Hey Marco, can you") and calls_marco("marco") and not calls_marco("so Marco said")
    said = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(), say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None)
    assert "answered" in b.hear("Hey Marco") and said and said[-1] in HEARD
    audio = SimpleNamespace(speaking=False, out_level=0.0, in_level=0.0)
    booth = SimpleNamespace(rolling=False, busy=False, called_at=clock.monotonic())
    assert halo.booth_state(booth, audio) == ("thinking", 0.0)
    booth.called_at -= 10
    assert halo.booth_state(booth, audio) == ("listening", 0.0)


def test_the_listener_hands_on_each_partial_and_yields_only_finished_sentences(monkeypatch, tmp_path):
    import asyncio
    import json

    from hiremarco import hearing

    events = [{"type": "partialTranscript", "transcript": "Hey Mar"},
              {"type": "partialTranscript", "transcript": "Hey Marco, re"},
              {"type": "speechComplete", "transcript": "Hey Marco, record."}]

    class FakeSocket:
        def __init__(self):
            self.sent = []

        async def send(self, data):
            self.sent.append(data)

        async def recv(self):
            return json.dumps({"sessionId": "s"})

        def __aiter__(self):
            async def gen():
                for e in events:
                    yield json.dumps(e)
            return gen()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    monkeypatch.setenv("MODEL_API_KEY", "k")
    partials = []
    listener = hearing.Listener(connect=lambda url: FakeSocket(), on_partial=partials.append)

    async def mic():
        if False:
            yield b""

    async def run():
        return [line async for line in listener.sentences(mic())]

    assert asyncio.run(run()) == ["Hey Marco, record."] and partials == ["Hey Mar", "Hey Marco, re"]


def test_once_awake_he_needs_no_name_until_a_take_or_a_quiet_stretch():
    from hiremarco.studio.booth import AWAKE, MISSED

    said, links, did = [], [], []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: did.append(c.action) or c.describe(),
              say=said.append, feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None,
              live=lambda: "http://x", send_link=links.append)
    b.hear("Hey Marco.")
    assert "link texted" in b.hear("Give me the live view.") and links == ["Live view: http://x"]
    assert "play" in b.hear("Play it back.")  # still awake, still no name
    assert b.hear("can you pass me the water") is None and MISSED not in said  # not for him: let pass
    b.hear("Record.")
    assert b.rolling and b.hear("stop") is None  # sung or said during the take: never a command without his name
    assert "stop" in b.hear("Marco, stop.")
    b.awake_at -= AWAKE + 1
    assert b.hear("Give me the live view.") is None and len(links) == 1


def test_thats_all_puts_him_to_sleep_and_his_name_wakes_him():
    from types import SimpleNamespace

    from hiremarco.studio.booth import DISMISSED
    from hiremarco.studio.commands import Command

    for line in ("Marco, that's all.", "Marco, thanks", "Marco, go to sleep", "Marco, we're good"):
        assert understand(line, client=None) == Command("dismiss"), line
    said = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(), say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None)
    b.hear("Hey Marco.")
    assert "dismissed" in b.hear("Thanks, Marco.") and said[-1] == DISMISSED and b.asleep
    assert b.hear("Play it back.") is None  # asleep: no name, no command
    audio = SimpleNamespace(speaking=False, out_level=0.0, in_level=0.1)
    assert halo.booth_state(b, audio) == ("asleep", 0.0)
    assert "play" in b.hear("Marco, play it back.") and not b.asleep


def test_his_answer_to_his_name_varies_and_asks_how_the_take_felt_once_after_it():
    from hiremarco.studio.booth import AFTER_TAKE, HEARD

    said = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(), say=said.append,
              feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None)
    answers = []
    for _ in range(12):
        b.awake_at = -100.0
        b.hear("Hey Marco.")
        answers.append(said[-1])
    assert all(a in HEARD for a in answers)
    assert all(answers[i] not in answers[max(0, i - 3):i] for i in range(len(answers)))  # never three alike
    b.hear("Marco, record.")
    b.hear("Marco, stop.")
    b.awake_at = -100.0
    b.hear("Hey Marco.")
    assert said[-1] in AFTER_TAKE
    b.awake_at = -100.0
    b.hear("Hey Marco.")
    assert said[-1] in HEARD

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

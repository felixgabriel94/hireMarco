import threading

import numpy as np
import pytest

from hiremarco.studio.audio import DuplexAudio, resample


def test_resample_keeps_duration_and_level():
    tone = (np.sin(np.arange(24000) / 10) * 16000).astype("<i2")
    out = resample(tone, 24000, 48000)
    assert out.size == 48000 and out.dtype == np.float32
    assert np.max(np.abs(out)) == pytest.approx(16000 / 32768, abs=0.01)
    assert resample(tone, 24000, 24000).size == 24000 and resample(np.zeros(0, "<i2"), 24000, 48000).size == 0


def make(frames=100):
    heard = []
    audio = DuplexAudio(device=None, rate=1000, mic_channel=2, out_pair=(3, 4), in_channels=4, out_channels=4,
                        on_input=heard.append, blocksize=frames)
    return audio, heard


def run_callbacks(audio, n, frames=100):
    for i in range(n):
        indata = np.zeros((frames, 4), dtype="float32")
        indata[:, 1] = i + 1  # the mic lives on channel 2
        outdata = np.ones((frames, 4), dtype="float32")  # garbage that must be overwritten
        audio.callback(indata, outdata, frames, None, None)
        yield outdata


def test_the_mic_channel_is_forwarded_and_silence_is_written_when_marco_is_quiet():
    audio, heard = make()
    outs = list(run_callbacks(audio, 2))
    assert [h[0] for h in heard] == [1.0, 2.0] and all(h.size == 100 for h in heard)
    assert all(not np.any(o) for o in outs)


def test_a_line_is_written_on_the_out_pair_across_callbacks_and_play_returns_when_drained():
    audio, _ = make()
    line = (np.full(250, 8000, dtype="<i2"))  # 250 samples at the device rate, spans three callbacks
    done = threading.Event()

    def speak():
        audio.play(line, audio.rate)
        done.set()

    t = threading.Thread(target=speak)
    t.start()
    outs = []
    for _ in range(50):
        outs.extend(run_callbacks(audio, 1))
        if done.is_set():
            break
    t.join(timeout=1)
    assert done.is_set()
    written = np.concatenate([o[:, 2] for o in outs])  # channel 3
    assert np.count_nonzero(written) == 250 and np.allclose(written[written != 0], 8000 / 32768)
    assert np.array_equal(outs[0][:, 2], outs[0][:, 3])  # both channels of the pair
    assert not np.any(np.concatenate([o[:, 0] for o in outs]))  # nothing on channels outside the pair


def test_an_out_channel_beyond_the_device_is_ignored_not_an_error():
    audio, _ = make()
    audio.out_pair = (3, 9)
    audio._pending.put(np.full(10, 0.5, dtype="float32"))
    outdata = np.zeros((100, 4), dtype="float32")
    audio.callback(np.zeros((100, 4), dtype="float32"), outdata, 100, None, None)
    assert np.count_nonzero(outdata[:, 2]) == 10 and not np.any(outdata[:, 3])


def test_interrupt_stops_marco_mid_word_and_play_returns():
    audio, _ = make()
    done = threading.Event()

    def speak():
        audio.play(np.full(5000, 8000, dtype="<i2"), audio.rate)  # five seconds at the device rate
        done.set()

    t = threading.Thread(target=speak)
    t.start()
    for _ in range(100):  # until the line is queued
        if audio.speaking:
            break
        threading.Event().wait(0.01)
    list(run_callbacks(audio, 2))
    assert audio.speaking
    audio.interrupt()
    t.join(timeout=1)
    assert done.is_set() and not audio.speaking
    outs = list(run_callbacks(audio, 1))
    assert not np.any(outs[0])  # nothing left to play


def test_the_artist_talking_over_marco_is_told_from_his_own_bleed():
    from hiremarco.studio.booth import Barge

    b = Barge()
    block = np.zeros(10)
    for _ in range(3):
        assert not b.hear(0.006, 0.06, block)  # he talks; the mic hears a tenth of him (bleed 0.1)
    assert not b.hear(0.007, 0.06, block) and not b.hear(0.008, 0.06, block)  # just his bleed, a bit louder
    assert not b.hear(0.05, 0.06, block)  # one loud block is a cough, not the artist
    assert b.hear(0.06, 0.06, block)  # two running: the artist is talking
    assert len(b.release()) == 5 and b.blocks == 0


def test_the_desk_listens_on_the_macbook_mic_and_plays_on_the_speakers(monkeypatch):
    import sys
    import types

    devices = {"MacBook Pro Microphone": {"default_samplerate": 48000, "max_input_channels": 1},
               "Universal Audio Thunderbolt": {"max_output_channels": 10}}
    fake = types.SimpleNamespace(query_devices=lambda name=None, kind=None: devices[name])
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setenv("HIREMARCO_TALKBACK_DEVICE", "Universal Audio Thunderbolt")
    desk = DuplexAudio.desk_from_config(lambda block: None)
    assert desk.device == "MacBook Pro Microphone" and desk.out_device == "Universal Audio Thunderbolt"
    assert desk.out_pair == (1, 2) and desk.in_channels == 1 and desk.mic_channel == 1


def test_mixing_mode_does_not_move_him_the_menu_does():
    from hiremarco.studio.booth import Booth, Tape
    from hiremarco.studio.commands import understand

    moved = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(),
              say=lambda text: None, feedback=lambda a, r: None, tape=Tape(1000, seconds=2), log=lambda line: None,
              on_place=moved.append)
    b.hear("Marco, let's do mixing now")
    assert moved == [] and b.session.mode == "mixing"  # mixing can happen at the mic

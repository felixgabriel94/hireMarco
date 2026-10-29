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

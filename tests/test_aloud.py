"""What Marco listens to plays on his Apollo pair beside the model call, stops when the next thing starts, and never
stops the work when the pair is out of reach."""

import time

import numpy as np

from hiremarco.studio import aloud


class FakeStream:
    def __init__(self, slow=0.0):
        self.writes, self.slow, self.closed = [], slow, False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True

    def write(self, block):
        self.writes.append(block.copy())
        time.sleep(self.slow)


def test_a_clip_lands_on_marcos_pair_and_the_next_clip_stops_it(monkeypatch):
    monkeypatch.setattr(aloud, "where", lambda: ("Universal Audio Thunderbolt", [5, 6]))
    monkeypatch.delenv("HIREMARCO_ALOUD", raising=False)
    rate, pcm = 1000, np.column_stack([np.full(500, 0.25, dtype="float32"), np.full(500, -0.25, dtype="float32")])
    stream = FakeStream()
    clip = aloud.play(pcm, rate, stream=stream)
    clip.thread.join(2.0)
    assert clip.done and clip.seconds == 0.5 and stream.closed
    out = np.concatenate(stream.writes)
    assert out.shape == (500, 6) and float(out[0, 4]) == 0.25 and float(out[0, 5]) == -0.25 and not out[:, :4].any()

    slow = FakeStream(slow=0.05)
    first = aloud.play(np.zeros((rate * 5, 2), dtype="float32"), rate, stream=slow)
    time.sleep(0.12)
    second = aloud.play(np.zeros((100, 2), dtype="float32"), rate, stream=FakeStream())
    first.thread.join(2.0)
    assert first.done and first.played < rate * 5 and second is not first
    aloud.stop()
    second.thread.join(2.0)
    assert second.done


def test_no_pair_or_switched_off_means_silence_not_a_stop(monkeypatch):
    monkeypatch.setattr(aloud, "where", lambda: (_ for _ in ()).throw(RuntimeError("no Apollo")))
    monkeypatch.delenv("HIREMARCO_ALOUD", raising=False)
    assert aloud.play(np.zeros((10, 2), dtype="float32"), 1000) is None
    monkeypatch.setattr(aloud, "where", lambda: ("Universal Audio Thunderbolt", [5, 6]))
    monkeypatch.setenv("HIREMARCO_ALOUD", "off")
    assert aloud.play(np.zeros((10, 2), dtype="float32"), 1000, stream=FakeStream()) is None


def test_a_fade_takes_the_clip_out_over_its_seconds_and_ends_it(monkeypatch):
    # Owner 2026-11-04: the arrival pad goes out over a second when the session is up
    import time

    rate = 1000
    stream = FakeStream()
    clip = aloud.Clip(np.ones((rate * 5, 2), dtype="float32"), rate, None, [1, 2], stream=stream)
    clip.fade(0.5)                       # from frame 0: half a second of ramp, then the end
    clip.thread.start()
    clip.thread.join(5)
    assert clip.done
    written = np.concatenate(stream.writes) if stream.writes else np.zeros((0, 2))
    assert 400 <= len(written) <= 700    # the ramp's length, in blocks of 100 frames
    assert written[0, 0] == 1.0 and written[-1, 0] < 0.25

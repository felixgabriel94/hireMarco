import json
from datetime import datetime, timedelta

import numpy as np
import pytest
import soundfile as sf

from hiremarco.film import FilmRecorder, Segmenter, channel_list


def ticking_clock():
    t = [datetime(2026, 10, 29, 10, 0, 0).astimezone()]

    def now():
        t[0] += timedelta(seconds=1)
        return t[0]

    return now


def ramp(frames, channels, start=0):
    # Each channel carries its own scaled ramp so order and continuity are checkable.
    base = (np.arange(start, start + frames) % 1000) / 2000.0
    return np.column_stack([base * (c + 1) / channels for c in range(channels)]).astype("float32")


def test_segments_roll_over_on_one_clock(tmp_path):
    seg = Segmenter(tmp_path, rate=100, channels=3, segment_seconds=2, clock=ticking_clock())
    for i in range(5):
        seg.write(ramp(90, 3, start=i * 90))  # 450 frames: segments of 200, 200, 50
    seg.close()
    assert [sf.info(f).frames for f in seg.files] == [200, 200, 50]
    assert seg.frames == 450
    rows = [json.loads(line) for line in (tmp_path / "film.jsonl").read_text().splitlines()]
    assert [r["first_sample"] for r in rows] == [0, 200, 400]
    joined = np.concatenate([sf.read(f, dtype="float32")[0] for f in seg.files])
    assert joined.shape == (450, 3)
    assert np.allclose(joined, ramp(450, 3), atol=1e-5)  # nothing lost or reordered at the seams


def test_segment_files_are_24_bit_multichannel(tmp_path):
    seg = Segmenter(tmp_path, rate=48000, channels=5, segment_seconds=60, clock=ticking_clock())
    seg.write(ramp(480, 5))
    seg.close()
    info = sf.info(seg.files[0])
    assert (info.subtype, info.channels, info.samplerate) == ("PCM_24", 5, 48000)


def test_block_with_wrong_channel_count_is_refused(tmp_path):
    seg = Segmenter(tmp_path, rate=100, channels=2)
    with pytest.raises(ValueError):
        seg.write(np.zeros((10, 3), dtype="float32"))


class FakeStream:
    def __init__(self, callback, blocks):
        self.callback, self.blocks = callback, blocks
        self.closed = False

    def start(self):
        for i, block in enumerate(self.blocks):
            self.callback(block, len(block), None, "input overflow" if i == 1 else None)

    def stop(self):
        pass

    def close(self):
        self.closed = True


def test_recorder_keeps_only_the_asked_channels_in_order(tmp_path):
    # The interface offers 12 inputs; the film keeps the mic (1) and virtual pairs (9-10, 11-12).
    full = [np.tile(np.arange(1, 13, dtype="float32") / 100, (64, 1)) for _ in range(3)]
    streams = []
    rec = FilmRecorder(device="Apollo", channels=[1, 9, 10, 11, 12], rate=48000, folder=tmp_path,
                       stream_factory=lambda cb: streams.append(FakeStream(cb, full)) or streams[-1])
    rec.start()
    files = rec.stop()
    data, rate = sf.read(files[0], dtype="float32")
    assert data.shape == (192, 5)
    assert np.allclose(data[0], [0.01, 0.09, 0.10, 0.11, 0.12], atol=1e-5)
    assert rec.dropped == 1  # the overflow is counted
    assert streams[0].closed
    assert rec.seconds == pytest.approx(192 / 48000)


def test_channel_list():
    assert channel_list("1, 9,10") == [1, 9, 10]
    for bad in (None, "", "0,1", "1,1"):
        with pytest.raises(ValueError):
            channel_list(bad)

import asyncio

import numpy as np
import pytest

from hiremarco.studio import webrtc
from hiremarco.studio.show import NoLogicWindow


@pytest.mark.parametrize("size, cap, expected", [
    ((3200, 1848), 1600, (1600, 924)),
    ((1201, 801), 1600, (1200, 800)),
    ((2000, 1001), 1600, (1600, 800)),
])
def test_the_capture_size_is_capped_and_even(size, cap, expected):
    assert webrtc.scaled(*size, cap) == expected


class FakeCapture:
    def __init__(self, window, max_width):
        self.window, self.max_width, self.frames, self.latest, self.stopped = window, max_width, 0, None, False

    def start(self):
        self.frames, self.latest = 45, np.zeros((924, 1600, 4), np.uint8)

    def stop(self):
        self.stopped = True


def test_no_logic_window_means_no_video():
    video = webrtc.LogicVideo(find_window=lambda: None, capture=FakeCapture)
    with pytest.raises(NoLogicWindow):
        video.start()
    assert video.probe().startswith("video off: NoLogicWindow")


def test_the_probe_reports_size_and_frames_and_stops_the_capture():
    video = webrtc.LogicVideo(find_window=lambda: 475, capture=FakeCapture)
    assert video.probe(seconds=0) == "video on: 1600x924, 45 frames in 0.0 s" and video.capture is None


def test_a_capture_that_cannot_start_leaves_no_connection_open():
    def refuse():
        raise PermissionError("screen recording not allowed")

    peers = webrtc.Peers(lambda: None, on_first=refuse)
    with pytest.raises(PermissionError):
        asyncio.run(peers.answer({"type": "offer", "sdp": "v=0"}))
    assert peers.open == set()


def test_the_bitrate_is_raised_for_a_session_window():
    from aiortc.codecs import h264

    webrtc.tune_h264()
    assert h264.DEFAULT_BITRATE == 4_000_000 and h264.MAX_BITRATE == 8_000_000

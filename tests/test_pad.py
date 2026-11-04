import numpy as np

from hiremarco.studio import aloud, pad


def test_the_pad_swells_holds_and_sits_under_the_ceiling():
    pcm = pad.aurora(seconds=8.0, rate=8000)
    assert pcm.shape == (64000, 2) and pcm.dtype == np.float32
    assert np.max(np.abs(pcm)) <= 0.86
    first, mid = np.abs(pcm[:400]).max(), np.abs(pcm[32000:40000]).max()
    assert first < 0.05 < mid                       # a swell from near silence to the hold
    assert np.abs(pcm[-200:]).max() < 0.08           # the release at the end
    assert not np.allclose(pcm[:, 0], pcm[:, 1])     # a little width


def test_the_pad_plays_on_the_pair_and_goes_out_on_a_fade(monkeypatch):
    class FakeStream:
        def __init__(self):
            self.frames = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, block):
            self.frames.append(np.array(block, copy=True))

    monkeypatch.setattr(aloud, "where", lambda: (None, [1, 2]))
    monkeypatch.setattr(pad, "aurora", lambda *a, **k: np.ones((8000, 2), dtype=np.float32) * 0.5)
    stream = FakeStream()
    monkeypatch.setattr(aloud, "play", lambda pcm, rate, stream=None: aloud.Clip(pcm, rate, None, [1, 2], stream=FakeStream()))
    clip = pad.start()
    assert clip is not None and clip.seconds == 8000 / 48000


def test_the_pad_is_rendered_once_into_the_state_folder_and_read_back(tmp_path, monkeypatch):
    from hiremarco import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(pad, "aurora", lambda *a, **k: np.ones((int(pad.RATE * pad.SECONDS), 2), dtype=np.float32) * 0.5)
    first = pad.prepare()
    assert (tmp_path / "pad-aurora.npy").exists() and first.shape == (int(pad.RATE * pad.SECONDS), 2)
    monkeypatch.setattr(pad, "aurora", lambda *a, **k: (_ for _ in ()).throw(AssertionError("rendered twice")))
    again = pad.prepare()
    assert again.shape == first.shape and float(again[0, 0]) == 0.5

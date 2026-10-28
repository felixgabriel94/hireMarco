import numpy as np

from hiremarco.routing import mic_levels, probe


def loopback(pairs):
    """A fake interface: output channel o comes back on input pairs[o]."""
    def playrec(out, rate, device, input_mapping, output_mapping, blocking):
        rec = np.zeros((out.shape[0], len(input_mapping)), dtype="float32")
        for o, i in pairs.items():
            rec[:, i - 1] += out[:, o - 1]
        return rec
    return playrec


def test_virtual_pair_found_on_its_inputs():
    heard = probe("Apollo", (7, 8), outputs=10, inputs=16,
                  playrec=loopback({7: 7, 8: 8, 5: 5, 6: 6}))
    assert set(heard) == {7, 8}
    assert all(-34 < db < -32 for db in heard.values())  # 0.03 peak sine is about -33 dBFS RMS


def test_nothing_heard_is_an_empty_answer():
    assert probe("Apollo", (5, 6), outputs=10, inputs=16, playrec=loopback({})) == {}


def test_mic_levels_name_the_live_input():
    def rec(frames, samplerate, device, mapping):
        data = np.zeros((frames, len(mapping)), dtype="float32")
        data[:, 0] = 0.1 * np.sin(np.arange(frames) / 5)
        return data
    assert list(mic_levels("Apollo", 16, rec=rec)) == [1]

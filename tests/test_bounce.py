"""The print: the Bounce dialog's settings, the file waited for and read back."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from hiremarco.studio import bounce


def test_the_two_specs_differ_only_where_they_should():
    assert bounce.MIX.bits == "32-bit float" and bounce.MASTER.bits == "24-bit"
    for spec in (bounce.MIX, bounce.MASTER):
        assert spec.file_type == "WAVE" and spec.dither == "None" and spec.mode == "Offline"
        assert spec.normalize == "Off" and spec.tail and not spec.add_to_project
    assert bounce.MIX.args() == ["WAVE", "32-bit float", "keep", "Interleaved", "None", "Offline", "Off", "1", "0", "0"]


def test_the_dialog_report_is_read_including_the_time():
    report = "requires\tRequires 198.6 MB of free disk space  (Time 8:32)\nstart\t 1 1 1 1\nend\t 257 1 1 1\n"
    opened = bounce.parse_opened(report)
    assert opened.seconds == 512
    assert opened.start.split() == ["1", "1", "1", "1"] and opened.end.split()[0] == "257"
    assert bounce.parse_opened("").seconds is None


def test_print_names_carry_song_purpose_and_date():
    assert bounce.print_name("aguacero", "master", "2026-11-02") == "aguacero - master 2026-11-02"
    assert bounce.print_name("a/b: c", "mix", "2026-11-02").startswith("a-b- c - mix")


def test_wait_for_returns_once_the_file_stops_growing(tmp_path):
    path = tmp_path / "x.wav"
    clock = {"t": 0.0}
    sizes = iter([0, 10, 20, 20, 20, 20, 20, 20, 20, 20])

    def sleep(s):
        clock["t"] += s
        try:
            path.write_bytes(b"x" * next(sizes))
        except StopIteration:
            pass

    took = bounce.wait_for(path, timeout_s=60, settle_s=1.0, sleep=sleep, clock=lambda: clock["t"])
    assert took >= 1.0 and path.stat().st_size == 20


def test_wait_for_gives_up():
    with pytest.raises(TimeoutError):
        bounce.wait_for(Path("/nonexistent/x.wav"), timeout_s=2, sleep=lambda s: None,
                        clock=iter(range(0, 100)).__next__)


def test_dry_run_plans_and_touches_nothing(tmp_path):
    b = bounce.Bouncer(dry_run=True)
    printed = b.print(bounce.MASTER, tmp_path, "song - master 2026-11-02")
    assert printed.path == tmp_path / "song - master 2026-11-02.wav"
    assert not printed.path.exists()
    assert b.planned == ["open the Bounce dialog (24-bit WAVE)"]


def test_an_existing_file_is_never_overwritten(tmp_path):
    target = tmp_path / "song - master 2026-11-02.wav"
    sf.write(target, np.zeros((100, 2), dtype="float32"), 48000)
    with pytest.raises(FileExistsError):
        bounce.Bouncer(dry_run=True).print(bounce.MASTER, tmp_path, "song - master 2026-11-02")


def test_a_print_is_read_back(tmp_path, monkeypatch):
    target = tmp_path / "song - mix 2026-11-02.wav"
    calls = []

    def run(args):
        calls.append(args[0])
        if args[0] == "save":
            sf.write(target, np.zeros((4800, 2), dtype="float32"), 48000, subtype="FLOAT")
            return "bouncing"
        return "requires\tRequires 1 MB of free disk space  (Time 0:10)\nstart\t 1 1 1 1\nend\t 9 1 1 1\n"

    monkeypatch.setattr(bounce.gate, "execute_effect", lambda conn, fn, **kw: fn())
    b = bounce.Bouncer(run=run, conn=object(), sleep=lambda s: None)
    printed = b.print(bounce.MIX, tmp_path, "song - mix 2026-11-02", timeout_s=30)
    assert calls == ["open", "save"]
    assert printed.rate == 48000 and printed.subtype == "FLOAT" and printed.channels == 2
    assert printed.seconds == 0.1

"""The booth starts as the server's own background process: no Terminal window, its lines in booth.log."""

from hiremarco import config, server


def test_the_booth_starts_in_the_background_with_its_lines_in_the_log(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    started = []
    out = server.start_booth_quietly(running=lambda: False, popen=lambda argv, **kw: started.append((argv, kw)))
    assert out == "booth started"
    argv, kw = started[0]
    assert "main(['booth'])" in argv[-1] and kw["start_new_session"] and kw["env"]["HIREMARCO_FROM_APP"] == "1"
    assert kw["stdout"].name == str(tmp_path / "booth.log")


def test_a_running_booth_is_left_alone():
    assert server.start_booth_quietly(running=lambda: True, popen=lambda *a, **k: 1 / 0) == "booth running"

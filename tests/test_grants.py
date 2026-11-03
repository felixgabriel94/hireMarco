"""Whose grants a process has: under Terminal the booth and the recorder are quiet children; under anything else they
open through hidden Terminal windows."""

import sys

from hiremarco import config, crew, grants, server


def test_off_macos_nothing_is_known_and_nothing_is_under_terminal():
    if sys.platform == "darwin":
        return
    assert grants.responsible_pid() is None and grants.responsible_name() == ""
    assert not grants.under_terminal()


def test_only_terminal_counts():
    assert grants.under_terminal("Terminal")
    assert not grants.under_terminal("itself") and not grants.under_terminal("") and not grants.under_terminal("uv")


def test_the_log_line_says_which():
    for name, word in (("Terminal", "quiet children"), ("itself", "hidden Terminal windows"), ("", "unknown process")):
        setattr(grants, "responsible_name", lambda pid=None, n=name: n)
        assert word in grants.line()


def test_under_terminal_the_booth_is_the_servers_own_child(monkeypatch):
    monkeypatch.setattr(grants, "under_terminal", lambda name=None: True)
    monkeypatch.setattr(server, "start_booth_quietly", lambda running: "booth started quietly")
    assert server.start_booth(running=lambda: False) == "booth started quietly"


def test_under_terminal_the_recorder_is_a_quiet_child_with_its_lines_in_the_log(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(grants, "under_terminal", lambda name=None: True)
    started = []
    monkeypatch.setattr(crew.subprocess, "Popen", lambda argv, **kw: started.append((argv, kw)))
    crew.open_recorder(tmp_path / "2026-11-04")
    argv, kw = started[0]
    assert argv[-3:] == ["film", "roll", str(tmp_path / "2026-11-04")] and kw["start_new_session"]
    assert kw["stdout"].name == str(tmp_path / "screenrec.log") and kw["env"]["PYTHONUNBUFFERED"] == "1"


def test_elsewhere_the_recorder_opens_through_a_hidden_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(grants, "under_terminal", lambda name=None: False)
    opened = []
    monkeypatch.setattr(crew.subprocess, "run", lambda argv, **kw: opened.append(argv))
    monkeypatch.setattr(crew.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    crew.open_recorder(tmp_path / "2026-11-04")
    assert opened[0][:5] == ["open", "-g", "-j", "-a", "Terminal"] and (tmp_path / "film.command").exists()

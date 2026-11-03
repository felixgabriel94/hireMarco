"""Whose grants a process has. macOS counts a process under its responsible process and lends it that app's microphone,
screen and Accessibility grants: anything started from a Terminal window, however deep, is Terminal's. A process a
launchd job starts answers for itself and has none (live 2026-11-03: the job com.hiremarco.serve ran Marco's server,
so the booth and the recorder it started were refused the screen, while the same children under Terminal were not).

So: a server under Terminal starts the booth and the recorder as its own quiet children, with no window anywhere; a
server under anything else opens them through a Terminal .command, hidden as fast as it can be."""

from __future__ import annotations

import os
import subprocess
import sys

TERMINAL = "Terminal"


def responsible_pid(pid: int | None = None) -> int | None:
    """The pid macOS holds responsible for ``pid`` (this process by default); None off macOS or when unknown."""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes

        ask = ctypes.CDLL("/usr/lib/system/libquarantine.dylib").responsibility_get_pid_responsible_for_pid
        ask.restype, ask.argtypes = ctypes.c_int, [ctypes.c_int]
        found = ask(pid or os.getpid())
    except (OSError, AttributeError):
        return None
    return found if found > 0 else None


def responsible_name(pid: int | None = None) -> str:
    """"Terminal", "itself" (a launchd job, or a login item), another app's name, or "" when unknown."""
    who = responsible_pid(pid)
    if not who:
        return ""
    if who == (pid or os.getpid()):
        return "itself"
    try:
        out = subprocess.run(["ps", "-o", "comm=", "-p", str(who)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return str(who)
    return os.path.basename(out.strip()) or str(who)


def under_terminal(name: str | None = None) -> bool:
    """Whether this process (or the one named) runs with Terminal's grants."""
    return (responsible_name() if name is None else name) == TERMINAL


def line() -> str:
    """One line for the server's log at start, so a day's TCC refusals are read in a second."""
    name = responsible_name()
    if name == TERMINAL:
        return "serve: under Terminal: the booth and the recorder start as quiet children, no window"
    return (f"serve: under {name or 'an unknown process'}, not Terminal: no screen or microphone grants here, "
            "so the booth and the recorder open through hidden Terminal windows")

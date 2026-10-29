"""Buses as tracks, and channel strips saved as patches: the template's building blocks.

A bus made by a send lives only in the Mixer, so it can't be selected in the Tracks area, saved as a patch, or
exported on its own channel. Marco gives it a track: in the Mixer he selects the bus strip with one click on its
name (Accessibility clicks select nothing there; a real click does, live 2026-10-29), then the Mixer's own
Options > Create Tracks for Selected Channel Strips. A track's channel strip is then saved as a patch from the
Library (``scripts/library_io.applescript``).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

SCRIPTS = Path(__file__).with_name("scripts")


def _osascript(args: list[str]) -> str:
    done = subprocess.run(["osascript", *args], capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-300:] or f"osascript exit {done.returncode}")
    return done.stdout.strip()


NAME_FIELD = '''
on findArea(el, depth)
	if depth > 7 then return missing value
	tell application "System Events"
		repeat with k in (every UI element of el)
			try
				if (role of k) is "AXLayoutArea" and (description of k) is "Mixer" then return contents of k
			end try
			set f to my findArea(contents of k, depth + 1)
			if f is not missing value then return f
		end repeat
	end tell
	return missing value
end findArea
on run argv
	tell application "Logic Pro" to activate
	delay 0.3
	tell application "System Events" to tell process "Logic Pro"
		if not (exists (first window whose name contains "Mixer")) then
			click menu item "Open Mixer" of menu 1 of menu bar item "Window" of menu bar 1
			delay 1.2
		end if
		set w to first window whose name contains "Mixer"
	end tell
	set area to findArea(w, 0)
	tell application "System Events" to tell process "Logic Pro"
		set f to first UI element of (first UI element of area whose description is (item 1 of argv)) whose description is "name"
		set p to position of f
		set z to size of f
		return ((item 1 of p) + (item 1 of z) / 2) & " " & ((item 2 of p) + (item 2 of z) / 2)
	end tell
end run
'''

FOCUSED = ('tell application "System Events" to tell process "Logic Pro" to return description of '
           '(value of attribute "AXFocusedUIElement")')


def bus_track(strip: str, run: Callable[[list[str]], str] = _osascript, press=None) -> str:
    """Give a Mixer-only channel strip ("Aux 1") its own track, proved by the strip having focus before the menu."""
    if press is None:
        from hiremarco.studio.recall import click as press
    where = run(["-e", NAME_FIELD, strip]).replace(",", " ").split()
    x, y = float(where[0]), float(where[-1])
    press(x, y)
    time.sleep(0.5)
    focused = run(["-e", FOCUSED])
    if focused != strip:
        raise RuntimeError(f"the Mixer selected {focused!r}, not {strip!r}; no track made")
    return run([str(SCRIPTS / "mixer_io.applescript"), "Options", "Create Tracks for Selected Channel Strips"])


def save_patch(track: str, name: str, run: Callable[[list[str]], str] = _osascript) -> str:
    """The selected track's channel strip saved as a patch called ``name``; refused when the dialog offers another."""
    return run([str(SCRIPTS / "library_io.applescript"), track, name])

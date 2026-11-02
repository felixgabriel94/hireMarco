"""The Stereo Out: Marco's hands on the master channel strip.

The mastering chain lives in the Stereo Out's inserts. That strip has no
track, so the surface cannot reach it; Marco works it in Logic's Mixer
window instead (mapped live 2026-11-02). Reading is accessibility, free of
side effects: each insert is a group named after its plugin with a bypass
checkbox, and the thin button under the last one is the empty slot. A plugin
goes in through Logic's own plug-in menu: a real click on the empty slot
opens it (the menu is a window outside the accessibility tree, found by its
bounds), a click in its search field, the plugin's name typed, the first
result clicked and its first variant (stereo) picked; the plugin's window
then opens and is closed. Every change goes through the gate on the
``logic`` channel. Logic's own Console Recall plugin, when the artist keeps it
on the strip, is never touched: it is the console's memory, not processing.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hiremarco import gate

SCRIPTS = Path(__file__).parent / "scripts"
TENANT = "owner"
UNTOUCHED = ("Console Re",)        # Logic's short name for UAD Console Recall: left alone on every job
SEARCH_Y, FIRST_ROW_Y, ITEM_Y = 18.0, 49.0, 12.0   # offsets inside the plug-in menu window and its submenu


@dataclass
class Insert:
    name: str
    bypassed: bool
    x: float
    y: float

    @property
    def marcos(self) -> bool:
        return not any(self.name.startswith(u) for u in UNTOUCHED)


@dataclass
class Strip:
    slot: tuple[float, float, float, float] | None
    inserts: list[Insert]
    assistant: tuple[float, float, float, float] | None


def _jxa(script: str, *args: str) -> str:
    done = subprocess.run(["osascript", "-l", "JavaScript", str(SCRIPTS / script), *args], capture_output=True,
                          text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:] or f"osascript exit {done.returncode}")
    return done.stdout.strip()


def _osa(script: str) -> str:
    done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:] or f"osascript exit {done.returncode}")
    return done.stdout.strip()


def _hover(x: float, y: float) -> None:
    """The pointer moved to a screen point, nothing pressed: a menu row with a submenu opens it on hover."""
    import Quartz

    Quartz.CGEventPost(Quartz.kCGHIDEventTap,
                       Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), 0))


def parse_strip(report: str) -> Strip:
    data = json.loads(report)
    return Strip(tuple(data["slot"]) if data.get("slot") else None,
                 [Insert(str(n), bool(b), float(x), float(y)) for n, b, x, y in data.get("inserts", [])],
                 tuple(data["assistant"]) if data.get("assistant") else None)


def front_is_logic() -> None:
    name = _osa('tell application "System Events" to get name of first process whose frontmost is true')
    if name != "Logic Pro":
        raise RuntimeError(f"Logic is not in front ({name or 'nothing'}); nothing was clicked")


class StereoOut:
    def __init__(self, *, jxa: Callable[[str], str] = _jxa, osa: Callable[[str], str] = _osa, click=None,
                 hover=None, conn=None, rules_path: Path | None = None, dry_run: bool = False, sleep=time.sleep):
        if click is None:
            from hiremarco.studio.recall import click
        self.jxa, self.osa, self.click, self.sleep = jxa, osa, click, sleep
        self.hover = hover or _hover
        self.conn, self.rules_path, self.dry_run = conn, rules_path, dry_run
        self.planned: list[str] = []

    def _gated(self, run, capability: str, message: str):
        if self.dry_run:
            self.planned.append(message)
            return f"dry run: {message}"
        return gate.execute_effect(self.conn or gate.connect(), run, tenant_id=TENANT,
                                   idempotency_key=f"stereo_out:{time.time_ns()}", capability=capability,
                                   channel="logic", target="*", message=message, department="studio",
                                   rules_path=self.rules_path)

    def open_mixer(self) -> None:
        """The Mixer window, opened from the Window menu when it is not already there, then made tall at the top
        left so every insert on a strip is on screen (seven inserts scrolled the slots out of reach, live 2026-11-02)."""
        names = self.osa('tell application "System Events" to tell process "Logic Pro" to get name of windows')

        def run() -> str:
            if "Mixer" not in names:
                self.osa('tell application "Logic Pro" to activate')
                self.sleep(0.3)
                front_is_logic()
                self.osa('tell application "System Events" to tell process "Logic Pro" to click menu item "Open Mixer" '
                         'of menu 1 of menu bar item "Window" of menu bar 1')
                self.sleep(1.0)
            placed = self.jxa("mixer_window.js")
            self.sleep(0.4)
            return f"mixer window {placed}"
        self._gated(run, "mixer_window", "open the Mixer window, tall")

    def read(self) -> Strip:
        return parse_strip(self.jxa("stereo_out.js"))

    def menus(self) -> list[list[float]]:
        return json.loads(self.jxa("menu_bounds.js") or "[]")

    def insert(self, name: str) -> Strip:
        """``name`` as Logic's plug-in menu finds it; the first search result's first variant goes in."""
        if self.dry_run:
            self._gated(None, "insert", f"insert {name} on the Stereo Out")
            return Strip(None, [], None)
        before = self.read()
        if before.slot is None:
            raise RuntimeError("the Stereo Out shows no empty insert slot")

        def run() -> str:
            if self.menus():
                # a menu left open holds Logic: an activate would hang (live 2026-11-02); Escape goes through
                # System Events alone and frees it
                self.osa('tell application "System Events" to key code 53')
                self.sleep(0.5)
            self.osa('tell application "Logic Pro" to activate')
            self.sleep(0.3)
            front_is_logic()
            x, y, w, h = before.slot
            self.click(x + w / 2, y + h / 2)
            self.sleep(0.9)
            menus = self.menus()
            if not menus:
                raise RuntimeError("the plug-in menu did not open")
            mx, my, mw, _ = menus[0]
            self.click(mx + mw / 2, my + SEARCH_Y)     # the search field, across the top of the menu
            self.sleep(0.3)
            if not self.menus():
                raise RuntimeError("the plug-in menu closed before the search")
            # typed in short pieces: a long name sent at once lost all but its first letter (live 2026-11-02), and a
            # paste never reached the field. Then the keyboard, not the mouse (live 2026-11-02): Tab leaves the
            # field for the list, Down takes the first result, Right opens its variants (the first is stereo),
            # Return takes it; a Recent entry has no variants and Return takes the row itself.
            for start in range(0, len(name), 6):
                piece = name[start:start + 6].replace("\\", "\\\\").replace('"', '\\"')
                self.osa(f'tell application "System Events" to keystroke "{piece}"')
                self.sleep(0.25)
            self.sleep(0.8)
            if not self.menus():
                raise RuntimeError(f"the plug-in menu closed while {name!r} was typed")
            for code in (48, 125, 124):               # Tab, Down, Right
                self.osa(f'tell application "System Events" to key code {code}')
                self.sleep(0.4)
            self.osa('tell application "System Events" to key code 36')   # Return
            self.sleep(1.8)
            if self.menus():                          # what counts is the strip, read below, not the menu
                self._snapshot(f"menu open after {name}")
                self.osa('tell application "System Events" to key code 53')
                self.sleep(0.4)
                if self.menus():
                    self.osa('tell application "System Events" to key code 53')
                    self.sleep(0.4)
            return f"{name} picked"
        self._gated(run, "insert", f"insert {name} on the Stereo Out")
        after = self.read()
        if len(after.inserts) != len(before.inserts) + 1:
            self._snapshot(f"{name} did not land")
            raise RuntimeError(f"{name} did not land on the Stereo Out (reads {[i.name for i in after.inserts]})")
        self.close_windows()
        return after

    def _snapshot(self, why: str) -> None:
        """The screen as it was when a step failed, kept in the state folder so the failure can be read later."""
        try:
            from hiremarco import config

            folder = Path(config.STATE_DIR) / "capture"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%dT%H-%M-%S")
            safe = "".join(c if c.isalnum() else "-" for c in why)[:40]
            subprocess.run(["screencapture", "-x", "-m", "-t", "jpg", str(folder / f"{stamp}_stereo-out_{safe}.jpg")],
                           check=False, timeout=15)
        except Exception:
            pass

    def close_windows(self) -> int:
        """Plug-in windows Logic opened on an insert: every window that is not the Tracks or the Mixer window."""
        out = self.jxa("close_plugin_windows.js")
        self.sleep(0.3)
        return int(out or 0)

    def bypass(self, on: bool, *, names: list[str] | None = None, rows: list[float] | None = None) -> Strip:
        """Marco's inserts bypassed (``on``) or back in, by their bypass checkboxes; the untouched ones stay.
        ``names`` or ``rows`` (vertical positions, for a name that repeats) narrow it to some of them."""
        strip = self.read()
        wanted = [i for i in strip.inserts if i.marcos and (names is None or i.name in names)
                  and (rows is None or any(abs(i.y - r) < 4 for r in rows)) and i.bypassed != on]
        if not wanted:
            return strip

        def run() -> str:
            front_is_logic()
            for ins in wanted:
                self.jxa("stereo_out_bypass.js", ins.name, f"{ins.y:g}")   # by name and row: a name can repeat
                self.sleep(0.2)
            return f"{'bypassed' if on else 'back in'}: " + ", ".join(i.name for i in wanted)
        self._gated(run, "bypass", f"{'bypass' if on else 'un-bypass'} {', '.join(i.name for i in wanted)} on the Stereo Out")
        after = self.read()
        rows = {(w.name, round(w.y)) for w in wanted}
        off = [i.name for i in after.inserts if (i.name, round(i.y)) in rows and i.bypassed != on]
        if off:
            raise RuntimeError(f"bypass did not take on {', '.join(off)}")
        return after

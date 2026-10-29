"""Console Recall's SYNC switch, pressed by Marco and proved lit.

UA's Console Recall plug-in stores UAD Console's whole state in the Logic song when SYNC is on (UA, "Console
Recall Plug-In"). SYNC is drawn inside UA's own editor, so neither Logic's Controls view (it shows only "Session
State", which UA says never to automate) nor Accessibility can reach it. Marco does what a person does: he finds
the plug-in's window, clicks the switch at its place in that window, and reads the switch back from a capture of
the window: lit is bright, off is the grey of the panel (0.66 against 0.35, live 2026-10-29). The click lands only
inside the window it measured, and only when the switch reads off.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

# where SYNC sits in the Console Recall editor, as a fraction of its window (Logic 11, Editor view, 465 x 237 pt)
SYNC_AT = (0.0731, 0.7025)
LIT = 0.5  # mean brightness of the switch face: 0.35 off, 0.66 on


def _osascript(script: str) -> str:
    done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-200:])
    return done.stdout.strip()


def window_frame(name: str, run: Callable[[str], str] = _osascript) -> tuple[float, float, float, float]:
    """The plug-in window's position and size in screen points, as Logic reports it."""
    out = run('tell application "System Events" to tell process "Logic Pro" to get {position, size} of '
              f'(first window whose name is "{name}")')
    x, y, w, h = (float(v) for v in out.split(", "))
    return x, y, w, h


def window_id(frame: tuple[float, float, float, float]) -> int:
    import Quartz

    x, y, w, h = frame
    for info in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID):
        b = info["kCGWindowBounds"]
        if info.get("kCGWindowOwnerName") == "Logic Pro" and (b["X"], b["Y"], b["Width"], b["Height"]) == (x, y, w, h):
            return int(info["kCGWindowNumber"])
    raise LookupError("the plug-in window is not on screen")


def brightness(png: Path, at: tuple[float, float] = SYNC_AT, radius: int = 12) -> float:
    """Mean brightness, 0 to 1, of a small square around a point given as a fraction of the image."""
    from AppKit import NSBitmapImageRep

    rep = NSBitmapImageRep.imageRepWithContentsOfFile_(str(png))
    if rep is None:
        raise RuntimeError(f"could not read {png}")
    cx, cy = int(at[0] * rep.pixelsWide()), int(at[1] * rep.pixelsHigh())
    values = []
    for x in range(cx - radius, cx + radius, 2):
        for y in range(cy - radius, cy + radius, 2):
            c = rep.colorAtX_y_(x, y)
            values.append((c.redComponent() + c.greenComponent() + c.blueComponent()) / 3)
    return sum(values) / len(values)


def capture(wid: int, path: Path) -> Path:
    subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), str(path)], check=True, timeout=10)
    return path


def click(x: float, y: float) -> None:
    """One left click at a screen point; the pointer goes back where it was."""
    import Quartz

    before = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    for kind in (Quartz.kCGEventMouseMoved, Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, kind, (x, y), 0))
        time.sleep(0.08)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, before, 0))


def ensure_sync(window: str = "Stereo Out", *, frame=window_frame, find=window_id, shoot=capture,
                light=brightness, press=click, run: Callable[[str], str] = _osascript) -> str:
    """SYNC on in the open Console Recall window named ``window`` (Logic names it after its channel), proved lit."""
    run('tell application "Logic Pro" to activate')
    time.sleep(0.4)
    box = frame(window, run)
    with tempfile.TemporaryDirectory() as tmp:
        before = light(shoot(find(box), Path(tmp) / "before.png"))
        if before >= LIT:
            return f"SYNC already on (reads {before:.2f})"
        x, y, w, h = box
        press(x + SYNC_AT[0] * w, y + SYNC_AT[1] * h)
        time.sleep(0.6)
        after = light(shoot(find(frame(window, run)), Path(tmp) / "after.png"))
    if after < LIT:
        raise RuntimeError(f"clicked SYNC but it still reads off ({after:.2f})")
    return f"SYNC on (read {before:.2f} -> {after:.2f})"

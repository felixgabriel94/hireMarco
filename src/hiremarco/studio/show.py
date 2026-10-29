"""\"Marco, show me\": what is on the Mac, sent to the artist's phone, so the ISO box has a window.

Logic's main window is captured with ``screencapture`` (the window only, not the
whole screen) and sent to the Owner's WhatsApp as a picture with a one-line
caption. Through the gate like every send: Owner only, inside the 24-hour
window, counted against the daily limit.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from hiremarco import config


def logic_window_id() -> int | None:
    """The window number of Logic's main window, for screencapture -l: its largest normal window on screen."""
    script = Path(__file__).parent / "scripts" / "logic_window.js"
    done = subprocess.run(["osascript", "-l", "JavaScript", str(script)], capture_output=True, text=True, timeout=10)
    try:
        return int(done.stdout.strip())
    except ValueError:
        return None


class NoLogicWindow(RuntimeError):
    """Logic has no window on screen; nothing else on the screen is captured in its place."""


def capture(window_id: int | None) -> bytes:
    if not window_id:
        raise NoLogicWindow("Logic Pro has no window on screen")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "show.png"
        subprocess.run(["screencapture", "-x", "-t", "png", "-l", str(window_id), str(path)], check=True, timeout=15)
        return path.read_bytes()


def show(caption: str = "Here's the session.", *, send: Callable[[bytes, str], str] | None = None,
         grab: Callable[[], bytes] | None = None) -> str:
    png = (grab or (lambda: capture(logic_window_id())))()
    if send is None:
        from hiremarco.whatsapp import WhatsApp

        owner = config.require("OWNER_WHATSAPP")
        client = WhatsApp()

        def send(data: bytes, text: str) -> str:
            return client.send_image(owner, data, text, idempotency_key=f"show:{time.time_ns()}")

    return send(png, caption)

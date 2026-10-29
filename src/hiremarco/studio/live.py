"""The live view: Logic's window on the artist's phone, while Marco works.

Logic Remote shows a mixer, not what Marco is doing. This shows the window
itself: Logic's main window is captured a few times a second (that window
only, not the rest of the screen) and served as a stream a phone browser
plays in a plain page. The link carries a token kept in the settings file,
so it stays the same between runs and the phone can keep it as a bookmark;
``--new-link`` makes a new one and the old link stops working. Capture runs
only while someone is watching.

Pictures, not video: a few frames a second, enough to watch knobs move and
presets load from the ISO box.
"""

from __future__ import annotations

import asyncio
import secrets
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from hiremarco import config

BOUNDARY = "marcoframe"

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>Marco live</title>
<style>
html, body { margin: 0; height: 100%; background: #111; color: #aaa; font: 13px -apple-system, sans-serif; }
body { display: flex; flex-direction: column; }
#view { flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; }
img { max-width: 100%; max-height: 100%; object-fit: contain; }
#bar { padding: 6px 12px; display: flex; justify-content: space-between; }
</style></head>
<body><div id="view"><img src="stream?t={token}" alt="Logic, live"></div>
<div id="bar"><span>Marco live</span><span>view only</span></div></body></html>
"""


def grab_logic(width: int | None = None) -> bytes:
    """One JPEG of Logic's main window, scaled to ``width`` pixels wide when given."""
    from hiremarco.studio.show import NoLogicWindow, logic_window_id

    window = logic_window_id()
    if not window:
        raise NoLogicWindow("Logic Pro has no window on screen")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "live.jpg"
        subprocess.run(["screencapture", "-x", "-o", "-t", "jpg", "-l", str(window), str(path)], check=True, timeout=10, capture_output=True)
        if width:
            subprocess.run(["sips", "--resampleWidth", str(width), str(path)], check=True, timeout=10,
                           capture_output=True)
        return path.read_bytes()


class Frames:
    """The latest frame, captured in the background while at least one viewer is watching."""

    def __init__(self, grab: Callable[[], bytes], fps: float = 4.0):
        self.grab = grab
        self.interval = 1.0 / max(fps, 0.5)
        self.latest = b""
        self.seq = 0
        self.error = ""
        self.viewers = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def capture_once(self) -> None:
        try:
            frame = self.grab()
        except Exception as exc:  # a missing window or a refused permission: keep the last frame, say why
            self.error = f"{type(exc).__name__}: {exc}"[:200]
            return
        with self._lock:
            self.latest, self.seq, self.error = frame, self.seq + 1, ""

    def _run(self) -> None:
        while self.viewers > 0:
            started = time.monotonic()
            self.capture_once()
            time.sleep(max(0.0, self.interval - (time.monotonic() - started)))
        self._thread = None

    def join(self) -> None:
        with self._lock:
            self.viewers += 1
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

    def leave(self) -> None:
        with self._lock:
            self.viewers = max(0, self.viewers - 1)


def link_token(*, new: bool = False) -> str:
    token = None if new else config.get("HIREMARCO_LIVE_TOKEN")
    if not token:
        token = secrets.token_urlsafe(18)
        config.set_value("HIREMARCO_LIVE_TOKEN", token)
    return token


def lan_address() -> str | None:
    for interface in ("en0", "en1"):
        done = subprocess.run(["ipconfig", "getifaddr", interface], capture_output=True, text=True)
        if done.stdout.strip():
            return done.stdout.strip()
    return None


def make_app(frames: Frames, token: str, *, max_frames: int | None = None):
    """The page and its stream. A request without the token gets a plain 404, as if nothing were here."""
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, Response, StreamingResponse
    from starlette.routing import Route

    def allowed(request) -> bool:
        return secrets.compare_digest(request.query_params.get("t", ""), token)

    async def page(request):
        if not allowed(request):
            return Response(status_code=404)
        return HTMLResponse(PAGE.replace("{token}", token), headers={"Cache-Control": "no-store"})

    async def frame(request):
        if not allowed(request):
            return Response(status_code=404)
        if not frames.latest:
            frames.capture_once()
        if not frames.latest:
            return Response(frames.error or "no frame yet", status_code=503)
        return Response(frames.latest, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    async def stream(request):
        if not allowed(request):
            return Response(status_code=404)

        async def parts():
            frames.join()
            sent, seen = 0, -1
            try:
                while max_frames is None or sent < max_frames:
                    if frames.seq != seen and frames.latest:
                        seen, data = frames.seq, frames.latest
                        yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(data)}\r\n\r\n"
                               .encode() + data + b"\r\n")
                        sent += 1
                    await asyncio.sleep(frames.interval / 2)
            finally:
                frames.leave()

        return StreamingResponse(parts(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
                                 headers={"Cache-Control": "no-store"})

    return Starlette(routes=[Route("/", page), Route("/frame.jpg", frame), Route("/stream", stream)])

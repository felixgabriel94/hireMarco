"""Marco Live on screen: the event stream rendered by the Owner's design, in a panel that never takes the front.

The page is ``trace/index.html`` (built by ``scripts/build_live_page.py`` from the Owner's design: fonts and icon
beside it in ``trace/assets``, no network, no sample). It lives in a WKWebView inside a non-activating panel, so it can sit on the TV while
a run goes on in Logic. Python tails ``events.jsonl`` four times a second, turns each row into the page's words
(``events.for_page``) and hands them over one at a time, spaced as the design asks; a replay feeds a recorded file at
its true timing and the page says REPLAY for its whole length. While a job's process is alive the page hears a beat, so
a four-minute print reads as Marco at work; when that process is gone the beat stops and the page falls to IDLE.
The detail drawer is toggled by a flag file, since a non-activating panel takes no keyboard.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path

from hiremarco import config, events

PAGE = Path(__file__).with_name("trace") / "index.html"
DETAIL_FLAG = "trace.detail"
TICK_S = 0.25
PACE_S = 1.6        # the design's spacing between events
PACE_AFTER_STAGE_S = 0.5   # a stage and the call it announces land nearly together
PACE_BEHIND_S = 0.4        # the fastest it goes when many rows wait, so the screen never falls far behind the run
BEHIND = 12
BEAT_S = 8.0
LAYOUTS = {"banner": (1920, 312), "full": (1920, 1080)}


def detail_flag() -> Path:
    return Path(config.STATE_DIR) / DETAIL_FLAG


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


class Pacer:
    """Rows in, page events out, spaced; the running job's process is what keeps the beat."""

    def __init__(self) -> None:
        self.waiting: deque[dict] = deque()
        self.next_at = 0.0
        self.beat_at = 0.0
        self.pid: int | None = None

    def add(self, rows: list[dict]) -> None:
        for row in rows:
            if row.get("kind") == "job_started":
                self.pid = row.get("pid")
            elif row.get("kind") == "job_ended":
                self.pid = None
            event = events.for_page(row)
            if event is not None:
                self.waiting.append(event)

    def due(self, now: float) -> list[dict]:
        """The one event whose turn it is, an empty beat while a job is alive, or None's stand-in: nothing."""
        if self.waiting and now >= self.next_at:
            event = self.waiting.popleft()
            gap = PACE_AFTER_STAGE_S if event.get("type") == "stage" else PACE_S
            self.next_at = now + (PACE_BEHIND_S if len(self.waiting) > BEHIND else gap)
            self.beat_at = now + BEAT_S
            return [event]
        return []

    def beat(self, now: float) -> bool:
        if now >= self.beat_at and alive(self.pid):
            self.beat_at = now + BEAT_S
            return True
        return False


def resume_point(rows: list[dict]) -> list[dict]:
    """A window opened mid-run picks up from that job's start; one opened between runs starts empty."""
    for k in range(len(rows) - 1, -1, -1):
        if rows[k].get("kind") == "job_ended":
            return []
        if rows[k].get("kind") == "job_started":
            return rows[k:] if alive(rows[k].get("pid")) else []
    return []


def show(*, screen: int = 2, fill: float = 0.96, unit: float | None = None, layout: str = "banner", replay: Path | None = None,
         speed: float = 1.0, at: Path | None = None) -> None:
    import AppKit
    import WebKit
    from Foundation import NSMakeRect, NSObject, NSTimer, NSURL
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    screens = list(AppKit.NSScreen.screens())
    chosen = screens[min(max(screen, 1), len(screens)) - 1]
    frame = chosen.visibleFrame()
    page_w, page_h = LAYOUTS[layout]
    width = frame.size.width * fill
    height = width * page_h / page_w
    if height > frame.size.height * fill:
        height = frame.size.height * fill
        width = height * page_w / page_h
    left = frame.origin.x + (frame.size.width - width) / 2
    # a banner sits along the bottom, over Logic's lower edge; the full page is centered. Either can be dragged and resized
    bottom = frame.origin.y + (frame.size.height - height) * (0.02 if layout == "banner" else 0.5)
    # a titled, resizable panel the Owner can drag by its title bar or its body and resize at its edges
    # (2026-11-02: a borderless full-screen panel could not be moved or shrunk and sat partly off the TV);
    # still non-activating, so Logic keeps the front
    style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable | AppKit.NSWindowStyleMaskResizable
             | AppKit.NSWindowStyleMaskNonactivatingPanel | AppKit.NSWindowStyleMaskUtilityWindow)
    screen_frame = chosen.frame()
    # the screen initializer takes a rect in that screen's own coordinates (origin at its bottom left)
    rel = NSMakeRect(left - screen_frame.origin.x, bottom - screen_frame.origin.y, width, height)
    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_screen_(
        rel, style, AppKit.NSBackingStoreBuffered, False, chosen)
    panel.setTitle_("Marco Live")
    panel.setLevel_(AppKit.NSFloatingWindowLevel)
    panel.setBecomesKeyOnlyIfNeeded_(True)
    panel.setHidesOnDeactivate_(False)
    panel.setMovableByWindowBackground_(True)
    panel.setMinSize_((640, 104))
    panel.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(0.043, 0.043, 0.051, 1.0))
    conf = WebKit.WKWebViewConfiguration.alloc().init()
    view = WebKit.WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, width, height), conf)
    view.setValue_forKey_(False, "drawsBackground")
    view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
    panel.setContentView_(view)
    # the page fills the content area, so the title bar goes on top of the height, not out of it
    outer = panel.frameRectForContentRect_(NSMakeRect(left, bottom, width, height))
    panel.setFrame_display_(NSMakeRect(left, bottom, outer.size.width, outer.size.height), True)   # absolute, checked after the order front
    view.loadFileURL_allowingReadAccessToURL_(NSURL.fileURLWithPath_(str(PAGE)), NSURL.fileURLWithPath_(str(PAGE.parent)))

    source = events.path() if at is None else at
    pacer = Pacer()
    feed = {"offset": 0, "started": time.monotonic(), "rows": [], "t0": None, "detail": None, "ready": False}
    if replay is not None:
        feed["rows"] = list(events.read_all(replay))
        if feed["rows"]:
            feed["t0"] = _ts(feed["rows"][0]["ts"])

    def run_js(code: str) -> None:
        view.evaluateJavaScript_completionHandler_(code, None)

    def push(page_events: list[dict]) -> None:
        run_js(f"window.marco && window.marco.push({json.dumps(page_events, ensure_ascii=False)})")

    class Ticker(NSObject):
        def ready_(self, timer):
            scale = f"window.marco.scale({unit})," if unit else ""
            run_js(f"window.marco && (window.marco.layout({json.dumps(layout)}), {scale} window.marco.replay({'true' if replay else 'false'}))")
            if replay is None:
                rows, feed["offset"] = events.tail(source, 0)
                pacer.add(resume_point(rows))
            feed["ready"] = True

        def tick_(self, timer):
            if not feed["ready"]:
                return
            now = time.monotonic()
            if replay is not None:
                elapsed = (now - feed["started"]) * speed
                due = []
                while feed["rows"] and _ts(feed["rows"][0]["ts"]) - feed["t0"] <= elapsed:
                    due.append(feed["rows"].pop(0))
                pacer.add(due)
            else:
                rows, feed["offset"] = events.tail(source, feed["offset"])
                pacer.add(rows)
            page_events = pacer.due(now)
            if page_events:
                push(page_events)
            elif pacer.beat(now):
                push([])
            want = detail_flag().exists()
            if want != feed["detail"]:
                feed["detail"] = want
                run_js(f"window.marco && window.marco.detail({'true' if want else 'false'})")

    ticker = Ticker.alloc().init()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.8, ticker, "ready:", None, False)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(TICK_S, ticker, "tick:", None, True)
    panel.orderFrontRegardless()
    f = panel.frame()
    print(f"Marco Live ({layout}) at x {f.origin.x:.0f} y {f.origin.y:.0f} {f.size.width:.0f} x {f.size.height:.0f} on screen {screen}; "
          f"drag it by its title bar, resize at its edges; it never takes the front", flush=True)
    AppHelper.runEventLoop()


def _ts(text: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(text).timestamp()

"""The live trace on screen: Marco's event stream rendered as cards, in a panel that never takes the front.

The page is ``trace/index.html`` (HTML, CSS and a small script; system
fonts; no network). It lives in a WKWebView inside the same non-activating
panel as the plain log window, so it can sit on the TV while a run goes on
in Logic. Python tails ``events.jsonl`` four times a second and hands new
rows to the page; a replay feeds a recorded file at its true timing and
the header says REPLAY for its whole length. The detail drawer is toggled
by a flag file, since a non-activating panel takes no keyboard.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from hiremarco import config, events

PAGE = Path(__file__).with_name("trace") / "index.html"
DETAIL_FLAG = "trace.detail"
TICK_S = 0.25


def detail_flag() -> Path:
    return Path(config.STATE_DIR) / DETAIL_FLAG


def show(*, screen: int = 2, fill: float = 0.92, unit: float | None = None, replay: Path | None = None,
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
    width, height = frame.size.width * fill, frame.size.height * fill
    left, bottom = frame.origin.x + (frame.size.width - width) / 2, frame.origin.y + (frame.size.height - height) / 2
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
    panel.setTitle_("Marco Live Trace")
    panel.setLevel_(AppKit.NSFloatingWindowLevel)
    panel.setBecomesKeyOnlyIfNeeded_(True)
    panel.setHidesOnDeactivate_(False)
    panel.setMovableByWindowBackground_(True)
    panel.setMinSize_((640, 360))
    panel.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(0.043, 0.043, 0.051, 1.0))
    conf = WebKit.WKWebViewConfiguration.alloc().init()
    view = WebKit.WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, width, height), conf)
    view.setValue_forKey_(False, "drawsBackground")
    view.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
    panel.setContentView_(view)
    panel.setFrame_display_(NSMakeRect(left, bottom, width, height), True)   # absolute, checked after the order front
    view.loadHTMLString_baseURL_(PAGE.read_text(), NSURL.fileURLWithPath_(str(PAGE.parent)))

    # the unit scales the page: 1 px per unit on a 1920-point TV; smaller screens scale down
    scale = unit if unit is not None else max(0.5, min(1.0, width / 1920.0))
    source = events.path() if at is None else at
    feed = {"offset": 0, "started": time.monotonic(), "rows": [], "t0": None, "detail": None}
    if replay is not None:
        feed["rows"] = list(events.read_all(replay))
        if feed["rows"]:
            feed["t0"] = _ts(feed["rows"][0]["ts"])

    def push(rows: list[dict]) -> None:
        if rows:
            view.evaluateJavaScript_completionHandler_(f"window.marco && window.marco.push({json.dumps(rows, ensure_ascii=False)})", None)

    class Ticker(NSObject):
        def ready_(self, timer):
            view.evaluateJavaScript_completionHandler_(f"window.marco && (window.marco.scale({scale}), window.marco.replay({'true' if replay else 'false'}))", None)
            if replay is None:
                rows, feed["offset"] = events.tail(source, 0)
                push(rows[-12:])

        def tick_(self, timer):
            if replay is not None:
                elapsed = (time.monotonic() - feed["started"]) * speed
                due = []
                while feed["rows"] and _ts(feed["rows"][0]["ts"]) - feed["t0"] <= elapsed:
                    due.append(feed["rows"].pop(0))
                push(due)
            else:
                rows, feed["offset"] = events.tail(source, feed["offset"])
                push(rows)
            want = detail_flag().exists()
            if want != feed["detail"]:
                feed["detail"] = want
                view.evaluateJavaScript_completionHandler_(f"window.marco && window.marco.detail({'true' if want else 'false'})", None)

    ticker = Ticker.alloc().init()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.8, ticker, "ready:", None, False)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(TICK_S, ticker, "tick:", None, True)
    panel.orderFrontRegardless()
    f = panel.frame()
    print(f"trace panel at x {f.origin.x:.0f} y {f.origin.y:.0f} {f.size.width:.0f} x {f.size.height:.0f} on screen {screen}; "
          f"drag it by its title bar, resize at its edges; it never takes the front", flush=True)
    AppHelper.runEventLoop()


def _ts(text: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(text).timestamp()

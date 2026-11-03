"""The terminal panel: what Marco's booth prints, on the TV, where the camera wants it (Owner 2026-11-03).

The booth runs in Terminal for its permissions, but a Terminal window never shows on the MacBook: the app opens it
hidden, and this panel shows the same lines on the TV instead, so the recorder can film it as its own file. Light on
dark, monospaced, the newest line at the bottom, read from ``booth.log`` twice a second. Like Marco Live it is a
non-activating panel with no Dock tile: it never takes the front from Logic.
"""

from __future__ import annotations

import re
from pathlib import Path

from hiremarco import config

TITLE = "Marco Terminal"
LINES = 22
POINT = 20.0
INK = (0.86, 0.90, 0.86)
PAPER = (0.03, 0.03, 0.04)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r")


def log_path() -> Path:
    return Path(config.STATE_DIR) / "booth.log"


def tail(path: Path, lines: int = LINES, *, limit: int = 64_000) -> list[str]:
    """The last lines of the log, escape codes taken out; an empty list when there is no log yet."""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - limit))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows = [_ANSI.sub("", row) for row in text.splitlines()]
    return [row for row in rows if row.strip()][-lines:]


def show(*, screen: int = 2, at: Path | None = None, lines: int = LINES, point: float = POINT,
         share: tuple[float, float, float, float] = (0.02, 0.02, 0.96, 0.62)) -> None:
    """The panel on display ``screen`` (2 is the TV), covering ``share`` = (left, bottom, width, height) of it: by
    default the lower part, under the Marco Live banner."""
    import AppKit
    from Foundation import NSMakeRect, NSObject, NSTimer
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)   # no Dock tile, never the active app
    screens = list(AppKit.NSScreen.screens())
    chosen = screens[min(max(screen, 1), len(screens)) - 1]
    frame = chosen.visibleFrame()
    left = frame.origin.x + frame.size.width * share[0]
    bottom = frame.origin.y + frame.size.height * share[1]
    width, height = frame.size.width * share[2], frame.size.height * share[3]
    style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskNonactivatingPanel
             | AppKit.NSWindowStyleMaskUtilityWindow)
    screen_frame = chosen.frame()
    window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_screen_(
        NSMakeRect(left - screen_frame.origin.x, bottom - screen_frame.origin.y, width, height), style,
        AppKit.NSBackingStoreBuffered, False, chosen)
    window.setFrameOrigin_((left, bottom))
    window.setBecomesKeyOnlyIfNeeded_(True)
    window.setHidesOnDeactivate_(False)
    window.setTitle_(TITLE)
    window.setLevel_(AppKit.NSFloatingWindowLevel)
    paper = AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*PAPER, 1.0)
    window.setBackgroundColor_(paper)
    view = AppKit.NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    view.setEditable_(False)
    view.setSelectable_(False)
    view.setBackgroundColor_(paper)
    view.setTextContainerInset_((18, 14))
    window.setContentView_(view)
    font = AppKit.NSFont.monospacedSystemFontOfSize_weight_(point, AppKit.NSFontWeightRegular)
    ink = AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*INK, 1.0)
    source = at or log_path()
    last: dict = {"rows": None}

    def render():
        rows = tail(source, lines)
        if rows == last["rows"]:
            return
        last["rows"] = rows
        text = AppKit.NSAttributedString.alloc().initWithString_attributes_(
            "\n".join(rows), {AppKit.NSFontAttributeName: font, AppKit.NSForegroundColorAttributeName: ink})
        view.textStorage().setAttributedString_(text)
        view.scrollToEndOfDocument_(None)

    class Ticker(NSObject):
        def tick_(self, timer):
            render()

    ticker = Ticker.alloc().init()
    render()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.5, ticker, "tick:", None, True)
    window.orderFrontRegardless()
    AppHelper.runEventLoop()

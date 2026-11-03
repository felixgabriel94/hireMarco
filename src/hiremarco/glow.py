"""The glow: Logic's window outlined in the brand's blue while Marco works (Owner 2026-11-03).

While a master job's process lives, Logic's front window carries a breathing blue outline, and each event that
lands on Marco Live gives it a small pulse: the audience sees that he is running the session, not that he is away.
The halo is his presence when he is with the Owner; the glow is his hand on the work. Between jobs there is nothing.

The panel is see-through, borderless, non-activating and ignores the mouse, so Logic keeps the front and every click
passes through. Its frame follows Logic's front window, read from System Events twice a second. No Dock tile: the
process is an accessory, like Marco Live.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path

from hiremarco import events

ACCENT_OKLCH = (0.72, 0.185, 264.0)   # trace/design.html --accent, the one home of the brand blue
MARGIN = 6.0           # points outside the window the stroke sits at
STROKE = 5.0
RADIUS = 14.0
BREATH_S = 4.0         # one slow breath
ALPHA_LOW, ALPHA_HIGH = 0.38, 0.85
PULSE_S = 0.7          # a landed event: a quick rise that fades
WINDOW_POLL_S = 0.5
FRONT_WINDOW = ('tell application "System Events" to tell process "Logic Pro" to get {position, size} of window 1')


def oklch_to_srgb(l: float, c: float, h: float) -> tuple[float, float, float]:
    """The brand token as sRGB in 0 to 1, by the OKLab transform (Ottosson), clipped to the gamut."""
    a, b = c * math.cos(math.radians(h)), c * math.sin(math.radians(h))
    l_, m_, s_ = l + 0.3963377774 * a + 0.2158037573 * b, l - 0.1055613458 * a - 0.0638541728 * b, l - 0.0894841775 * a - 1.2914855480 * b
    l3, m3, s3 = l_ ** 3, m_ ** 3, s_ ** 3
    r = 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3
    g = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3
    bl = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3

    def gamma(x: float) -> float:
        x = min(max(x, 0.0), 1.0)
        return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055

    return gamma(r), gamma(g), gamma(bl)


def breath(t: float) -> float:
    """The resting alpha at time t: a slow sine between the low and the high."""
    return ALPHA_LOW + (ALPHA_HIGH - ALPHA_LOW) * (0.5 - 0.5 * math.cos(2 * math.pi * t / BREATH_S))


def pulse(since: float | None) -> float:
    """What a landed event adds, fading over PULSE_S; nothing when none landed."""
    if since is None or since < 0 or since >= PULSE_S:
        return 0.0
    return (1.0 - since / PULSE_S) * (1.0 - ALPHA_HIGH)


class State:
    """Working while a job's process lives; a pulse for each row that lands meanwhile."""

    def __init__(self, alive: Callable[[int | None], bool] | None = None):
        self.pid: int | None = None
        self.pulsed_at: float | None = None
        self.alive = alive or _alive

    def add(self, rows: list[dict], now: float) -> None:
        for row in rows:
            kind = row.get("kind")
            if kind == "job_started":
                self.pid = row.get("pid")
            elif kind == "job_ended":
                self.pid = None
            elif self.pid and row.get("model") != events.VOICE_MODEL:
                self.pulsed_at = now

    def working(self) -> bool:
        if self.pid and not self.alive(self.pid):
            self.pid = None   # a job that died without its last row
        return bool(self.pid)

    def alpha(self, now: float) -> float:
        if not self.working():
            return 0.0
        since = None if self.pulsed_at is None else now - self.pulsed_at
        return min(1.0, breath(now) + pulse(since))


def _alive(pid: int | None) -> bool:
    from hiremarco.tracewindow import alive

    return alive(pid)


def panel_rect(window: tuple[float, float, float, float], screen_height: float, margin: float = MARGIN) -> tuple[float, float, float, float]:
    """System Events gives a window's top-left corner with y down from the top of the main screen; AppKit wants the
    bottom-left with y up. The panel is the window plus a margin on every side."""
    x, y, w, h = window
    return x - margin, screen_height - (y + h) - margin, w + 2 * margin, h + 2 * margin


def front_window(run: Callable[[str], str]) -> tuple[float, float, float, float] | None:
    """Logic's front window, or None when it has none (a dialog, no project)."""
    try:
        parts = [float(v) for v in run(FRONT_WINDOW).split(", ")]
    except (ValueError, OSError, RuntimeError):
        return None
    return (parts[0], parts[1], parts[2], parts[3]) if len(parts) == 4 and parts[2] > 0 and parts[3] > 0 else None


def show(*, at: Path | None = None) -> None:
    """The glow on the Mac's own screen, over Logic, until closed."""
    import AppKit
    from Foundation import NSMakeRect, NSObject, NSTimer
    from PyObjCTools import AppHelper

    from hiremarco.studio.recall import _osascript

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    main = AppKit.NSScreen.screens()[0]
    screen_h = main.frame().size.height
    red, green, blue = oklch_to_srgb(*ACCENT_OKLCH)

    class GlowView(AppKit.NSView):
        alpha = 0.0

        def drawRect_(self, rect):
            if self.alpha <= 0.0:
                return
            bounds = self.bounds()
            inset = STROKE / 2 + 1
            path = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(bounds.origin.x + inset, bounds.origin.y + inset, bounds.size.width - 2 * inset, bounds.size.height - 2 * inset),
                RADIUS, RADIUS)
            path.setLineWidth_(STROKE)
            AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, self.alpha).setStroke()
            path.stroke()
            soft = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(bounds.origin.x + 1, bounds.origin.y + 1, bounds.size.width - 2, bounds.size.height - 2), RADIUS + 2, RADIUS + 2)
            soft.setLineWidth_(STROKE * 2.4)
            AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, self.alpha * 0.22).setStroke()
            soft.stroke()

    style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(NSMakeRect(0, 0, 10, 10), style, AppKit.NSBackingStoreBuffered, False)
    panel.setLevel_(AppKit.NSFloatingWindowLevel)
    panel.setOpaque_(False)
    panel.setHasShadow_(False)
    panel.setIgnoresMouseEvents_(True)
    panel.setHidesOnDeactivate_(False)
    panel.setBackgroundColor_(AppKit.NSColor.clearColor())
    panel.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
    view = GlowView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
    panel.setContentView_(view)

    source = events.path() if at is None else at
    state = State()
    feed = {"offset": 0, "window": None, "polled": 0.0}
    try:
        feed["offset"] = source.stat().st_size   # a glow opened between runs starts quiet; a run already going catches up below
        rows, _ = events.tail(source, 0)
        from hiremarco.tracewindow import resume_point

        state.add(resume_point(rows), time.monotonic())
    except OSError:
        pass

    class Ticker(NSObject):
        def tick_(self, timer):
            now = time.monotonic()
            try:
                rows, feed["offset"] = events.tail(source, feed["offset"])
            except OSError:
                rows = []
            state.add(rows, now)
            if now - feed["polled"] >= WINDOW_POLL_S:
                feed["polled"] = now
                feed["window"] = front_window(_osascript) if state.working() else None
            alpha = state.alpha(now) if feed["window"] else 0.0
            if feed["window"] and alpha > 0:
                x, y, w, h = panel_rect(feed["window"], screen_h)
                panel.setFrame_display_(NSMakeRect(x, y, w, h), False)
                if not panel.isVisible():
                    panel.orderFrontRegardless()
            elif panel.isVisible():
                panel.orderOut_(None)
            view.alpha = alpha
            view.setNeedsDisplay_(True)

    ticker = Ticker.alloc().init()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1 / 30.0, ticker, "tick:", None, True)
    AppHelper.runEventLoop()

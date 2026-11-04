"""The glow: Logic's front window outlined in the brand's blue while Marco works (Owner 2026-11-03).

While a master job's process lives, the Logic window Marco is working in carries a soft blue light along its edge:
layered, breathing, with a slow drift of brightness around the frame, like air moving. Each event that lands on
Marco Live gives it a small pulse. When a run starts the light is born where the halo sits, a ring at the centre of
the screen that stretches out to the window and leaves a fading trail, so it reads as the halo splitting; when the
run ends it draws back the same way. Between jobs there is nothing.

The panel covers the Mac's own screen, see-through, borderless, non-activating, ignoring the mouse, so Logic keeps
the front and every click passes through. The window's edge is read from the window server ten times a second, no
scripting round trip, and the outline eases to a new window in a few frames, so it moves with Marco, not after him.
No Dock tile: the process is an accessory, like Marco Live.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path

from hiremarco import events

ACCENT_OKLCH = (0.72, 0.185, 264.0)   # trace/design.html --accent, the one home of the brand blue
RADIUS = 14.0
BREATH_S = 4.0         # one slow breath
ALPHA_LOW, ALPHA_HIGH = 0.45, 0.95
PULSE_S = 0.7          # a landed event: a quick rise that fades
LAYERS = ((30.0, 0.07), (18.0, 0.14), (10.0, 0.30), (4.5, 1.0))   # stroke width and share of the alpha, outside in: light, not a line
DRIFT_S = 6.0          # one lap of the brighter stretch around the frame
WINDOW_POLL_S = 0.1    # the window server read, ten a second
EASE = 0.38            # how much of the way to a new frame each tick (30 a second): about a tenth of a second to settle
BIRTH_S = 0.8          # the halo's ring stretching into the window, and back at the end
BIRTH_R = 64.0         # the ring's radius where it starts, the halo's size at the centre of the screen
TRAIL = (0.18, 0.36)   # ghost outlines behind the moving one during the birth, in time, and their alphas below
TRAIL_ALPHA = (0.35, 0.18)
MIN_W, MIN_H = 200.0, 120.0   # anything smaller is a sheet or a palette, not a window Marco works in

Rect = tuple[float, float, float, float]


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
    """Working while a job's process lives; a pulse for each row that lands meanwhile; when the work began and ended."""

    def __init__(self, alive: Callable[[int | None], bool] | None = None):
        self.pid: int | None = None
        self.pulsed_at: float | None = None
        self.began_at: float | None = None
        self.ended_at: float | None = None
        self.alive = alive or _alive

    def add(self, rows: list[dict], now: float) -> None:
        for row in rows:
            kind = row.get("kind")
            if kind == "job_started":
                self.pid, self.began_at, self.ended_at = row.get("pid"), now, None
            elif kind == "job_ended":
                self._end(now)
            elif self.pid and row.get("model") != events.VOICE_MODEL:
                self.pulsed_at = now

    def _end(self, now: float) -> None:
        if self.pid:
            self.ended_at = now
        self.pid = None

    def working(self, now: float | None = None) -> bool:
        if self.pid and not self.alive(self.pid):
            self._end(now if now is not None else time.monotonic())   # a job that died without its last row
        return bool(self.pid)

    def phase(self, now: float) -> float:
        """0 when there is nothing to show, rising to 1 over BIRTH_S after a start, falling back to 0 after an end."""
        if self.working(now):
            return min(1.0, (now - self.began_at) / BIRTH_S) if self.began_at is not None else 1.0
        if self.ended_at is not None and now - self.ended_at < BIRTH_S:
            return max(0.0, 1.0 - (now - self.ended_at) / BIRTH_S)
        return 0.0

    def alpha(self, now: float) -> float:
        p = self.phase(now)
        if p <= 0.0:
            return 0.0
        since = None if self.pulsed_at is None else now - self.pulsed_at
        return min(1.0, breath(now) + pulse(since)) * p


def _alive(pid: int | None) -> bool:
    from hiremarco.tracewindow import alive

    return alive(pid)


def front_logic_window(infos: list[dict]) -> Rect | None:
    """The Logic window in front, from the window server's on-screen list (front first): its bounds with the top-left
    origin the server uses. Plug-in windows count, so the light follows Marco into one; sheets and palettes do not."""
    for info in infos:
        if info.get("kCGWindowOwnerName") != "Logic Pro" or int(info.get("kCGWindowLayer", 0) or 0) > 3:
            continue
        b = info.get("kCGWindowBounds") or {}
        try:
            x, y, w, h = float(b["X"]), float(b["Y"]), float(b["Width"]), float(b["Height"])
        except (KeyError, TypeError, ValueError):
            continue
        if w >= MIN_W and h >= MIN_H:
            return x, y, w, h
    return None


def view_rect(window: Rect, screen_height: float) -> Rect:
    """The window server gives a window's top-left corner with y down from the top of the main screen; AppKit draws
    with the bottom-left origin and y up. The same rectangle in the panel's own coordinates."""
    x, y, w, h = window
    return x, screen_height - (y + h), w, h


def ease(current: Rect | None, target: Rect, k: float = EASE) -> Rect:
    """A step of the outline toward where the window is: most of the way each tick, so a switch reads as a slide."""
    if current is None:
        return target
    return tuple(c + (t - c) * k for c, t in zip(current, target))   # type: ignore[return-value]


def birth(t: float, centre: tuple[float, float], target: Rect) -> tuple[Rect, float]:
    """The halo's ring stretching into the window: at t=0 a circle of BIRTH_R at the centre of the screen, at t=1 the
    window itself; eased so it leaves fast and lands soft. Returns the rect and its corner radius."""
    s = 1.0 - (1.0 - min(max(t, 0.0), 1.0)) ** 3
    cx, cy = centre
    ring = (cx - BIRTH_R, cy - BIRTH_R, 2 * BIRTH_R, 2 * BIRTH_R)
    rect = tuple(a + (b - a) * s for a, b in zip(ring, target))
    return rect, BIRTH_R + (RADIUS - BIRTH_R) * s   # type: ignore[return-value]


def show(*, at: Path | None = None) -> None:
    """The glow on the Mac's own screen, over Logic, until closed."""
    import AppKit
    import Quartz
    from Foundation import NSMakeRect, NSObject, NSTimer
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    main = AppKit.NSScreen.screens()[0]
    screen = main.frame()
    screen_h = screen.size.height
    red, green, blue = oklch_to_srgb(*ACCENT_OKLCH)
    centre = (screen.size.width / 2, screen_h / 2)

    def colour(alpha: float):
        return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, max(0.0, min(1.0, alpha)))

    def outline(rect: Rect, radius: float, alpha: float, drift: float) -> None:
        x, y, w, h = rect
        inset = LAYERS[0][0] / 2 + 1
        shape = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x + inset, y + inset, max(w - 2 * inset, 1), max(h - 2 * inset, 1)), radius, radius)
        shape.setLineCapStyle_(AppKit.NSRoundLineCapStyle)
        for width, share in LAYERS:   # layered light: wide and faint outside, narrow and bright at the edge
            shape.setLineWidth_(width)
            colour(alpha * share * 0.55).setStroke()
            shape.stroke()
        # the drift: a brighter stretch that travels around the frame, like air moving along the edge
        lap = 2 * (w + h)
        shape.setLineWidth_(LAYERS[-1][0] + 2)
        shape.setLineDash_count_phase_([lap * 0.18, lap * 0.82], 2, -drift * lap)
        colour(alpha * 0.55).setStroke()
        shape.stroke()

    class GlowView(AppKit.NSView):
        rect = None        # where the light is now, eased
        target = None      # where the window is
        alpha = 0.0
        phase = 0.0
        drift = 0.0

        def drawRect_(self, dirty):
            if self.alpha <= 0.0 or self.target is None:
                return
            if self.phase < 1.0:   # being born out of the halo, or drawing back into it, with a trail that fades
                for back, trail_alpha in zip(TRAIL, TRAIL_ALPHA):
                    rect, radius = birth(self.phase - back, centre, self.target)
                    outline(rect, radius, self.alpha * trail_alpha, self.drift)
                rect, radius = birth(self.phase, centre, self.target)
                outline(rect, radius, self.alpha, self.drift)
                return
            outline(self.rect or self.target, RADIUS, self.alpha, self.drift)

    style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(screen, style, AppKit.NSBackingStoreBuffered, False)
    panel.setLevel_(AppKit.NSFloatingWindowLevel)
    panel.setOpaque_(False)
    panel.setHasShadow_(False)
    panel.setIgnoresMouseEvents_(True)
    panel.setHidesOnDeactivate_(False)
    panel.setBackgroundColor_(AppKit.NSColor.clearColor())
    panel.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary | AppKit.NSWindowCollectionBehaviorStationary)
    view = GlowView.alloc().initWithFrame_(NSMakeRect(0, 0, screen.size.width, screen_h))
    panel.setContentView_(view)

    source = events.path() if at is None else at
    state = State()
    feed = {"offset": 0, "polled": 0.0, "t0": time.monotonic()}
    try:
        feed["offset"] = source.stat().st_size   # a glow opened between runs starts quiet; a run already going catches up below
        rows, _ = events.tail(source, 0)
        from hiremarco.tracewindow import resume_point

        state.add(resume_point(rows), time.monotonic())
        state.began_at = time.monotonic() - BIRTH_S   # already working: no birth to show
    except OSError:
        pass

    def windows() -> list[dict]:
        return list(Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
                                                      Quartz.kCGNullWindowID) or [])

    class Ticker(NSObject):
        def tick_(self, timer):
            now = time.monotonic()
            try:
                rows, feed["offset"] = events.tail(source, feed["offset"])
            except OSError:
                rows = []
            state.add(rows, now)
            showing = state.phase(now) > 0.0
            if showing and now - feed["polled"] >= WINDOW_POLL_S:
                feed["polled"] = now
                found = front_logic_window(windows())
                if found is not None:
                    view.target = view_rect(found, screen_h)
            view.alpha = state.alpha(now) if view.target is not None else 0.0
            view.phase = state.phase(now)
            view.drift = ((now - feed["t0"]) / DRIFT_S) % 1.0
            if view.target is not None:
                view.rect = ease(view.rect, view.target)
            if view.alpha > 0 and not panel.isVisible():
                panel.orderFrontRegardless()
            elif view.alpha <= 0 and panel.isVisible():
                panel.orderOut_(None)
                view.rect = None
            view.setNeedsDisplay_(True)

    ticker = Ticker.alloc().init()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1 / 30.0, ticker, "tick:", None, True)
    AppHelper.runEventLoop()

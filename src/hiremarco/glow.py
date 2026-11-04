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
ALPHA_LOW, ALPHA_HIGH = 0.55, 0.92
PULSE_S = 0.7          # a landed event: a quick rise that fades
# stroke width and share of the alpha, wide and faint to narrow and fuller, with no hard core: an aura that fades
# both ways from the edge, air, not a line (Owner 2026-11-03)
LAYERS = ((56.0, 0.08), (40.0, 0.12), (28.0, 0.18), (18.0, 0.27), (11.0, 0.38), (6.0, 0.48))   # a third stronger (Owner 2026-11-04)
MAX_LAYER = 20  # the window server's layer up to which a Logic window counts: a modal panel ("Choose a Project") is 8, a
                # loading banner higher; menus and tooltips sit above 20
DRIFT_S = 6.0          # one lap of the brighter stretch around the frame
WINDOW_POLL_S = 0.1    # the window server read, ten a second
EASE = 0.38            # how much of the way to a new frame each tick (30 a second): about a tenth of a second to settle
BIRTH_S = 1.25         # the halo's orb flowing into the window's frame, and back at the end (Owner 2026-11-03: a genie, not lines)
BIRTH_R = 110.0        # the orb's radius where it starts, at the centre of the window it will frame, where the halo floats
LOST_S = 0.45          # the light fading when Logic has no window to frame for a moment
MIN_W, MIN_H = 150.0, 60.0    # anything smaller is a palette or a tooltip; a loading banner and a sheet both count (Owner 2026-11-03)

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
        self.job = False   # a master job is lit: it ends on its own row, not on the command's that started it
        self.alive = alive or _alive

    def add(self, rows: list[dict], now: float) -> None:
        for row in rows:
            kind = row.get("kind")
            if kind in ("job_started", "work_started"):   # a master job, or the booth at work in Logic for one command
                if not self.pid:   # a light already on stays on: no second birth for work inside work
                    self.began_at, self.ended_at = now, None
                self.pid = row.get("pid") or self.pid
                self.job = kind == "job_started" or (self.job and kind == "work_started")
            elif kind == "job_ended" or (kind == "work_ended" and not self.job):
                self._end(now)   # a command's end does not end a job it started: the job's own last row does
            elif self.pid and row.get("model") != events.VOICE_MODEL:
                self.pulsed_at = now

    def _end(self, now: float) -> None:
        if self.pid:
            self.ended_at = now
        self.pid, self.job = None, False

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
        if info.get("kCGWindowOwnerName") != "Logic Pro" or int(info.get("kCGWindowLayer", 0) or 0) > MAX_LAYER:
            continue
        if float(info.get("kCGWindowAlpha", 1.0) or 0.0) <= 0.0:   # a window Logic holds but has not shown (its launch, 2026-11-03)
            continue
        if "kCGWindowIsOnscreen" in info and not info.get("kCGWindowIsOnscreen"):
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


def smooth(t: float) -> float:
    """Smoothstep: no hard start or stop, the same curve the halo eases with."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def birth(t: float, centre: tuple[float, float], target: Rect) -> tuple[Rect, float]:
    """The halo's orb flowing into the window's frame: at t=0 a circle of BIRTH_R at the centre of the window, where
    the halo floats, at t=1 the window itself, by smoothstep both ways. Returns the rect and its corner radius."""
    s = smooth(t)
    cx, cy = centre
    ring = (cx - BIRTH_R, cy - BIRTH_R, 2 * BIRTH_R, 2 * BIRTH_R)
    rect = tuple(a + (b - a) * s for a, b in zip(ring, target))
    return rect, BIRTH_R + (RADIUS - BIRTH_R) * s   # type: ignore[return-value]


def centre_of(rect: Rect) -> tuple[float, float]:
    x, y, w, h = rect
    return x + w / 2, y + h / 2


def softness(t: float) -> float:
    """How much wider and fainter the light is while it is still the orb: 1 when landed, more at the start."""
    return 1.0 + 1.4 * (1.0 - smooth(t))


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

    def outline(rect: Rect, radius: float, alpha: float, drift: float, soft: float = 1.0) -> None:
        x, y, w, h = rect
        # the stroke sits on the window's edge itself, half out and half in, not inside it (Owner 2026-11-03)
        shape = AppKit.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x, y, max(w, 1), max(h, 1)), radius, radius)
        shape.setLineCapStyle_(AppKit.NSRoundLineCapStyle)
        # layered light, wide and faint outside, narrow and bright at the edge; each layer breathes on its own slow
        # phase, so the whole edge shimmers like air rather than anything travelling around it (Owner 2026-11-03:
        # no bubble, the whole outline airy, like the air off a waterfall); wider and fainter while still the orb
        for k, (width, share) in enumerate(LAYERS):
            sway = 0.85 + 0.15 * math.sin(2 * math.pi * (drift + 0.21 * k))
            shape.setLineWidth_(width * soft)
            colour(alpha * share * 0.8 * sway / soft).setStroke()
            shape.stroke()

    class GlowView(AppKit.NSView):
        rect = None        # where the light is now, eased
        target = None      # where the window is
        alpha = 0.0
        phase = 0.0
        drift = 0.0

        shown = 0.0        # eased 0 to 1: the light fading when Logic has no window for a moment
        ending = False     # the work is over: the light fades where it is, and the halo fades in (Owner 2026-11-03)

        def drawRect_(self, dirty):
            if self.alpha <= 0.0 or self.target is None or self.shown <= 0.0:
                return
            if self.phase < 1.0 and self.shown >= 0.99 and not self.ending:   # the orb flowing into the frame: one shape, no trail, no lines
                rect, radius = birth(self.phase, centre_of(self.rect or self.target), self.target)
                outline(rect, radius, self.alpha * self.shown * smooth(self.phase), self.drift, softness(self.phase))
                return
            outline(self.rect or self.target, RADIUS, self.alpha * self.shown, self.drift)

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
                infos = windows()
                found = front_logic_window(infos)
                if found != feed.get("found"):   # every switch on the record, for a frame that looks stuck (Owner 2026-11-04)
                    feed["found"] = found
                    front = [(i.get("kCGWindowName") or "?", int(i.get("kCGWindowLayer", 0) or 0), i.get("kCGWindowBounds"))
                             for i in infos if i.get("kCGWindowOwnerName") == "Logic Pro"][:4]
                    print(f"{time.strftime('%H:%M:%S')} frame {found} of Logic's windows {front}", flush=True)
                if found is not None:
                    if view.target is None and state.working(now) and not feed.get("born"):
                        state.began_at = now   # the first window of this work: the orb flows into it from the halo
                    feed["born"] = True
                    feed["lost"] = False
                    view.target = view_rect(found, screen_h)
                else:
                    feed["lost"] = True   # no window of Logic's to frame right now: the light fades, the frame stays put
            if not state.working(now) and state.phase(now) <= 0.0:
                feed["born"] = False
            want = 1.0 if (view.target is not None and not feed.get("lost")) else 0.0
            view.shown += (want - view.shown) * min(1.0, (1 / 30.0) / LOST_S * 3)
            if view.shown < 0.01:
                view.shown = 0.0
            view.alpha = state.alpha(now) if view.target is not None else 0.0
            view.phase = state.phase(now)
            view.ending = not state.working(now) and state.ended_at is not None
            view.drift = ((now - feed["t0"]) / DRIFT_S) % 1.0
            if view.target is not None:
                view.rect = view.target   # window to window the light jumps, no travel (Owner 2026-11-03); only the birth flows
            if view.alpha > 0 and view.shown > 0 and not panel.isVisible():
                panel.orderFrontRegardless()
            elif (view.alpha <= 0 or view.shown <= 0) and panel.isVisible():
                panel.orderOut_(None)
                view.rect = None
                if view.alpha <= 0:
                    view.target = None
            view.setNeedsDisplay_(True)

    ticker = Ticker.alloc().init()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1 / 30.0, ticker, "tick:", None, True)
    AppHelper.runEventLoop()

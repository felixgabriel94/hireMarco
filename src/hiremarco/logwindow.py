"""The window the film watches: Marco's last eight steps, light on dark, 24 point, fixed size and place.

An AppKit panel through PyObjC (no Tk on this Python), floating over Logic so
the camera sees it in the corner: the model id in one accent color, the step in
plain words, the seconds dim at the end; newest at the bottom; refreshed from
``marco.log`` twice a second. It is a non-activating panel: it never takes the
front from Logic, because Marco's hands refuse to click when Logic is not in
front and a window that stole the front killed run 32 (2026-11-02). Nothing is
typed into it and it takes no clicks.
"""

from __future__ import annotations

from pathlib import Path

from hiremarco import stream

LINES = 8
WIDTH, HEIGHT = 960, 440
POINT = 24.0
COLUMN = 18                      # characters of the model column (muse-voice-transcribe-1.0 fits cut)
WORDS = 110                      # characters of a step shown; the log file keeps the whole line
ACCENT = (0.50, 0.82, 1.00)      # the model id
INK = (0.92, 0.92, 0.90)         # the step
DIM = (0.55, 0.55, 0.55)         # the seconds
PAPER = (0.07, 0.07, 0.08)


def show(at: Path | None = None, *, x: float | None = None, y: float | None = None, lines: int = LINES,
         screen: int = 1, point: float = POINT, fill: float | None = None) -> None:
    """The panel on display ``screen`` (1 is the Mac's own); ``fill`` is the share of that display it covers
    (the TV across the room takes 0.9 at 32 point), else the fixed size at the display's top right."""
    import AppKit
    from Foundation import NSMakeRect, NSObject, NSTimer
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)   # no Dock tile, never the active app
    screens = list(AppKit.NSScreen.screens())
    chosen = screens[min(max(screen, 1), len(screens)) - 1]
    frame = chosen.visibleFrame()
    width, height = (frame.size.width * fill, frame.size.height * fill) if fill else (WIDTH, HEIGHT)
    left = frame.origin.x + (frame.size.width - width) / 2 if fill else (frame.origin.x + frame.size.width - width - 24)
    bottom = frame.origin.y + (frame.size.height - height) / 2 if fill else (frame.origin.y + frame.size.height - height - 24)
    left, bottom = (x if x is not None else left), (y if y is not None else bottom)
    style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
             | AppKit.NSWindowStyleMaskNonactivatingPanel | AppKit.NSWindowStyleMaskUtilityWindow)
    # made on the chosen display: a frame given to a panel made on the main display is pulled back onto it
    # (2026-11-02: the TV panel landed over Logic on the laptop)
    window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_screen_(
        NSMakeRect(left, bottom, width, height), style, AppKit.NSBackingStoreBuffered, False, chosen)
    window.setFrameOrigin_((left, bottom))
    window.setBecomesKeyOnlyIfNeeded_(True)
    window.setHidesOnDeactivate_(False)
    window.setTitle_("Marco")
    window.setLevel_(AppKit.NSFloatingWindowLevel)
    window.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*PAPER, 1.0))
    view = AppKit.NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    view.setEditable_(False)
    view.setSelectable_(False)
    view.setDrawsBackground_(True)
    view.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*PAPER, 1.0))
    view.setTextContainerInset_((20, 16))
    window.setContentView_(view)

    font = AppKit.NSFont.monospacedSystemFontOfSize_weight_(point, AppKit.NSFontWeightRegular)
    colors = {name: AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*rgb, 1.0)
              for name, rgb in (("accent", ACCENT), ("ink", INK), ("dim", DIM))}
    paragraph = AppKit.NSMutableParagraphStyle.alloc().init()   # a wrapped step stays in its own column
    paragraph.setHeadIndent_(COLUMN * point * 0.6)
    paragraph.setParagraphSpacing_(point * 0.25)

    def render(rows: list[dict]):
        text = AppKit.NSMutableAttributedString.alloc().init()
        for row in rows[-lines:]:
            pieces = [(f"{row.get('model', stream.MARCO)[:COLUMN - 1]:<{COLUMN}}", "accent"),
                      (row.get("text", "")[:WORDS], "ink")]
            if "seconds" in row:
                pieces.append((f"  {row['seconds']:.1f} s", "dim"))
            for words, color in pieces:
                text.appendAttributedString_(AppKit.NSAttributedString.alloc().initWithString_attributes_(
                    words, {AppKit.NSFontAttributeName: font, AppKit.NSForegroundColorAttributeName: colors[color],
                            AppKit.NSParagraphStyleAttributeName: paragraph}))
            text.appendAttributedString_(AppKit.NSAttributedString.alloc().initWithString_attributes_(
                "\n", {AppKit.NSFontAttributeName: font, AppKit.NSParagraphStyleAttributeName: paragraph}))
        view.textStorage().setAttributedString_(text)
        view.scrollToEndOfDocument_(None)

    class Ticker(NSObject):
        def tick_(self, timer):
            render(stream.tail(lines, at=at))

    ticker = Ticker.alloc().init()
    render(stream.tail(lines, at=at))
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.5, ticker, "tick:", None, True)
    window.orderFrontRegardless()   # shown, never activated: Logic keeps the front
    AppHelper.runEventLoop()

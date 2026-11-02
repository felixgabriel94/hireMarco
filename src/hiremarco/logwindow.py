"""The window the film watches: Marco's last eight steps, light on dark, 24 point, fixed size and place.

An AppKit window through PyObjC (no Tk on this Python), floating over Logic so
the camera sees it in the corner: the model id in one accent color, the step in
plain words, the seconds dim at the end; newest at the bottom; refreshed from
``marco.log`` twice a second. Nothing is typed into it and it takes no clicks.
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


def show(at: Path | None = None, *, x: float | None = None, y: float | None = None, lines: int = LINES) -> None:
    import AppKit
    from Foundation import NSMakeRect, NSObject, NSTimer
    from PyObjCTools import AppHelper

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    screen = AppKit.NSScreen.mainScreen().visibleFrame()
    left = screen.origin.x + screen.size.width - WIDTH - 24 if x is None else x
    bottom = screen.origin.y + screen.size.height - HEIGHT - 24 if y is None else y
    style = AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(left, bottom, WIDTH, HEIGHT), style, AppKit.NSBackingStoreBuffered, False)
    window.setTitle_("Marco")
    window.setLevel_(AppKit.NSFloatingWindowLevel)
    window.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*PAPER, 1.0))
    view = AppKit.NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, HEIGHT))
    view.setEditable_(False)
    view.setSelectable_(False)
    view.setDrawsBackground_(True)
    view.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*PAPER, 1.0))
    view.setTextContainerInset_((20, 16))
    window.setContentView_(view)

    font = AppKit.NSFont.monospacedSystemFontOfSize_weight_(POINT, AppKit.NSFontWeightRegular)
    colors = {name: AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*rgb, 1.0)
              for name, rgb in (("accent", ACCENT), ("ink", INK), ("dim", DIM))}
    paragraph = AppKit.NSMutableParagraphStyle.alloc().init()   # a wrapped step stays in its own column
    paragraph.setHeadIndent_(COLUMN * POINT * 0.6)
    paragraph.setParagraphSpacing_(POINT * 0.25)

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
    window.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)
    AppHelper.runEventLoop()

"""Marco records his own screens for the film: every picture on its own file, straight to the LaCie.

Apple's ScreenCaptureKit records each source with its own stream and writes it with the Mac's hardware encoder
(``SCRecordingOutput``, macOS 15), so no frame passes through Python. The streams (Owner 2026-11-03):

    logic-main                          Logic's main window, recorded even when something lies over it
    logic-window-<title>-<HHMMSS>       every other Logic window (mixer, plug-ins, dialogs), each its own file,
                                        from the moment it appears until it closes
    logic-all                           the safety copy: Logic's windows on its display, overlapping as they were live
    live-trace                          the Marco Live panel
    terminal                            the terminal panel on the TV
    tv                                  the whole TV
    macbook                             the whole MacBook display: Logic opening from the Dock, anything else

Files go to ``<day>/screen/<stream>/<stream>_<YYYYMMDD-HHMMSS>.mov`` in 15-minute pieces, all cut at the same
moment; ``<day>/screen/screen.jsonl`` gives each file's first frame on the Mac clock, to the millisecond, and the
file's creation date is set to it. The Apollo's audio records beside them through ``film.py`` into
``<day>/audio/apollo``. ``screenrec.json`` in the state folder says what is live, for the crew and for Marco's hands
(who wait for a new window's recording before working in it).

The process takes no Dock tile (Accessory policy) and keeps the Mac awake while it runs. SIGINT or SIGTERM ends
every file cleanly.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from hiremarco import config

LOGIC = "com.apple.logic10"
SEGMENT_SECONDS = 15 * 60
WATCH_S = 0.5
FPS = 30
MIN_SIDE = 80               # smaller Logic windows are menus, tooltips and the like
RETRIES = 3
SETTLE_S = 12.0
TRACE_TITLE = "Marco Live"
TERMINAL_TITLE = "Marco Terminal"
STATUS = "screenrec.json"
MOV = "com.apple.quicktime-movie"
HEVC = "hvc1"


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:40] or "untitled"


def stamp(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%Y%m%d-%H%M%S")


def local_iso(t: float) -> str:
    return datetime.fromtimestamp(t).astimezone().isoformat(timespec="milliseconds")


def even(n: float) -> int:
    return max(2, int(n) // 2 * 2)


def logic_windows(windows) -> list:
    """Logic's real windows on screen, biggest first: layer 0, not tiny."""
    found = []
    for w in windows:
        app = w.owningApplication()
        if app is None or app.bundleIdentifier() != LOGIC or not w.isOnScreen() or w.windowLayer() != 0:
            continue
        f = w.frame()
        if f.size.width < MIN_SIDE or f.size.height < MIN_SIDE:
            continue
        found.append(w)
    return sorted(found, key=lambda w: -(w.frame().size.width * w.frame().size.height))


def plan_logic(windows, main_id: int | None, known: dict[int, str], now: float) -> tuple[int | None, dict[int, str]]:
    """Which window is the main one (kept while it lives) and the stream name of every other one, named once."""
    ids = [w.windowID() for w in windows]
    if main_id not in ids:
        main_id = ids[0] if ids else None
    names = {}
    for w in windows:
        wid = w.windowID()
        if wid == main_id:
            continue
        names[wid] = known.get(wid) or f"logic-window-{slug(w.title() or '')}-{datetime.fromtimestamp(now).strftime('%H%M%S')}"
    return main_id, names


# ------------------------------------------------------------------------------------------------ ScreenCaptureKit

def _wait(start: Callable[[Callable], None], what: str, timeout: float = 10.0):
    done, box = threading.Event(), {}

    def handler(*result):
        box["result"] = result
        done.set()

    start(handler)
    if not done.wait(timeout):
        raise TimeoutError(f"{what} did not answer in {timeout:.0f} s")
    return box["result"]


def shareable():
    import ScreenCaptureKit as SCK

    content, error = _wait(SCK.SCShareableContent.getShareableContentWithCompletionHandler_, "the window list")
    if error is not None or content is None:
        raise PermissionError(f"ScreenCaptureKit refused the window list: {error}")
    return content


def builtin(display) -> bool:
    import Quartz

    return bool(Quartz.CGDisplayIsBuiltin(display.displayID()))


_DELEGATE = None


def delegate_class():
    """The recording delegate, defined once: Objective-C class names are global to the process."""
    global _DELEGATE
    if _DELEGATE is not None:
        return _DELEGATE
    import objc
    from Foundation import NSObject

    class MarcoRecordingDelegate(NSObject, protocols=[objc.protocolNamed("SCRecordingOutputDelegate")]):
        def recordingOutputDidStartRecording_(self, output):
            piece = getattr(self, "piece", None)
            if piece is not None:
                piece.began(time.time())

        def recordingOutput_didFailWithError_(self, output, error):
            piece = getattr(self, "piece", None)
            if piece is not None:
                piece.failed(str(error)[:200])

        def recordingOutputDidFinishRecording_(self, output):
            piece = getattr(self, "piece", None)
            if piece is not None:
                piece.finished()

    _DELEGATE = MarcoRecordingDelegate
    return _DELEGATE


class Piece:
    """One file: a recording output on a stream, from its first frame to its last."""

    def __init__(self, stream: "Stream", path: Path):
        import ScreenCaptureKit as SCK
        from Foundation import NSURL

        self.stream, self.path = stream, path
        self.first_frame: float | None = None
        self.error = ""
        self.done = threading.Event()
        cfg = SCK.SCRecordingOutputConfiguration.alloc().init()
        cfg.setOutputURL_(NSURL.fileURLWithPath_(str(path)))
        cfg.setOutputFileType_(MOV)          # AVFileTypeQuickTimeMovie, without AVFoundation's bindings
        cfg.setVideoCodecType_(HEVC)         # AVVideoCodecTypeHEVC, the Mac's hardware encoder
        self.delegate = delegate_class().alloc().init()
        self.delegate.piece = self
        self.output = SCK.SCRecordingOutput.alloc().initWithConfiguration_delegate_(cfg, self.delegate)

    def began(self, t: float) -> None:
        if self.first_frame is None:
            self.first_frame = t
            self.stream.recorder.manifest(self.path, t)

    def failed(self, error: str) -> None:
        self.error = error
        self.done.set()
        self.stream.died(error)

    def finished(self) -> None:
        self.done.set()
        if self.first_frame is not None:
            set_created(self.path, self.first_frame)


def set_created(path: Path, t: float) -> None:
    """The file's creation date is its first frame, so Final Cut and Finder show when it began."""
    try:
        from Foundation import NSDate, NSFileCreationDate, NSFileManager, NSFileModificationDate

        NSFileManager.defaultManager().setAttributes_ofItemAtPath_error_(
            {NSFileCreationDate: NSDate.dateWithTimeIntervalSince1970_(t)}, str(path), None)
        _ = NSFileModificationDate
    except Exception:
        pass


class Stream:
    """One source on file: a content filter and its stream, cut into pieces."""

    def __init__(self, recorder: "Recorder", name: str, make: Callable[[object], tuple]):
        self.recorder, self.name, self.make = recorder, name, make
        self.folder = recorder.screen / name
        self.sc = None
        self.piece: Piece | None = None
        self.pieces: list[Piece] = []
        self.live = False
        self.error = ""
        self.tries = 0
        self.ended = False

    def _new_piece(self, t: float) -> Piece:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{self.name}_{stamp(t)}.mov"
        n = 2
        while path.exists():
            path = self.folder / f"{self.name}_{stamp(t)}-{n}.mov"
            n += 1
        piece = Piece(self, path)
        self.pieces.append(piece)
        return piece

    def start(self, content) -> None:
        import CoreMedia
        import ScreenCaptureKit as SCK

        content_filter, width, height, source = self.make(content)
        config_ = SCK.SCStreamConfiguration.alloc().init()
        config_.setWidth_(even(width))
        config_.setHeight_(even(height))
        if source is not None:
            config_.setSourceRect_(source)
        config_.setMinimumFrameInterval_(CoreMedia.CMTimeMake(1, FPS))
        config_.setShowsCursor_(True)
        config_.setQueueDepth_(6)
        self.sc = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(content_filter, config_, None)
        piece = self._new_piece(time.time())
        ok, error = self.sc.addRecordingOutput_error_(piece.output, None)
        if not ok:
            raise RuntimeError(f"the recording output was refused: {error}")
        (start_error,) = _wait(self.sc.startCaptureWithCompletionHandler_, f"{self.name} start")
        if start_error is not None:
            raise PermissionError(f"{self.name} would not start: {start_error}")
        self.piece, self.live, self.error = piece, True, ""

    def rotate(self) -> None:
        """A new piece without a gap: the next file is added before the last one is let go."""
        if self.sc is None or self.piece is None or not self.live:
            return
        old, new = self.piece, self._new_piece(time.time())
        ok, _ = self.sc.addRecordingOutput_error_(new.output, None)
        if ok:
            self.sc.removeRecordingOutput_error_(old.output, None)
        else:   # one output at a time on this macOS: the smallest gap there is
            self.sc.removeRecordingOutput_error_(old.output, None)
            old.done.wait(5)
            ok, error = self.sc.addRecordingOutput_error_(new.output, None)
            if not ok:
                self.died(f"the next piece was refused: {error}")
                return
        self.piece = new

    def died(self, error: str) -> None:
        self.live, self.error = False, error
        self.recorder.changed()

    def stop(self) -> None:
        self.ended = True
        if self.sc is not None:
            try:
                _wait(self.sc.stopCaptureWithCompletionHandler_, f"{self.name} stop", timeout=10)
            except TimeoutError:
                pass
        for piece in self.pieces:
            piece.done.wait(10)
            if piece.first_frame is not None:
                set_created(piece.path, piece.first_frame)
        self.sc, self.live = None, False


class Recorder:
    """Every stream for one roll, the window watcher, the 15-minute cut and the status file."""

    def __init__(self, day: Path, *, segment_seconds: int = SEGMENT_SECONDS, audio: bool = True):
        self.day = day
        self.screen = day / "screen"
        self.screen.mkdir(parents=True, exist_ok=True)
        self.segment_seconds = segment_seconds
        self.streams: dict[str, Stream] = {}
        self.retired: list[Stream] = []    # windows closed, main window replaced: their files still count
        self.window_streams: dict[int, str] = {}
        self.main_id: int | None = None
        self.problems: list[str] = []
        self.audio = None
        self.want_audio = audio
        self.audio_error = ""
        self.ready = False
        self.stopping = threading.Event()
        self._lock = threading.Lock()
        self.started = time.time()

    # bookkeeping
    def manifest(self, path: Path, t: float) -> None:
        row = {"file": str(path.relative_to(self.screen)), "first_frame": local_iso(t)}
        with self._lock, (self.screen / "screen.jsonl").open("a") as out:
            out.write(json.dumps(row) + "\n")
        self.changed()

    def screen_files(self) -> int:
        return sum(1 for s in [*self.streams.values(), *self.retired] for p in s.pieces if p.first_frame is not None)

    def retire(self, name: str, *, wait: bool = False) -> None:
        stream = self.streams.pop(name, None)
        if stream is None:
            return
        self.retired.append(stream)
        if wait:
            stream.stop()
        else:
            threading.Thread(target=stream.stop, daemon=True).start()

    def changed(self) -> None:
        files = self.screen_files()
        audio_files = len(self.audio.segmenter.files) if self.audio is not None else 0
        state = {"pid": os.getpid(), "day": str(self.day), "started": local_iso(self.started), "ready": self.ready,
                 "audio_live": self.audio is not None and not self.audio_error, "audio_error": self.audio_error,
                 "streams": {n: {"live": s.live, "error": s.error,
                                 "file": str(s.piece.path) if s.piece else None} for n, s in self.streams.items()},
                 "files": files + audio_files, "problems": list(self.problems)}
        path = Path(config.STATE_DIR) / STATUS
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(path)

    # the sources
    def _window_maker(self, window_id: int):
        def make(content):
            import ScreenCaptureKit as SCK

            window = next((w for w in content.windows() if w.windowID() == window_id), None)
            if window is None:
                raise LookupError(f"window {window_id} is gone")
            content_filter = SCK.SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)
            scale = content_filter.pointPixelScale()
            f = window.frame()
            return content_filter, f.size.width * scale, f.size.height * scale, None
        return make

    def _titled_maker(self, title: str):
        def make(content):
            window = next((w for w in content.windows() if (w.title() or "") == title and w.isOnScreen()), None)
            if window is None:
                raise LookupError(f"the {title} panel is not on screen")
            return self._window_maker(window.windowID())(content)
        return make

    def _display_maker(self, pick: Callable):
        def make(content):
            import ScreenCaptureKit as SCK

            display = pick(content)
            if display is None:
                raise LookupError("that display is not connected")
            content_filter = SCK.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display, [])
            scale = content_filter.pointPixelScale()
            return content_filter, display.width() * scale, display.height() * scale, None
        return make

    def _logic_all_maker(self, content):
        import ScreenCaptureKit as SCK

        windows = logic_windows(content.windows())
        if not windows:
            raise LookupError("Logic has no window")
        f = windows[0].frame()
        cx, cy = f.origin.x + f.size.width / 2, f.origin.y + f.size.height / 2
        display = next((d for d in content.displays()
                        if d.frame().origin.x <= cx < d.frame().origin.x + d.frame().size.width
                        and d.frame().origin.y <= cy < d.frame().origin.y + d.frame().size.height), None)
        if display is None:
            raise LookupError("Logic's display was not found")
        apps = [a for a in content.applications() if a.bundleIdentifier() == LOGIC
                or a.applicationName() == "MarcoHalo"]
        content_filter = SCK.SCContentFilter.alloc().initWithDisplay_includingApplications_exceptingWindows_(
            display, apps, [])
        scale = content_filter.pointPixelScale()
        return content_filter, display.width() * scale, display.height() * scale, None

    def _start(self, name: str, make, content, *, required: bool) -> None:
        stream = self.streams.get(name) or Stream(self, name, make)
        self.streams[name] = stream
        try:
            stream.start(content)
        except Exception as exc:
            stream.live, stream.error = False, f"{type(exc).__name__}: {exc}"[:200]
            if not required:
                del self.streams[name]
        self.changed()

    def start(self) -> None:
        if self.want_audio:
            try:
                from hiremarco.film import FilmRecorder

                self.audio = FilmRecorder(folder=self.day / "audio" / "apollo")
                self.audio.start()
            except Exception as exc:
                self.audio_error = f"{type(exc).__name__}: {exc}"[:200]
        content = shareable()
        tv = lambda c: next((d for d in c.displays() if not builtin(d)), None)          # noqa: E731
        mac = lambda c: next((d for d in c.displays() if builtin(d)), None)            # noqa: E731
        self._start("tv", self._display_maker(tv), content, required=True)
        self._start("macbook", self._display_maker(mac), content, required=True)
        self._start("live-trace", self._titled_maker(TRACE_TITLE), content, required=True)
        self._start("terminal", self._titled_maker(TERMINAL_TITLE), content, required=True)
        self._follow_logic(content)
        deadline = time.time() + SETTLE_S   # a panel the crew just opened takes a moment to reach the screen
        while not all(s.live for s in self.streams.values()) and time.time() < deadline:
            time.sleep(1)
            content = shareable()
            for stream in self.streams.values():
                if not stream.live:
                    try:
                        stream.start(content)
                    except Exception as exc:
                        stream.error = f"{type(exc).__name__}: {exc}"[:200]
            self.changed()
        self.ready = all(s.live for s in self.streams.values()) and (not self.want_audio or not self.audio_error)
        self.changed()

    def _follow_logic(self, content) -> None:
        """Logic's main window, the safety copy, and one stream per other window: started when it appears,
        ended when it closes."""
        windows = logic_windows(content.windows())
        main_id, names = plan_logic(windows, self.main_id, self.window_streams, time.time())
        if main_id != self.main_id:
            for name in ("logic-main", "logic-all"):
                self.retire(name)
            self.main_id = main_id
            if main_id is not None:
                self._start("logic-main", self._window_maker(main_id), content, required=True)
                self._start("logic-all", self._logic_all_maker, content, required=True)
        for wid, name in list(self.window_streams.items()):
            if wid not in names:
                self.retire(name)
                del self.window_streams[wid]
                self.changed()
        for wid, name in names.items():
            if wid not in self.window_streams:
                self.window_streams[wid] = name
                self._start(name, self._window_maker(wid), content, required=False)

    def _revive(self, content) -> None:
        for name, stream in list(self.streams.items()):
            if stream.live or stream.ended:
                continue
            if stream.tries >= RETRIES:
                line = f"The {name.replace('-', ' ')} recording stopped and I couldn't restart it."
                if line not in self.problems:
                    self.problems.append(line)
                    self.changed()
                continue
            stream.tries += 1
            try:
                if stream.sc is not None:
                    try:
                        _wait(stream.sc.stopCaptureWithCompletionHandler_, "old stream stop", timeout=5)
                    except Exception:
                        pass
                stream.start(content)
            except Exception as exc:
                stream.error = f"{type(exc).__name__}: {exc}"[:200]
            self.changed()

    def run(self) -> None:
        next_cut = self.started + self.segment_seconds
        while not self.stopping.is_set():
            self.stopping.wait(WATCH_S)
            if self.stopping.is_set():
                break
            try:
                content = shareable()
                self._follow_logic(content)
                self._revive(content)
            except Exception as exc:
                print(f"screenrec: watch: {type(exc).__name__}: {exc}", flush=True)
            if self.audio is not None and self.audio.dropped and "audio overflow" not in self.audio_error:
                self.audio_error = f"audio overflow x{self.audio.dropped}"
            if time.time() >= next_cut:
                next_cut += self.segment_seconds
                for stream in list(self.streams.values()):
                    try:
                        stream.rotate()
                    except Exception as exc:
                        stream.died(f"rotate: {type(exc).__name__}: {exc}"[:200])
                self.changed()

    def stop(self) -> None:
        self.stopping.set()
        threads = [threading.Thread(target=s.stop, daemon=True) for s in [*self.streams.values(), *self.retired]
                   if not s.ended]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        if self.audio is not None:
            try:
                self.audio.stop()
            except Exception as exc:
                self.audio_error = f"{type(exc).__name__}: {exc}"[:200]
        self.ready = False
        self.changed()


def no_dock_tile() -> None:
    """A Cocoa app session without a Dock tile: ScreenCaptureKit needs the window server, the film doesn't need a
    Python rocket in the Dock."""
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def main(day: Path) -> int:
    no_dock_tile()
    awake = subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
    recorder = Recorder(day)

    def end(signum, frame):
        recorder.stopping.set()

    signal.signal(signal.SIGINT, end)
    signal.signal(signal.SIGTERM, end)
    try:
        recorder.start()
        print(f"screenrec: rolling into {day}: " + ", ".join(
            f"{n} {'live' if s.live else 'OFF ' + s.error}" for n, s in recorder.streams.items())
              + (f"; audio {'OFF ' + recorder.audio_error if recorder.audio_error else 'live'}"), flush=True)
        recorder.run()
    finally:
        recorder.stop()
        awake.terminate()
        print(f"screenrec: stopped, {recorder.screen_files()} screen files", flush=True)
    return 0

"""The smooth live view: Logic's window as real video over WebRTC.

Apple's ScreenCaptureKit records Logic's main window only, at up to 30
frames a second; aiortc encodes it to H.264 and sends it to the phone's
browser over WebRTC, under a second behind. The phone's page posts its offer
to ``/offer`` with the same token as the picture stream, and falls back to
that stream when WebRTC cannot connect. On the home network the two connect
directly; away from home WebRTC needs a relay (TURN), which is not set up.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

import numpy as np

FPS = 30
BITRATE = 4_000_000  # sharp enough for a session's small text on the local network
MAX_BITRATE = 8_000_000


def tune_h264() -> None:
    """aiortc's H.264 limits are sized for a webcam (1 to 3 Mbps); a session window needs more."""
    from aiortc.codecs import h264

    h264.DEFAULT_BITRATE, h264.MAX_BITRATE = BITRATE, MAX_BITRATE


def even(n: float) -> int:
    return max(2, int(n) // 2 * 2)


def scaled(width: float, height: float, max_width: int) -> tuple[int, int]:
    """The capture size: the window's pixels, no wider than ``max_width``, both sides even for the encoder."""
    if width <= max_width:
        return even(width), even(height)
    return even(max_width), even(height * max_width / width)


def bgra_from(pixel_buffer) -> np.ndarray | None:
    """One CVPixelBuffer (32BGRA) as an H x W x 4 array, copied out before the buffer goes back."""
    import Quartz

    Quartz.CVPixelBufferLockBaseAddress(pixel_buffer, Quartz.kCVPixelBufferLock_ReadOnly)
    try:
        width = Quartz.CVPixelBufferGetWidth(pixel_buffer)
        height = Quartz.CVPixelBufferGetHeight(pixel_buffer)
        row = Quartz.CVPixelBufferGetBytesPerRow(pixel_buffer)
        base = Quartz.CVPixelBufferGetBaseAddress(pixel_buffer)
        if base is None:
            return None
        data = np.frombuffer(base.as_buffer(row * height), dtype=np.uint8).reshape(height, row // 4, 4)
        return data[:, :width, :].copy()
    finally:
        Quartz.CVPixelBufferUnlockBaseAddress(pixel_buffer, Quartz.kCVPixelBufferLock_ReadOnly)


class WindowCapture:
    """ScreenCaptureKit on one window. ``latest`` is the newest frame; the window itself picks which one."""

    def __init__(self, window_id: int, *, max_width: int = 1600, fps: int = FPS):
        self.window_id = window_id
        self.max_width = max_width
        self.fps = fps
        self.latest: np.ndarray | None = None
        self.frames = 0
        self.error = ""
        self._stream = None
        self._output = None
        self._lock = threading.Lock()

    def _wait(self, start: Callable[[Callable], None], what: str, timeout: float = 10.0):
        done, box = threading.Event(), {}

        def handler(*result):
            box["result"] = result
            done.set()

        start(handler)
        if not done.wait(timeout):
            raise TimeoutError(f"{what} did not answer in {timeout:.0f} s")
        return box["result"]

    def start(self) -> None:
        import CoreMedia
        import objc
        import ScreenCaptureKit as SCK
        from AppKit import NSApplication
        from Foundation import NSObject

        NSApplication.sharedApplication()  # ScreenCaptureKit needs the window server session a Cocoa app opens
        content, error = self._wait(SCK.SCShareableContent.getShareableContentWithCompletionHandler_,
                                    "the window list")
        if error is not None or content is None:
            raise PermissionError(f"ScreenCaptureKit refused the window list: {error}")
        window = next((w for w in content.windows() if w.windowID() == self.window_id), None)
        if window is None:
            raise LookupError(f"window {self.window_id} is not in ScreenCaptureKit's list")

        content_filter = SCK.SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)
        frame = window.frame()  # in points; the capture is asked for in pixels
        scale = content_filter.pointPixelScale() if hasattr(content_filter, "pointPixelScale") else 2.0
        width, height = scaled(frame.size.width * scale, frame.size.height * scale, self.max_width)
        config = SCK.SCStreamConfiguration.alloc().init()
        config.setWidth_(width)
        config.setHeight_(height)
        config.setMinimumFrameInterval_(CoreMedia.CMTimeMake(1, self.fps))
        config.setPixelFormat_(1111970369)  # kCVPixelFormatType_32BGRA
        config.setShowsCursor_(True)
        config.setQueueDepth_(5)

        capture = self

        class Output(NSObject, protocols=[objc.protocolNamed("SCStreamOutput")]):
            def stream_didOutputSampleBuffer_ofType_(self, stream, sample, kind):
                # an exception here would end the whole process from inside ScreenCaptureKit's queue
                try:
                    if kind != SCK.SCStreamOutputTypeScreen:
                        return
                    pixels = CoreMedia.CMSampleBufferGetImageBuffer(sample)
                    if not pixels:  # an idle frame: the window did not change
                        return
                    if hasattr(pixels, "pointerAsInteger"):
                        # CoreMedia hands back a bare pointer; Core Video's functions take the object
                        pixels = objc.objc_object(c_void_p=pixels.pointerAsInteger)
                    image = bgra_from(pixels)
                    if image is not None:
                        with capture._lock:
                            capture.latest = image
                            capture.frames += 1
                except Exception as exc:
                    capture.error = f"{type(exc).__name__}: {exc}"[:200]

        self._output = Output.alloc().init()
        self._stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(content_filter, config, None)
        ok, add_error = self._stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self._output, SCK.SCStreamOutputTypeScreen, None, None)
        if not ok:
            raise RuntimeError(f"ScreenCaptureKit would not take the output: {add_error}")
        (start_error,) = self._wait(self._stream.startCaptureWithCompletionHandler_, "the capture start")
        if start_error is not None:
            raise PermissionError(f"ScreenCaptureKit would not start: {start_error}")

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._wait(self._stream.stopCaptureWithCompletionHandler_, "the capture stop", timeout=5)
            except TimeoutError:
                pass
            self._stream = None


def window_track(source: Callable[[], np.ndarray | None]):
    """An aiortc video track that sends the newest frame at 30 frames a second, repeating it when nothing moved."""
    import av
    from aiortc import VideoStreamTrack

    class WindowTrack(VideoStreamTrack):
        def __init__(self):
            super().__init__()
            self.blank = np.zeros((720, 1280, 4), dtype=np.uint8)

        async def recv(self):
            pts, time_base = await self.next_timestamp()
            image = source()
            frame = av.VideoFrame.from_ndarray(self.blank if image is None else image, format="bgra")
            frame.pts, frame.time_base = pts, time_base
            return frame

    return WindowTrack()


def prefer_h264(pc) -> None:
    """H.264 first: the phone decodes it in hardware, and its bitrate is the one tuned above."""
    from aiortc import RTCRtpSender

    codecs = RTCRtpSender.getCapabilities("video").codecs
    h264 = [c for c in codecs if c.mimeType == "video/H264"]
    rest = [c for c in codecs if c.mimeType != "video/H264"]
    for transceiver in pc.getTransceivers():
        if transceiver.kind == "video" and h264:
            transceiver.setCodecPreferences(h264 + rest)


class Peers:
    """The open WebRTC connections, each closed when its phone goes away; the capture runs while any is open."""

    def __init__(self, source: Callable[[], np.ndarray | None], *, on_first: Callable[[], None] = lambda: None,
                 on_last: Callable[[], None] = lambda: None):
        self.source = source
        self.on_first = on_first
        self.on_last = on_last
        self.open: set = set()

    async def answer(self, offer: dict) -> dict:
        from aiortc import RTCPeerConnection, RTCSessionDescription

        if not self.open:
            await asyncio.to_thread(self.on_first)
        pc = RTCPeerConnection()
        self.open.add(pc)

        @pc.on("connectionstatechange")
        async def changed():
            if pc.connectionState in ("failed", "closed", "disconnected"):
                await self.close(pc)

        pc.addTrack(window_track(self.source))
        prefer_h264(pc)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type=offer["type"]))
        await pc.setLocalDescription(await pc.createAnswer())
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    async def close(self, pc) -> None:
        if pc in self.open:
            self.open.discard(pc)
            await pc.close()
            if not self.open:
                await asyncio.to_thread(self.on_last)

    async def close_all(self) -> None:
        for pc in list(self.open):
            await self.close(pc)


class LogicVideo:
    """Logic's main window, captured while a phone is watching: started by the first peer, stopped by the last."""

    def __init__(self, *, max_width: int = 1600, find_window: Callable[[], int | None] | None = None,
                 capture: Callable[..., WindowCapture] = WindowCapture):
        self.max_width = max_width
        self.find_window = find_window
        self.make_capture = capture
        self.capture: WindowCapture | None = None

    def start(self) -> None:
        from hiremarco.studio.show import NoLogicWindow, logic_window_id

        window = (self.find_window or logic_window_id)()
        if not window:
            raise NoLogicWindow("Logic Pro has no window on screen")
        capture = self.make_capture(window, max_width=self.max_width)
        capture.start()
        self.capture = capture

    def stop(self) -> None:
        if self.capture is not None:
            self.capture.stop()
            self.capture = None

    def latest(self) -> np.ndarray | None:
        return self.capture.latest if self.capture else None

    def probe(self, seconds: float = 1.5) -> str:
        """Start, count the frames for a moment, stop: one line saying whether video works on this Mac."""
        import time

        try:
            self.start()
        except Exception as exc:
            return f"video off: {type(exc).__name__}: {exc}"[:240]
        time.sleep(seconds)
        frames, image = self.capture.frames, self.capture.latest
        self.stop()
        if image is None:
            return "video off: the capture started but sent no frames (move a window and try again)"
        height, width = image.shape[:2]
        return f"video on: {width}x{height}, {frames} frames in {seconds:.1f} s"

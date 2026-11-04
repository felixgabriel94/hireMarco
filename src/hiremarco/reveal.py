"""SAM 3.1 in motion, both ways (Owner 2026-11-04, for the film).

Out: the "what SAM sees" picture as a short MP4 for the edit: the photo alone, then each find outlined and numbered
one after another, then the whole picture held. Dress me and the 6176 each write one beside their PNG. A clip that
can't be written is left out and logged; the WhatsApp replies never wait on it or fail for it.

In: a WhatsApp video becomes one photo, its sharpest frame, because SAM reads still images. The frames are read with
PyAV (already a dependency), sampled across the clip, and scored by the variance of a Laplacian on a small grey copy:
the frame with the most fine edge is the one held still.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
from PIL import Image

FPS = 30
FIRST_S = 1.0    # the photo alone, before SAM's first find
STEP_S = 0.45    # each find stays this long before the next comes on
FADE_S = 0.18    # and comes on over this long
LAST_S = 3.0     # the whole picture, held
CODECS = ("libx264", "h264", "mpeg4")
SAMPLES = 40     # frames scored across a video, at most


def _even(image: Image.Image) -> Image.Image:
    w, h = image.size
    return image if not (w % 2 or h % 2) else image.crop((0, 0, w - w % 2, h - h % 2))


def timeline(states: Sequence[Image.Image], fps: int = FPS) -> list[Image.Image]:
    """Every frame of the clip: the first state held, each next one faded in and held, the last held long."""
    states = [_even(s.convert("RGB")) for s in states]
    size = states[0].size
    states = [s if s.size == size else s.resize(size) for s in states]
    frames = [states[0]] * max(1, round(FIRST_S * fps))
    fade, hold = max(1, round(FADE_S * fps)), max(1, round((STEP_S - FADE_S) * fps))
    for before, after in zip(states, states[1:]):
        frames += [Image.blend(before, after, (i + 1) / fade) for i in range(fade)]
        frames += [after] * hold
    frames += [states[-1]] * max(1, round((LAST_S - STEP_S + FADE_S) * fps))
    return frames


def write_clip(states: Sequence[Image.Image], path: Path, fps: int = FPS) -> Path:
    """The states as an H.264 MP4 at ``path``."""
    import av

    frames = timeline(states, fps)
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w") as out:
        stream = None
        for codec in CODECS:
            try:
                stream = out.add_stream(codec, rate=fps)
                break
            except Exception:  # this build of FFmpeg lacks it; the next one will do
                continue
        if stream is None:
            raise RuntimeError("no video encoder in this PyAV build")
        stream.width, stream.height = frames[0].size
        stream.pix_fmt = "yuv420p"
        if stream.codec_context.name == "libx264":
            stream.options = {"crf": "18", "preset": "medium"}
        for image in frames:
            for packet in stream.encode(av.VideoFrame.from_image(image)):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    return path


def try_clip(states: Sequence[Image.Image], path: Path, log: Callable[[str], object] = print) -> Path | None:
    try:
        return write_clip(states, path)
    except Exception as exc:  # never in the way of the replies
        log(f"reveal clip not written: {type(exc).__name__}: {str(exc)[-160:]}")
        return None


def sharpness(image: Image.Image) -> float:
    grey = np.asarray(image.convert("L").resize((320, max(1, round(320 * image.height / image.width)))), dtype=float)
    lap = (-4 * grey[1:-1, 1:-1] + grey[:-2, 1:-1] + grey[2:, 1:-1] + grey[1:-1, :-2] + grey[1:-1, 2:])
    return float(lap.var())


def _upright(image: Image.Image, rotation: float) -> Image.Image:
    turn = round(rotation or 0) % 360
    return image.rotate(turn, expand=True) if turn in (90, 180, 270) else image


def sharpest_frame(video: bytes, samples: int = SAMPLES) -> bytes:
    """The sharpest frame of a video, as JPEG bytes. Raises ValueError when no frame can be read."""
    import av

    try:
        with av.open(io.BytesIO(video)) as clip:
            stream = clip.streams.video[0]
            total = stream.frames or 0
            every = max(1, total // samples) if total else 4
            best, best_score = None, -1.0
            for i, frame in enumerate(clip.decode(stream)):
                if i % every:
                    continue
                image = _upright(frame.to_image(), getattr(frame, "rotation", 0))
                score = sharpness(image)
                if score > best_score:
                    best, best_score = image, score
    except (av.error.FFmpegError, IndexError) as exc:
        raise ValueError(f"the video could not be read: {type(exc).__name__}") from exc
    if best is None:
        raise ValueError("the video has no frame to read")
    out = io.BytesIO()
    best.convert("RGB").save(out, "JPEG", quality=95)
    return out.getvalue()

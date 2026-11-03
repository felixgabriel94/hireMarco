#!/usr/bin/env python3
"""Marco's assistant editor: line up a shoot for Final Cut Pro.

Reads every media file under a shoot folder (one subfolder per device),
places each clip on one clock, locks clips to the frame by audio, and writes
an FCPXML file that Final Cut imports with File > Import > XML.

Media is never copied, moved or changed. Outputs go to --out only.

Usage:
  uv run python scripts/assistant_editor.py SHOOT_DIR --out OUT_DIR [--anchor DEVICE]
         [--events events.jsonl] [--search 300] [--tz America/New_York]
         [--name "Day 1"] [--transcribe]

Needs ffprobe and ffmpeg on PATH, and numpy.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import numpy as np

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".mxf", ".mts", ".avi"}
AUDIO_EXT = {".wav", ".bwf", ".aif", ".aiff", ".m4a", ".mp3", ".caf", ".flac"}
SR = 8000  # analysis sample rate for sync
CHUNK_S = 60.0  # seconds of a clip used for each sync probe
MIN_Z = 12.0  # correlation peak z-score each agreeing probe needs

# ---------------------------------------------------------------- model


@dataclass
class Clip:
    path: Path
    device: str
    duration: float
    has_video: bool
    has_audio: bool
    fps: Fraction | None = None  # frames per second
    width: int = 0
    height: int = 0
    audio_rate: int = 48000
    audio_channels: int = 2
    tc_seconds: float = 0.0  # media start time (embedded timecode) in seconds
    tc_samples: int = 0  # broadcast WAV time reference, in samples
    tc_string: str = ""
    drop_frame: bool = False
    camera: str = ""
    audio_lead: float = 0.0  # seconds the audio stream starts after the video stream in the file
    raw_start: float | None = None  # epoch seconds from the device clock
    raw_source: str = ""
    start: float | None = None  # epoch seconds on the master clock
    method: str = ""
    z: float = 0.0
    matched_to: str = ""
    transcript: str = ""
    asset_id: str = ""

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def end(self) -> float:
        return (self.start or 0.0) + self.duration


# ---------------------------------------------------------------- probing


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def parse_time_tag(value: str, local_tz: ZoneInfo, assume_local: bool = False) -> float | None:
    v = value.strip()
    if not v:
        return None
    v = v.replace("Z", "+00:00")
    # 2026-11-03T10:04:05-0500 -> -05:00
    m = re.match(r"^(.*[T ]\d\d:\d\d:\d\d(?:\.\d+)?)([+-]\d\d)(\d\d)$", v)
    if m:
        v = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    try:
        t = dt.datetime.fromisoformat(v)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=local_tz if assume_local else dt.timezone.utc)
    return t.timestamp()


def tc_to_seconds(tc: str, fps: Fraction) -> tuple[float, bool]:
    drop = ";" in tc
    parts = re.split(r"[:;.]", tc)
    if len(parts) != 4:
        return 0.0, False
    h, m, s, f = (int(p) for p in parts)
    nominal = round(float(fps))
    if drop and nominal in (30, 60):
        d = 2 if nominal == 30 else 4
        total_min = 60 * h + m
        frames = (nominal * 3600 * h + nominal * 60 * m + nominal * s + f) - d * (total_min - total_min // 10)
    else:
        frames = (nominal * 3600 * h + nominal * 60 * m + nominal * s + f)
    # frames play at the real rate (e.g. 30000/1001)
    return float(Fraction(frames) / fps), drop


def probe(path: Path, device: str, local_tz: ZoneInfo) -> Clip | None:
    try:
        info = json.loads(run([
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path)]))
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return None
    streams = info.get("streams", [])
    fmt = info.get("format", {})
    ftags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not v and not a:
        return None
    try:
        duration = float(fmt.get("duration") or (v or a).get("duration"))
    except (TypeError, ValueError):
        return None
    c = Clip(path=path, device=device, duration=duration,
             has_video=v is not None, has_audio=a is not None)
    if v:
        cands = []
        for key in ("r_frame_rate", "avg_frame_rate"):
            try:
                f = Fraction(v.get(key) or "0/1")
                if f > 0:
                    cands.append(f)
            except (ValueError, ZeroDivisionError):
                pass
        try:  # counted frames over length: right when avg_frame_rate is skewed by a short last frame
            nf = int(v.get("nb_frames") or 0)
            vd = float(v.get("duration") or duration)
            if nf > 0 and vd > 0:
                cands.insert(0, Fraction(nf / vd).limit_denominator(100000))
        except (TypeError, ValueError):
            pass
        fr = next((k for k in cands if snap_fps(k, strict=True)), cands[0] if cands else Fraction(30))
        c.fps = snap_fps(fr)  # variable-rate screen recordings land on the nearest standard rate
        c.width, c.height = int(v.get("width") or 0), int(v.get("height") or 0)
    if a:
        c.audio_rate = int(a.get("sample_rate") or 48000)
        try:
            c.audio_lead = float(a.get("start_time") or 0.0) - (float(v.get("start_time") or 0.0) if v else 0.0)
        except (TypeError, ValueError):
            c.audio_lead = 0.0
        c.audio_channels = int(a.get("channels") or 2)
    # timecode: stream tags (tmcd or video) or format tags
    tc = ftags.get("timecode")
    for s in streams:
        st = {k.lower(): val for k, val in (s.get("tags") or {}).items()}
        tc = tc or st.get("timecode")
    if not v and ftags.get("time_reference", "").isdigit():
        c.tc_samples = int(ftags["time_reference"])
    if tc and c.fps:
        c.tc_string = tc
        c.tc_seconds, c.drop_frame = tc_to_seconds(tc, c.fps)
    c.camera = " ".join(x for x in (
        ftags.get("com.apple.quicktime.make") or ftags.get("make") or "",
        ftags.get("com.apple.quicktime.model") or ftags.get("model") or "") if x).strip()
    # capture time, most trusted first
    qt = ftags.get("com.apple.quicktime.creationdate")
    if qt:
        c.raw_start, c.raw_source = parse_time_tag(qt, local_tz), "quicktime creationdate"
    # broadcast WAV: ffmpeg reports origination date as "date" and origination time as "creation_time" (HH-MM-SS)
    bdate = ftags.get("origination_date") or (ftags.get("date") if re.match(r"^\d{4}[-:]\d\d[-:]\d\d$", ftags.get("date", "")) else "")
    if c.raw_start is None and bdate and not v:
        d0 = dt.datetime.strptime(bdate.replace(":", "-"), "%Y-%m-%d").replace(tzinfo=local_tz)
        btime = ftags.get("origination_time") or ftags.get("creation_time", "")
        if c.tc_samples:
            c.raw_start = d0.timestamp() + c.tc_samples / c.audio_rate
            c.raw_source = "bwf time reference (local)"
        elif re.match(r"^\d\d[-:]\d\d[-:]\d\d$", btime):
            h, m, sec = (int(x) for x in re.split(r"[-:]", btime))
            c.raw_start = d0.timestamp() + h * 3600 + m * 60 + sec
            c.raw_source = "bwf origination (local)"
    if c.raw_start is None and ftags.get("origination_date"):
        od = ftags.get("origination_date", "").replace(":", "-")
        ot = ftags.get("origination_time", "00:00:00").replace("-", ":")
        c.raw_start = parse_time_tag(f"{od}T{ot}", local_tz, assume_local=True)
        c.raw_source = "bwf origination (local)"
    if c.raw_start is None and ftags.get("creation_time"):
        c.raw_start, c.raw_source = parse_time_tag(ftags["creation_time"], local_tz), "creation_time"
    if c.raw_start is None:
        c.raw_start = path.stat().st_mtime - duration
        c.raw_source = "file modified time minus length (weak)"
    return c


def snap_fps(fr: Fraction, strict: bool = False) -> Fraction | None:
    """Nearest standard rate within 1 %. strict: None if none is that close; else nearest standard."""
    known = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001),
             Fraction(30), Fraction(50), Fraction(60000, 1001), Fraction(60),
             Fraction(100), Fraction(120000, 1001), Fraction(120)]
    best = min(known, key=lambda k: abs(float(k) - float(fr)) / float(k))
    if abs(float(best) - float(fr)) / float(best) <= 0.01:
        return best
    return None if strict else best


# ---------------------------------------------------------------- audio


class AudioCache:
    def __init__(self, root: Path):
        self.root = root
        self.memo: dict[Path, np.ndarray] = {}
        root.mkdir(parents=True, exist_ok=True)

    def prepped(self, clip: Clip) -> np.ndarray:
        if clip.path not in self.memo:
            x = prep(self.get(clip))
            peak = np.abs(x).max() if len(x) else 0.0
            self.memo[clip.path] = (x / peak if peak > 0 else x).astype(np.float32)
        return self.memo[clip.path]

    def get(self, clip: Clip) -> np.ndarray:
        key = hashlib.sha1(f"{clip.path}|{clip.path.stat().st_size}|{clip.path.stat().st_mtime}".encode()).hexdigest()[:16]
        f = self.root / f"{key}.f32"
        if not f.exists():
            tmp = f.with_suffix(".tmp")
            with open(tmp, "wb") as out:
                subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(clip.path),
                                "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                               check=True, stdout=out)
            tmp.rename(f)
        return np.fromfile(f, dtype=np.float32)


def prep(x: np.ndarray) -> np.ndarray:
    # float32 throughout: an all-day body-mic file at 8 kHz is ~1 GB as float32, twice that as float64
    x = x.astype(np.float32, copy=False)
    x = x - np.float32(x.mean(dtype=np.float64)) if len(x) else x
    # high-pass by first difference: room tone and hum matter less
    return np.diff(x, prepend=x[:1]) if len(x) else x


def gcc_phat(sig: np.ndarray, ref: np.ndarray) -> tuple[int, float]:
    """Return (lag, z) where sig[n] ~ ref[n + lag], i.e. sig starts lag samples into ref."""
    n = len(sig) + len(ref)
    nfft = 1 << (n - 1).bit_length()
    S = np.fft.rfft(sig, nfft)
    R = np.fft.rfft(ref, nfft)
    X = np.conj(S) * R
    X /= np.abs(X) + 1e-12
    cc = np.fft.irfft(X, nfft)
    valid = cc[: max(1, len(ref) - len(sig) + 1)]  # sig fully inside ref
    a = np.abs(valid)
    i = int(np.argmax(a))
    mask = np.ones(len(a), bool)
    mask[max(0, i - SR // 50): i + SR // 50] = False  # ignore 40 ms around peak
    rest = a[mask] if mask.any() else a
    z = (a[i] - rest.mean()) / (rest.std() + 1e-12)
    return i, float(z)


# ---------------------------------------------------------------- sync


def render_window(clips: list[Clip], cache: AudioCache, t0: float, t1: float) -> np.ndarray:
    """Audio of the given placed clips between master times t0 and t1."""
    n = int(round((t1 - t0) * SR))
    out = np.zeros(n, np.float64)
    for c in clips:
        if not c.has_audio or c.start is None or c.end < t0 or c.start > t1:
            continue
        x = cache.prepped(c)
        a = int(round((c.start + c.audio_lead - t0) * SR))
        lo, hi = max(0, a), min(n, a + len(x))
        if hi > lo:
            out[lo:hi] += x[lo - a: hi - a]
    return out


def matches(seg: np.ndarray, placed: list[Clip], cache: AudioCache, t0: float, t1: float) -> list[tuple[float, float, Clip]]:
    """Correlate one probe against each placed clip on its own. Returns (audio start, z, clip) per clip.

    The reference is the clip's own sound inside [t0, t1], never zero padding: a peak measured
    against digital silence looks exceptional and is not. The lag is only valid where the
    probe lies wholly inside that sound.
    """
    out = []
    L = len(seg) / SR
    hang = 0.3 * L  # a probe may hang over either edge of the sound by 30 %: overlap stays at least 70 %
    for c in placed:
        if not c.has_audio or c.start is None:
            continue
        a0, a1 = max(t0, c.start + c.audio_lead), min(t1, c.end + c.audio_lead)
        if a1 - a0 < 0.7 * L:
            continue
        ref = render_window([c], cache, a0 - hang, a1 + hang)
        if np.abs(ref).max() < 1e-9 or len(ref) <= len(seg):
            continue
        lag, z = gcc_phat(seg, ref)
        out.append((a0 - hang + lag / SR, z, c))
    return out


def try_sync(clip: Clip, placed: list[Clip], cache: AudioCache, guess: float, search: float):
    """Find clip start on the master clock near guess. Returns (start, z, matched) or None.

    The clip is cut into up to three separate probes. A sync counts only when at least two
    probes, each with a strong peak against the SAME placed clip, land on the same start
    within 5 ms. One strong peak on its own is not trusted: chance peaks between unrelated
    recordings can score high.
    """
    x = cache.prepped(clip)
    if len(x) < SR * 2 or np.abs(x).max() < 1e-6:
        return None
    dur = len(x) / SR
    if dur >= 12.0:
        n, plen = 3, min(CHUNK_S, dur / 3)
    elif dur >= 4.0:
        n, plen = 2, dur / 2
    else:
        n, plen = 1, dur
    probes = [max(0.0, (i + 0.5) * dur / n - plen / 2) for i in range(n)]
    if dur > 3 * CHUNK_S:
        long = long_clip_probes(clip, placed, guess, dur, search)
        if long:
            probes, plen = long
    results: list[tuple[float, float, Clip]] = []  # (clip start, z, reference clip)
    for p in probes:
        seg = x[int(p * SR): int((p + plen) * SR)].astype(np.float64)
        if np.abs(seg).max() < 1e-6:
            continue
        t0 = guess + clip.audio_lead + p - search
        t1 = guess + clip.audio_lead + p + len(seg) / SR + search
        for a_start, z, ref_clip in matches(seg, placed, cache, t0, t1):
            results.append((a_start - p - clip.audio_lead, z, ref_clip))
    strong = [r for r in results if r[1] >= MIN_Z]
    best = None
    for r in strong:
        agree = [k for k in strong if k[2] is r[2] and abs(k[0] - r[0]) < 0.005]
        if len(agree) >= 2 and (best is None or len(agree) > best[2] or (len(agree) == best[2] and r[1] > best[1])):
            best = (float(np.median([k[0] for k in agree])), min(k[1] for k in agree), len(agree), r[2])
    if best is None and len(probes) == 1 and strong:
        top = max(strong, key=lambda k: k[1])
        if top[1] >= 3 * MIN_Z:
            best = (top[0], top[1], 1, top[2])  # very short clip: one probe, much stronger peak needed
    if best is None:
        return None
    return best[0], best[1], best[3].name


def long_clip_probes(clip: Clip, placed: list[Clip], guess: float, dur: float, search: float):
    """Probe positions for a long recording (an all-day body mic): only where placed clips have sound.

    Spread over a long file, three probes mostly land where nothing else was recording, so the two
    that must agree never can. Here the overlap between the clip's expected span and the placed
    sound is found, and up to three 60 s probes are spread across it (offsets into the clip).
    """
    lo, hi = guess - search, guess + dur + search
    spans = []
    for a, b in covered(placed, 0.0):
        a, b = max(a, lo), min(b, hi)
        if b - a >= 4.0:
            spans.append((a, b))
    if not spans:
        return []
    total = sum(b - a for a, b in spans)
    plen = min(CHUNK_S, max(4.0, total / 3))  # a short overlap gets three shorter probes, not one long one
    out = []
    for i in range(3):
        target = (i + 0.5) * total / 3  # the middle of the i-th third of the overlapping sound
        for a, b in spans:
            if target <= b - a:
                p = a + target - plen / 2 - guess - clip.audio_lead
                out.append(min(max(0.0, p), max(0.0, dur - plen)))
                break
            target -= b - a
    return sorted(set(round(p, 3) for p in out)), plen


def align(clips: list[Clip], anchor: str, cache: AudioCache, search: float, local_tz: ZoneInfo, log) -> dict[str, float]:
    """Place every clip on the anchor device's clock. Returns device clock offsets."""
    offsets: dict[str, float] = {anchor: 0.0}
    for c in clips:
        if c.device == anchor:
            c.start, c.method, c.z = c.raw_start, "anchor clock", 0.0
        elif "Mac clock" in c.raw_source:  # from Marco's own manifests: same clock as his recorder, to the ms
            c.start, c.method, c.z = c.raw_start, "anchor clock", 0.0
            offsets.setdefault(c.device, 0.0)
    placed = [c for c in clips if c.start is not None]
    pending = [c for c in clips if c.start is None]
    utc_shift = local_tz.utcoffset(dt.datetime.now()).total_seconds()
    # pass 1: audio sync against anything already placed, longest clips first
    progress = True
    while progress and pending:
        progress = False
        for c in sorted(list(pending), key=lambda k: -k.duration):
            if not c.has_audio:
                continue
            candidates = [offsets[c.device]] if c.device in offsets else [0.0, utc_shift, -utc_shift]
            hit = None
            for off in candidates:
                r = try_sync(c, placed, cache, c.raw_start + off, search)
                if r and r[1] >= MIN_Z:
                    hit = r
                    break
            if hit:
                c.start, c.z, c.matched_to = hit
                c.method = "audio sync"
                pending.remove(c)
                placed.append(c)
                devs = [k.start - k.raw_start for k in placed if k.device == c.device and k.method == "audio sync"]
                offsets[c.device] = float(np.median(devs))
                progress = True
                log(f"  synced {c.device}/{c.path.name}  z={c.z:.1f}  clock offset {c.start - c.raw_start:+.3f}s")
        if not progress and pending:
            progress = wide_search(pending, placed, offsets, cache, log)
    # pass 2: clips with no usable audio follow their device's clock offset
    for c in pending:
        if c.device in offsets:
            c.start, c.method = c.raw_start + offsets[c.device], "device clock offset"
        else:
            c.start, c.method = c.raw_start, "own clock only (unsynced)"
        log(f"  placed {c.device}/{c.path.name} by {c.method}")
    return offsets


def covered(placed: list[Clip], pad: float) -> list[tuple[float, float]]:
    """Time ranges where placed clips have sound, merged, padded."""
    spans = sorted((c.start - pad, c.end + pad) for c in placed if c.has_audio and c.start is not None)
    out: list[tuple[float, float]] = []
    for a, b in spans:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def coarse_scan(clip: Clip, placed: list[Clip], cache: AudioCache, win: float) -> list[tuple[float, float]]:
    """One 60 s probe from the clip's middle, slid over every window with placed sound. Returns (start, z) hits."""
    x = cache.prepped(clip).astype(np.float64)
    p = max(0.0, len(x) / SR / 2 - CHUNK_S / 2)
    seg = x[int(p * SR): int((p + CHUNK_S) * SR)]
    if len(seg) < SR * 2 or np.abs(seg).max() < 1e-6:
        return []
    hits = []
    for a, b in covered(placed, win):
        t = a
        while t < b:
            t0, t1 = t, min(b, t + 2 * win)
            for a_start, z, _ in matches(seg, placed, cache, t0, t1):
                hits.append((a_start - p - clip.audio_lead, z))
            t += 2 * win - CHUNK_S
    return sorted(hits, key=lambda h: -h[1])[:6]


def wide_search(pending: list[Clip], placed: list[Clip], offsets: dict[str, float], cache: AudioCache, log) -> bool:
    """A device whose clock is far off: find its longest clip anywhere there is placed sound.

    A coarse one-probe scan picks the few best windows; each is then confirmed by try_sync, which
    needs separate probes of the clip to agree. One strong peak on its own is not enough.
    """
    if not any(c.has_audio and c.start is not None for c in placed):
        return False
    for dev in sorted({c.device for c in pending if c.device not in offsets}):
        cands = sorted([c for c in pending if c.device == dev and c.has_audio], key=lambda k: -k.duration)
        if not cands:
            continue
        c = cands[0]
        log(f"  {dev}: clock far from the others, scanning the whole day for {c.path.name}")
        best = None
        for start, z in coarse_scan(c, placed, cache, 600.0):
            if z < MIN_Z * 0.5:
                continue
            r = try_sync(c, placed, cache, start, 2.0)
            if r and (best is None or r[1] > best[1]):
                best = r
        if best:
            c.start, c.z, c.matched_to = best
            c.method = "audio sync"
            offsets[dev] = c.start - c.raw_start
            pending.remove(c)
            placed.append(c)
            log(f"  synced {dev}/{c.path.name} by full scan  z={c.z:.1f}  clock offset {offsets[dev]:+.3f}s")
            return True
    return False


# ---------------------------------------------------------------- Marco's recording manifests


def apply_manifests(clips: list[Clip], tz: ZoneInfo, log):
    """screen.jsonl and film.jsonl (Mac clock, milliseconds) beat any file tag."""
    by_name = {c.path.name: c for c in clips}
    seen = set()
    for c in clips:
        for d in [c.path.parent, *c.path.parents][:4]:
            for mf in ("screen.jsonl", "film.jsonl", "talkback.jsonl"):
                f = d / mf
                if f in seen or not f.exists():
                    continue
                seen.add(f)
                n = 0
                for line in f.read_text(errors="replace").splitlines():
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    name = Path(str(e.get("file") or e.get("path") or "")).name
                    ts = next((e[k] for k in ("first_frame", "first_frame_at", "began", "played_at", "start", "ts") if k in e), None)
                    if name in by_name and ts:
                        t = parse_time_tag(str(ts), tz, assume_local=True)
                        if t is not None:
                            by_name[name].raw_start, by_name[name].raw_source = t, f"{mf} (Mac clock, ms)"
                            n += 1
                log(f"  {f}: exact start for {n} files")


# ---------------------------------------------------------------- count-in detector


def countin_template(sr: int = SR) -> np.ndarray:
    """Marco's Roll cue: 1 kHz beeps at 0, 0.5, 1.0 s (60 ms) and 1.5 s (250 ms, the sync mark)."""
    t = np.arange(int(2.0 * sr)) / sr
    y = np.zeros_like(t)
    for at, dur in ((0.0, 0.06), (0.5, 0.06), (1.0, 0.06), (1.5, 0.25)):
        m = (t >= at) & (t < at + dur)
        y[m] = np.sin(2 * np.pi * 1000.0 * (t[m] - at))
    return y


def find_countins(x: np.ndarray, sr: int = SR) -> list[tuple[float, float]]:
    """Seconds (onset of the long beep) where the count-in is heard, with a score, strongest first.

    Envelope matched filter: the four-beep rhythm is unique enough that speech and music do not
    mimic it; the long beep's onset is then refined on the raw 1 kHz band.
    """
    if len(x) < sr * 3:
        return []
    # 1 kHz band energy envelope at 1 ms steps
    n = len(x)
    t = np.arange(n) / sr
    band = x * np.exp(-2j * np.pi * 1000.0 * t)
    hop = sr // 1000
    frames = n // hop
    env = np.abs(band[: frames * hop].reshape(frames, hop).mean(axis=1))
    env = env / (np.median(env) + 1e-9)
    tmpl = np.zeros(2000)
    for at, dur in ((0, 60), (500, 60), (1000, 60), (1500, 250)):
        tmpl[at: at + dur] = 1.0
    tmpl -= tmpl.mean()
    score = np.correlate(env, tmpl, mode="valid")
    if not len(score):
        return []
    thresh = score.mean() + 8 * score.std()
    hits = []
    i = 0
    while i < len(score):
        if score[i] > thresh:
            j = i + int(np.argmax(score[i: i + 2000]))
            if complete_countin(env[j: j + 2000]):
                hits.append((j / 1000.0 + 1.5, float((score[j] - score.mean()) / (score.std() + 1e-9))))
            i = j + 2000
        else:
            i += 1
    return sorted(hits, key=lambda h: -h[1])


def complete_countin(e: np.ndarray) -> bool:
    """All four beats present at their spacing, the fourth long, each well above the gaps between them.

    A camera that started after the first beat, or a count buried in room sound, fails here
    rather than locking one beat off.
    """
    if len(e) < 1760:
        return False
    beats = [e[5:55].mean(), e[505:555].mean(), e[1005:1055].mean(), e[1505:1555].mean()]
    tail = e[1600:1740].mean()  # the long beat still sounding where a short one would have stopped
    gaps = np.concatenate([e[100:480], e[600:980], e[1100:1480]]).mean()
    return min(beats) > 4 * gaps and tail > 3 * gaps and tail > 0.4 * beats[3]


# ---------------------------------------------------------------- markers from Marco's log


def load_events(path: Path, local_tz: ZoneInfo) -> list[tuple[float, str, str]]:
    out = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict):
            continue
        ts = next((e[k] for k in ("ts", "time", "timestamp", "at", "t", "when") if k in e), None)
        if ts is None:
            continue
        if isinstance(ts, (int, float)):
            t = float(ts) / (1000.0 if ts > 1e11 else 1.0)
        else:
            t = parse_time_tag(str(ts), local_tz, assume_local=True)
        if t is None:
            continue
        label = next((str(e[k]) for k in ("event", "type", "kind", "step", "action", "name", "msg", "message", "text") if k in e), "event")
        model = next((str(e[k]) for k in ("model", "model_id") if k in e), "")
        detail = next((str(e[k]) for k in ("summary", "detail", "text", "msg", "message") if k in e and str(e[k]) != label), "")
        out.append((t, label[:80], (f"{model} | " if model else "") + detail[:400]))
    return sorted(out)


def load_slates(shoot: Path, tz: ZoneInfo, log) -> list[tuple[float, str, str]]:
    """Roll / Action / Cut from the recorder's slate log (crew talk, kept off the live trace)."""
    out = []
    for f in sorted(shoot.rglob("slate.jsonl")) + sorted(shoot.rglob("crew.jsonl")):
        n = 0
        for line in f.read_text(errors="replace").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(e, dict):
                continue
            kind = str(e.get("kind") or e.get("cmd") or "").strip().lower()
            ts = e.get("at") or e.get("ts")
            t = parse_time_tag(str(ts), tz, assume_local=True) if ts else None
            if kind and t is not None:
                out.append((t, kind.capitalize(), "slate"))
                n += 1
        log(f"  {f}: {n} slate marks")
    return out


# ---------------------------------------------------------------- transcripts (optional)


LANG = "en"  # set by --lang; "auto" lets whisper guess, which invents text on clips without speech

WHISPER_MODELS = [
    Path.home() / ".local/share/whisper-cpp/models/ggml-large-v3-turbo.bin",
    Path.home() / "tools/whisper.cpp/models/ggml-large-v3.bin",
]


def transcribe(clip: Clip, out: Path, log) -> str:
    """Local speech to text with whisper.cpp. Writes an .srt next to the outputs."""
    exe = shutil.which("whisper-cli")
    model = next((m for m in WHISPER_MODELS if m.exists()), None)
    if not exe or not model:
        log("  whisper-cli or model not found; skipping transcripts")
        return ""
    tdir = out / "transcripts"
    tdir.mkdir(exist_ok=True)
    stem = f"{clip.device}__{clip.path.stem}"
    txt = tdir / f"{stem}.txt"
    if txt.exists():
        return txt.read_text().strip()
    wav = tdir / f"{stem}.16k.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(clip.path), "-vn", "-ac", "1",
                    "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)
    try:
        subprocess.run([exe, "-m", str(model), "-f", str(wav), "-l", LANG, "-otxt", "-osrt",
                        "-of", str(tdir / stem), "-np"], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        log(f"  transcription failed for {clip.path.name}: {e.stderr[-300:] if e.stderr else e}")
        return ""
    finally:
        wav.unlink(missing_ok=True)
    text = " ".join(txt.read_text().split()) if txt.exists() else ""
    log(f"  transcribed {clip.device}/{clip.path.name}: {text[:60]}")
    return text


# ---------------------------------------------------------------- FCPXML


class Timebase:
    def __init__(self, fps: Fraction):
        self.fd = 1 / fps  # frame duration

    def frames(self, seconds: float, how=round) -> int:
        return int(how(seconds / float(self.fd)))

    def t(self, seconds: float, how=round) -> str:
        return rt(self.frames(seconds, how) * self.fd)


def rt(x: Fraction) -> str:
    x = Fraction(x)
    if x.denominator == 1:
        return f"{x.numerator}s"
    return f"{x.numerator}/{x.denominator}s"


def file_url(p: Path) -> str:
    return "file://" + quote(str(p.resolve()))


class Writer:
    def __init__(self, clips: list[Clip], tb_fps: Fraction, local_tz: ZoneInfo):
        self.clips = clips
        self.tb = Timebase(tb_fps)
        self.tz = local_tz
        self.root = ET.Element("fcpxml", version="1.9")
        self.res = ET.SubElement(self.root, "resources")
        self.formats: dict[tuple, str] = {}
        self.n = 0
        self.timeline_fmt = self.format_for(tb_fps, *self.common_size())
        for c in clips:
            self.add_asset(c)

    def nid(self, p: str) -> str:
        self.n += 1
        return f"{p}{self.n}"

    def common_size(self) -> tuple[int, int]:
        sizes = [(c.width, c.height) for c in self.clips if c.has_video and c.width]
        return max(set(sizes), key=sizes.count) if sizes else (1920, 1080)

    def format_for(self, fps: Fraction, w: int, h: int) -> str:
        key = (fps, w, h)
        if key not in self.formats:
            fid = self.nid("r")
            ET.SubElement(self.res, "format", id=fid, frameDuration=rt(1 / fps), width=str(w), height=str(h))
            self.formats[key] = fid
        return self.formats[key]

    def asset_start(self, c: Clip) -> Fraction:
        if c.has_video and c.fps:
            return Timebase(c.fps).frames(c.tc_seconds) * (1 / c.fps)
        return Fraction(c.tc_samples, c.audio_rate)

    def asset_duration(self, c: Clip) -> Fraction:
        if c.has_video and c.fps:
            return Timebase(c.fps).frames(c.duration, math.floor) * (1 / c.fps)
        return Fraction(int(c.duration * c.audio_rate), c.audio_rate)

    def add_asset(self, c: Clip):
        c.asset_id = self.nid("r")
        attrs = dict(id=c.asset_id, name=c.name, start=rt(self.asset_start(c)), duration=rt(self.asset_duration(c)),
                     hasVideo="1" if c.has_video else "0", hasAudio="1" if c.has_audio else "0")
        if c.has_video and c.fps:
            attrs["format"] = self.format_for(c.fps, c.width, c.height)
            attrs["videoSources"] = "1"
        if c.has_audio:
            attrs.update(audioSources="1", audioChannels=str(c.audio_channels), audioRate=str(c.audio_rate))
        a = ET.SubElement(self.res, "asset", **attrs)
        ET.SubElement(a, "media-rep", kind="original-media", src=file_url(c.path))

    def tod(self, epoch: float) -> float:
        """Seconds since local midnight: timeline timecode reads as time of day."""
        d = dt.datetime.fromtimestamp(epoch, self.tz)
        return d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6

    def clip_el(self, parent, c: Clip, offset_s: float, lane: int | None, role: str, extra_kw: str | None = None,
                note: str | None = None, max_dur: float | None = None):
        dur = c.duration if max_dur is None else min(c.duration, max_dur)
        own = parent.tag == "event"  # browser clips keep their own frame count; timeline clips use the timeline's
        dur_t = rt(self.asset_duration(c)) if own and max_dur is None else self.tb.t(dur, math.floor)
        attrs = dict(ref=c.asset_id, name=c.name, offset=self.tb.t(offset_s),
                     start=rt(self.asset_start(c)), duration=dur_t)
        if lane is not None:
            attrs["lane"] = str(lane)
        if c.has_video and c.fps:
            attrs["format"] = self.format_for(c.fps, c.width, c.height)
            attrs["tcFormat"] = "DF" if c.drop_frame else "NDF"
        if c.has_audio:
            attrs["audioRole"] = role
        if not c.has_video:
            attrs.pop("format", None)
        el = ET.SubElement(parent, "asset-clip", **attrs)
        if note:
            ET.SubElement(el, "note").text = note
        kws = [c.device] + ([extra_kw] if extra_kw else [])
        ET.SubElement(el, "keyword", start=rt(self.asset_start(c)), duration=dur_t, value=", ".join(kws))
        return el

    def clip_note(self, c: Clip) -> str:
        local = dt.datetime.fromtimestamp(c.start, self.tz).strftime("%H:%M:%S.%f")[:-3]
        bits = [f"Shot {local} ({c.method}"
                + (f", match z {c.z:.0f}" if c.method == "audio sync" else "") + ")",
                f"Clock source: {c.raw_source}"]
        if c.camera:
            bits.append(f"Camera: {c.camera}")
        if c.transcript:
            bits.append("Transcript: " + c.transcript)
        return "\n".join(bits)

    def build(self, name: str, events: list[tuple[float, str, str]], role_for: dict[str, str], gap_join: float):
        ev = ET.Element("event", name=f"{name} (Marco)")
        # every clip in the browser, with keywords and notes
        for c in sorted(self.clips, key=lambda k: k.start):
            el_parent = ev
            attrs_offset = 0.0
            el = self.clip_el(el_parent, c, attrs_offset, None, role_for.get(c.device, "dialogue"),
                              note=self.clip_note(c))
            el.attrib.pop("offset", None)
            for t, label, detail in events:
                if c.start <= t < c.end:
                    rel = float(self.asset_start(c)) + (t - c.start)
                    self.insert_marker(el, rel, label, detail, c)
        # day project: everything on one timeline, one lane per device, timecode = time of day
        t_first = min(c.start for c in self.placeable())
        t_last = max(c.end for c in self.placeable())
        day0 = self.tb.frames(self.tod(t_first), math.floor) * self.tb.fd
        total = self.tb.frames(t_last - t_first + 1, math.ceil) * self.tb.fd
        proj = ET.SubElement(ev, "project", name=f"{name} aligned, all devices")
        seq = ET.SubElement(proj, "sequence", format=self.timeline_fmt, duration=rt(total), tcStart=rt(day0),
                            tcFormat="NDF", audioLayout="stereo", audioRate="48k")
        spine = ET.SubElement(seq, "spine")
        gap = ET.SubElement(spine, "gap", name="Day", offset=rt(day0), start=rt(day0), duration=rt(total))
        lanes = self.device_lanes()
        for c in sorted(self.placeable(), key=lambda k: (lanes[k.device], k.start)):
            off = float(day0) + (c.start - t_first) + (self.tod(t_first) - float(day0))
            self.clip_el(gap, c, off, lanes[c.device], role_for.get(c.device, "dialogue"))
        for t, label, detail in events:
            if t_first <= t <= t_last:
                m = ET.SubElement(gap, "marker", start=self.tb.t(float(day0) + (t - t_first) + (self.tod(t_first) - float(day0))),
                                  duration=rt(self.tb.fd), value=label)
                if detail:
                    m.set("note", detail)
        # per setup (clips that overlap in time): a stacked-lanes project and a multicam clip
        for i, group in enumerate(self.setups(gap_join), 1):
            if len({c.device for c in group}) < 2:
                continue
            when = dt.datetime.fromtimestamp(min(c.start for c in group), self.tz).strftime("%H%M")
            self.stacked(ev, f"{name} setup {i:02d} {when}", group, role_for, events)
            self.multicam(ev, f"{name} setup {i:02d} {when} multicam", group, role_for, events)
        self.root.append(ev)

    def stacked(self, ev, title: str, group: list[Clip], role_for, events):
        t0 = min(c.start for c in group)
        t1 = max(c.end for c in group)
        tc0 = self.tb.frames(self.tod(t0), math.floor) * self.tb.fd
        lead = self.tod(t0) - float(tc0)
        total = self.tb.frames(t1 - t0 + lead, math.ceil) * self.tb.fd
        proj = ET.SubElement(ev, "project", name=title)
        seq = ET.SubElement(proj, "sequence", format=self.timeline_fmt, duration=rt(total), tcStart=rt(tc0),
                            tcFormat="NDF", audioLayout="stereo", audioRate="48k")
        gap = ET.SubElement(ET.SubElement(seq, "spine"), "gap", name="Setup", offset=rt(tc0), start=rt(tc0), duration=rt(total))
        lanes = self.device_lanes()
        for c in sorted(group, key=lambda k: (lanes[k.device], k.start)):
            weak = c.method not in ("audio sync", "anchor clock")
            lane = lanes[c.device] + (50 if weak else 0)
            el = self.clip_el(gap, c, float(tc0) + lead + (c.start - t0), lane, role_for.get(c.device, "dialogue"),
                              extra_kw="needs your eye" if weak else None)
            if weak:
                ET.SubElement(el, "marker", start=rt(self.asset_start(c)), duration=rt(self.tb.fd),
                              value=f"Needs your eye: placed by {c.method}, not by sound", completed="0")
        for t, label, detail in events:
            if t0 <= t <= t1:
                m = ET.SubElement(gap, "marker", start=self.tb.t(float(tc0) + lead + (t - t0)), duration=rt(self.tb.fd), value=label)
                if detail:
                    m.set("note", detail)

    def insert_marker(self, el, rel_s: float, label: str, detail: str, c: Clip):
        fd = (1 / c.fps) if (c.has_video and c.fps) else self.tb.fd
        frames = int(round(rel_s / float(fd)))
        m = ET.SubElement(el, "marker", start=rt(frames * fd), duration=rt(fd), value=label)
        if detail:
            m.set("note", detail)

    def device_lanes(self) -> dict[str, int]:
        devs = sorted({c.device for c in self.clips}, key=lambda d: (not any(k.has_video for k in self.clips if k.device == d), d))
        return {d: i + 1 for i, d in enumerate(devs)}

    def placeable(self) -> list[Clip]:
        return [c for c in self.clips if not c.method.startswith("clock far off")]

    def setups(self, gap_join: float) -> list[list[Clip]]:
        groups: list[list[Clip]] = []
        for c in sorted(self.placeable(), key=lambda k: k.start):
            if groups and c.start <= max(k.end for k in groups[-1]) + gap_join:
                groups[-1].append(c)
            else:
                groups.append([c])
        return groups

    def multicam(self, ev, title: str, group: list[Clip], role_for, events):
        t0 = min(c.start for c in group)
        t1 = max(c.end for c in group)
        tc0 = self.tb.frames(self.tod(t0), math.floor) * self.tb.fd
        lead = self.tod(t0) - float(tc0)  # first clip sits this far after tc0
        total = self.tb.frames(t1 - t0 + lead, math.ceil) * self.tb.fd
        mid = self.nid("r")
        media = ET.SubElement(self.res, "media", id=mid, name=title)
        mc = ET.SubElement(media, "multicam", format=self.timeline_fmt, tcStart=rt(tc0), tcFormat="NDF")
        # one angle per device; a second angle if a device's clips overlap each other
        angles: list[tuple[str, list[Clip]]] = []
        for dev in sorted({c.device for c in group}):
            rows: list[list[Clip]] = []
            for c in sorted([k for k in group if k.device == dev], key=lambda k: k.start):
                for r in rows:
                    if r[-1].end <= c.start:
                        r.append(c)
                        break
                else:
                    rows.append([c])
            for j, r in enumerate(rows):
                angles.append((dev if j == 0 else f"{dev} {j + 1}", r))
        video_angle = audio_angle = None
        for aname, row in angles:
            aid = hashlib.sha1(f"{title}|{aname}".encode()).hexdigest()[:12]
            ang = ET.SubElement(mc, "mc-angle", name=aname, angleID=aid)
            cursor = 0  # frames from tc0
            for c in row:
                pos = self.tb.frames(c.start - t0 + lead)
                if pos > cursor:
                    ET.SubElement(ang, "gap", name="Gap", offset=rt(tc0 + cursor * self.tb.fd), start="3600s",
                                  duration=rt((pos - cursor) * self.tb.fd))
                    cursor = pos
                elif pos < cursor:  # rounding overlap, trim the head by the overlap
                    pos = cursor
                dur_f = self.tb.frames(c.duration - (pos * float(self.tb.fd) - (c.start - t0 + lead)), math.floor)
                if dur_f <= 0:
                    continue
                el = self.clip_el(ang, c, float(tc0 + pos * self.tb.fd), None, role_for.get(c.device, "dialogue"))
                el.set("duration", rt(dur_f * self.tb.fd))
                cursor = pos + dur_f
            if video_angle is None and any(k.has_video for k in row):
                video_angle = aid
            if role_for.get(row[0].device) == "dialogue" and not any(k.has_video for k in row) and audio_angle is None:
                audio_angle = aid
        if video_angle is None:
            video_angle = angles and hashlib.sha1(f"{title}|{angles[0][0]}".encode()).hexdigest()[:12]
        if audio_angle is None:
            audio_angle = video_angle
        mcc = ET.SubElement(ev, "mc-clip", ref=mid, name=title, start=rt(tc0), duration=rt(total))
        if video_angle == audio_angle:
            ET.SubElement(mcc, "mc-source", angleID=video_angle, srcEnable="all")
        else:
            ET.SubElement(mcc, "mc-source", angleID=video_angle, srcEnable="video")
            ET.SubElement(mcc, "mc-source", angleID=audio_angle, srcEnable="audio")
        for t, label, detail in events:
            if t0 <= t <= t1:
                m = ET.SubElement(mcc, "marker", start=self.tb.t(float(tc0) + lead + (t - t0)), duration=rt(self.tb.fd), value=label)
                if detail:
                    m.set("note", detail)
        ET.SubElement(mcc, "keyword", start=rt(tc0), duration=rt(total), value="multicam")

    def write(self, path: Path):
        ET.indent(self.root)
        body = ET.tostring(self.root, encoding="unicode")
        path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n\n' + body + "\n")


# ---------------------------------------------------------------- main


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shoot", type=Path, help="shoot folder, one subfolder per device")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--anchor", help="device folder whose clock is trusted (default: Marco's recordings if present, else the longest)")
    ap.add_argument("--events", type=Path, help="Marco events.jsonl for markers")
    ap.add_argument("--search", type=float, default=300.0, help="seconds either side of the clock guess to search (default 300)")
    ap.add_argument("--tz", default="America/New_York")
    ap.add_argument("--name", default=None)
    ap.add_argument("--fps", default=None, help="timeline rate, e.g. 30000/1001 (default: most common camera rate)")
    ap.add_argument("--join", type=float, default=30.0, help="seconds between clips that still count as one setup")
    ap.add_argument("--transcribe", action="store_true", help="local whisper.cpp transcripts into clip notes (runs after the first FCPXML is written)")
    ap.add_argument("--lang", default="en", help="transcript language for whisper (default en; es for Spanish; auto)")
    ap.add_argument("--truth", action="append", help="device folder(s) with a network-synced clock that sets time of day (default: iphone/screen/marco folders)")
    ap.add_argument("--extra", type=Path, action="append", default=[], help="another folder to include as its own device (repeatable), e.g. Marco's screen recordings")
    args = ap.parse_args(argv)

    for tool in ("ffprobe", "ffmpeg"):
        if not shutil.which(tool):
            print(f"missing {tool} on PATH", file=sys.stderr)
            return 2
    global LANG
    LANG = args.lang
    tz = ZoneInfo(args.tz)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "log.txt", "a")

    def log(s: str):
        print(s)
        logf.write(s + "\n")
        logf.flush()

    log(f"== assistant editor {dt.datetime.now(tz).isoformat(timespec='seconds')} on {args.shoot}")
    sources: list[tuple[Path, str]] = []
    shoot = args.shoot.resolve()
    for p in sorted(shoot.rglob("*")):
        if p.is_file() and p.suffix.lower() in VIDEO_EXT | AUDIO_EXT and not p.name.startswith("._"):
            rel = p.relative_to(shoot)
            # device = top folder. Inside screen/ and audio/ each subfolder is its own stream (screen/manual,
            # audio/apollo, audio/talkback); inside a camera folder, subfolders are cards and stay one device.
            dev = rel.parts[0] if len(rel.parts) > 1 else "loose"
            if len(rel.parts) > 2 and rel.parts[0].lower() in ("screen", "audio"):
                dev = f"{rel.parts[0]}-{rel.parts[1]}"
            sources.append((p, dev))
    for extra in args.extra:
        for p in sorted(extra.resolve().rglob("*")):
            if p.is_file() and p.suffix.lower() in VIDEO_EXT | AUDIO_EXT and not p.name.startswith("._"):
                sources.append((p, extra.name))
    clips = []
    for p, dev in sources:
        c = probe(p, dev, tz)
        if c:
            clips.append(c)
        else:
            log(f"  skipped (unreadable): {p}")
    if not clips:
        log("no media found")
        return 1
    apply_manifests(clips, tz, log)
    devices = sorted({c.device for c in clips})
    log(f"found {len(clips)} clips on {len(devices)} devices: {', '.join(devices)}")
    anchor = args.anchor
    if not anchor:
        # the device with the most recorded sound: everything else syncs to it by ear
        pref = [d for d in devices if any(k in d.lower() for k in ("apollo", "booth", "audio-apollo"))
                and any(c.has_audio for c in clips if c.device == d)]
        anchor = pref[0] if pref else max(devices, key=lambda d: sum(c.duration for c in clips if c.device == d and c.has_audio))
    if anchor not in devices:
        log(f"anchor {anchor!r} not among devices")
        return 1
    log(f"anchor clock: {anchor}")
    cache = AudioCache(out / ".audio-cache")
    offsets = align(clips, anchor, cache, args.search, tz, log)
    # true time of day: shift everything so network-clock devices read their own clock
    truth = args.truth or [d for d in devices if any(k in d.lower() for k in ("iphone", "screen", "marco", "phone"))]
    diffs = [c.raw_start - c.start for c in clips if c.device in truth and c.method in ("audio sync", "anchor clock")]
    if any("Mac clock" in c.raw_source and c.start is not None for c in clips):
        diffs, truth = [], ["Marco's recordings (Mac clock)"]  # Marco's own manifests already carry true time of day
        shift = 0.0
    else:
        shift = float(np.median(diffs)) if diffs else 0.0
    if abs(shift) > 0.0005:
        for c in clips:
            if not c.method.startswith("own clock"):  # unsynced clips already read their own clock
                c.start += shift
        offsets = {d: o + shift for d, o in offsets.items()}
    locked = [c.start for c in clips if c.method in ("audio sync", "anchor clock")]
    if locked:
        mid = float(np.median(locked))
        for c in clips:
            if c.method not in ("audio sync", "anchor clock") and abs(c.start - mid) > 12 * 3600:
                c.method = "clock far off (in the browser only, not on timelines)"
                log(f"  {c.device}/{c.path.name}: camera clock far from the rest; kept out of timelines")
    log(f"time of day taken from: {', '.join(truth) if (diffs or shift == 0.0 and truth and 'Mac clock' in truth[0]) else anchor + ' (no network-clock device synced)'}; shift {shift:+.3f}s")
    events = load_events(args.events, tz) if args.events and args.events.exists() else []
    events = sorted(events + load_slates(shoot, tz, log))
    # count-ins: where each clip heard Marco's Roll cue, as a check on the sync and an extra marker
    heard: dict[str, list[float]] = {}
    for c in clips:
        if c.has_audio and c.start is not None and not c.method.startswith("clock far off"):
            for sec, score in find_countins(cache.get(c).astype(np.float64)):
                heard.setdefault(c.device, []).append(c.start + c.audio_lead + sec)
    marks = sorted(t for v in heard.values() for t in v)
    groups: list[list[float]] = []
    for t in marks:
        if groups and t - groups[-1][-1] < 1.0:
            groups[-1].append(t)
        else:
            groups.append([t])
    for g in groups:
        spread = (max(g) - min(g)) * 1000
        events.append((float(np.median(g)), "Roll cue", f"heard by {len(g)} clips, spread {spread:.0f} ms"))
        log(f"  count-in at {dt.datetime.fromtimestamp(np.median(g), tz).strftime('%H:%M:%S.%f')[:-3]} heard by {len(g)} clips, spread {spread:.0f} ms")
    events.sort()
    if args.fps:
        fps = Fraction(args.fps)
    else:
        rates = [c.fps for c in clips if c.has_video and c.fps]
        fps = max(set(rates), key=rates.count) if rates else Fraction(30000, 1001)
    role_for = {d: ("dialogue" if any(c.has_audio for c in clips if c.device == d) else "video") for d in devices}
    name = args.name or dt.datetime.fromtimestamp(min(c.start for c in clips), tz).strftime("Shoot %Y-%m-%d")
    fx = out / f"{name}.fcpxml"

    def write_fcpxml():
        w = Writer(clips, fps, tz)
        w.build(name, events, role_for, args.join)
        w.write(fx)

    write_fcpxml()
    log(f"wrote {fx} (ready to import)")
    if args.transcribe:
        for c in sorted(clips, key=lambda k: k.start):
            if c.has_audio:
                c.transcript = transcribe(c, out, log)
        write_fcpxml()
        log(f"rewrote {fx} with transcripts in clip notes")
    with open(out / "alignment.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["device", "file", "shot_at_local", "length_s", "method", "match_z", "clock_offset_s", "clock_source", "camera", "matched_with"])
        for c in sorted(clips, key=lambda k: k.start):
            wr.writerow([c.device, str(c.path), dt.datetime.fromtimestamp(c.start, tz).isoformat(timespec="milliseconds"),
                         f"{c.duration:.2f}", c.method, f"{c.z:.1f}", f"{c.start - c.raw_start:+.3f}", c.raw_source, c.camera, c.matched_to])
    synced = sum(1 for c in clips if c.method in ("audio sync", "anchor clock"))
    placed_clips = [c for c in clips if not c.method.startswith("clock far off")]
    t_a, t_b = min(c.start for c in placed_clips), max(c.end for c in placed_clips)
    n_markers = sum(1 for t, _, _ in events if t_a <= t <= t_b)
    weak = [c for c in clips if c.method.startswith(("own clock", "clock far off"))]
    summary = (f"{len(clips)} clips, {len(devices)} devices, {synced} locked by sound or anchor, "
               f"{len(clips) - synced - len(weak)} placed by device clock, {len(weak)} unsynced, {n_markers} Marco markers on the day timeline")
    log(summary)
    log("device clock offsets vs anchor: " + ", ".join(f"{d} {o:+.3f}s" for d, o in offsets.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

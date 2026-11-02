"""The print: Logic's Bounce dialog, driven by Marco, and the file read back.

A session is printed twice per mastering job (Owner 2026-11-02): the mix as it
stands, with nothing on the Stereo Out, 32-bit float, for the mastering
engineer; and the master, 24-bit, with his chain on the Stereo Out. Both are
WAVE, interleaved, the session's own sample rate, no dither (dither belongs to
a 16-bit delivery only), normalize off, offline, with the audio tail. The
dialog is mapped in ``scripts/bounce_io.applescript``; every press goes through
the gate on the ``logic`` channel. After the press this side waits for the
file to land and stop growing, then reads it back with ``soundfile``: a print
nobody read is not a print.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf

from hiremarco import gate

SCRIPT = Path(__file__).parent / "scripts" / "bounce_io.applescript"
TENANT = "owner"
SETTLE_S = 3.0        # the file's size unchanged this long means Logic has finished writing it
RATES = {44100: "44.1 kHz", 48000: "48 kHz", 88200: "88.2 kHz", 96000: "96 kHz", 176400: "176.4 kHz", 192000: "192 kHz"}


@dataclass(frozen=True)
class Spec:
    bits: str = "24-bit"             # 8-bit | 16-bit | 24-bit | 32-bit float
    file_type: str = "WAVE"          # AIFF | WAVE | CAF
    rate: str = "keep"               # the session's rate unless one of RATES' names
    fmt: str = "Interleaved"         # Split | Interleaved
    dither: str = "None"             # None only above 16-bit; a 16-bit print names a POW-r
    mode: str = "Offline"            # Automatic | Offline | Realtime
    normalize: str = "Off"
    tail: bool = True
    tempo: bool = False
    add_to_project: bool = False

    def args(self) -> list[str]:
        return [self.file_type, self.bits, self.rate, self.fmt, self.dither, self.mode, self.normalize,
                "1" if self.tail else "0", "1" if self.tempo else "0", "1" if self.add_to_project else "0"]


MIX = Spec(bits="32-bit float")      # the mix for mastering: no limiter, headroom kept, float so nothing clips
MASTER = Spec(bits="24-bit")         # the master as delivered


@dataclass
class Opened:
    requires: str
    start: str
    end: str

    @property
    def seconds(self) -> float | None:
        m = re.search(r"Time (\d+):(\d\d)", self.requires)
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None


@dataclass
class Printed:
    path: Path
    seconds: float
    rate: int
    subtype: str
    channels: int
    took_s: float


def _osascript(args: list[str]) -> str:
    done = subprocess.run(["osascript", str(SCRIPT), *args], capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-240:] or f"osascript exit {done.returncode}")
    return done.stdout


def parse_opened(report: str) -> Opened:
    fields = {"requires": "", "start": "", "end": ""}
    for line in report.splitlines():
        key, _, value = line.partition("\t")
        if key in fields:
            fields[key] = value.strip().replace("\t", " ")
    return Opened(**fields)


def print_name(song: str, purpose: str, today: str) -> str:
    """'aguacero - master 2026-11-02' (Logic adds the extension); the purpose names what the file is."""
    clean = re.sub(r"[/:\\]+", "-", song).strip() or "song"
    return f"{clean} - {purpose} {today}"


def wait_for(path: Path, *, timeout_s: float, settle_s: float = SETTLE_S, sleep=time.sleep, clock=time.monotonic) -> float:
    """Until the file exists and its size has not changed for ``settle_s``; the seconds it took."""
    started = clock()
    last_size, last_change = -1, clock()
    while clock() - started < timeout_s:
        if path.exists():
            size = path.stat().st_size
            if size != last_size:
                last_size, last_change = size, clock()
            elif size > 0 and clock() - last_change >= settle_s:
                return round(clock() - started, 1)
        sleep(0.5)
    raise TimeoutError(f"{path.name} did not land within {timeout_s:.0f} s")


class Bouncer:
    def __init__(self, *, run=_osascript, conn=None, rules_path: Path | None = None, dry_run: bool = False,
                 sleep=time.sleep):
        self.run, self.conn, self.rules_path, self.dry_run, self.sleep = run, conn, rules_path, dry_run, sleep
        self.planned: list[str] = []

    def _gated(self, run, message: str) -> str:
        if self.dry_run:
            self.planned.append(message)
            return f"dry run: {message}"
        return gate.execute_effect(self.conn or gate.connect(), run, tenant_id=TENANT,
                                   idempotency_key=f"bounce:{time.time_ns()}", capability="bounce",
                                   channel="logic", target="*", message=message, department="studio",
                                   rules_path=self.rules_path)

    def open(self, spec: Spec) -> Opened:
        report = self._gated(lambda: self.run(["open", *spec.args()]), f"open the Bounce dialog ({spec.bits} {spec.file_type})")
        return parse_opened(report) if not self.dry_run else Opened("", "", "")

    def cancel(self) -> str:
        return self._gated(lambda: self.run(["cancel"]), "cancel the Bounce dialog")

    def print(self, spec: Spec, folder: Path, name: str, *, timeout_s: float | None = None) -> Printed:
        """Open, set, save, wait, read back. ``name`` is without extension; Logic adds it."""
        folder = Path(folder).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{name}.{'wav' if spec.file_type == 'WAVE' else spec.file_type.lower()}"
        if target.exists():
            raise FileExistsError(f"{target} already exists; nothing was overwritten")
        opened = self.open(spec)
        if self.dry_run:
            return Printed(target, 0.0, 0, "", 0, 0.0)
        started = time.monotonic()
        try:
            self._gated(lambda: self.run(["save", str(folder), name]), f"bounce {name} into {folder}")
        except Exception:
            try:
                self.run(["cancel"])
            finally:
                raise
        # offline bounces run several times faster than real time; realtime ones take the song's length plus a margin
        budget = timeout_s or max(120.0, (opened.seconds or 600.0) * (2.0 if spec.mode == "Realtime" else 1.0) + 60.0)
        took = wait_for(target, timeout_s=budget, sleep=self.sleep)
        info = sf.info(target)
        return Printed(target, round(info.duration, 2), info.samplerate, info.subtype, info.channels,
                       round(time.monotonic() - started, 1))

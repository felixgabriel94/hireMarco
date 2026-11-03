"""The Apollo's monitor output, moved by Marco on the Owner's word: a slow fade, never a jump.

The monitor section of UAD Console is ``/devices/D/outputs/4`` on the Owner's Apollo Twin X
(named MONITOR, read live 2026-11-03): ``CRMonitorLevel`` is the control room level in dB,
``Mute`` its mute. Both are written over the same control service as the inserts
(``studio/console.py``).

Rules (Owner 2026-11-03): the level never goes above -40 dB, the apartment's ceiling; a
change is a fade at about 1 dB a second in small steps, never a jump, which protects the
speakers; "stop" halts a fade where it is; a failure leaves the level where it was; the
level does not move between Roll and Cut; the mute for a take is plain and immediate. A
hand on the knob (the level moved by more than a step between ticks, or the mute turned
on) ends the fade too: the room is his. Nothing here writes to the event stream: the
monitor is the room's business, not the work on Marco Live.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from hiremarco import config
from hiremarco.studio.console import Console, ConsoleError

OUTPUT = 4
NAME = "MONITOR"
LEVEL = "CRMonitorLevel"
MUTE = "Mute"
CAP_DB = -40.0          # the apartment's ceiling; refused above it
FLOOR_DB = -96.0        # Console's bottom
STEP_DB = 3.0           # "lower it" / "turn it up"
LOT_DB = 6.0            # "a lot", "much", "way"
RATE_DB_S = 1.0         # the fade's speed
TICK_S = 0.1            # one small write per tick: 0.1 dB at a time
HAND_DB = 0.75          # a read this far from the last write is a hand on the knob (room for a 1 dB engine grid)
ROLLING_FLAG = "rolling"   # present in the state dir between Roll and Cut; the recorder owns it


def path(device: int = 0) -> str:
    return f"/devices/{device}/outputs/{OUTPUT}"


def rolling() -> bool:
    return (config.STATE_DIR / ROLLING_FLAG).exists()


def _value(console: Console, prop: str):
    return console.get(f"{path(console.device)}/{prop}/value")


def check_output(console: Console) -> None:
    """The output Marco writes is the monitor and nothing else; a different Name is refused."""
    name = str(_value(console, "Name") or "")
    if name.strip().upper() != NAME:
        raise ConsoleError(f"output {OUTPUT} is {name!r}, not {NAME}; nothing written")


def level(console: Console) -> float:
    value = _value(console, LEVEL)
    try:
        return float(value)
    except (TypeError, ValueError) as bad:
        raise ConsoleError(f"the monitor level reads {value!r}, not a number") from bad


def muted(console: Console) -> bool:
    return bool(_value(console, MUTE))


def clamp(target: float) -> float:
    return min(CAP_DB, max(FLOOR_DB, float(target)))


def write_level(console: Console, db: float) -> None:
    """The one place a level is written; anything above the cap is refused here as well."""
    if db > CAP_DB + 1e-9:
        raise ConsoleError(f"{db:.1f} dB is above the cap of {CAP_DB:.0f} dB")
    console.set(path(console.device), LEVEL, round(float(db), 3))


@dataclass
class Fade:
    ended: float
    reason: str      # "arrived", "stopped", "hand", "muted", "lost"


def fade(console: Console, target: float, *, stop: threading.Event | None = None,
         sleep: Callable[[float], None] = time.sleep, rate_db_s: float = RATE_DB_S,
         tick_s: float = TICK_S) -> Fade:
    """Move the level to ``target`` (held within the cap) one small step a tick. ``stop`` halts it between steps;
    a hand on the knob or the mute coming on ends it; a write or read that fails ends it where the last write
    landed. Returns where it ended and why."""
    target = clamp(target)
    try:
        check_output(console)
        at = level(console)
    except (ConsoleError, OSError):
        return Fade(float("nan"), "lost")
    step = rate_db_s * tick_s
    reason = "arrived"
    while abs(target - at) > 1e-6:
        if stop is not None and stop.is_set():
            reason = "stopped"
            break
        nxt = target if abs(target - at) <= step else at + (step if target > at else -step)
        try:
            write_level(console, nxt)
        except (ConsoleError, OSError):
            reason = "lost"
            break
        at = nxt
        sleep(tick_s)
        try:
            if muted(console):
                reason = "muted"
                break
            read = level(console)
        except (ConsoleError, OSError):
            reason = "lost"
            break
        if abs(read - at) > HAND_DB:
            at, reason = read, "hand"
            break
    try:
        return Fade(level(console), reason)
    except (ConsoleError, OSError):
        return Fade(at, reason)


@dataclass
class Request:
    """What the Owner asked for: a step (dB, signed), a named level, or a stop."""
    kind: str                 # "step", "level", "stop"
    db: float = 0.0


_THING = r"(it|them|the (volume|speakers|monitors|music|sound|level|beat|track|song))"
_TAIL = r"( (a lot|a bit|a little|a notch|a touch|much|way|please))*[.!]*$"
_UP = rf"^((turn|bring|put|crank|take|push|pump) {_THING} up|louder|raise {_THING}|{_THING} up){_TAIL}"
_DOWN = rf"^((turn|bring|put|take) {_THING} down|lower {_THING}|quieter|softer|{_THING} down){_TAIL}"
_LEVEL = rf"^((set|put|take|bring|leave) {_THING} (to|at) |(volume|speakers|monitors|level) (to |at )?)(?P<db>-\d{{1,2}}(\.\d)?)( db)?( please)?[.!]*$"
_LOT = r"\b(a lot|much|way)\b"
_STOP = r"^(stop|stop it|stop there|hold it|hold|that's good|that's enough|enough|there|right there|good)( please)?[.!]*$"


def words(said: str, *, fading: bool = False) -> Request | None:
    """The Owner's exact words for the monitor, or None for anything else: the brain keeps the rest. The whole
    line has to be the ask, so "lower the vocal in the chorus" is not taken. ``fading``: "stop" and the like count
    only while a fade is on, so a stop meant for something else is not taken here."""
    text = " ".join(said.lower().replace("’", "'").split())
    if not text or len(text.split()) > 8:
        return None
    text = re.sub(r"^(marco|hey marco|please|can you|could you|would you|will you)[, ]+", "", text)
    if fading and re.match(_STOP, text):
        return Request("stop")
    if m := re.match(_LEVEL, text):
        return Request("level", float(m.group("db")))
    if re.match(_UP, text):
        return Request("step", LOT_DB if re.search(_LOT, text) else STEP_DB)
    if re.match(_DOWN, text):
        return Request("step", -(LOT_DB if re.search(_LOT, text) else STEP_DB))
    return None


def _db(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


class Hand:
    """One pair of hands on the monitor: at most one fade at a time, a stop for it, and the memory of a mute
    Marco set himself so that Cut gives back exactly what Roll took."""

    def __init__(self, console: Console | None = None, *, start: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep, rolling: Callable[[], bool] = rolling):
        self.console = console or Console()
        self.start = start or (lambda f: threading.Thread(target=f, daemon=True).start())
        self.sleep = sleep
        self.rolling = rolling
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.fading = False
        self.muted_by_me = False

    # the level, on his word
    def answer(self, request: Request, reply: Callable[[str], None]) -> str:
        """Carry the request out and tell him, in one short line, where the level ended. Returns the log line."""
        if request.kind == "stop":
            if not self.fading:
                return "nothing to stop"
            self.stop.set()
            return "stopping the fade"
        if self.rolling():
            reply("We're rolling. I'll leave the speakers where they are until Cut.")
            return "held: rolling"
        if self.fading:
            reply("Still moving it. Say stop, then ask again.")
            return "held: a fade is on"
        try:
            check_output(self.console)
            at = level(self.console)
        except (ConsoleError, OSError) as bad:
            reply("I can't reach Console right now, so the speakers stay where they are.")
            return f"held: {type(bad).__name__}: {str(bad)[:60]}"
        wanted = at + request.db if request.kind == "step" else request.db
        capped = wanted > CAP_DB + 1e-9
        if capped and at >= CAP_DB - 1e-9:
            reply(f"That's the top, {_db(CAP_DB)}. I won't go past it in the apartment.")
            return f"refused: at the cap {_db(at)}"
        target = clamp(wanted)
        if abs(target - at) < 1e-6:
            reply(f"It's already at {_db(at)}.")
            return f"already at {_db(at)}"
        self.stop.clear()
        self.fading = True

        def run() -> None:
            try:
                done = fade(self.console, target, stop=self.stop, sleep=self.sleep)
            finally:
                self.fading = False
            ended = done.ended
            if ended != ended:  # nan: nothing could be read
                reply("I lost Console on the way; the speakers stay where they are.")
                return
            word = "Down" if ended < at else "Up"
            if done.reason == "stopped":
                reply(f"Stopped at {_db(ended)}.")
            elif done.reason == "hand":
                reply(f"You've got it. It's at {_db(ended)}.")
            elif done.reason == "muted":
                reply(f"The speakers are muted now; the level sits at {_db(ended)}.")
            elif done.reason == "lost":
                reply(f"Console stopped answering on the way; it's at {_db(ended)}.")
            elif capped:
                reply(f"{word} to {_db(ended)}, the top for the apartment.")
            else:
                reply(f"{word} to {_db(ended)}.")

        self.start(run)
        return f"fading {_db(at)} to {_db(target)}"

    # the mute, for a take
    def mute(self) -> bool:
        """Mute the monitors for a take, remembering whether that was Marco's doing. Returns True when it was."""
        with self.lock:
            check_output(self.console)
            if muted(self.console):
                self.muted_by_me = False
                return False
            self.console.set(path(self.console.device), MUTE, True)
            self.muted_by_me = True
            return True

    def unmute(self) -> bool:
        """Give the monitors back only if Marco took them. Returns True when he did."""
        with self.lock:
            if not self.muted_by_me:
                return False
            self.console.set(path(self.console.device), MUTE, False)
            self.muted_by_me = False
            return True


_HAND: Hand | None = None


def hand() -> Hand:
    global _HAND
    if _HAND is None:
        _HAND = Hand()
    return _HAND

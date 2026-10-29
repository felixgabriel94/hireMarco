"""UAD Console, driven over the UA Mixer Engine's control service.

The engine listens on TCP 4710 and speaks one text command per message, ended
by a NUL byte: ``get <path>`` answers JSON ``{"path", "data"}``, and
``set <path>/<Property>/value <value>`` sets one property and answers the new
value, or ``{"error": ...}``. Learned live on 2026-10-29 on an Apollo Twin X:

- an insert slot is ``/devices/D/inputs/N/effects/S`` (four per channel), the
  Unison slot is ``/devices/D/inputs/N/preamps/0/effects/0``;
- writing a plug-in's name to a slot's ``EffectName`` loads it, an empty name
  unloads it, and a name Console doesn't know is refused (Status = -3);
- a plug-in's controls are ``.../parameters/P`` with ``Name``, a read-only
  ``StringValue`` (what the plug-in shows) and a writable ``NormalizedValue``
  from 0 to 1. The map from one to the other is the plug-in's own (Auto-Tune's
  Key is floor(v * 11), Retune Speed is not linear), so a value is set by
  reading back: a numeric control by bisection, a named one (a key, a scale, a
  switch) from a sweep of the whole range.

Only UAD plug-ins load here, and only on the Apollo's own DSP: a UAD-2
Satellite serves the DAW, not Console (UA help center).
"""

from __future__ import annotations

import json
import math
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass

HOST = "127.0.0.1"
PORT = 4710
SWEEP_STEPS = 200
BISECT_ROUNDS = 22

# The gentle base for printed tuning (decided 2026-10-29 from UA's and Antares' manuals): a clean start
# that leaves the tight calls to Flex Pitch.
GENTLE_TUNE = {"Retune Speed": 40.0, "Flex-Tune": 30.0, "Humanize": 15.0, "Natural Vibrato": 0.0}
AUTO_TUNE = "UAD Auto-Tune Realtime Advanced"


class ConsoleError(RuntimeError):
    pass


def tcp_send(command: str, host: str = HOST, port: int = PORT, timeout: float = 3.0) -> str:
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(command.encode() + b"\0")
        reply = b""
        try:
            while not reply.endswith(b"\0"):
                chunk = sock.recv(1 << 20)
                if not chunk:
                    break
                reply += chunk
        except socket.timeout:
            pass
    return reply.rstrip(b"\0").decode(errors="replace")


@dataclass(frozen=True)
class Slot:
    number: int  # 1 to 4 as Console shows them; 0 is the Unison slot
    name: str
    power: bool


class Console:
    def __init__(self, send: Callable[[str], str] = tcp_send, device: int = 0, settle: float = 0.05):
        self.send = send
        self.device = device
        self.settle = settle
        self._authorized: set[str] | None = None

    # the wire
    def get(self, path: str):
        answer = json.loads(self.send(f"get {path}"))
        if "error" in answer:
            raise ConsoleError(f"{path}: {answer['error']}")
        return answer["data"]

    def set(self, path: str, prop: str, value) -> object:
        text = ("true" if value else "false") if isinstance(value, bool) else value
        if isinstance(text, float):
            text = f"{text:.6f}"
        answer = json.loads(self.send(f"set {path}/{prop}/value {text}"))
        if "error" in answer:
            raise ConsoleError(f"{path} {prop}: {answer['error']}")
        return answer["data"]

    # places
    def slot_path(self, channel: int, slot: int) -> str:
        if slot == 0:
            return f"/devices/{self.device}/inputs/{channel}/preamps/0/effects/0"
        if not 1 <= slot <= 4:
            raise ConsoleError(f"Console has inserts 1 to 4 (0 is Unison), not {slot}")
        return f"/devices/{self.device}/inputs/{channel}/effects/{slot - 1}"

    def channel_name(self, channel: int) -> str:
        return self.get(f"/devices/{self.device}/inputs/{channel}/Name/value")

    def slots(self, channel: int) -> list[Slot]:
        found = []
        for number in range(5):
            props = self.get(self.slot_path(channel, number))["properties"]
            found.append(Slot(number, props["EffectName"]["value"] or "", bool(props["Power"]["value"])))
        return found

    # plug-ins
    def authorized(self) -> set[str]:
        """UAD plug-ins this Mac may run: authorized, or in a demo with days left (Console's own flags)."""
        if self._authorized is None:
            names = set()
            for key in self.get("/plugins").get("children", {}):
                props = self.get(f"/plugins/{key}")["properties"]
                flag = lambda name: props.get(name, {}).get("value")  # noqa: E731
                if flag("Authorized") or (flag("Demoing") and (flag("DemoDaysRemaining") or 0) > 0):
                    names.add(props["Name"]["value"])
            self._authorized = names
        return self._authorized

    def may_run(self, logic_name: str) -> bool:
        """Whether a plug-in named as Logic lists it ("UAD Neve 1073 (s/s)") may be loaded: a UAD one only if
        Console says so; anything else is not Console's to judge."""
        name = logic_name
        while name.endswith(")") and " (" in name:  # Logic adds "(s/s)"; "CLA-76 (s) (s/s)" carries two
            name = name.rsplit(" (", 1)[0]
        return not name.startswith("UAD ") or name in self.authorized()

    def find_plugin(self, words: str) -> str:
        """The one authorized plug-in whose name holds every word: "la-2a silver" finds "UAD Teletronix LA-2A Silver"."""
        wanted = [w for w in words.lower().replace("uad", " ").split() if w]
        names = sorted(self.authorized())
        exact = [n for n in names if n.lower() == words.lower() or n.lower() == f"uad {words.lower()}"]
        if exact:
            return exact[0]
        hits = [n for n in names if all(w in n.lower() for w in wanted)]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ConsoleError(f"no authorized UAD plug-in matches {words!r}")
        current = [n for n in hits if "legacy" not in n.lower()]
        if len(current) == 1:
            return current[0]
        raise ConsoleError(f"{words!r} matches {len(hits)} plug-ins: {', '.join(hits)}")

    def load(self, channel: int, slot: int, words: str) -> str:
        name = self.find_plugin(words)
        path = self.slot_path(channel, slot)
        self.set(path, "EffectName", name)
        time.sleep(self.settle * 10)
        landed = self.get(f"{path}/EffectName/value")
        if landed != name:
            raise ConsoleError(f"asked for {name} in slot {slot}, Console shows {landed!r}")
        return name

    def unload(self, channel: int, slot: int) -> None:
        path = self.slot_path(channel, slot)
        self.set(path, "EffectName", "")
        time.sleep(self.settle * 10)
        landed = self.get(f"{path}/EffectName/value")
        if landed:
            raise ConsoleError(f"slot {slot} still holds {landed}")

    # controls
    def params(self, channel: int, slot: int) -> dict[str, dict]:
        base = f"{self.slot_path(channel, slot)}/parameters"
        found = {}
        for key in self.get(base).get("children", {}):
            props = self.get(f"{base}/{key}")["properties"]
            found[props["Name"]["value"]] = {
                "path": f"{base}/{key}",
                "shown": props.get("StringValue", {}).get("value"),
                "normalized": props.get("NormalizedValue", {}).get("value"),
                "steps": props.get("StepValue", {}).get("values"),
            }
        return found

    def _shown(self, path: str) -> str:
        for _ in range(10):  # a value being redrawn can read empty for a moment (Retune Speed, live)
            shown = self.get(f"{path}/StringValue/value")
            if shown not in ("", None):
                return str(shown)
            time.sleep(self.settle)
        return ""

    def _put(self, path: str, normalized: float) -> str:
        self.set(path, "NormalizedValue", min(1.0, max(0.0, normalized)))
        return self._shown(path)

    def set_param(self, channel: int, slot: int, name: str, value) -> str:
        """Set one control to what the plug-in should show (40, "E", "MINOR", "Comp"), read back."""
        controls = self.params(channel, slot)
        match = next((n for n in controls if n.lower() == str(name).lower()), None)
        if match is None:
            raise ConsoleError(f"no control called {name!r}; it has {', '.join(controls)}")
        path = controls[match]["path"]
        try:
            target = float(value)
        except (TypeError, ValueError):
            return self._seek_label(path, str(value))
        return self._seek_number(path, target)

    def _seek_number(self, path: str, target: float) -> str:
        # Retune Speed shows nothing at the very ends of its range (live 2026-10-29), so the ends step inward
        lo = next((v for v in (0.0, 0.01, 0.02, 0.05) if _number(self._put(path, v)) is not None), None)
        hi = next((v for v in (1.0, 0.99, 0.98, 0.95) if _number(self._put(path, v)) is not None), None)
        if lo is None or hi is None:
            raise ConsoleError(f"{path} does not show a number")
        low_shown, high_shown = _number(self._put(path, lo)), _number(self._put(path, hi))
        if not min(low_shown, high_shown) <= target <= max(low_shown, high_shown):
            raise ConsoleError(f"{target:g} is outside {low_shown:g} to {high_shown:g}")
        rising = high_shown > low_shown
        for _ in range(BISECT_ROUNDS):
            mid = (lo + hi) / 2
            shown = _number(self._put(path, mid))
            if shown is None:
                break
            if (shown < target) == rising:
                lo = mid
            else:
                hi = mid
        def miss(v: float) -> float:
            shown = _number(self._put(path, v))
            return abs(shown - target) if shown is not None else math.inf

        return self._put(path, min((lo, hi), key=miss))

    def _seek_label(self, path: str, label: str) -> str:
        """A named value (a key, a scale, a switch): sweep the range, then sit in the middle of its band."""
        band: list[float] = []
        for i in range(SWEEP_STEPS + 1):
            v = i / SWEEP_STEPS
            if self._put(path, v).lower() == label.lower():
                band.append(v)
            elif band:
                break
        if not band:
            raise ConsoleError(f"{label!r} never showed on {path}")
        shown = self._put(path, (band[0] + band[-1]) / 2)
        if shown.lower() != label.lower():
            raise ConsoleError(f"set {label!r}, it shows {shown!r}")
        return shown

    def tune(self, channel: int, key: str, scale: str, slot: int | None = None) -> dict[str, str]:
        """Point the channel's Auto-Tune at a key and scale, with the gentle base."""
        if slot is None:
            slot = next((s.number for s in self.slots(channel) if s.name == AUTO_TUNE), None)
            if slot is None:
                raise ConsoleError(f"no {AUTO_TUNE} on {self.channel_name(channel)}")
        done = {"Key": self.set_param(channel, slot, "Key", key.upper()),
                "Scale": self.set_param(channel, slot, "Scale", scale.upper())}
        for name, value in GENTLE_TUNE.items():
            done[name] = self.set_param(channel, slot, name, value)
        return done


def _number(text: str | None) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None

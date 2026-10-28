"""Doing it in Logic: key commands for transport, MIDI for the knobs.

Transport goes through Logic's own key commands, sent by System Events, so a
command takes a fraction of a second once it is understood. The knob moves
go out on a virtual MIDI port, "Marco Knobs", that Logic's Controller
Assignments map to three plugin parameters; each move is one bounded step,
so nothing jumps to an extreme.

The key map below holds Logic's shortcuts. The ones marked ``custom`` are
assigned once in Logic's Key Commands window on setup day; until a live run
confirms a shortcut, treat it as unverified. ``dry_run`` plans every press
and MIDI message without touching Logic.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from hiremarco import config, gate
from hiremarco.studio.commands import Command

TENANT = "owner"
APP = "Logic Pro"

# name -> (key, modifiers). key is a character, or "code:<n>" for a macOS key code.
KEYMAP: dict[str, tuple[str, tuple[str, ...]]] = {
    "play_stop": ("code:49", ()),                                # space
    "record": ("r", ()),
    "go_to_start": ("code:36", ()),                              # return
    "new_audio_track": ("a", ("option", "command")),
    "go_to_position": ("/", ()),                                 # opens Go to Position
    "set_left_locator": ("l", ("control", "option", "command")),  # custom, assigned 2026-10-28
    "set_right_locator": ("k", ("control", "option", "command")), # custom, assigned 2026-10-28
    "autopunch_on": ("p", ("control", "option", "command")),      # custom (Toggle Autopunch Mode), assigned 2026-10-28
    "record_arm": ("r", ("control",)),                            # Toggle Track Record Enable, Logic's default
}
MARKERS_PATH_KEY = "HIREMARCO_MARKERS"   # json {"chorus": 33, "verse 2": 17} bars, per session

KNOB_CC = {"tuning": 20, "reverb": 21, "delay": 22}
KNOB_STEP = 8
KNOB_RANGE = {"tuning": (0, 127), "reverb": (0, 110), "delay": (0, 100)}
PRE_ROLL_BARS = 1


@dataclass
class Press:
    key: str
    modifiers: tuple[str, ...] = ()
    then_type: str = ""


def _script(press: Press) -> str:
    using = ""
    if press.modifiers:
        using = " using {" + ", ".join(f"{m} down" for m in press.modifiers) + "}"
    if press.key.startswith("code:"):
        action = f"key code {int(press.key[5:])}{using}"
    else:
        action = f'keystroke "{press.key}"{using}'
    lines = [f'tell application "{APP}" to activate', 'tell application "System Events"', f"  {action}"]
    if press.then_type:
        lines += ["  delay 0.2", f'  keystroke "{press.then_type}"', "  key code 36"]
    lines.append("end tell")
    return "\n".join(lines)


def _osascript(script: str) -> None:
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=10)


class Knobs:
    """Three bounded knobs on a virtual MIDI port, values kept between runs."""

    def __init__(self, send: Callable[[int, int], None] | None = None, state_path: Path | None = None):
        self.state_path = state_path or Path(os.environ.get("HIREMARCO_STATE", config.STATE_DIR)) / "knobs.json"
        self.values = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self._send = send
        self._port = None

    def _midi(self, cc: int, value: int) -> None:
        if self._send:
            return self._send(cc, value)
        import mido

        if self._port is None:
            mido.set_backend("mido.backends.rtmidi")
            self._port = mido.open_output("Marco Knobs", virtual=True)
            time.sleep(0.5)  # a new port needs a moment before Logic is listening to it
        self._port.send(mido.Message("control_change", control=cc, value=value))

    def move(self, knob: str, direction: str, steps: int) -> int:
        """A step up or down stays inside the knob's soft range; ``set`` goes exactly to the percent he said."""
        low, high = KNOB_RANGE[knob]
        if direction == "set":
            value = max(0, min(127, round(steps / 100 * 127)))
        else:
            value = int(self.values.get(knob, 64))
            value += KNOB_STEP * steps * (1 if direction == "up" else -1)
            value = max(low, min(high, value))
        self._midi(KNOB_CC[knob], value)
        self.values[knob] = value
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.values))
        return value


@dataclass
class Plan:
    presses: list[Press] = field(default_factory=list)
    knob: tuple[str, str, int] | None = None


def markers() -> dict[str, int]:
    path = os.environ.get(MARKERS_PATH_KEY)
    if not path or not Path(path).exists():
        return {}
    return {k.lower(): int(v) for k, v in json.loads(Path(path).read_text()).items()}


def plan(command: Command) -> Plan:
    k = KEYMAP
    p = lambda name, then="": Press(k[name][0], k[name][1], then)  # noqa: E731
    pos = lambda bar: p("go_to_position", f"{bar} 1 1 1")  # noqa: E731
    a = command.action
    if a in ("play", "stop"):
        return Plan([p("play_stop")])
    if a == "record":
        return Plan([p("record")])
    if a == "go_to_start":
        return Plan([p("go_to_start")])
    if a == "new_track":
        return Plan([p("new_audio_track"), p("record_arm")])
    if a == "arm_track":
        return Plan([p("record_arm")])
    if a == "go_to_bar" and command.bar > 0:
        return Plan([pos(command.bar)])
    if a == "go_to_section":
        bar = markers().get(command.section.lower())
        if bar is None:
            raise gate.Refused(f"no marker called {command.section!r} in this session")
        return Plan([pos(bar)])
    if a == "punch":
        bar = command.bar or markers().get(command.section.lower(), 0)
        if bar <= 0:
            raise gate.Refused("punch needs a bar or a known section")
        start = max(1, bar - PRE_ROLL_BARS)
        return Plan([pos(bar), p("set_left_locator"), pos(bar + 1), p("set_right_locator"), p("autopunch_on"),
                     pos(start), p("record")])
    if a == "knob":
        if command.direction == "set":
            return Plan(knob=(command.knob, "set", command.percent))
        return Plan(knob=(command.knob, command.direction, command.steps))
    raise gate.Refused(f"{a} is not a Logic action")


class Logic:
    def __init__(self, *, dry_run: bool = False, conn: sqlite3.Connection | None = None,
                 run_script: Callable[[str], None] | None = None, knobs: Knobs | None = None,
                 rules_path: Path | None = None, preset_dir: Path | None = None,
                 load_preset: Callable[[str], str] | None = None):
        self.dry_run = dry_run
        self.preset_dir = preset_dir
        self.load_preset = load_preset
        self.conn = conn
        self.run_script = run_script or _osascript
        self.knobs = knobs
        self.rules_path = rules_path
        self.planned: list[str] = []

    def do(self, command: Command) -> str:
        if command.action == "preset":
            return self._preset(command)
        steps = plan(command)
        if self.dry_run:
            self.planned += [_script(press) for press in steps.presses]
            if steps.knob:
                self.planned.append("midi {} {} {}".format(*steps.knob))
            return f"dry run: {command.describe()}"

        def run() -> str:
            for press in steps.presses:
                self.run_script(_script(press))
                time.sleep(0.05)
            if steps.knob:
                value = (self.knobs or Knobs()).move(*steps.knob)
                return f"{command.describe()} ({value})"
            return command.describe()

        return self._gated(run, command.action, command.describe())

    def _preset(self, command: Command) -> str:
        from hiremarco.studio import presets

        name = presets.match(command.text, presets.list_presets(self.preset_dir))
        if name is None:
            raise gate.Refused(f"no saved preset matches {command.text!r}")
        if self.dry_run:
            self.planned.append(f"preset {name}")
            return f"dry run: preset {name}"

        def run() -> str:
            (self.load_preset or presets.load)(name)
            return f"preset {name}"

        return self._gated(run, "preset", f"preset {name}")

    def _gated(self, run, capability: str, message: str) -> str:
        return gate.execute_effect(
            self.conn or gate.connect(), run, tenant_id=TENANT, idempotency_key=f"logic:{uuid.uuid4()}",
            capability=capability, channel="logic", target="*", message=message,
            department="studio", rules_path=self.rules_path,
        )

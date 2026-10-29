"""Marco as a Mackie Control surface for Logic.

Logic ships Mackie Control support (``Logic Control.bundle`` in its MIDI
Device Plug-ins), and a Mackie surface can do in Logic what no script can:
browse the plug-in menu and insert or remove a plug-in in any of 15 slots,
select tracks, run the transport, all without the screen and without Logic in
front (Apple, Control Surfaces Support guide: Plug-in Mixer and Plug-in
Channel views). Marco is that surface on a pair of virtual MIDI ports named
``Marco Control``.

What Logic shows on the surface's display comes back as SysEx
``F0 00 00 66 14 12 <offset> <text...> F7`` into a 2 x 56 character screen,
so every step is read back before the next one: the name of the plug-in a
V-Pot has preselected is on the display before Marco presses to confirm.

Message map (Mackie Control protocol, as documented by libMackieControl and
htlab's reverse-engineered spec): buttons are Note On, 0x7F press and 0x00
release; V-Pots turn by CC 0x10-0x17 (bit 6 is the direction, the low bits the
clicks); a V-Pot press is note 0x20-0x27.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

PORT = "Marco Control"
HEADER = [0x00, 0x00, 0x66, 0x14]  # Mackie, Mackie Control main unit
WIDTH = 56

NOTE = {
    "rec": 0x00, "solo": 0x08, "mute": 0x10, "select": 0x18, "vpot": 0x20,
    "track": 0x28, "send": 0x29, "pan": 0x2A, "plugin": 0x2B, "eq": 0x2C, "instrument": 0x2D,
    "bank_left": 0x2E, "bank_right": 0x2F, "channel_left": 0x30, "channel_right": 0x31,
    "flip": 0x32, "global": 0x33, "name_value": 0x34,
    "rewind": 0x5B, "forward": 0x5C, "stop": 0x5D, "play": 0x5E, "record": 0x5F,
    "up": 0x60, "down": 0x61, "left": 0x62, "right": 0x63,
}


@dataclass
class Screen:
    """The surface's two display lines, as Logic last wrote them."""

    cells: list[str] = field(default_factory=lambda: [" "] * (2 * WIDTH))

    def write(self, offset: int, text: str) -> None:
        for i, ch in enumerate(text):
            if 0 <= offset + i < len(self.cells):
                self.cells[offset + i] = ch

    @property
    def lines(self) -> tuple[str, str]:
        joined = "".join(self.cells)
        return joined[:WIDTH], joined[WIDTH:]

    def strip(self, n: int) -> tuple[str, str]:
        """The 7 characters over channel strip n (0 to 7), top and bottom."""
        top, bottom = self.lines
        return top[7 * n:7 * n + 7].strip(), bottom[7 * n:7 * n + 7].strip()


def handshake_reply(data: list[int]) -> list[int] | None:
    """Answer Logic's device query (0x00) as a main unit would; anything else needs no answer."""
    if data[:4] != HEADER or len(data) < 5:
        return None
    if data[4] == 0x00:  # device query -> host connection query with a serial number and challenge
        return HEADER + [0x01] + list(b"MARCO01") + [0x00, 0x00, 0x00, 0x00]
    if data[4] == 0x02:  # host connection reply -> confirmation with the same serial
        return HEADER + [0x03] + list(b"MARCO01")
    if data[4] == 0x13:  # version request (Logic's port scan, seen live 2026-10-29) -> version reply
        return HEADER + [0x14] + list(b"V1.02")
    return None


class Surface:
    """The ports, the screen, and the moves. ``send``/``receive`` are injectable for tests."""

    def __init__(self, send: Callable[[object], None] | None = None, log: Callable[[str], None] | None = None):
        self.screen = Screen()
        self.version = 0  # counts display writes, so a move can wait for Logic to redraw
        self.mode = ["", ""]  # the two-character mode display: "P2" is insert slot 2 in Plug-in view
        self.lit: dict[int, bool] = {}
        self.log = log or (lambda line: None)
        self._send = send
        self._out = self._in = None

    def open(self) -> None:
        import mido

        mido.set_backend("mido.backends.rtmidi")
        self._out = mido.open_output(PORT, virtual=True)
        self._in = mido.open_input(PORT, virtual=True, callback=self.receive)

    def close(self) -> None:
        for port in (self._in, self._out):
            if port is not None:
                port.close()

    def send(self, message) -> None:
        if self._send:
            self._send(message)
        elif self._out is not None:
            self._out.send(message)

    # what Logic says
    def receive(self, message) -> None:
        if message.type == "sysex":
            data = list(message.data)
            if data[:5] == HEADER + [0x12] and len(data) > 5:
                self.screen.write(data[5], bytes(data[6:]).decode("ascii", errors="replace"))
                self.version += 1
                top, bottom = self.screen.lines
                self.log(f"screen | {top} | {bottom}")
                return
            reply = handshake_reply(data)
            if reply is not None:
                import mido

                self.send(mido.Message("sysex", data=reply))
                self.log(f"handshake {data[4]:02x} answered")
                return
            self.log("sysex " + " ".join(f"{b:02x}" for b in data))
        elif message.type == "note_on":
            self.lit[message.note] = message.velocity > 0
        elif message.type == "control_change" and message.control in (0x4A, 0x4B):
            value = message.value & 0x3F
            self.mode[0x4B - message.control] = chr(value + 0x40) if value < 0x20 else chr(value)
        elif message.type not in ("clock",):
            self.log(str(message))

    # what Marco does
    def press(self, name: str, index: int = 0, hold: float = 0.05) -> None:
        import mido

        note = NOTE[name] + index
        self.send(mido.Message("note_on", note=note, velocity=0x7F))
        time.sleep(hold)
        self.send(mido.Message("note_on", note=note, velocity=0))

    def turn(self, strip: int, clicks: int) -> None:
        """Turn V-Pot ``strip`` by ``clicks``: positive is clockwise."""
        import mido

        value = min(abs(clicks), 0x3F) | (0x40 if clicks < 0 else 0)
        self.send(mido.Message("control_change", control=0x10 + strip, value=value))


def slot_text(screen: Screen, strip: int) -> str:
    """What the bottom line shows from strip n on: a preselected plug-in's full name runs past its 7 cells."""
    return screen.lines[1][7 * strip:].strip()


def step(surface: Surface, strip: int, clicks: int = 1, timeout: float = 0.5, tries: int = 3) -> str | None:
    """Turn one V-Pot until its text changes; None when three turns changed nothing (the end of the list).
    Logic sometimes swallows a single click (live 2026-10-29), so a turn that changes nothing is repeated."""
    before = slot_text(surface.screen, strip)
    for _ in range(tries):
        surface.turn(strip, clicks)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.02)
            if slot_text(surface.screen, strip) != before:
                time.sleep(0.03)  # let the rest of the line land
                return slot_text(surface.screen, strip)
    return None


def seek(surface: Surface, strip: int, wanted: str, limit: int = 900) -> str:
    """Step from the empty choice until the preselected name starts with ``wanted``; nothing is confirmed."""
    for _ in range(20):
        surface.turn(strip, -63)
        time.sleep(0.03)
    time.sleep(0.3)
    target = wanted.lower()
    for _ in range(limit):
        name = step(surface, strip)
        if name is None:
            break
        if name.lower().startswith(target):
            return name
    raise LookupError(f"{wanted!r} is not in Logic's plug-in list")


def to_empty(surface: Surface, strip: int) -> None:
    for _ in range(20):
        surface.turn(strip, -63)
        time.sleep(0.03)
    time.sleep(0.3)


def scan(surface: Surface, strip: int, limit: int = 2000) -> list[str]:
    """Logic's whole plug-in list, in V-Pot order, one waited step at a time; nothing is confirmed."""
    to_empty(surface, strip)
    names: list[str] = []
    for _ in range(limit):
        name = step(surface, strip)
        if name is None:
            break
        names.append(name)
    to_empty(surface, strip)
    return names


def pick(names: list[str], words: str) -> int:
    """The one index whose name holds every word ("la-2a silver"); an exact name wins, then a stereo one."""
    wanted = words.lower().split()
    exact = [i for i, n in enumerate(names) if n.lower() in (words.lower(), f"{words.lower()} (s/s)")]
    if exact:
        return exact[0]
    hits = [i for i, n in enumerate(names) if all(w in n.lower() for w in wanted)]
    if len(hits) > 1:
        current = [i for i in hits if "legacy" not in names[i].lower() and "(m)" not in names[i].lower()]
        hits = current if current else hits
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise LookupError(f"{words!r} is not in Logic's plug-in list (scan again if it was just installed)")
    raise LookupError(f"{words!r} matches {len(hits)}: " + ", ".join(names[i] for i in hits[:8]))


def heal(surface: Surface, strip: int, names: list[str], limit: int = 40) -> None:
    """The display shows a name the scan missed (a retried click can land twice): step back to a known
    name, then forward to the next known one, and write what lies between into the index."""
    where = {n: i for i, n in enumerate(names)}
    for _ in range(limit):
        shown = slot_text(surface.screen, strip)
        if shown.startswith("--") or shown in where:
            break
        if step(surface, strip, -1) is None:
            break
    shown = slot_text(surface.screen, strip)
    at = -1 if shown.startswith("--") else where.get(shown)
    if at is None:
        raise LookupError(f"lost in the plug-in list at {shown!r}: scan again")
    found: list[str] = []
    for _ in range(limit):
        name = step(surface, strip, 1)
        if name is None or name in where:
            break
        found.append(name)
    names[at + 1:at + 1] = found


def jump(surface: Surface, strip: int, names: list[str], target_name: str, rounds: int = 160) -> str:
    """Preselect target_name by read-back: Logic moves a V-Pot turn by a varying amount (a 63-click turn
    moved 42 or 43 entries, a 10-click turn 5, live 2026-10-29), so each turn is sized from the distance
    left, the display is read, and the last entries are single steps. A name the index lacks is learned on
    the way (``heal``). Nothing is confirmed."""
    for _ in range(rounds):
        where = {n: i for i, n in enumerate(names)}
        target = where[target_name]
        shown = slot_text(surface.screen, strip)
        at = -1 if shown.startswith("--") else where.get(shown)
        if at is None:
            heal(surface, strip, names)
            continue
        distance = target - at
        if distance == 0:
            return shown
        sign = 1 if distance > 0 else -1
        clicks = 1 if abs(distance) <= 2 else min(63, max(2, round(abs(distance) * 1.4)))
        if step(surface, strip, sign * clicks) is None and at in (-1, len(names) - 1):
            raise LookupError("the V-Pot stopped moving before the target")
    raise LookupError(f"did not reach {target_name!r} in {rounds} moves")


def slot_now(surface: Surface) -> int | None:
    """The insert slot Plug-in Mixer view shows, from the mode display ("P1" to "P9", then "10" to "15")."""
    left, right = surface.mode
    if left == "P" and right.isdigit():
        return int(right)
    if (left + right).isdigit():
        return int(left + right)
    return None


def wait_for(check: Callable[[], bool], timeout: float = 1.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return check()


def mixer_view(surface: Surface) -> None:
    """Pan, then Plug-in: Logic lands in Plug-in Mixer view, one insert slot across the eight strips."""
    surface.press("pan")
    wait_for(lambda: slot_now(surface) is None)  # Pan mode shows "PN"
    surface.press("plugin")
    if not wait_for(lambda: slot_now(surface) is not None) or surface.screen.lines[0].startswith("Ins1Pl"):
        raise LookupError("Logic did not open Plug-in Mixer view")
    time.sleep(0.3)


def go_slot(surface: Surface, slot: int) -> None:
    if not 1 <= slot <= 15:
        raise LookupError("Logic has insert slots 1 to 15")
    for _ in range(20):
        now = slot_now(surface)
        if now == slot:
            time.sleep(0.25)  # the bottom line redraws for the new slot
            return
        if now is None:
            raise LookupError("not in Plug-in Mixer view")
        surface.press("down" if slot > now else "up")
        wait_for(lambda: slot_now(surface) != now, 0.8)
    raise LookupError(f"could not reach insert slot {slot}")


def strip_of(surface: Surface, track: str) -> int:
    """The strip whose short name Logic shows is spelled inside ``track`` ("OS_6x_" in
    "OS_6ix_149_vocal_remnants_Em"): Logic shortens names by dropping letters, so the short name is a
    subsequence of the full one."""
    if track.isdigit():
        return int(track)
    def inside(short: str, full: str) -> bool:
        letters = iter(full.lower())
        return bool(short) and all(ch in letters for ch in short.lower())
    def ends(short: str, full: str) -> int:  # shared start plus shared end: "ins117" beats "Inst 1" for "instrumental 117"
        a, b = short.lower(), full.lower()
        start = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        end = next((i for i, (x, y) in enumerate(zip(a[::-1], b[::-1])) if x != y), min(len(a), len(b)))
        return start + end

    hits = [n for n in range(8) if inside(surface.screen.strip(n)[0], track)]
    scored = sorted(((ends(surface.screen.strip(n)[0], track), n) for n in hits), reverse=True)
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        raise LookupError(f"{track!r} matches strips {hits}; give the strip number (0 to 7)")
    return scored[0][1]


def insert(surface: Surface, names: list[str], track: str, slot: int, words: str, replace: bool = False) -> str:
    """Put a plug-in into a track's insert slot in one go: Plug-in Mixer view, the slot, a guard against
    replacing what is there, the jump with read-back, the press, then a read of the slot to prove it."""
    mixer_view(surface)
    strip = strip_of(surface, track)
    go_slot(surface, slot)
    there = surface.screen.strip(strip)[1]
    if there not in ("--", "") and not replace:
        raise LookupError(f"insert {slot} on that track already holds {there}; say replace to swap it")
    shown = jump(surface, strip, names, names[pick(names, words)])
    surface.press("vpot", strip)
    time.sleep(0.8)
    mixer_view(surface)  # the press opened Plug-in Edit view; back to the slots to read the result
    go_slot(surface, slot)
    landed = surface.screen.strip(strip)[1]
    if landed in ("--", ""):
        raise LookupError(f"pressed {shown}, but insert {slot} reads empty")
    return f"{shown} in insert {slot} (the strip reads {landed})"


def remove(surface: Surface, track: str, slot: int) -> str:
    mixer_view(surface)
    strip = strip_of(surface, track)
    go_slot(surface, slot)
    there = surface.screen.strip(strip)[1]
    if there in ("--", ""):
        return f"insert {slot} was already empty"
    to_empty(surface, strip)
    if not slot_text(surface.screen, strip).startswith("--"):
        raise LookupError("could not preselect the empty choice")
    surface.press("vpot", strip)
    time.sleep(0.8)
    mixer_view(surface)
    go_slot(surface, slot)
    if surface.screen.strip(strip)[1] not in ("--", ""):
        raise LookupError(f"insert {slot} still reads {surface.screen.strip(strip)[1]}")
    return f"removed {there} from insert {slot}"


PLUGIN_FOLDERS = ("/Library/Audio/Plug-Ins/Components", "~/Library/Audio/Plug-Ins/Components")
WATCH_EVERY = 300.0  # seconds between looks at the plug-in folders


def bundles(folders=PLUGIN_FOLDERS) -> set[str]:
    """The Audio Unit bundles installed, the plug-ins Logic can list."""
    from pathlib import Path

    found = set()
    for folder in folders:
        path = Path(folder).expanduser()
        if path.is_dir():
            found |= {p.name for p in path.iterdir() if p.suffix == ".component"}
    return found


def idle(surface: Surface) -> bool:
    """Logic is neither playing nor recording (the transport lights it sends the surface)."""
    return not surface.lit.get(NOTE["play"]) and not surface.lit.get(NOTE["record"])


def relearn(surface: Surface, index_path) -> list[str]:
    """Scan again on an empty slot and return the names that are new to the index."""
    import json as _json

    old = set(_json.loads(index_path.read_text())) if index_path.exists() else set()
    mixer_view(surface)
    go_slot(surface, 15)
    strip = next((n for n in range(8) if surface.screen.strip(n)[1] == "--" and surface.screen.strip(n)[0]), None)
    if strip is None:
        raise LookupError("no empty insert 15 to scan on")
    names = scan(surface, strip)
    surface.press("pan")
    index_path.write_text(_json.dumps(names, indent=0))
    return [n for n in names if n not in old]


def watch(surface: Surface, lock, index_path, every: float = WATCH_EVERY, stop=None) -> None:
    """When a plug-in is installed, learn Logic's list again once Logic is idle, and say what is new."""
    import json as _json

    snapshot = index_path.with_name("plugin_bundles.json")
    learned = index_path.with_name("learned_plugins.json")
    if not snapshot.exists():
        snapshot.write_text(_json.dumps(sorted(bundles())))
    while not (stop and stop.is_set()):
        time.sleep(every)
        now = bundles()
        added = now - set(_json.loads(snapshot.read_text()))
        if not added or not idle(surface):
            continue
        with lock:
            surface.log(f"new plug-in bundles {sorted(added)}: learning Logic's list again")
            try:
                fresh = relearn(surface, index_path)
            except LookupError as stopped:
                surface.log(f"relearn stopped: {stopped}")
                continue
        snapshot.write_text(_json.dumps(sorted(now)))
        learned.write_text(_json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S %z"), "new": fresh}))
        surface.log(f"learned {len(fresh)} new plug-in(s): {', '.join(fresh) or 'none yet (Logic may list it after a restart)'}")


def serve(sock_path, log_path) -> None:
    """Hold the ports open and take one command per connection on a Unix socket:
    ``press NAME [INDEX]``, ``turn STRIP CLICKS``, ``screen``. Every reply ends with the screen as it stands."""
    import socket as _socket
    from pathlib import Path

    log_file = Path(log_path).open("a", buffering=1)
    surface = Surface(log=lambda line: log_file.write(f"{time.strftime('%H:%M:%S')} {line}\n"))
    surface.open()
    sock_path = Path(sock_path)
    sock_path.unlink(missing_ok=True)
    server = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(4)
    surface.log(f"surface up on '{PORT}'")
    import threading

    lock = threading.Lock()
    index_path = Path(log_path).with_name("maps") / "logic_plugins.json"
    threading.Thread(target=watch, args=(surface, lock, index_path), daemon=True).start()
    try:
        while True:
            conn, _ = server.accept()
            with conn, lock:
                words = conn.recv(1024).decode().split()
                answer = "ok"
                try:
                    if words and words[0] == "press":
                        surface.press(words[1], int(words[2]) if len(words) > 2 else 0)
                    elif words and words[0] == "turn":
                        surface.turn(int(words[1]), int(words[2]))
                    elif words and words[0] == "seek":
                        answer = f"preselected {seek(surface, int(words[1]), ' '.join(words[2:]))}"
                    elif words and words[0] == "jump":
                        import json as _json

                        index = Path(log_path).with_name("maps") / "logic_plugins.json"
                        names = _json.loads(index.read_text())
                        started = time.monotonic()
                        before = len(names)
                        shown = jump(surface, int(words[1]), names, names[pick(names, " ".join(words[2:]))])
                        if len(names) != before:
                            index.write_text(_json.dumps(names, indent=0))
                        answer = (f"preselected {shown} in {time.monotonic() - started:.1f} s"
                                  + (f"; learned {len(names) - before} name(s)" if len(names) != before else ""))
                    elif words and words[0] in ("insert", "replace"):
                        import json as _json

                        index = Path(log_path).with_name("maps") / "logic_plugins.json"
                        names = _json.loads(index.read_text())
                        started = time.monotonic()
                        done = insert(surface, names, words[1], int(words[2]), " ".join(words[3:]),
                                      replace=words[0] == "replace")
                        index.write_text(_json.dumps(names, indent=0))
                        answer = f"{done} in {time.monotonic() - started:.1f} s"
                    elif words and words[0] == "learned":
                        learned = index_path.with_name("learned_plugins.json")
                        answer = learned.read_text() if learned.exists() else "nothing new learned yet"
                    elif words and words[0] == "remove":
                        answer = remove(surface, words[1], int(words[2]))
                    elif words and words[0] == "scan":
                        import json as _json

                        names = scan(surface, int(words[1]))
                        index = Path(log_path).with_name("maps") / "logic_plugins.json"
                        index.parent.mkdir(parents=True, exist_ok=True)
                        index.write_text(_json.dumps(names, indent=0))
                        answer = f"scanned {len(names)} plug-ins into {index}"
                    elif words and words[0] == "confirm":
                        surface.press("vpot", int(words[1]))
                    elif words and words[0] != "screen":
                        answer = f"unknown: {' '.join(words)}"
                    if words and words[0] != "screen":
                        surface.log(f"did {' '.join(words)}")
                        time.sleep(0.25)  # Logic redraws the display a moment after a move
                except (KeyError, IndexError, ValueError, LookupError) as bad:
                    answer = f"bad command: {bad}"
                top, bottom = surface.screen.lines
                conn.sendall(f"{answer}\n{top}\n{bottom}\n".encode())
    finally:
        surface.close()
        sock_path.unlink(missing_ok=True)


def ask(sock_path, command: str) -> str:
    import socket as _socket

    with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as conn:
        conn.connect(str(sock_path))
        conn.sendall(command.encode())
        return conn.recv(4096).decode()

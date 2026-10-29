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
    try:
        while True:
            conn, _ = server.accept()
            with conn:
                words = conn.recv(1024).decode().split()
                answer = "ok"
                try:
                    if words and words[0] == "press":
                        surface.press(words[1], int(words[2]) if len(words) > 2 else 0)
                    elif words and words[0] == "turn":
                        surface.turn(int(words[1]), int(words[2]))
                    elif words and words[0] == "seek":
                        answer = f"preselected {seek(surface, int(words[1]), ' '.join(words[2:]))}"
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

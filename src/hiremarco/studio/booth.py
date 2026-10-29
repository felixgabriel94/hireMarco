"""The booth loop: Felix talks, Marco runs the session.

The mic feeds two things at once: Muse Voice Transcribe, which hands back
each finished sentence, and a tape that keeps the last minutes of the mic so
"how was that take?" has the take to listen to. Each sentence addressed to
Marco becomes one command; the loop keeps the transport state from the
commands it sent, so talkback knows when a take is rolling and holds.

What Marco says, from the session script: "Rolling" before a take starts,
nothing for knob moves, "That's in the mix notes" for a note, and the full
producer's note after "how was that take?", ending "Want to punch it?" when
one spot would fix it. "Marco, punch it" then punches that spot.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import numpy as np

from hiremarco import config, gate
from hiremarco.studio.commands import Command, calls_marco, strip_wake
from hiremarco.studio.words import Writer
from hiremarco.studio.feedback import TakeNote

ROLLING = {"record", "play", "punch"}
TAPE_SECONDS = 10 * 60
NOTED = "That's in the mix notes."
LISTENING = "Let me listen."
DIALING = "Let me dial that in."
MISSED = "I missed that. Say it again?"
FAILED = "That one didn't take. I'll note it."
MIC_TAIL = 0.4  # seconds his hearing stays muted after he stops talking
ECHO_SECONDS = 15.0  # how long a line of his can come back through the mic as an echo
HERE = "Yeah?"
# The instant answer to his name: pre-made so it plays at once, picked so it never sounds like a loop. The Owner's
# own picks first (2026-10-29: keep him cool like that).
HEARD = ["Talk to me.", "What's up?", "Go ahead.", "Yeah?", "I'm here.", "Right here.", "What's good?",
         "Go for it.", "What you need?", "I'm listening."]
AFTER_TAKE = ["How we feeling?", "Talk to me.", "What you thinking?"]
DISMISSED = "Anytime."
AWAKE = 20.0  # seconds after the last exchange in which a sentence needs no "Marco"; the same quiet ends the halo
LIVE_ON = "Live view's on. The link's on the Mac."
LIVE_TEXTED = "Live view's on. I texted you the link."
STOPPED = "Stopped. Everything's held until you clear it from the desk."
# Lines Marco says often, made once at the start so they play the moment they are needed.
STOCK = ["Rolling", *HEARD, *AFTER_TAKE, DISMISSED, LIVE_ON, LIVE_TEXTED, NOTED, LISTENING, DIALING, MISSED, FAILED, STOPPED, "Here's how it goes.", "What key are we in?", "Put it back.",
         "Morning. Your session's up. Where do you want to start?"]


def _stem(words: str) -> str:
    """'Harmonies' -> 'harmony', 'Ad-libs' -> 'adlib', 'Harmony 2' -> 'harmony2': one shape for matching."""
    w = words.lower().replace("-", "").replace(" ", "")
    if w.endswith("ies"):
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]
    return w


class Tape:
    """The last TAPE_SECONDS of the mic, mono, with the current take's span marked."""

    def __init__(self, rate: int, seconds: int = TAPE_SECONDS):
        self.rate = rate
        self.buffer = np.zeros(rate * seconds, dtype="float32")
        self.written = 0  # samples since start
        self.take: tuple[int, int] | None = None
        self._start: int | None = None

    def write(self, block: np.ndarray) -> None:
        block = np.asarray(block, dtype="float32").reshape(-1)[-self.buffer.size:]
        pos = self.written % self.buffer.size
        first = min(block.size, self.buffer.size - pos)
        self.buffer[pos:pos + first] = block[:first]
        self.buffer[:block.size - first] = block[first:]
        self.written += block.size

    def mark_start(self) -> None:
        self._start = self.written

    def mark_stop(self) -> None:
        if self._start is not None:
            self.take = (self._start, self.written)
            self._start = None

    def last_take(self) -> np.ndarray:
        if self.take is None:
            return np.zeros(0, dtype="float32")
        start, end = self.take
        start = max(start, end - self.buffer.size, self.written - self.buffer.size)
        idx = np.arange(start, end) % self.buffer.size
        return self.buffer[idx].copy()


@dataclass
class Booth:
    understand: Callable[[str], Command | None]
    logic: Callable[[Command], str]
    say: Callable[[str], object]
    feedback: Callable[[np.ndarray, int], TakeNote]
    tape: Tape
    log: Callable[[str], None] = print
    rolling: bool = False
    notes: list[str] = field(default_factory=list)
    producer_notes: list[str] = field(default_factory=list)
    pending_punch: str = ""
    key: str = ""
    transcribe: Callable[[np.ndarray, int], list] | None = None
    play_clip: Callable[[np.ndarray, str], object] | None = None
    last_run: list = field(default_factory=list)
    plugin: object | None = None
    tracks: object | None = None          # studio.tracks.Tracks
    session: object | None = None         # studio.tracks.SessionState, from the scan at start
    mix_pass: Callable[[str], str] | None = None
    show: Callable[[str], str] | None = None
    live: Callable[[], str] | None = None             # starts the live view once, returns its link
    say_stopped: Callable[[], bool] | None = None     # the cache-only player for STOPPED, after the switch is on
    hearing: Callable[[], str] | None = None          # the full read, spoken, then the question
    reference: Callable[[str], str] | None = None     # "sound like X" -> the signature, spoken short
    busy: bool = False                                # a command is running: the halo shows him thinking
    called_at: float = 0.0                            # when his name was last heard, before the sentence ended
    settle: float = 0.8                               # seconds between making a track and naming it
    awake_at: float = -100.0                          # the last exchange: he listens without his name for AWAKE s
    asleep: bool = False                              # dismissed: the halo goes as soon as he finishes his line
    recent_answers: list[str] = field(default_factory=list)   # his last answers to his name, never three alike
    writer: object | None = None                      # studio.words.Writer: his content lines, written live
    last_said: str = ""
    heard_line: str = ""
    spoken: list = field(default_factory=list)        # (when, line) of his last lines, to know his own echo
    _asked_after_take: bool = False                   # the after-take answer is used once per take
    send_link: Callable[[str, str], str] | None = None  # (body, url) to the artist's phone; None or a refusal: the Mac

    def toggle(self) -> str:
        """Command+Option+M: wake him if he is away, send him away if he is with you. Held while a take rolls."""
        now = time.monotonic()
        if self.rolling:
            return self._done("shortcut", "held: a take is rolling", now)
        if self.asleep or now - self.awake_at >= AWAKE:
            self.asleep, self.awake_at = False, now
            self._speak(self._answer_to_name())
            return self._done("shortcut", "woken; listening without his name", now)
        self.awake_at, self.asleep = -100.0, True
        self._say("the artist is done talking for now; sign off", {}, DISMISSED)
        return self._done("shortcut", "sent away; listening for his name only", now)

    def _answer_to_name(self) -> str:
        """One of the instant answers: none of the last three, and an after-the-take one when a take just ended."""
        import random

        pool = AFTER_TAKE if self.tape.take is not None and not self.rolling and not self._asked_after_take else HEARD
        self._asked_after_take = pool is AFTER_TAKE or self._asked_after_take
        fresh = [line for line in pool if line not in self.recent_answers[-3:]] or pool
        line = random.choice(fresh)
        self.recent_answers.append(line)
        return line

    def _deliver(self, body: str, url: str) -> str:
        """Links go to the artist's phone as a message with a button when Marco can send one; else the Mac."""
        if self.send_link is None:
            return "printed and copied"
        try:
            self.send_link(body, url)
            return "texted"
        except Exception as exc:  # not set up yet, outside the 24-hour window, or held by the gate
            self.log(f"   (not texted: {getattr(exc, 'reason', None) or type(exc).__name__}; printed and copied)")
            return "printed and copied"

    def _say(self, moment: str, facts: dict, plain: str) -> None:
        """A line with content: written for this moment when a writer is wired, the plain line otherwise."""
        self._speak(self.writer.line(moment, facts, plain) if self.writer is not None else plain)

    def _echo(self, line: str) -> bool:
        """His own voice coming back through the mic. Live 2026-10-29: once awake, he heard his own line as the
        artist's next sentence and kept answering himself. The mic is muted while he talks (see on_input); this
        catches what slips past: a line that is one of his own from the last ECHO_SECONDS, word for word."""
        heard = _words(strip_wake(line) if strip_wake(line) is not None else line)
        if not heard:
            return False
        now = time.monotonic()
        for at, said in self.spoken:
            if now - at <= ECHO_SECONDS:
                if heard == _words(said):  # the whole line, word for word: the artist's "punch it" stays his
                    return True
        return False

    def _speak(self, text: str) -> None:
        self.last_said = text
        self.spoken.append((time.monotonic(), text))
        del self.spoken[:-6]
        try:
            self.say(text)
        except gate.Refused as held:
            self.log(f"   (held talkback: {held.reason})")

    def hear(self, line: str) -> str | None:
        started = time.monotonic()
        if self._echo(line):
            self.log(f"   (his own voice, not answered: {line})")
            return None
        # Once you have his attention, he stays with you: no "Marco" needed until a take starts or the two of you
        # go quiet for AWAKE seconds (Owner 2026-10-29: having to say the name every time is what he dislikes in
        # Siri). The take ends it, so nothing sung is taken for a command.
        implied = (not self.rolling and started - self.awake_at < AWAKE and strip_wake(line) is None)
        if implied:
            line = f"Marco, {line}"
        try:
            command = self.understand(line)
        except gate.Refused as refused:
            return self._done(f"heard: {line}", f"held: {refused.reason}", started)
        if command is None:
            return None  # not addressed to Marco
        self.awake_at = time.monotonic()
        self.asleep = False
        self.busy = True
        self.last_said = ""
        self.heard_line = line
        try:
            result = self.handle(command)
        except gate.Refused as refused:
            result = f"held: {refused.reason}"
        except Exception as exc:  # a failed action is said and logged; the booth keeps listening
            result = f"failed: {type(exc).__name__}: {str(exc)[-160:]}"
            self._say("an action failed", {"asked": line, "what_failed": result}, FAILED)
        finally:
            self.busy = False
        if self.writer is not None:
            self.writer.heard(line, self.last_said)
        return self._done(f"heard: {line}", result, started)

    def _done(self, first: str, last: str, started: float) -> str:
        text = f"{first} > {last} > {time.monotonic() - started:.1f} s"
        self.log(text)
        return text

    def _kill(self) -> str:
        """Everything stops and stays stopped: the gate's kill switch goes on, and only the desk clears it."""
        gate.set_kill_switch(True, "said in the booth")
        stopped = ""
        if self.rolling:
            try:
                self.logic(Command("stop"))
                stopped = ", transport stopped"
            except Exception as exc:  # the switch is already on; the stop is best effort
                stopped = f", transport stop failed ({type(exc).__name__})"
            self.rolling = False
            self.tape.mark_stop()
        heard = False
        if self.say_stopped is not None:
            try:
                heard = self.say_stopped()  # cache only: the gate refuses talkback once the switch is on
            except Exception as exc:
                self.log(f"   (say_stopped failed: {type(exc).__name__})")
        if not heard:
            try:
                self.say(STOPPED)
            except Exception:
                self.log(f"   Marco (text only): {STOPPED}")
        return f"kill switch on{stopped}; clear it from the desk with: marco gate kill off"

    def _tidy(self, command: Command) -> str:
        from hiremarco.studio.tracks import NotMapped, SessionState

        a = command.action
        if self.session is None:
            self.session = SessionState("recording", [])
        if a == "mode":
            if command.text:
                self.session.mode = command.text
                self._say("switched mode", {"mode_now": command.text}, f"{command.text.capitalize()} mode.")
                return f"mode set: {command.text}"
            self._say("asked which mode", {"mode": self.session.mode}, f"We're {self.session.mode}.")
            return f"mode: {self.session.mode}"
        if a == "balanced_watch":
            self.session.balanced_watch = command.text == "on"
            self._say("balance watch", {"watching_the_balance": self.session.balanced_watch},
                      "I'll keep it balanced as we go." if self.session.balanced_watch else "Okay, just recording.")
            return f"balanced watch {command.text}"
        if a == "mix_pass":
            if self.rolling:
                return "holding the mix pass until the take stops"
            if self.mix_pass is None:
                return "no mix pass wired in this booth"
            self._speak(DIALING)
            result = self.mix_pass("baseline: a clean balanced mix of what we have so far")
            self._speak(result)
            return f"mix pass: {result}"
        if self.tracks is None:
            return "no track control in this booth"
        try:
            if a == "label_track":
                name, what = self.tracks.label(command.text, self.session)
                self._say("named the track", {"role": command.text, "name": name, "result": what},
                          f"{name}. Rolling when you are.")
                return what
            if a == "name_track":
                return self.tracks.rename(command.text)
            if a == "stack":
                stem = _stem(command.text)
                named = [t.name for t in self.session.tracks if stem in _stem(t.name)]
                return self.tracks.stack(named or [command.text])
        except NotMapped as later:
            self._say("cannot do this one yet", {"asked": command.action, "why": str(later)},
                      "Noted. I'll do that one from the desk.")
            return str(later)
        return "nothing to do"

    def _run_check(self, lyric: str) -> str:
        from hiremarco.studio import pitch

        if self.rolling:
            return "holding the run check until the take stops"
        if not self.key:
            self._speak("What key are we in?")
            return "asked for the key"
        take = self.tape.last_take()
        if take.size == 0:
            return "no take on the tape yet"
        window = None
        if lyric and self.transcribe is not None:
            window = pitch.locate(lyric, self.transcribe(take, self.tape.rate))
            if window is None:
                self._speak(f"I couldn't find {lyric} in that take.")
                return f"lyric not found: {lyric}"
        run = pitch.run_in(take, self.tape.rate, self.key, window)
        self.last_run = run
        line = pitch.describe(run)
        self._speak(line)
        if run and self.play_clip is not None:
            self._speak("Here's how it goes.")
            try:
                self.play_clip(pitch.guide(run), f"guide: {' '.join(n.name for n in run)}")
            except gate.Refused as held:
                self.log(f"   (held guide: {held.reason})")
        where = f"{window[0]:.1f}-{window[1]:.1f} s (estimate)" if window else "whole take"
        return f"run check, {where}: {line}"

    def handle(self, command: Command) -> str:
        a = command.action
        if a == "kill":
            return self._kill()
        if a == "dismiss":
            self._say("the artist is done talking for now; sign off", {}, DISMISSED)
            self.awake_at, self.asleep = -100.0, True
            return "dismissed; listening for his name only"
        if a == "summon":
            self._speak(self._answer_to_name())
            return "called by name; answered and listening"
        if a == "unknown":
            # He heard his name but could not place the line: say so, never guess and never go quiet.
            self._say("did not understand; ask one specific question", {"heard": self.heard_line}, MISSED)
            return "not a studio command, nothing done; asked him to say it again"
        if a == "note":
            self.notes.append(command.text)
            self._say("kept a note for the mix", {"note": command.text}, NOTED)
            return f"note: {command.text}"
        if a == "take_feedback":
            if self.rolling:
                return "holding the note until the take stops"
            take = self.tape.last_take()
            if take.size == 0:
                return "no take on the tape yet"
            self._speak(LISTENING)  # the note takes a few seconds; silence would feel like a dropped line
            note = self.feedback(take, self.tape.rate)
            self.producer_notes.append(note.note)
            self.pending_punch = note.punch_where if note.punch else ""
            self._speak(note.spoken)
            return f"take note: {note.spoken}"
        if a == "hearing":
            if self.hearing is None:
                return "no session to hear in this booth"
            if self.rolling:
                return "holding the hearing until the take stops"
            self._speak(LISTENING)
            said = self.hearing()
            self._speak(said)
            return f"hearing: {said}"
        if a == "reference":
            if self.reference is None:
                return "no reference memory in this booth"
            line = self.reference(command.text)
            self._speak(line)
            return f"reference {command.text}: {line}"
        if a == "show":
            if self.show is None:
                return "no phone to show it on in this booth"
            try:
                message_id = self.show("Here's the session.")
            except gate.Refused as held:
                return f"held: {held.reason}"
            return f"shown on the phone ({message_id[-6:]})"
        if a == "live_view":
            if self.live is None:
                return "no live view in this booth"
            link = self.live()
            self.log(f"   live view: {link}")
            where = self._deliver("Live view of the session. Open it on the same Wi-Fi as the Mac.", link)
            self._say("live view on", {"link": "texted to the artist's phone" if where == "texted"
                                       else "on the Mac's screen, copied"}, LIVE_TEXTED if where == "texted" else LIVE_ON)
            return f"live view on, link {where}"
        if a in ("label_track", "name_track", "stack", "mix_pass", "balanced_watch", "mode"):
            return self._tidy(command)
        if a == "set_key":
            from hiremarco.studio.pitch import parse_key

            key = command.text.replace(" sharp", "#").replace(" flat", "b")
            try:
                parse_key(key)
            except ValueError:
                return f"didn't catch a key in {command.text!r}"
            self.key = key
            return f"key set: {key}"
        if a == "run_check":
            return self._run_check(command.text)
        if a in ("sound", "put_back"):
            if self.rolling:
                return "holding the sound change until the take stops"
            if self.plugin is None:
                return "no plugin window to work on"
            if a == "put_back":
                self.plugin.put_back()
                self._speak("Put it back.")
                return "sound put back"
            self._speak(DIALING)  # the whole chain takes Muse Wonder several seconds
            changed, said = self.plugin.design(command.text)
            self._speak(said)
            return f"sound across {len(changed)} plugin(s): {said}"
        if a == "preset" and self.rolling:
            return "holding the preset until the take stops"
        if a == "export":
            return "export is its own step: marco export-dialog, then the ready-to-mix check"
        if a == "punch" and not (command.bar or command.section):
            if not self.pending_punch:
                return "punch where? nothing pending"
            command = replace(command, section=self.pending_punch)
        if a == "new_track" and command.text and self.tracks is not None:
            # one move: make the track (Logic selects it), then name it for its kind
            made = self.logic(Command("new_track"))
            time.sleep(self.settle)  # Logic draws the new track and selects it before it can be named
            if self.session is None:
                from hiremarco.studio.tracks import SessionState

                self.session = SessionState("recording", [])
            try:
                name, what = self.tracks.label(command.text, self.session)
            except Exception as exc:
                failed = f"naming failed: {type(exc).__name__}: {str(exc)[-160:]}"
                self._say("made a new track but could not name it", {"role": command.text, "what_failed": failed},
                          FAILED)
                return f"{made}; {failed}"
            self._say("made a new track and named it", {"role": command.text, "name": name},
                      f"{name}. Rolling when you are.")
            return f"{made}; {what}"
        if a in ROLLING and not self.rolling:
            self._speak("Rolling")  # said while stopped, before the take starts
        result = self.logic(command)
        if a in ROLLING:
            self.rolling = True
            if a in ("record", "punch"):
                self.tape.mark_start()
                self.pending_punch = ""
        elif a == "stop":
            self.rolling = False
            self.tape.mark_stop()
            self._asked_after_take = False  # a new take: the next answer to his name can ask how it felt
        return result


def _song() -> str:
    return config.get("HIREMARCO_SONG") or "untitled"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


_LIVE: list = []
_HALO: list = []


SHORTCUT_PORT = 8790


def _shortcut_listener(booth: "Booth", sock) -> None:
    """The halo sends "toggle" here for Command+Option+M; the menu-bar app sends "live" for the live view link."""
    while True:
        data, _ = sock.recvfrom(64)
        if data.strip() == b"toggle":
            booth.toggle()
        elif data.strip() == b"live":  # the menu bar's "Text me the live view"
            booth.hear("Marco, give me the live view")


def _text_owner(body: str, url: str) -> str:
    """One text to the Owner's WhatsApp, through the gate. Turned on by HIREMARCO_TEXT_LINKS=on, after the
    first WhatsApp message (filmed Thursday) has gone out, so nothing else is his first message from Marco."""
    from hiremarco.whatsapp import WhatsApp

    return WhatsApp().send_link(config.require("OWNER_WHATSAPP"), body, url, "Open live view",
                                idempotency_key=f"link:{time.time_ns()}")


_LIVE_LOCK = threading.Lock()


def _booth_live() -> str:
    """The live view beside the booth: started with the session (or on the first ask), the same link after that."""
    from hiremarco.studio.live import LiveView

    with _LIVE_LOCK:
        if not _LIVE:
            view = LiveView.prepare()
            view.start_in_background()
            _LIVE.append(view)
    return _LIVE[0].link


def _open_live_view() -> None:
    """At the start of a session, so a link he sends always opens; capture runs only while a phone watches."""
    try:
        print(f"live view ready: {_booth_live()}")
    except Exception as exc:  # the session runs without it; asking for it later says why
        print(f"   (live view not started: {type(exc).__name__}: {str(exc)[-160:]})")


def _booth_hearing() -> str:
    """The full read of the exported tracks in HIREMARCO_STEMS, spoken; or what Marco needs first."""
    from pathlib import Path

    from hiremarco.mix import hearing
    from hiremarco.mix.ears import listen

    stems = config.get("HIREMARCO_STEMS")
    if not stems or not Path(stems).expanduser().is_dir():
        return "Export the tracks first and I'll give you a proper read."
    _, prefs = hearing.hear(listen(Path(stems).expanduser()), _song())
    return prefs.heard


def _booth_reference(who: str) -> str:
    from hiremarco.mix import hearing

    prefs = hearing.reference(_song(), who)
    first = prefs.signature.split(". ")[0]
    return f"{who}. Got it: {first}."


def run_booth(*, dry_run: bool = False) -> int:
    """The live loop on the booth mic, until Ctrl+C.

    Settings: HIREMARCO_MIC_DEVICE (input device name), HIREMARCO_MIC_CHANNEL
    (1-based, the Manley's input), HIREMARCO_MIC_RATE (48000 unless set).
    ``dry_run`` plans Logic's presses without sending them and prints Marco's
    lines instead of speaking them; the mic and the model are live.
    """
    import asyncio
    import socket

    from hiremarco import config
    from hiremarco.hearing import Listener, to_pcm24k
    from hiremarco.studio.commands import understand

    # One Marco at a time: two booths would open the mic twice and answer twice. The shortcut port is the lock.
    lock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        lock.bind(("127.0.0.1", SHORTCUT_PORT))
    except OSError:
        print("Marco is already listening (the menu-bar app, or another booth); this one is not started")
        return 1
    from hiremarco.studio.feedback import how_was_that_take
    from hiremarco.studio.logic import Logic
    from hiremarco.studio.chain import Channel
    from hiremarco.voice import Talkback

    from hiremarco.studio.audio import DuplexAudio

    logic = Logic(dry_run=dry_run)
    booth: Booth

    # Marco's voice plays through the same stream that carries the mic; the player is attached once it exists.
    talkback = None if dry_run else Talkback(lambda: booth.rolling, play=lambda pcm, rate: None)
    if talkback is not None:
        print(f"voice: {talkback.warm(STOCK)} stock line(s) made, the rest already cached")

    def say(text: str) -> object:
        if talkback is None:
            print(f"   Marco (text only): {text}")
            return None
        return talkback.say(text)

    from hiremarco.hearing import transcribe

    from hiremarco.studio.tracks import Tracks

    tracks = Tracks(dry_run=dry_run)
    session = tracks.scan() if not dry_run else None
    booth = Booth(understand=understand, logic=logic.do, say=say, feedback=how_was_that_take, tape=Tape(48000),
                  tracks=tracks, session=session,
                  show=None if dry_run else __import__("hiremarco.studio.show", fromlist=["show"]).show,
                  live=None if dry_run else _booth_live,
                  writer=None if dry_run or (config.get("HIREMARCO_LIVE_WORDS") or "on") == "off" else Writer(),
                  send_link=None if dry_run or (config.get("HIREMARCO_TEXT_LINKS") or "off") != "on" else _text_owner,
                  say_stopped=None if talkback is None else (lambda: talkback.say_stock(STOPPED)),
                  hearing=None if dry_run else _booth_hearing, reference=None if dry_run else _booth_reference,
                  key=config.get("HIREMARCO_SONG_KEY") or "",
                  plugin=None if dry_run else Channel(),
                  transcribe=lambda audio, r: transcribe(audio, r, diarize=False),
                  play_clip=(lambda pcm, label: print(f"   (guide, dry run: {label})")) if dry_run
                  else (lambda pcm, label: talkback.play_clip(pcm, label)))

    async def main() -> None:
        loop = asyncio.get_running_loop()
        chunks: asyncio.Queue[bytes] = asyncio.Queue()

        quiet_until = [0.0]

        def on_input(mono: np.ndarray) -> None:
            if mono.size == 0:
                return  # a glitch delivered nothing; sending an empty frame would break the hearing session
            booth.tape.write(mono)
            # While Marco talks, and a breath after, his hearing gets silence: the mic picks up his voice from the
            # headphones, and he answered himself (live 2026-10-29). The stream keeps its pace with zeros.
            now = time.monotonic()
            if audio.speaking:
                quiet_until[0] = now + MIC_TAIL
            heard = np.zeros_like(mono) if now < quiet_until[0] else mono
            loop.call_soon_threadsafe(chunks.put_nowait, to_pcm24k(heard, audio.rate).tobytes())

        async def mic():
            while True:
                yield await chunks.get()

        audio = DuplexAudio.from_config(on_input)
        booth.tape = Tape(audio.rate)
        if talkback is not None:
            talkback.play = audio.play
        halo = None
        if (config.get("HIREMARCO_HALO") or "on") != "off":
            from hiremarco.studio.halo import Halo, booth_state

            halo = Halo(lambda: booth_state(booth, audio))
            try:
                halo.start()
                subprocess.run(["osascript", "-e", 'tell application "Logic Pro" to activate'], timeout=10)
                print("halo: up; it shows over Logic while Logic is in front")
            except Exception as exc:  # the halo is the look, not the work: the booth runs without it
                print(f"   (halo off: {type(exc).__name__}: {str(exc)[-160:]})")
                halo = None
        if halo is not None:
            _HALO.append(halo)
        threading.Thread(target=_shortcut_listener, args=(booth, lock), daemon=True).start()
        if not dry_run:
            threading.Thread(target=_open_live_view, daemon=True).start()
        with audio:
            print(f"booth live on {audio.device or 'the default interface'}, mic channel {audio.mic_channel}, "
                  f"Marco on outputs {audio.out_pair[0]}-{audio.out_pair[1]}, one stream"
                  + (" (dry run)" if dry_run else "") + "; Ctrl+C stops")
            if session is not None:
                print(f"session: {len(session.tracks)} track(s), {session.mode} mode"
                      + (f" (track scan failed: {session.scan_error})" if session.scan_error else ""))
            # His hearing is one realtime session; if the service drops it, open another and keep listening.
            while True:
                try:
                    def heard_name(partial: str) -> None:
                        if calls_marco(partial):
                            booth.called_at = time.monotonic()

                    async for line in Listener(on_partial=heard_name).sentences(mic()):
                        await asyncio.to_thread(booth.hear, line)
                    break  # the mic closed
                except RuntimeError as dropped:
                    print(f"   (hearing dropped: {dropped}; reconnecting)")
                    while not chunks.empty():  # audio from the dead session would arrive out of context
                        chunks.get_nowait()
                    await asyncio.sleep(0.5)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    if _LIVE:
        _LIVE[0].stop()
    if _HALO:
        _HALO[0].stop()
    print(f"booth closed: {len(booth.notes)} note(s), {len(booth.producer_notes)} producer note(s)")
    return 0

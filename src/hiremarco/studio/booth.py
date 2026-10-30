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

import os
import random
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

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
THINKING = ["Hmm.", "Okay.", "Let me see.", "One sec.", "Mm, okay."]
STOP_ALONE = {"stop", "stop stop", "okay stop", "ok stop", "cut", "cut it", "stop recording", "stop the take",
              "hold on", "hold up", "stop there", "let's stop", "lets stop"}
COUNT_IN_SECONDS = float(os.environ.get("HIREMARCO_COUNT_IN_SECONDS", "0"))  # Logic's count-in, if on
TUNE_CENTER, TUNE_DRIFT = 80.0, 30.0  # a first pass that still sounds like the artist; the last 20% is theirs
FLEX_REFERENCE_LIMIT = 5.0  # cents off 440 beyond which Flex Pitch is skipped for the session (Owner 2026-10-29)
AUTO_NOTE_SECONDS = 8  # a take this long or longer gets his note when it stops; shorter is a test or a false start
FILLER_AFTER = 0.7  # seconds of thinking before he lets you know he is on it
MIC_TAIL = 0.4  # seconds his hearing stays muted after he stops talking
ECHO_SECONDS = 15.0  # how long a line of his can come back through the mic as an echo
HERE = "Yeah?"
# The instant answer to his name: pre-made so it plays at once, picked so it never sounds like a loop. Cool and
# warm, never curt (Owner 2026-10-29: "Go ahead" reads as rude, so it and its cousins are out).
HEARD = ["Talk to me.", "What's up?", "Yeah?", "I'm here.", "Right here.", "What's good?", "I'm listening.",
         "Hey, what's up?", "I got you, what's up?", "What are we thinking?"]
AFTER_TAKE = ["How we feeling?", "Talk to me.", "What you thinking?"]
DISMISSED = "Anytime."
AWAKE = 20.0  # seconds after the last exchange in which a sentence needs no "Marco"; the same quiet ends the halo
LIVE_ON = "Live view's on. The link's on the Mac."
LIVE_TEXTED = "Live view's on. I texted you the link."
STOPPED = "Stopped. Everything's held until you clear it from the desk."
# Lines Marco says often, made once at the start so they play the moment they are needed.
STOCK = ["Rolling", *HEARD, *THINKING, *AFTER_TAKE, DISMISSED, LIVE_ON, LIVE_TEXTED, NOTED, LISTENING, DIALING, MISSED, FAILED, STOPPED, "Here's how it goes.", "What key are we in?", "Put it back.",
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
    reference_cents: float = 0.0                      # the beat's tuning against A = 440: Auto-Tune and his pass follow it
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
    on_place: Callable[[str], None] | None = None     # "booth" or "desk": chosen by the artist, not by the mode
    history: list[str] = field(default_factory=list)  # the recent exchanges and what was done, for his replies
    offer: Callable[[], str] | None = None            # what a "yes" does: the last thing he offered
    soloed: bool = False                              # he soloed a track, and takes it off before the next take
    a_cappella: bool = False                          # this take is recorded with the vocal soloed, on purpose
    take_start: object | None = None                  # (Position, tempo, beats per bar) read when the take began
    auto_note: bool = False                           # a note after every take of AUTO_NOTE_SECONDS or more
    fillers: bool = True                              # "Hmm." while he thinks; off in tests that count lines
    _filled: bool = False
    _beat_region: str = ""                            # the beat region last read, for Logic's own tempo reading
    _asked_after_take: bool = False                   # the after-take answer is used once per take
    send_link: Callable[[str, str], str] | None = None  # (body, url) to the artist's phone; None or a refusal: the Mac
    console: object | None = None                     # studio.console.Console: the UAD inputs, Auto-Tune on the vocal
    surface: Callable[[str], str] | None = None       # one command to his Mackie surface, its reply
    flex: Callable[[str], str] | None = None          # Flex Pitch's first pass in the given key, its read-back
    vocal_input: int = 0                              # the Console channel the vocal mic comes in on (ANALOG 1)
    load_beat: Callable[..., str] | None = None       # studio.beat_in.BeatLoader.load: a session with the beat on Beat
    text_owner: Callable[[str], str] | None = None    # one WhatsApp text to the artist; None: the line is said only
    last_setup: dict = field(default_factory=dict)    # the key, tempo and beat gain the session was last set to

    def beat_arrived(self, path: Path, name: str | None = None) -> str:
        """A beat in his inbox (Owner 2026-10-29): a new session from the template with the beat on the Beat track
        inside PROD, then read and set, tempo, beat level and the Console's key, without waiting for a yes (Owner
        2026-10-30: a sent beat means set it up), and a text to him when it is done. Held while a take rolls."""
        if self.load_beat is None:
            return "no beat loader in this booth"
        if self.rolling:
            return "holding the beat until the take stops"
        self._say("a beat arrived; opening a session from the template with it on the Beat track",
                  {"file": path.name, "song": name}, "Got the beat. Setting up the session.")
        try:
            loaded = self.load_beat(path, name) if name else self.load_beat(path)
        except Exception as exc:  # the file stays where it was; he hears why
            self._say("could not put the beat in a session", {"file": path.name, "why": str(exc)[-160:]},
                      "I couldn't put the beat in the session. It's still in the inbox.")
            self._text(f"I couldn't put {path.name} in a session. It's still in the inbox.")
            return f"beat not loaded: {type(exc).__name__}: {str(exc)[-160:]}"
        if self.tracks is not None:
            self.session = self.tracks.scan()
        self.last_setup = {}
        read = self._read_beat(ask=False)
        setup = ""
        if self.offer is not None:
            apply, self.offer = self.offer, None
            setup = apply()
        done = self.last_setup
        song = name or path.stem
        if done:  # Owner 2026-10-30: the text is just "session's ready."; the details are in Logic and the log
            sent = self._text("session's ready.")
        else:
            sent = self._text(f"{song} is on the Beat track, but I couldn't read its key and tempo.")
        return f"{loaded}; {read}; set: {setup or 'nothing'}; {sent}"

    def _text(self, body: str) -> str:
        if self.text_owner is None:
            return "no text line"
        try:
            return f"texted: {self.text_owner(body)}"
        except Exception as exc:  # outside the window, held by the gate, or the line is down; the log says which
            return f"not texted: {type(exc).__name__}: {str(exc)[-80:]}"

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

    def session_facts(self) -> str:
        """What a good engineer has in his head without asking: the mode, the tracks, whether a take is rolling."""
        mode = self.session.mode if self.session is not None else "recording"
        tracks = [t.name for t in self.session.tracks][:24] if self.session is not None else []
        take = "a take is rolling" if self.rolling else ("a take was just recorded" if self.tape.take else "no take yet")
        return f"session: {mode} mode; tracks: {', '.join(tracks) or 'unknown'}; {take}; key: {self.key or 'not set'}"

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
        if self.writer is None:
            self._speak(plain)
            return
        facts = {**facts, "session": self.session_facts()}
        self._speak(self._in_time(lambda: self.writer.line(moment, facts, plain)))

    def _in_time(self, work: Callable[[], object]) -> object:
        """Run ``work``; if it is still thinking after FILLER_AFTER, say a short "Hmm." once per exchange, the
        way a person does, instead of a silence that feels like a dropped line."""
        box: dict = {}

        def run() -> None:
            try:
                box["value"] = work()
            except BaseException as exc:  # handed back to the caller as it was
                box["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(FILLER_AFTER)
        if worker.is_alive() and not self._filled and not self.rolling and self.fillers:
            self._filled = True
            fresh = [line for line in THINKING if line not in self.recent_answers[-2:]] or THINKING
            line = random.choice(fresh)
            self.recent_answers.append(line)
            self._speak(line)
        worker.join()
        if "error" in box:
            raise box["error"]
        return box["value"]

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
        elif self.rolling and strip_wake(line) is None and " ".join(_words(line)) in STOP_ALONE:
            # a take: "stop" said on its own ends it without his name (Owner 2026-10-29); a lyric is never
            # just the word, and everything else sung stays the artist's
            line = "Marco, stop."
        self._filled = False
        try:
            command = self._in_time(lambda: self.understand(line))
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
        self.history.append(f"artist: {line} | done: {result} | marco said: {self.last_said}")
        del self.history[:-8]
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
                return self.tracks.rename(track_title(command.text))
            if a == "stack":
                stem = _stem(command.text)
                named = [t.name for t in self.session.tracks if stem in _stem(t.name)]
                return self.tracks.stack(named or [command.text])
        except NotMapped as later:
            self._say("cannot do this one yet", {"asked": command.action, "why": str(later)},
                      "Noted. I'll do that one from the desk.")
            return str(later)
        return "nothing to do"

    def _tune_take(self) -> str:
        """His first tuning pass on the selected track's take: his ear, two amounts, a new file beside the take."""
        from hiremarco.studio import analyze, tune

        if self.rolling:
            return "holding the first pass until the take stops"
        if not self.key:
            self._speak("What key are we in?")
            return "asked for the key before tuning"
        if self.tracks is None:
            return "no track control in this booth"
        regions = self.tracks.regions()
        path = analyze.find_audio(regions[-1]) if regions else None
        if path is None:
            self._say("could not find the take's file to tune", {"regions": regions[-3:]},
                      "I can't find that take's file. Select the vocal track and ask me again.")
            return "no take file found"
        target, before, after = self._in_time(lambda: tune.first_pass(path, self.key, center=TUNE_CENTER,
                                                                      drift=TUNE_DRIFT,
                                                                      reference_cents=self.reference_cents))
        subprocess.run(["open", "-R", str(target)], capture_output=True)  # in Finder, to drag under the take
        self._say("finished a first tuning pass; the tuned take is a new file next to the original, shown in Finder",
                  {"notes": before["notes"], "median_cents_off_before": before["median_cents_off"],
                   "median_cents_off_after": after["median_cents_off"], "vibrato_notes_left_alone": before["vibrato_notes"],
                   "amounts": f"center {TUNE_CENTER:g}, drift {TUNE_DRIFT:g}"},
                  f"First pass done. {before['median_cents_off']:g} cents off down to {after['median_cents_off']:g}. "
                  "It's in Finder next to your take.")
        return (f"first pass on {path.name}: median {before['median_cents_off']} to {after['median_cents_off']} cents off, "
                f"{before['notes']} notes, vibrato kept on {before['vibrato_notes']}; wrote {target.name}")

    def _beat(self):
        """The selected track's audio, read for key and tempo: (reading, file), or why not, already said."""
        from hiremarco.studio import analyze

        if self.tracks is None:
            return "no track control in this booth"
        regions = self.tracks.regions()
        if not regions:
            self._say("the selected track has no audio to read", {}, "Select the beat's track and ask me again.")
            return "no regions on the selected track"
        path = analyze.find_audio(regions[0])
        if path is None:
            self._say("could not find the beat's file", {"region": regions[0]}, "I can't find that file on the Mac.")
            return f"no file found for {regions[0]!r}"
        self._beat_region = regions[0]
        return self._in_time(lambda: analyze.read(path)), path

    def console_check(self) -> str:
        """At the booth's start: what the Console's Auto-Tune still holds from the last session. It is reset
        from this session's beat at setup ("what key is the beat in?" and yes); until then it is not trusted."""
        if self.console is None:
            return "no Console in this booth"
        try:
            controls = self.console.params(self.vocal_input, self.console._auto_tune_slot(self.vocal_input))
        except Exception as exc:
            return f"Console Auto-Tune not read: {type(exc).__name__}: {str(exc)[-100:]}"
        shown = {name: (controls.get(name) or {}).get("shown") for name in ("Key", "Scale", "Detune")}
        held = f"{shown['Key']} {str(shown['Scale']).lower()}, {shown['Detune'] or '0'} cents"
        return f"Console Auto-Tune holds {held} from before; reset at setup from this session's beat"

    def _logic_tempo(self, region: str) -> tuple[list[float], str]:
        """Logic's Smart Tempo on the beat, as an engineer starts a session (Owner 2026-10-29): the region selected
        from the surface, Apply Region Tempo to Project Tempo, the map read, then undone, so only the settled
        whole tempo is written."""
        if self.surface is None or self.tracks is None or not hasattr(self.tracks, "region_tempo"):
            return [], "no Logic tempo control in this booth"
        try:
            self.surface(f"select {region.replace(' ', '+')}")
            self.tracks.region_tempo(region)
            events = self.tracks.tempo_map()
            self.tracks.undo("Apply Region Tempo to Project Tempo")
        except Exception as exc:  # his own reading still stands
            return [], f"Logic's reading not taken: {type(exc).__name__}: {str(exc)[-120:]}"
        return events, f"Logic's map: {len(events)} event(s)"

    def _beat_key(self, reading, path) -> tuple[str, str]:
        """The key to use and why. A producer's own label (the beat's file name, else a track named like
        "..._Em") outranks the ear, which picks the right notes on about 58% of labelled loops and the right home
        key on 36% (measured 2026-10-29 on 180 of the Owner's loops)."""
        from hiremarco.studio import analyze

        names = [path.stem] + ([t.name for t in self.session.tracks] if self.session is not None else [])
        labelled = next((k for k in (analyze.label(n)[0] for n in names) if k), None)
        if labelled and analyze.same_notes(labelled, reading.key):
            return labelled, f"your files say {labelled} and the ear hears the same notes"
        if labelled:
            return labelled, f"your files say {labelled}; the ear heard {reading.key}"
        return reading.key, f"by ear, an estimate (same notes as {analyze.relative(reading.key)})"

    def _read_beat(self, ask: bool = True) -> str:
        """The selected track's audio: its key and tempo, said, and offered for the session. ``ask`` False: read and
        left as the offer without the question, for a caller that applies it at once (a beat he sent)."""
        found = self._beat()
        if isinstance(found, str):
            return found
        reading, path = found
        key, why = self._beat_key(reading, path)
        from hiremarco.studio.analyze import label, settle_tempo

        events, logic_note = self._in_time(lambda: self._logic_tempo(self._beat_region))
        bpm, tempo_why = settle_tempo(reading.bpm, label(path.stem)[1], events)
        region = self._beat_region
        try:
            gain, loud, peak = self._beat_level(path)
        except Exception as exc:  # key and tempo still stand; the level is left as it is and the log says why
            gain, loud, peak = None, None, f"not measured: {type(exc).__name__}"
        try:
            from hiremarco.studio.analyze import tuning

            a4, cents = self._in_time(lambda: tuning(path))
        except Exception:  # the reference stays at 440 and the log line says so
            a4, cents = None, None

        def apply() -> str:
            self.last_setup = {"key": key, "bpm": bpm, "gain": gain}
            self.key = key
            self.reference_cents = cents or 0.0
            done = [f"key {key} for pitch checks"]
            try:
                done.append(self.tracks.set_tempo(bpm))
            except Exception as exc:  # the key still stands; the log says why the tempo did not
                done.append(f"tempo not set: {type(exc).__name__}: {str(exc)[-80:]}")
            if self.console is not None:  # the Console's Auto-Tune follows the session key
                from hiremarco.studio.analyze import split_key

                try:
                    self.console.tune(self.vocal_input, *split_key(key))
                    if cents is not None:
                        done.append(f"Auto-Tune reference {self.console.detune(self.vocal_input, cents)} (A = {a4:g} Hz)")
                    done.append(f"Auto-Tune on {key}")
                except Exception as exc:
                    done.append(f"Auto-Tune not set: {type(exc).__name__}: {str(exc)[-80:]}")
            if gain is not None:
                done.append(self._set_beat_gain(region, gain))
            self._say("set the session from the beat", {"key": key, "tempo": bpm, "beat_gain_db": gain, "done": done},
                      f"Done. {key}, {bpm:g}" + (", and the beat's sitting at minus twenty." if gain is not None else "."))
            return "; ".join(done)

        self.offer = apply
        if ask:
            self._say("read the beat's key and tempo and its level; offer to set the session to it", {
                "key": key, "how_the_key_was_found": why, "bpm": bpm, "how_the_tempo_was_found": tempo_why,
                "or_half_double": reading.bpm_other or None, "beat_loudness_lufs": loud, "beat_true_peak_db": peak,
                "region_gain_to_reach_minus_20_lufs": gain, "beat_tuning_a4_hz": a4},
                f"Sounds like {key}, {bpm:g} BPM. The beat's hot, so I'll bring it down {abs(gain):g} dB. Set the session?"
                if gain is not None and gain < 0 else f"Sounds like {key}, {bpm:g} BPM. Want me to set the session to that?")
        return (f"beat read from {path.name}: {key} ({why}), {bpm:g} BPM ({tempo_why}; {logic_note}); "
                + (f"level {loud} LUFS, true peak {peak} dBTP, gain {gain:+.1f} dB to reach -20 LUFS" if gain is not None
                   else f"level {peak}") + (f"; tuning A = {a4:g} Hz ({cents:+g} cents)" if a4 else "; tuning not measured"))

    def _beat_level(self, path) -> tuple[float, float, float]:
        """The region gain that puts this beat at -20 LUFS with peaks under -6 dBTP, from the file itself."""
        import soundfile as sf

        from hiremarco.mix.ears import beat_gain

        audio, rate = sf.read(str(path), always_2d=True)
        return beat_gain(audio, rate)

    def _set_beat_gain(self, region: str, gain: float) -> str:
        if self.tracks is None or not hasattr(self.tracks, "region_gain"):
            return "beat gain not set: no Logic control in this booth"
        try:
            if self.surface is not None:
                self.surface(f"select {region.replace(' ', '+')}")  # the inspector shows the selected region
            return self.tracks.region_gain(region, gain)
        except Exception as exc:  # the session is set otherwise; the level is said to be undone
            return f"beat gain not set: {type(exc).__name__}: {str(exc)[-100:]}"

    def _stage_beat(self) -> str:
        """The beat at -20 LUFS on its own, without reading key and tempo again."""
        if self.tracks is None:
            return "no track control in this booth"
        from hiremarco.studio import analyze

        regions = self.tracks.regions()
        path = analyze.find_audio(regions[0]) if regions else None
        if path is None:
            self._say("could not find the beat's file", {}, "Select the beat's track and ask me again.")
            return "no beat file found"
        gain, loud, peak = self._in_time(lambda: self._beat_level(path))
        done = self._set_beat_gain(regions[0], gain)
        self._say("set the beat's level to -20 LUFS with region gain", {"loudness_before": loud, "gain": gain,
                  "result": done}, f"Beat's at minus twenty. Down {abs(gain):g} dB." if "not set" not in done
                  else "I couldn't set the beat's gain.")
        return f"{done} (was {loud} LUFS, {peak} dBTP)"

    def _tune_console(self, said_key: str) -> str:
        """The Console's Auto-Tune on the vocal input, pointed at a key: the one said, else the session's, else the
        beat's (read now from the selected track). The gentle base comes with it; Flex does the tight work later."""
        from hiremarco.studio.analyze import split_key

        if self.console is None:
            return "no Console in this booth"
        key, read = said_key or self.key, ""
        if not key:
            found = self._beat()
            if isinstance(found, str):
                return found
            key, why = self._beat_key(*found)
            read = f"read the beat as {key} ({why}); "
        try:
            root, scale = split_key(key)
            shown = self._in_time(lambda: self.console.tune(self.vocal_input, root, scale))
        except Exception as exc:  # Console closed, no Auto-Tune on the input, or a key it does not list
            self._say("could not set the Console's Auto-Tune", {"key": key, "why": str(exc)[-160:]},
                      "I couldn't set the Auto-Tune. Is Console open with it on your input?")
            return f"{read}Auto-Tune not set: {type(exc).__name__}: {str(exc)[-120:]}"
        self.key = key  # the tune and the pitch checks agree on one key
        self._say("set the Console's Auto-Tune on the vocal to the key, with a gentle base", {
            "key": key, "settings": shown}, f"Auto-Tune's on {root} {scale}.")
        return f"{read}Auto-Tune on input {self.vocal_input + 1}: " + ", ".join(f"{k} {v}" for k, v in shown.items())

    def _flex_pass(self) -> str:
        """Flex Pitch's first pass on the take in the editor: the session key and Pitch Correction 80."""
        if self.flex is None:
            return "no Flex control in this booth"
        if self.rolling:
            return "holding the Flex pass until the take stops"
        if not self.key:
            self._speak("What key are we in?")
            return "asked for the key before Flex"
        if abs(self.reference_cents) > FLEX_REFERENCE_LIMIT:
            # Flex Pitch corrects to A = 440 here; on a beat tuned elsewhere the vocal would land off the beat
            # (Owner ruling 2026-10-29: skip Flex for those sessions, Auto-Tune and his own pass instead)
            self._say("Flex Pitch would tune to 440 but the beat is tuned elsewhere; offer his own pass instead",
                      {"beat_tuning_cents": self.reference_cents},
                      f"This beat sits {self.reference_cents:+g} cents off 440, so Flex would pull you off it. "
                      "Want my tuning pass instead? It follows the beat.")
            self.offer = self._tune_take
            return f"Flex skipped: beat at {self.reference_cents:+g} cents; offered his own pass"
        try:
            shown = self._in_time(lambda: self.flex(self.key))
        except Exception as exc:  # the editor not open on the take, or Logic not showing Flex
            self._say("could not run the Flex Pitch pass", {"why": str(exc)[-200:]},
                      "Flex didn't take. Open the take in the editor with Flex Pitch on and ask me again.")
            return f"Flex not applied: {type(exc).__name__}: {str(exc)[-160:]}"
        self._say("ran a first Flex Pitch pass on the take; it is in Logic to listen to", {"read_back": shown},
                  "First pass is in Flex. Have a listen.")
        return f"Flex first pass: {shown}"

    def _surface_track(self, words: str) -> str:
        """The track a plug-in goes on, as the surface takes it: "selected", or a name with "+" for its spaces."""
        if not words:
            return "selected"
        names = [t.name for t in self.session.tracks] if self.session is not None else []
        hits = [n for n in names if words.lower() in n.lower()]
        return (hits[0] if len(hits) == 1 else words).replace(" ", "+")

    def _insert_plugin(self, command: Command) -> str:
        """A plug-in into a Logic insert slot through his Mackie surface: the first empty slot unless one was said."""
        if self.surface is None:
            return "no control surface in this booth"
        if self.rolling:
            return "holding the plug-in until the take stops"
        if not command.text:
            self._speak("Which plug-in?")
            return "asked which plug-in"
        track = self._surface_track(command.track)
        try:
            reply = self._in_time(lambda: self.surface(f"insert {track} {command.slot} {command.text}"))
        except OSError:
            self._say("the control surface is not running", {}, "My control surface isn't up. Give me a second.")
            return "surface not running"
        answer = reply.splitlines()[0] if reply else "no answer"
        if answer.startswith(("bad command", "unknown")):
            self._say("could not insert the plug-in", {"asked": command.text, "why": answer},
                      f"Couldn't get {command.text} in. {answer.split(': ', 1)[-1]}")
            return f"insert refused: {answer}"
        self._say("put the plug-in on the track", {"asked": command.text, "result": answer}, f"{command.text}'s in.")
        return answer

    def _unsolo_for_the_take(self) -> None:
        if self.soloed and self.tracks is not None:
            try:
                self.tracks.solo(False)
                self.log("   (solo off for the take)")
            except Exception as exc:  # the take matters more; the log says the solo stayed
                self.log(f"   (solo could not come off: {type(exc).__name__})")
            self.soloed = False

    def _play_back(self, command: Command) -> str:
        """Play the last take from its start, or from a line in it; then it plays and he stays quiet."""
        from hiremarco.studio import pitch
        from hiremarco.studio.logic import markers

        lyric = command.text.strip().lower()
        if command.action == "play_from_lyric" and lyric in ("that", "it", "this", "that part", "it back"):
            command = Command("play_take")
        if command.action == "play_from_lyric":
            try:
                bar = markers().get(lyric)
            except Exception:
                bar = None
            if bar:  # "play from the chorus": a marker, not a lyric
                return self.logic(Command("play_from", text=f"{bar} 1 1 1"))
        if self.rolling:
            self.logic(Command("stop"))
            self.rolling = False
            self.tape.mark_stop()
        if self.take_start is None:
            self._say("cannot play the take back: its start was not read", {}, "I didn't catch where that take started.")
            return "no take start known"
        start, tempo, beats_per_bar = self.take_start
        if command.action == "play_take":
            result = self.logic(Command("play_from", text=start.typed()))
            self.rolling = True
            return f"playing the take from {start.typed()}: {result}"
        take = self.tape.last_take()
        if take.size == 0 or self.transcribe is None:
            return "no take on the tape to search"
        window = pitch.locate(lyric, self.transcribe(take, self.tape.rate))
        if window is None:
            self._say("could not find that line in the take", {"line": lyric}, f"I couldn't find {lyric} in that take.")
            return f"lyric not found: {lyric}"
        lead_in = max(0.0, window[0] - 1.0 - COUNT_IN_SECONDS)  # a second before the line, so it lands on the word
        at = start.later(lead_in, tempo, beats_per_bar)
        result = self.logic(Command("play_from", text=at.typed()))
        self.rolling = True
        return f"playing from {lyric!r} at {at.typed()} (estimate): {result}"

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
        if a == "chat":
            # conversation, not a command: his reply was written with the recent exchanges, so it can say what he
            # did or did not do; nothing is performed
            self._speak(command.text or MISSED)
            return f"talked: {command.text[:80]}"
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
            from hiremarco.studio.tracks import TrackInfo

            self.session.tracks.append(TrackInfo(len(self.session.tracks) + 1, name, 0))  # he knows it is there now
            self._say("made a new track and named it", {"role": command.text, "name": name},
                      f"{name}. Rolling when you are.")
            return f"{made}; {what}"
        if a in ("play_take", "play_from_lyric"):
            return self._play_back(command)
        if a in ("solo", "unsolo"):
            if self.tracks is None:
                return "no track control in this booth"
            done = self.tracks.solo(a == "solo")  # silent: you hear the result
            self.soloed = a == "solo"
            return done
        if a == "tune_take":
            return self._tune_take()
        if a == "read_beat":
            return self._read_beat()
        if a == "stage_beat":
            return self._stage_beat()
        if a == "tune_console":
            return self._tune_console(command.text)
        if a == "flex_pass":
            return self._flex_pass()
        if a == "insert_plugin":
            return self._insert_plugin(command)
        if a == "accept":
            if self.offer is None:
                return self.handle(Command("chat", text=self.writer.line("the artist said yes but nothing was offered; "
                                                                        "ask what they want", {}, "What are we doing?")
                                           if self.writer is not None else "What are we doing?"))
            offer, self.offer = self.offer, None
            return offer()
        if a == "go_again":  # "let's go again": the solo comes off by itself and the next take rolls
            return self.handle(Command("record"))
        if a == "next_part":  # moving on: back to the full mix, then where to pick it up
            self._unsolo_for_the_take()
            self._say("the artist wants to record a different part; ask where to pick it up", {}, "Where do you want to pick it up?")
            return "ready for the next part"
        if a == "a_cappella":  # the one time the solo stays on while recording: the vocal alone, no beat
            if self.tracks is not None and not self.soloed:
                self.tracks.solo(True)
                self.soloed = True
            self.a_cappella = True
            return self.handle(Command("record"))
        if a in ("record", "punch") and not self.rolling and not self.a_cappella:
            self._unsolo_for_the_take()  # an engineer takes the solo off before a take without being told
        if a == "record" and self.tracks is not None and not self.rolling:
            try:
                self.take_start = self.tracks.where()  # where this take begins, to play it back or find a line
            except Exception as exc:  # recording matters more than knowing where; playback will say it cannot
                self.take_start = None
                self.log(f"   (playhead not read: {type(exc).__name__}: {str(exc)[-100:]})")
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
            self.a_cappella = False  # a cappella is for that take
            self.tape.mark_stop()
            self._asked_after_take = False  # a new take: the next answer to his name can ask how it felt
            take = self.tape.last_take()
            if self.auto_note and take.size >= AUTO_NOTE_SECONDS * self.tape.rate:
                # after a real take he says how it went, like a producer would, then moves on: hype when it is
                # good, the one spot to fix when it is not (Owner 2026-10-29)
                note = self.feedback(take, self.tape.rate)
                self.producer_notes.append(note.note)
                self.pending_punch = note.punch_where if note.punch else ""
                self._speak(note.spoken)
                result = f"{result}; take note: {note.spoken}"
        return result


def _song() -> str:
    return config.get("HIREMARCO_SONG") or "untitled"


class Barge:
    """Hearing the artist talk over Marco in the booth.

    The first LEARN blocks of each of his lines measure how much of his voice the mic picks up from the
    headphones (the artist is quiet then, almost always); after that, a mic level more than RATIO times that
    bleed and above FLOOR, for HOLD blocks running, is the artist talking. The blocks muted meanwhile are kept,
    so the first words of the interruption reach his hearing.
    """

    LEARN, RATIO, FLOOR, HOLD, KEEP = 3, 3.0, 0.01, 2, 5

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.blocks = 0
        self.bleed = 0.0
        self.loud = 0
        self.kept: list = []

    def hear(self, mic: float, voice: float, block) -> bool:
        self.blocks += 1
        self.kept = (self.kept + [block])[-self.KEEP:]
        if self.blocks <= self.LEARN:
            if voice > 1e-4:
                self.bleed = max(self.bleed, mic / voice)
            return False
        expected = self.bleed * voice
        self.loud = self.loud + 1 if mic > max(self.FLOOR, self.RATIO * expected) else 0
        return self.loud >= self.HOLD

    def release(self) -> list:
        kept, self.kept = self.kept, []
        self.reset()
        return kept


NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
                "eight": "8", "nine": "9", "ten": "10"}


def track_title(name: str) -> str:
    """'harmony one' -> 'Harmony 1', 'lead vox' -> 'Lead Vox': names as they read on a track header."""
    words = [NUMBER_WORDS.get(w.lower(), w) for w in name.strip().split()]
    return " ".join(w if any(c.isupper() for c in w[1:]) else w[:1].upper() + w[1:] for w in words)


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
        elif data.strip() == b"stop":  # the menu-bar app: Logic quit, Pause, or Quit; the same as Ctrl+C
            import os
            import signal

            os.kill(os.getpid(), signal.SIGINT)
        elif data.strip() == b"live":  # the menu bar's "Text me the live view"
            booth.hear("Marco, give me the live view")
        elif data.strip() in (b"place booth", b"place desk") and booth.on_place is not None:
            booth.on_place(data.strip().split()[1].decode())  # the menu bar's "Listen at"


def _text_owner_plain(body: str) -> str:
    """One WhatsApp text to the artist, through the gate, inside the 24-hour window his own message opened."""
    from hiremarco.whatsapp import WhatsApp

    owner = config.require("OWNER_WHATSAPP")
    return WhatsApp().send_text(owner, body, idempotency_key=f"booth-text:{time.time_ns()}") or "sent"


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


def start_surface(state=None, ask=None, spawn=None) -> str:
    """His Mackie surface, started with the booth when it is not already up, and left running after: Logic keeps
    the surface it found, and a booth restart should not make Logic lose it."""
    import sys

    from hiremarco import config
    from hiremarco.studio import mcu

    state = Path(state or config.STATE_DIR)
    ask = ask or (lambda: mcu.ask(state / "mcu.sock", "screen"))
    try:
        ask()
        return "surface already up"
    except OSError:
        pass
    spawn = spawn or (lambda argv: subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                    stderr=subprocess.DEVNULL, start_new_session=True))
    spawn([sys.executable, "-c", "import sys; from hiremarco.cli import main; sys.exit(main(['mcu', 'serve']))"])
    for _ in range(30):
        time.sleep(0.2)
        try:
            ask()
            return "surface started"
        except OSError:
            continue
    return "surface did not answer; plug-in inserts will say so"


def watch_inbox(booth: "Booth", inbox=None, *, poll: float = 2.0, rounds: int | None = None,
                sleep: Callable[[float], None] = time.sleep) -> list[str]:
    """His beat inbox, every ``poll`` seconds: each new beat once. A beat held for a rolling take comes back on a
    later poll; a loaded one moves to the inbox's "loaded" folder; a failed one stays where it is, tried once."""
    from hiremarco.studio.beat_in import Inbox, requested_name

    inbox = inbox or Inbox()
    tried: set = set()
    results: list[str] = []
    n = 0
    while rounds is None or n < rounds:
        n += 1
        try:
            for path in inbox.ready():
                if path in tried:
                    continue
                name = requested_name(path)
                result = booth.beat_arrived(path, name) if name else booth.beat_arrived(path)
                booth.log(f"beat inbox: {result}")
                results.append(result)
                if result.startswith("holding"):
                    continue
                tried.add(path)
                if not result.startswith(("beat not loaded", "no beat loader")):
                    inbox.done(path)
        except Exception as exc:  # the booth keeps running; the log says what broke
            booth.log(f"beat inbox: {type(exc).__name__}: {str(exc)[-120:]}")
        sleep(poll)
    return results


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
    if not dry_run:
        print(start_surface())
    from hiremarco.studio import flex, mcu
    from hiremarco.studio.console import Console
    booth = Booth(understand=lambda line: understand(line, context=[booth.session_facts(), *booth.history]),
                  logic=logic.do, auto_note=not dry_run, say=say, feedback=how_was_that_take, tape=Tape(48000),
                  tracks=tracks, session=session,
                  show=None if dry_run else __import__("hiremarco.studio.show", fromlist=["show"]).show,
                  live=None if dry_run else _booth_live,
                  writer=None if dry_run or (config.get("HIREMARCO_LIVE_WORDS") or "on") == "off" else Writer(),
                  send_link=None if dry_run or (config.get("HIREMARCO_TEXT_LINKS") or "off") != "on" else _text_owner,
                  say_stopped=None if talkback is None else (lambda: talkback.say_stock(STOPPED)),
                  hearing=None if dry_run else _booth_hearing, reference=None if dry_run else _booth_reference,
                  key=config.get("HIREMARCO_SONG_KEY") or "",
                  plugin=None if dry_run else Channel(),
                  console=None if dry_run else Console(),
                  surface=None if dry_run else (lambda line: mcu.ask(config.STATE_DIR / "mcu.sock", line)),
                  flex=None if dry_run else flex.first_pass,
                  load_beat=None if dry_run else __import__("hiremarco.studio.beat_in", fromlist=["BeatLoader"])
                  .BeatLoader().load,
                  text_owner=None if dry_run else _text_owner_plain,
                  transcribe=lambda audio, r: transcribe(audio, r, diarize=False),
                  play_clip=(lambda pcm, label: print(f"   (guide, dry run: {label})")) if dry_run
                  else (lambda pcm, label: talkback.play_clip(pcm, label)))

    if not dry_run:
        print(booth.console_check())
        threading.Thread(target=watch_inbox, args=(booth,), daemon=True).start()

    async def main() -> None:
        loop = asyncio.get_running_loop()
        chunks: asyncio.Queue[bytes] = asyncio.Queue()

        quiet_until = [0.0]
        barge = Barge()

        rig: dict = {}

        def send(block: np.ndarray) -> None:
            loop.call_soon_threadsafe(chunks.put_nowait, to_pcm24k(block, rig["audio"].rate).tobytes())

        def on_input(mono: np.ndarray) -> None:
            if mono.size == 0:
                return  # a glitch delivered nothing; sending an empty frame would break the hearing session
            audio = rig["audio"]
            booth.tape.write(mono)
            # While Marco talks, and a breath after, his hearing gets silence: the mic picks up his voice from the
            # headphones, and he answered himself (live 2026-10-29). The stream keeps its pace with zeros. If the
            # artist talks over him, clearly louder than that bleed, he stops mid-word and hears the artist,
            # from the blocks held back while he was talking.
            now = time.monotonic()
            if audio.speaking:
                quiet_until[0] = now + MIC_TAIL
                if rig.get("place") == "booth" and barge.hear(audio.in_level, audio.out_level, mono):
                    audio.interrupt()
                    quiet_until[0] = now
                    for held in barge.release():
                        send(held)
                    booth.log("   (talked over: stopped and listening)")
                    return
            else:
                barge.reset()
            send(np.zeros_like(mono) if now < quiet_until[0] else mono)

        async def mic():
            while True:
                yield await chunks.get()

        audio = DuplexAudio.from_config(on_input)
        rig.update(audio=audio, place="booth")
        booth.tape = Tape(audio.rate)
        if talkback is not None:
            talkback.play = audio.play

        def move(place: str) -> None:
            """The booth: the vocal mic and the headphones. The desk: the MacBook mic and the speakers. The artist
            picks it from the menu bar (Owner 2026-10-29: mixing can happen at the mic, so the mode does not)."""
            if place not in ("booth", "desk") or place == rig["place"]:
                return
            try:
                fresh = (DuplexAudio.desk_from_config if place == "desk" else DuplexAudio.from_config)(on_input)
                fresh.start()
            except Exception as exc:  # he stays where he was and says why in the log
                print(f"   (could not move to the {place}: {type(exc).__name__}: {str(exc)[-120:]})")
                return
            old = rig["audio"]
            rig.update(audio=fresh, place=place)
            if talkback is not None:
                talkback.play = fresh.play
            old.stop()
            print(f"   (now at the {place}: listening on {fresh.device}, Marco on {fresh.out_device} "
                  f"{fresh.out_pair[0]}-{fresh.out_pair[1]})")

        booth.on_place = move
        halo = None
        if (config.get("HIREMARCO_HALO") or "on") != "off":
            from hiremarco.studio.halo import Halo, booth_state

            halo = Halo(lambda: booth_state(booth, rig["audio"]))
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
        audio.start()
        try:
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
        finally:
            rig["audio"].stop()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    if _LIVE:
        _LIVE[0].stop()
    if _HALO:
        _HALO[0].stop()
    print(f"booth closed: {len(booth.notes)} note(s), {len(booth.producer_notes)} producer note(s)", flush=True)
    # Leave now: a screen-capture callback still in flight would call into a Python that is shutting down and
    # abort the process (live 2026-10-29: "'NoneType' object is not callable" from ScreenCaptureKit at exit).
    import sys as _sys

    _sys.stdout.flush()
    os._exit(0)

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

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import numpy as np

from hiremarco import config, gate
from hiremarco.studio.commands import Command
from hiremarco.studio.feedback import TakeNote

ROLLING = {"record", "play", "punch"}
TAPE_SECONDS = 10 * 60
NOTED = "That's in the mix notes."
LISTENING = "Let me listen."
DIALING = "Let me dial that in."
MISSED = "I missed that. Say it again?"
STOPPED = "Stopped. Everything's held until you clear it from the desk."
# Lines Marco says often, made once at the start so they play the moment they are needed.
STOCK = ["Rolling", NOTED, LISTENING, DIALING, MISSED, STOPPED, "Here's how it goes.", "What key are we in?", "Put it back.",
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
    say_stopped: Callable[[], bool] | None = None     # the cache-only player for STOPPED, after the switch is on
    hearing: Callable[[], str] | None = None          # the full read, spoken, then the question
    reference: Callable[[str], str] | None = None     # "sound like X" -> the signature, spoken short

    def _speak(self, text: str) -> None:
        try:
            self.say(text)
        except gate.Refused as held:
            self.log(f"   (held talkback: {held.reason})")

    def hear(self, line: str) -> str | None:
        started = time.monotonic()
        try:
            command = self.understand(line)
        except gate.Refused as refused:
            return self._done(f"heard: {line}", f"held: {refused.reason}", started)
        if command is None:
            return None  # not addressed to Marco
        try:
            result = self.handle(command)
        except gate.Refused as refused:
            result = f"held: {refused.reason}"
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
                self._speak(f"{command.text.capitalize()} mode.")
                return f"mode set: {command.text}"
            self._speak(f"We're {self.session.mode}.")
            return f"mode: {self.session.mode}"
        if a == "balanced_watch":
            self.session.balanced_watch = command.text == "on"
            self._speak("I'll keep it balanced as we go." if self.session.balanced_watch else "Okay, just recording.")
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
                self._speak(f"{name}. Rolling when you are.")
                return what
            if a == "name_track":
                return self.tracks.rename(command.text)
            if a == "stack":
                stem = _stem(command.text)
                named = [t.name for t in self.session.tracks if stem in _stem(t.name)]
                return self.tracks.stack(named or [command.text])
        except NotMapped as later:
            self._speak("Noted. I'll do that one from the desk.")
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
        if a == "unknown":
            # He heard his name but could not place the line: say so, never guess and never go quiet.
            self._speak(MISSED)
            return "not a studio command, nothing done; asked him to say it again"
        if a == "note":
            self.notes.append(command.text)
            self._speak(NOTED)
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
        return result


def _song() -> str:
    return config.get("HIREMARCO_SONG") or "untitled"


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

    import sounddevice as sd

    from hiremarco import config
    from hiremarco.hearing import Listener, to_pcm24k
    from hiremarco.studio.commands import understand
    from hiremarco.studio.feedback import how_was_that_take
    from hiremarco.studio.logic import Logic
    from hiremarco.studio.chain import Channel
    from hiremarco.voice import Talkback

    device = config.get("HIREMARCO_MIC_DEVICE") or None
    channel = int(config.get("HIREMARCO_MIC_CHANNEL") or 1)
    rate = int(config.get("HIREMARCO_MIC_RATE") or 48000)
    logic = Logic(dry_run=dry_run)
    booth: Booth

    talkback = None if dry_run else Talkback(lambda: booth.rolling)
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
    booth = Booth(understand=understand, logic=logic.do, say=say, feedback=how_was_that_take, tape=Tape(rate),
                  tracks=tracks, session=session,
                  show=None if dry_run else __import__("hiremarco.studio.show", fromlist=["show"]).show,
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

        def callback(indata, frames, time_info, status) -> None:
            mono = np.asarray(indata)[:, channel - 1].copy()
            booth.tape.write(mono)
            loop.call_soon_threadsafe(chunks.put_nowait, to_pcm24k(mono, rate).tobytes())

        async def mic():
            while True:
                yield await chunks.get()

        with sd.InputStream(device=device, channels=channel, samplerate=rate, dtype="float32",
                            blocksize=rate // 10, callback=callback):
            print(f"booth live on {device or 'the default input'} channel {channel}"
                  + (" (dry run)" if dry_run else "") + "; Ctrl+C stops")
            if session is not None:
                print(f"session: {len(session.tracks)} track(s), {session.mode} mode")
            async for line in Listener().sentences(mic()):
                await asyncio.to_thread(booth.hear, line)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    print(f"booth closed: {len(booth.notes)} note(s), {len(booth.producer_notes)} producer note(s)")
    return 0

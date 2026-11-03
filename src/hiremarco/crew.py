"""Roll, Action, Cut: the Owner's crew words on set, carried out with no model in the loop and never on Marco Live.

The Owner texts the exact word (Owner 2026-11-03):

    Roll        every screen and the Apollo start recording into the day's folder on the LaCie
    Roll test   the same, into 13-footage/clap-test
    Action      a take marker
    Cut         the recording stops

Nothing of it reaches the event stream, Marco does not answer on WhatsApp (the chat is on camera and the glasses are
a linked device), and spoken crew words or slates ("Session, take 2", "B-roll, the keys") are set talk, never a
command. The only exception is a problem: when a stream cannot start or dies and cannot be restarted, Marco plays the
problem sound and texts the Owner what is wrong.

Roll: the LaCie is checked first (never a silent fallback to the Mac), the recorder starts as its own process
(``marco film roll``, opened through a hidden Terminal, because a process Marco's server starts itself is refused the
screen while one Terminal starts has it: live 2026-11-03, the booth's rule too), and Marco waits until every stream
is live. Only then the count-in plays, on the MacBook's own
speakers (picked by name, so the cameras hear it) and on Marco's Apollo channel (the headphones and the film's audio).
The long fourth beep is the Roll instant written to ``screen/slate.jsonl``. Right after the count the monitors are
muted if they were not already; Cut unmutes them only if Marco muted them. The speakers' level does not move from Roll
to Cut (``monitor.ROLLING_FLAG``).
"""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import numpy as np

from hiremarco import config, events

FOOTAGE = Path("/Volumes/LaCie/hireMarco Hackathon/13-footage")
SOUNDS_ON_LACIE = Path("/Volumes/LaCie/hireMarco Hackathon/pre-production/set-sound-options")
ROLL_SOUND, CUT_SOUND, PROBLEM_SOUND = "E-countin-roll.wav", "E-countin-cut.wav", "Z-problem.wav"
ROLL_MARK_S = 1.5             # the long fourth beep's onset in the count-in: the Roll instant
MACBOOK_SPEAKERS = "MacBook Pro Speakers"
READY_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 40.0
WATCH_S = 2.0
STATUS = "screenrec.json"

_WORDS = {"roll": "roll", "roll test": "roll test", "action": "action", "cut": "cut"}
_SCENES = r"(session|morning|cold open|email|long night|balcony|scene [\w-]+)"
_NUMBER = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"


def _plain(said: str) -> str:
    text = " ".join(said.lower().replace("’", "'").split())
    return re.sub(r"[.!,]+$", "", text).strip()


def words(said: str) -> str | None:
    """The crew word when the whole message is one, else None: "Roll", "roll.", "ROLL TEST", "Cut!"."""
    return _WORDS.get(_plain(said or ""))


def set_talk(heard: str) -> bool:
    """Spoken crew words and slates: said on set, for the cameras and the editor, never to Marco."""
    text = re.sub(r"[.!?,]", "", _plain(heard or ""))
    if text in ("roll", "rolling", "roll test", "action", "cut", "speed", "mark", "marker", "mark it", "camera rolling",
                "sound speed", "roll sound", "roll camera", "and action", "and cut"):
        return True
    if re.fullmatch(rf"({_SCENES}|[\w' -]{{1,30}}) take {_NUMBER}( again)?", text):
        return True
    return bool(re.match(r"^b ?-?roll\b", text))


# ------------------------------------------------------------------------------------------------ where it goes

def day_folder(test: bool = False, *, root: Path = FOOTAGE, now: datetime | None = None) -> Path:
    return root / ("clap-test" if test else (now or datetime.now()).strftime("%Y-%m-%d"))


def local_iso(t: float) -> str:
    return datetime.fromtimestamp(t).astimezone().isoformat(timespec="milliseconds")


def slate(folder: Path, kind: str, at: float, **more) -> dict:
    row = {"file": "slate", "kind": kind, "at": local_iso(at), **more}
    path = folder / "screen" / "slate.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        out.write(json.dumps(row) + "\n")
    return row


def status_path() -> Path:
    return Path(config.STATE_DIR) / STATUS


def read_status(path: Path | None = None) -> dict:
    try:
        return json.loads((path or status_path()).read_text())
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------------------------------------ sounds

def sound_path(name: str) -> Path | None:
    """The cue from the state folder (copied there the first time it is found on the LaCie), so the problem sound
    still plays when the LaCie is the problem."""
    kept = Path(config.STATE_DIR) / "sounds" / name
    source = SOUNDS_ON_LACIE / name
    try:
        if source.exists() and (not kept.exists() or kept.stat().st_size != source.stat().st_size):
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_bytes(source.read_bytes())
    except OSError:
        pass
    return kept if kept.exists() else None


def outputs() -> list[tuple[str | None, list[int] | None]]:
    """Where a cue plays: the MacBook's speakers by name, and Marco's channel pair on the Apollo."""
    from hiremarco.voice.talkback import channel_pair

    apollo = config.get("HIREMARCO_TALKBACK_DEVICE") or "Universal Audio Thunderbolt"
    return [(MACBOOK_SPEAKERS, None), (apollo, channel_pair(config.get("HIREMARCO_TALKBACK_CHANNELS")))]


def _play_on(device: str | None, mapping: list[int] | None, pcm: np.ndarray, rate: int, started: dict) -> None:
    import sounddevice as sd

    stereo = pcm if pcm.ndim == 2 else np.column_stack([pcm, pcm])
    stereo = stereo[:, :2] if stereo.shape[1] >= 2 else np.column_stack([stereo[:, 0], stereo[:, 0]])
    width = max(mapping) if mapping else 2
    block = np.zeros((len(stereo), width), dtype=np.float32)
    for i, channel in enumerate(mapping or [1, 2]):
        block[:, channel - 1] = stereo[:, i]
    with sd.OutputStream(device=device, channels=width, samplerate=rate, dtype="float32") as out:
        started.setdefault("at", time.time() + float(out.latency or 0.0))
        out.write(block)
        time.sleep(float(out.latency or 0.0) + 0.05)


def play(name: str, *, places=None, player=_play_on) -> tuple[float | None, list[str]]:
    """The cue on every output at once. Returns when its first sample left (wall clock) and what failed."""
    import soundfile as sf

    path = sound_path(name)
    if path is None:
        return None, [f"{name} not found"]
    pcm, rate = sf.read(str(path), dtype="float32", always_2d=True)
    started: dict = {}
    failed: list[str] = []

    def one(device, mapping):
        try:
            player(device, mapping, pcm, rate, started)
        except Exception as exc:
            failed.append(f"{device}: {type(exc).__name__}: {str(exc)[:80]}")

    threads = [threading.Thread(target=one, args=place, daemon=True) for place in (places or outputs())]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    return started.get("at"), failed


# ------------------------------------------------------------------------------------------------ the crew

def recorder_command(folder: Path) -> list[str]:
    return [sys.executable, "-c", "import sys; from hiremarco.cli import main; sys.exit(main(sys.argv[1:]))",
            "film", "roll", str(folder)]


def recorder_script(folder: Path) -> Path:
    """The recorder's .command, for Terminal to open: Terminal's screen grant comes with it, and the first line hides
    Terminal again the instant the window exists (Owner 2026-11-03: never a Terminal window on the MacBook)."""
    log = Path(config.STATE_DIR) / "screenrec.log"
    script = Path(config.STATE_DIR) / "film.command"
    words = " ".join(shlex.quote(w) for w in recorder_command(folder))
    body = ("#!/bin/zsh\n"
            "printf '\\e]0;hireMarco recorder\\a'\n"
            "osascript -e 'tell application \"System Events\" to set visible of process \"Terminal\" to false' >/dev/null 2>&1 &\n"
            f"cd {shlex.quote(str(Path(__file__).resolve().parents[2]))} || exit 1\n"
            "export PYTHONUNBUFFERED=1\n"
            f"exec {words} >> {shlex.quote(str(log))} 2>&1\n")
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body)
    script.chmod(0o755)
    return script


def hide_terminal(delays=(0.3, 1.5, 3.0)) -> None:
    for delay in delays:
        time.sleep(delay)
        subprocess.run(["osascript", "-e", 'tell application "System Events" to set visible of process "Terminal" to false'],
                       check=False, capture_output=True, timeout=10)


def open_recorder(folder: Path) -> None:
    """Open the recorder's .command behind the front app in a hidden Terminal, and hide Terminal again as it comes."""
    script = recorder_script(folder)
    subprocess.run(["open", "-g", "-j", "-a", "Terminal", str(script)], check=False, timeout=15)
    threading.Thread(target=hide_terminal, daemon=True, name="hide-terminal").start()


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def panel_running() -> bool:
    done = subprocess.run(["pgrep", "-f", "hiremarco.cli import main.*terminal|marco terminal"],
                          capture_output=True, text=True)
    return bool(done.stdout.strip())


def start_panel() -> None:
    """The terminal panel on the TV: the booth's terminal, shown where the camera wants it, never on the MacBook."""
    if panel_running():
        return
    log = Path(config.STATE_DIR) / "terminal-panel.log"
    subprocess.Popen([sys.executable, "-c", "import sys; from hiremarco.cli import main; sys.exit(main(sys.argv[1:]))",
                      "terminal"], stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)


class Crew:
    """One set: the recorder process, the slate, the cues and the monitors, one word at a time, in order."""

    def __init__(self, *, root: Path = FOOTAGE, tell: Callable[[str], None] | None = None,
                 play_cue: Callable[[str], tuple[float | None, list[str]]] = play, hand=None,
                 spawn: Callable[[Path], None] = open_recorder, status: Callable[[], dict] = read_status,
                 is_alive: Callable[[int | None], bool] = alive, kill: Callable[[int, int], None] = os.kill,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time,
                 panel: Callable[[], None] = start_panel, ready_timeout: float = READY_TIMEOUT_S):
        self.root = root
        self.tell = tell or (lambda text: None)
        self.play_cue = play_cue
        self._hand = hand
        self.spawn = spawn
        self.status = status
        self.is_alive = is_alive
        self.kill = kill
        self.sleep = sleep
        self.clock = clock
        self.panel = panel
        self.ready_timeout = ready_timeout
        self.pid: int | None = None        # the recorder's process, read from its status file
        self.folder: Path | None = None
        self.rolled_at: float | None = None
        self.told: set[str] = set()
        self.lock = threading.Lock()
        self._watching = False

    @property
    def hand(self):
        if self._hand is None:
            from hiremarco.studio import monitor

            self._hand = monitor.hand()
        return self._hand

    def rolling(self) -> bool:
        return self.pid is not None and self.is_alive(self.pid)

    def problem(self, text: str) -> None:
        """The one time Marco breaks the silence on set: the problem sound, then a text saying what is wrong."""
        if text in self.told:
            return
        self.told.add(text)
        self.play_cue(PROBLEM_SOUND)
        self.tell(f"{text} ({datetime.fromtimestamp(self.clock()).strftime('%-I:%M:%S%p').lower()})")

    def _flag(self, on: bool) -> None:
        from hiremarco.studio import monitor

        flag = Path(config.STATE_DIR) / monitor.ROLLING_FLAG
        if on:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(str(os.getpid()))
        else:
            flag.unlink(missing_ok=True)

    # the words
    def do(self, word: str) -> str:
        with self.lock:
            if word in ("roll", "roll test"):
                return self.roll(test=word == "roll test")
            if word == "action":
                return self.action()
            if word == "cut":
                return self.cut()
            return f"crew: {word}?"

    def roll(self, *, test: bool = False) -> str:
        if self.rolling():
            return "crew: already rolling, left alone"
        if not self.root.is_dir() or not os.access(self.root, os.W_OK):
            self.problem("I can't see the LaCie, so nothing is recording. Plug it in and text Roll again.")
            return "crew: no LaCie, not rolling"
        folder = day_folder(test, root=self.root)
        (folder / "screen").mkdir(parents=True, exist_ok=True)
        self.folder, self.told = folder, set()
        self._flag(True)
        try:
            self.panel()
        except Exception:
            pass   # the recorder says so if the panel is missing
        try:
            status_path().unlink()
        except OSError:
            pass
        self.spawn(folder)
        state = self._wait_ready()
        if self.pid is None or not self.is_alive(self.pid):
            self.pid = None
            self._flag(False)
            self.problem("The recorder didn't start, so nothing is recording. Text Roll again; if it fails twice, "
                         "start it from the keyboard: marco crew roll.")
            return "crew: the recorder did not start"
        if not state.get("ready"):
            missing = [n for n, s in (state.get("streams") or {}).items() if not s.get("live")]
            if not state.get("audio_live"):
                missing.append("Apollo audio")
            what = ", ".join(missing) or "the recorder"
            self.problem(f"Not everything is recording: {what} didn't start. The rest is rolling. Text Cut to stop.")
        else:
            at, failed = self.play_cue(ROLL_SOUND)
            if at is not None:
                self.rolled_at = at + ROLL_MARK_S
            if failed and len(failed) == len(outputs()):
                self.problem("The count-in didn't play, but everything is recording.")
        roll_at = self.rolled_at or self.clock()
        self.rolled_at = roll_at
        slate(folder, "roll", roll_at, **({"test": True} if test else {}))
        try:
            self.hand.mute()
        except Exception as exc:
            self.problem(f"I couldn't mute the speakers ({type(exc).__name__}). Recording is fine.")
        self._watch()
        live = sum(1 for s in (state.get("streams") or {}).values() if s.get("live"))
        return f"crew: rolling into {folder.name}, {live} screens" + (" + audio" if state.get("audio_live") else "")

    def _wait_ready(self) -> dict:
        """The recorder's status file, once it says ready, or once its process is gone, or after the timeout."""
        waited, state = 0.0, {}
        while waited < self.ready_timeout:
            state = self.status()
            if state.get("pid"):
                self.pid = int(state["pid"])
                if state.get("ready"):
                    return state
                if not self.is_alive(self.pid):
                    return state
            self.sleep(0.25)
            waited += 0.25
        return state

    def _watch(self) -> None:
        """While rolling: a stream that died and could not come back is said once, by sound and text."""
        if self._watching:
            return
        self._watching = True

        def run():
            pid = self.pid
            while self.pid == pid and self.is_alive(pid):
                time.sleep(WATCH_S)
                for line in self.status().get("problems") or []:
                    self.problem(line)
            self._watching = False
            if self.pid == pid and self.folder is not None:   # gone without a Cut
                self.problem("The recorder stopped by itself. Text Roll to start again.")

        threading.Thread(target=run, daemon=True, name="crew-watch").start()

    def action(self) -> str:
        if not self.rolling() or self.folder is None:
            return "crew: action while not rolling, noted nowhere"
        slate(self.folder, "action", self.clock())
        return "crew: action"

    def cut(self) -> str:
        if self.pid is None or self.folder is None:
            self._flag(False)
            return "crew: cut while not rolling"
        cut_at = self.clock()
        self.play_cue(CUT_SOUND)
        pid, self.pid = self.pid, None
        try:
            self.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        waited = 0.0
        while self.is_alive(pid) and waited < STOP_TIMEOUT_S:
            self.sleep(0.25)
            waited += 0.25
        if self.is_alive(pid):
            try:
                self.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        state = self.status()
        files = int(state.get("files") or 0)
        length = round(cut_at - (self.rolled_at or cut_at), 1)
        slate(self.folder, "cut", cut_at, length_s=length, files=files)
        try:
            self.hand.unmute()
        except Exception:
            pass
        self._flag(False)
        self.rolled_at = None
        return f"crew: cut after {length:.0f} s, {files} files in {self.folder.name}"


# ------------------------------------------------------------------------------------------------ from WhatsApp

_CREW: Crew | None = None
_QUEUE: queue.Queue | None = None
_SEEN: dict[str, str] = {}


def crew(tell: Callable[[str], None] | None = None) -> Crew:
    global _CREW
    if _CREW is None:
        _CREW = Crew(tell=tell)
    elif tell is not None:
        _CREW.tell = tell
    return _CREW


def take(said: str, message_id: str, tell: Callable[[str], None], *, run: Callable[[str], str] | None = None) -> str | None:
    """The WhatsApp hook: None for any other words. A crew word is queued so words are done in the order sent, and
    the webhook answers at once; the result goes to serve's own log, never to the chat."""
    global _QUEUE
    word = words(said)
    if word is None:
        return None
    if message_id in _SEEN:
        return f"crew: {word} (already handled)"
    if len(_SEEN) > 200:
        _SEEN.clear()
    _SEEN[message_id] = word
    run = run or crew(tell).do
    if _QUEUE is None:
        _QUEUE = queue.Queue()

        def worker():
            while True:
                job = _QUEUE.get()
                with events.aside():
                    try:
                        print(job(), flush=True)
                    except Exception as exc:
                        print(f"crew: {type(exc).__name__}: {exc}", flush=True)

        threading.Thread(target=worker, daemon=True, name="crew").start()
    _QUEUE.put(lambda: run(word))
    return f"crew: {word} queued"

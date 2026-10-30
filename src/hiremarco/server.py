"""The running Marco: the WhatsApp webhook wired to his voice.

When the Owner writes, Marco marks it read, shows the typing dots, answers
through Muse Spark and replies, each step on his live log. Voice notes and
photos are acknowledged here and handled by the packages that need them. A
beat he sends as an audio file or a document is kept until he says to start
a session, by text, by the caption on the beat or by voice note; then the
booth puts it on the Beat track of a new session.
"""

from __future__ import annotations

import re
from pathlib import Path

from hiremarco import config, gate
from hiremarco.livelog import Trace
from hiremarco.marco import Marco
from hiremarco.whatsapp import Inbound, WhatsApp, make_app


def listen_only(message: Inbound) -> str:
    """Record that the Owner wrote (the webhook already did) and say nothing back."""
    return Trace(f"heard: {(message.text or message.kind)[:60]}").done("listening only, no reply")


def save_beat(message: Inbound, wa: WhatsApp, inbox: Path | None = None) -> tuple[Path, bool] | None:
    """A beat or instrumental he sends (an audio file or a document, not a voice note). It is kept in the inbox's
    "received" folder and set up only on his instruction (Owner 2026-10-30); a caption that is the instruction ("start
    a session for Midnight Drive") starts it at once. (path, started), or None for anything that is not a beat."""
    from hiremarco.studio.beat_in import INBOX, beat_file_name, keep_received, session_name, start_session, \
        wants_session

    if message.kind not in ("audio", "document") or message.voice or not message.media_id:
        return None
    name = beat_file_name(message.filename, message.mime_type, f"beat {message.id[-6:] or 'sent'}")
    if name is None:
        return None
    data, _ = wa.download_media(message.media_id)
    folder = inbox or INBOX
    kept = keep_received(data, name, folder)
    if wants_session(message.caption):
        return start_session(folder, session_name(message.caption)) or kept, True
    return kept, False


def voice_text(message: Inbound, wa: WhatsApp, listen=None) -> str:
    """What he said in a WhatsApp voice note, transcribed."""
    import io

    import soundfile as sf

    from hiremarco.hearing import transcribe

    data, _ = wa.download_media(message.media_id)
    audio, rate = sf.read(io.BytesIO(data), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    # he names songs in Spanish too: "Angel de Cristal" came back as "Anhil de Cristal" (live 2026-10-30)
    turns = (listen or (lambda a, r: transcribe(a, r, diarize=False, languages=["English", "Spanish"])))(audio, rate)
    return " ".join(t.text for t in turns).strip()


ENGLISH = ("Reply in English, even when he writes a word, a name or a song title in Spanish or another language. "
           "Answer in another language only when he asks you to.")
AFFIRM = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|go|go ahead|do it|please do|let'?s go|start it|si|sí|dale)\b",
                    re.I)
STATUS = re.compile(r"\b(?:did|have|has|is|are|was)\b.*\b(?:session|start(?:ed)?|set ?up|ready|done|loaded|logic)\b"
                    r"|\b(?:status|where are we|how'?s it going)\b", re.I)


def booth_running(port: int = 8790) -> bool:
    """His booth holds the shortcut port while it runs; a free port means it is not running."""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def ensure_booth(running=booth_running) -> str:
    """The booth sets sessions up; when it is not running, start it the way the menu-bar app does."""
    import subprocess

    if running():
        return "booth running"
    from hiremarco.studio.beat_in import wake_display

    wake_display()  # the Mac waits dark while he is away; his word lights it up
    script = config.STATE_DIR / "booth.command"
    if not script.exists():
        return "booth not running, and no booth.command to start it"
    subprocess.run(["open", "-a", "Terminal", str(script)], check=False, timeout=15)
    return "booth started"


def status(inbox: Path, running=booth_running) -> str:
    """Where his beat is, in one line he can read: waiting for his word, being set up, or set up."""
    from hiremarco.studio.beat_in import last_loaded, latest_received, pending, requested_name

    waiting = pending(inbox)
    if waiting:
        song = requested_name(waiting[-1]) or waiting[-1].stem
        return f"Setting up {song} now." if running() else f"Starting it now: {song}. My booth was off, so I'm opening it."
    kept = latest_received(inbox)
    if kept is not None:
        return f"Not yet. I have your beat ({kept.stem}). Say start and I'll set it up."
    done = last_loaded(inbox)
    if done is not None:
        return f"Yes. {requested_name(done) or done.stem} is set up in Logic."
    return "No beat yet. Send me one and tell me when to start."


def instruction(said: str, sender: str, message_id: str, wa: WhatsApp, inbox: Path | None,
                booth=ensure_booth, running=booth_running) -> str | None:
    """His words about a session, answered from the real state: start the beat he sent (on "start a session",
    "set it up", or a yes to Marco's question), take a corrected title, or say where things stand. None when the
    words are about something else (Owner 2026-10-30, after a live test where Marco missed all three)."""
    from hiremarco.studio.beat_in import INBOX, latest_received, pending, rename_pending, session_name, \
        start_session, title, wants_session

    folder = inbox or INBOX
    said = (said or "").strip()
    reply = lambda text, tag: wa.send_text(sender, text, idempotency_key=f"{tag}:{message_id}")  # noqa: E731
    short = 2 <= len(said.split()) <= 6 and "?" not in said and not re.match(r"(?i)(?:hey|hi|hello|yo|thanks|thank you|ok|okay|cool|nice|great)\b", said)
    kept, waiting = latest_received(folder), pending(folder)
    if STATUS.search(said) and ("?" in said or not wants_session(said)):
        line = status(folder, running)
        if pending(folder):
            booth()
        reply(line, "status")
        return f"status: {line}"
    if wants_session(said) or (kept is not None and AFFIRM.search(said)):
        song = session_name(said)
        if kept is not None:
            started = start_session(folder, song)
            reply(f"On it. Setting up {song or started.stem}.", "start")
            return f"session started for {started.name}" + (f" as {song!r}" if song else "") + f"; {booth()}"
        if waiting:
            if song:
                rename_pending(song, folder)
            line = f"Already on it: setting up {song or waiting[-1].stem}." + ("" if running() else
                                                                                " Opening my booth now.")
            reply(line, "start")
            return f"already started; {booth()}"
        reply("Send me the beat first, then tell me to start.", "nobeat")
        return "asked for the beat: none is waiting"
    if waiting and short and not AFFIRM.search(said):
        song = title(said)
        rename_pending(song, folder)
        reply(f"No problem. Naming it {song}.", "rename")
        return f"renamed the waiting session to {song!r}; {booth()}"
    return None


def handle(message: Inbound, *, marco: Marco | None = None, wa: WhatsApp | None = None,
           inbox: Path | None = None, listen=None, booth=None, running=None) -> str:
    wa = wa or WhatsApp()
    booth, running = booth or ensure_booth, running or booth_running
    heard = message.text or f"[{message.kind}]"
    trace = Trace(f"heard: {heard[:60]}")
    try:
        wa.mark_read(message.id, typing=True)
        beat = save_beat(message, wa, inbox)
        if beat is not None:
            path, started = beat
            if started:
                wa.send_text(message.sender, "Got the beat. Setting up the session.", idempotency_key=f"beat:{message.id}")
                return trace.done(f"beat {path.name} received with its instruction; session started; {booth()}")
            wa.send_text(message.sender, f"Got the beat ({path.stem}). Want me to start a session with it?",
                         idempotency_key=f"beat:{message.id}")
            return trace.done(f"beat kept as {path.name}, waiting for his word")
        said = message.text
        if message.kind == "audio" and message.voice and message.media_id:
            said = voice_text(message, wa, listen)
            trace.add(f"voice note: {said[:60]}")
        elif message.kind != "text":
            return trace.done(f"{message.kind} noted, no handler yet")
        started = instruction(said, message.sender, message.id, wa, inbox, booth=booth, running=running)
        if started is not None:
            return trace.done(started)
        if not said:
            return trace.done("nothing heard in the voice note")
        reply = (marco or Marco()).answer(said, job="whatsapp-reply", instructions=ENGLISH)
        if not reply.text.strip():  # Meta refuses an empty text; nothing is sent and the log says why
            return trace.done("no reply: the model returned no text")
        wa.send_text(message.sender, reply.text.strip(), idempotency_key=f"reply:{message.id}")
        return trace.done("replied")
    except gate.Refused as refused:
        return trace.done(f"held: {refused.reason}")
    except Exception as exc:  # the webhook must keep running; the log says what broke
        return trace.done(f"error: {type(exc).__name__}")


def build_app(*, reply: bool = True):
    from starlette.routing import Route

    from hiremarco.relay import make_relay

    return make_app(
        handle if reply else listen_only,
        verify_token=config.require("WHATSAPP_VERIFY_TOKEN"),
        app_secret=config.require("WHATSAPP_APP_SECRET"),
        owner=config.require("OWNER_WHATSAPP"),
        conn_factory=gate.connect,
        extra_routes=[Route("/llm/v1/chat/completions", make_relay(), methods=["POST"])],
    )

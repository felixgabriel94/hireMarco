"""The running Marco: the WhatsApp webhook wired to his voice.

When the Owner writes, Marco marks it read, shows the typing dots, answers
through Muse Spark and replies, each step on his live log. Voice notes and
photos are acknowledged here and handled by the packages that need them. A
beat he sends as an audio file or a document is kept until he says to start
a session, by text, by the caption on the beat or by voice note; then the
booth puts it on the Beat track of a new session.
"""

from __future__ import annotations

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
    turns = (listen or (lambda a, r: transcribe(a, r, diarize=False)))(audio, rate)
    return " ".join(t.text for t in turns).strip()


def instruction(said: str, sender: str, message_id: str, wa: WhatsApp, inbox: Path | None) -> str | None:
    """His words, when they tell Marco to set up a session: the last beat he sent is started and he is told so.
    None when the words are not that instruction."""
    from hiremarco.studio.beat_in import INBOX, latest_received, session_name, start_session, wants_session

    if not wants_session(said):
        return None
    folder = inbox or INBOX
    if latest_received(folder) is None:
        wa.send_text(sender, "Send me the beat first, then tell me to start.", idempotency_key=f"nobeat:{message_id}")
        return "asked for the beat: none is waiting"
    song = session_name(said)
    started = start_session(folder, song)
    wa.send_text(sender, f"On it. Setting up {song or started.stem}.", idempotency_key=f"start:{message_id}")
    return f"session started for {started.name}" + (f" as {song!r}" if song else "")


def handle(message: Inbound, *, marco: Marco | None = None, wa: WhatsApp | None = None,
           inbox: Path | None = None, listen=None) -> str:
    wa = wa or WhatsApp()
    heard = message.text or f"[{message.kind}]"
    trace = Trace(f"heard: {heard[:60]}")
    try:
        wa.mark_read(message.id, typing=True)
        beat = save_beat(message, wa, inbox)
        if beat is not None:
            path, started = beat
            if started:
                wa.send_text(message.sender, "Got the beat. Setting up the session.", idempotency_key=f"beat:{message.id}")
                return trace.done(f"beat {path.name} received with its instruction; session started")
            wa.send_text(message.sender, f"Got the beat ({path.stem}). Want me to start a session with it?",
                         idempotency_key=f"beat:{message.id}")
            return trace.done(f"beat kept as {path.name}, waiting for his word")
        said = message.text
        if message.kind == "audio" and message.voice and message.media_id:
            said = voice_text(message, wa, listen)
            trace.add(f"voice note: {said[:60]}")
        elif message.kind != "text":
            return trace.done(f"{message.kind} noted, no handler yet")
        started = instruction(said, message.sender, message.id, wa, inbox)
        if started is not None:
            return trace.done(started)
        if not said:
            return trace.done("nothing heard in the voice note")
        reply = (marco or Marco()).answer(said, job="whatsapp-reply")
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

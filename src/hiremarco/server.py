"""The running Marco: the WhatsApp webhook wired to his voice.

When the Owner writes, Marco marks it read, shows the typing dots, answers
through Muse Spark and replies, each step on his live log. Voice notes and
photos are acknowledged here and handled by the packages that need them. A
beat he sends as an audio file or a document is saved into the beat inbox,
where the booth puts it on the Beat track of a new session.
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


def save_beat(message: Inbound, wa: WhatsApp, inbox: Path | None = None) -> Path | None:
    """A beat or instrumental he sends (an audio file or a document, not a voice note) saved into the beat inbox,
    where the booth puts it on the Beat track of a new session (Owner 2026-10-29). None for anything else."""
    from hiremarco.studio.beat_in import INBOX, beat_file_name

    if message.kind not in ("audio", "document") or message.voice or not message.media_id:
        return None
    name = beat_file_name(message.filename, message.mime_type, f"beat {message.id[-6:] or 'sent'}")
    if name is None:
        return None
    data, _ = wa.download_media(message.media_id)
    folder = inbox or INBOX
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / name, 2
    while target.exists():
        target, n = folder / f"{Path(name).stem} {n}{Path(name).suffix}", n + 1
    partial = target.with_name(f".{target.name}.part")  # hidden until whole, so the inbox never takes half a file
    partial.write_bytes(data)
    partial.rename(target)
    return target


def handle(message: Inbound, *, marco: Marco | None = None, wa: WhatsApp | None = None,
           inbox: Path | None = None) -> str:
    wa = wa or WhatsApp()
    heard = message.text or f"[{message.kind}]"
    trace = Trace(f"heard: {heard[:60]}")
    try:
        wa.mark_read(message.id, typing=True)
        beat = save_beat(message, wa, inbox)
        if beat is not None:
            wa.send_text(message.sender, "Got the beat. It's going on the Beat track in a new session.",
                         idempotency_key=f"beat:{message.id}")
            return trace.done(f"beat saved to the inbox as {beat.name}")
        if message.kind != "text":
            return trace.done(f"{message.kind} noted, no handler yet")
        reply = (marco or Marco()).answer(message.text, job="whatsapp-reply")
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

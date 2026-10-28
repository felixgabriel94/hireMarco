"""The running Marco: the WhatsApp webhook wired to his voice.

When the Owner writes, Marco marks it read, shows the typing dots, answers
through Muse Spark and replies, each step on his live log. Voice notes and
photos are acknowledged here and handled by the packages that need them.
"""

from __future__ import annotations

from hiremarco import config, gate
from hiremarco.livelog import Trace
from hiremarco.marco import Marco
from hiremarco.whatsapp import Inbound, WhatsApp, make_app


def listen_only(message: Inbound) -> str:
    """Record that the Owner wrote (the webhook already did) and say nothing back."""
    return Trace(f"heard: {(message.text or message.kind)[:60]}").done("listening only, no reply")


def handle(message: Inbound, *, marco: Marco | None = None, wa: WhatsApp | None = None) -> str:
    wa = wa or WhatsApp()
    heard = message.text or f"[{message.kind}]"
    trace = Trace(f"heard: {heard[:60]}")
    try:
        wa.mark_read(message.id, typing=True)
        if message.kind != "text":
            return trace.done(f"{message.kind} noted, no handler yet")
        reply = (marco or Marco()).answer(message.text, job="whatsapp-reply")
        wa.send_text(message.sender, reply.text.strip(), idempotency_key=f"reply:{message.id}")
        return trace.done("replied")
    except gate.Refused as refused:
        return trace.done(f"held: {refused.reason}")
    except Exception as exc:  # the webhook must keep running; the log says what broke
        return trace.done(f"error: {type(exc).__name__}")


def build_app(*, reply: bool = True):
    return make_app(
        handle if reply else listen_only,
        verify_token=config.require("WHATSAPP_VERIFY_TOKEN"),
        app_secret=config.require("WHATSAPP_APP_SECRET"),
        owner=config.require("OWNER_WHATSAPP"),
        conn_factory=gate.connect,
    )

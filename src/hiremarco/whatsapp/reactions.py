"""Marco's reactions on Felix's WhatsApp messages (Owner 2026-11-02): fourteen, plain skin tone, and nothing else.

The code picks when the event is certain: a beat, a file, the last frame of a shoot, a call going, a draft ready, a job
started. The brain picks for chat, from ``MODEL_PICKS`` only. A reaction replaces a text only when nothing needs saying,
never proof, a preview or a question, and no "noted" comes with it. If WhatsApp refuses one with nothing else to say, he
says a short line instead, so Felix never gets silence. An email offer never reacts: nothing here runs without his own
message to react to. A reaction goes through the gate like a text: the same switch, kill switch and daily cap.
"""

from __future__ import annotations

from hiremarco import gate
from hiremarco.joblog import JobLog, JobRow
from hiremarco.whatsapp.client import WhatsAppError
from hiremarco.whatsapp.memory import remember

NOTED = "\N{THUMBS UP SIGN}"
ON_IT = "\N{MAN}‍\N{PERSONAL COMPUTER}"
DEAL = "\N{HANDSHAKE}"
CALLING = "\N{TELEPHONE RECEIVER}"
AUDIO = "\N{MINIDISC}"
FILE = "\N{PAPERCLIP}"
PHOTOS = "\N{CAMERA WITH FLASH}"
PURCHASE = "\N{SHOPPING TROLLEY}"
DRAFT = "\N{ENVELOPE}️"
DATE = "\N{TEAR-OFF CALENDAR}"
DONE_BY_HIM = "\N{WHITE HEAVY CHECK MARK}"
MONEY = "\N{MONEY WITH WINGS}"
BIG_WIN = "\N{FACE WITH LOOK OF TRIUMPH}"
LAUGH = "\N{FACE WITH TEARS OF JOY}"
ALLOWED = (NOTED, ON_IT, DEAL, CALLING, AUDIO, FILE, PHOTOS, PURCHASE, DRAFT, DATE, DONE_BY_HIM, MONEY, BIG_WIN, LAUGH)

# what the brain may choose, by name: these say nothing happened, so it can't claim work with one
MODEL_PICKS = {"noted": NOTED, "deal": DEAL, "audio": AUDIO, "purchase": PURCHASE, "date": DATE, "did_it": DONE_BY_HIM,
               "money": MONEY, "big_win": BIG_WIN, "laugh": LAUGH}
# the short line in its place when WhatsApp refuses a reaction and nothing else was going to be said
SAID_INSTEAD = {NOTED: "Noted.", DEAL: "Anytime.", AUDIO: "Got it.", PURCHASE: "Noted.", DATE: "Date noted.",
                DONE_BY_HIM: "Good.", MONEY: "Nice.", BIG_WIN: "Let's go.", LAUGH: "Ha.", FILE: "Got your file.",
                PHOTOS: "Got your photos.", ON_IT: "On it.", CALLING: "Calling now.", DRAFT: "Your draft's ready."}


def react(wa, sender: str, message_id: str, emoji: str) -> bool:
    """One reaction on one of his messages. False when it did not go, with the reason in the log and never to him; an
    emoji off the list does not go at all. The kill switch and the gate's limits hold it as they would a text."""
    if emoji not in ALLOWED or not message_id:
        return False
    try:
        wa.react(sender, message_id, emoji)
    except (gate.Refused, WhatsAppError) as held:
        JobLog().append(JobRow(job="whatsapp-reaction", ok=False, note=type(held).__name__))
        return False
    remember(wa.conn, "marco", f"[reacted {emoji}]")
    return True


def react_or_say(wa, sender: str, message_id: str, emoji: str, key: str) -> bool:
    """When the reaction is the whole reply: if it can't go, the short line goes instead."""
    if react(wa, sender, message_id, emoji):
        return True
    wa.send_text(sender, SAID_INSTEAD.get(emoji, "Got it."), idempotency_key=key)
    return False

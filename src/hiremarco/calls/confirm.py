"""The proof after a call: the place's confirmation email, found and sent to Felix with its link.

Owner 2026-10-31: the report ends with the confirmation, not Marco's word. After a booked or waitlisted call, Marco
watches the inbox for up to ``WATCH_S`` for mail from a sender RULES.md lets him read for booking confirmations,
reads it into fields with Muse Spark (the proof reader's schema), keeps it only when it names the place, and sends
Felix the booking and its link. No link in the email: the confirmation number. Nothing in time: he asks whether to
call to confirm. Plain words only.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import date, datetime, timezone
from datetime import time as clock
from email.utils import parsedate_to_datetime

from hiremarco import gate
from hiremarco.google.mail import MailItem
from hiremarco.offer import Place
from hiremarco.proof import INSTRUCTIONS, SCHEMA, Booking

TENANT = "owner"
PURPOSE = "booking confirmations"  # the read lines' purpose these emails come under
WATCH_S, EVERY_S = 2 * 60 * 60, 5 * 60
BOOKING_HOSTS = ("opentable", "resy", "sevenrooms", "exploretock", "tock")
WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}


def read(item: MailItem, client) -> Booking | None:
    """The confirmed booking an email holds, or None for anything else (a reminder, marketing, unreadable)."""
    prompt = f"From: {item.sender}\nSubject: {item.subject}\nDate: {item.date}\n\n{item.text[:6000]}"
    gate.check_model_call(TENANT, model=client.model, system=INSTRUCTIONS, prompt=prompt, joblog=client.joblog)
    reply = client.ask(prompt, developer=INSTRUCTIONS, job="confirm-read", max_completion_tokens=200,
                       reasoning_effort="minimal", response_format={
                           "type": "json_schema", "json_schema": {"name": "booking", "schema": SCHEMA, "strict": True}})
    try:
        data = json.loads(reply.text)
        if not data["is_confirmation"]:
            return None
        return Booking(restaurant=data["restaurant"].strip(), day=date.fromisoformat(data["date"]),
                       at=clock.fromisoformat(data["time"]), party_size=int(data["party_size"]),
                       name=data["name"].strip(), confirmation=data.get("confirmation", "").strip())
    except (KeyError, ValueError, TypeError):
        return None


def names_place(booking: Booking, place: Place) -> bool:
    words = [w for w in re.findall(r"[a-z]+", place.name.lower()) if len(w) > 2]
    return bool(words) and words[0] in booking.restaurant.lower()


def best_link(item: MailItem, place: Place) -> str:
    """The email's own link to view or manage the booking, if it has one."""
    def score(url: str) -> int:
        low = url.lower()
        return (3 * any(h in low for h in BOOKING_HOSTS) + 2 * any(w in low for w in ("reservation", "booking", "manage", "view"))
                - 5 * any(w in low for w in ("unsubscribe", "privacy", "terms", "facebook", "instagram", "twitter")))
    ranked = sorted(item.links, key=score, reverse=True)
    return ranked[0] if ranked and score(ranked[0]) > 0 else ""


def confirmed_text(place: Place, booking: Booking) -> str:
    when = booking.start.strftime("%A %-I:%M %p").replace(":00", "").replace("AM", "am").replace("PM", "pm")
    party = WORDS.get(booking.party_size, str(booking.party_size))
    return f"Confirmed: {place.name}, {when}, {party}" + (f", under {booking.name}" if booking.name else "") + "."


def watch(place: Place, since: datetime, mail, client, send_text: Callable[[str], None],
          send_link: Callable[[str, str], None], *, sleep=time.sleep, watch_s: float = WATCH_S,
          every_s: float = EVERY_S) -> str:
    """Wait for the confirmation and send it. Returns what happened, for the log."""
    if mail is None:
        from hiremarco.google import Mail

        mail = Mail()
    if client is None:
        from hiremarco.meta.client import MuseSpark

        client = MuseSpark()
    seen: set[str] = set()
    waited = 0.0
    while waited <= watch_s:
        try:
            items = mail.recent(newer_than="1d", purpose=PURPOSE)
        except Exception:  # the inbox could not be read this time: try again next round
            items = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            try:
                if parsedate_to_datetime(item.date) < since:
                    continue
            except (TypeError, ValueError):
                pass
            booking = read(item, client)
            if booking is None or not names_place(booking, place):
                continue
            link = best_link(item, place)
            if link:
                send_link(confirmed_text(place, booking) + " Here's the confirmation.", link)
                return f"confirmation from {item.sender} sent with its link"
            number = f" Confirmation number {booking.confirmation}." if booking.confirmation else ""
            send_text(confirmed_text(place, booking) + number + " It's in your email.")
            return f"confirmation from {item.sender} sent, no link in it"
        sleep(every_s)
        waited += every_s
    send_text(f"No confirmation email from {place.name} yet. Want me to call to confirm?")
    return "no confirmation within the watch"

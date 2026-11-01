import base64
import json
from datetime import datetime, timezone

from hiremarco.calls import confirm
from hiremarco.google.mail import MailItem, body_links
from hiremarco.offer import Place

PLACE = Place("american-social", "American Social Brickell", "17867068256")
SINCE = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
FIELDS = {"is_confirmation": True, "restaurant": "American Social", "date": "2026-11-05", "time": "21:30",
          "party_size": 4, "name": "Felix Betancourt", "confirmation": "AS-1234"}


class Client:
    model, joblog = "muse-spark-1.3", None

    def __init__(self, fields):
        self.fields = fields

    def ask(self, prompt, **kwargs):
        return type("Reply", (), {"text": json.dumps(self.fields)})()


class Mail:
    def __init__(self, *rounds):
        self.rounds = list(rounds)

    def recent(self, newer_than="1d", purpose=None):
        assert purpose == confirm.PURPOSE
        return self.rounds.pop(0) if self.rounds else []


def item(links=(), date="Sun, 01 Nov 2026 01:20:00 +0000", sender="no-reply@opentable.com"):
    return MailItem(id=date + sender, sender=sender, sender_name="", subject="Your reservation is confirmed",
                    date=date, text="Thursday 9:30 PM, party of 4", links=tuple(links))


def run(mail, fields=FIELDS):
    texts, links = [], []
    note = confirm.watch(PLACE, SINCE, mail, Client(fields), texts.append, lambda t, u: links.append((t, u)),
                         sleep=lambda s: None, watch_s=600, every_s=300)
    return note, texts, links


def test_the_confirmation_is_sent_with_its_view_link(monkeypatch):
    monkeypatch.setattr("hiremarco.gate.check_model_call", lambda *a, **k: None)
    found = item(links=["https://www.opentable.com/unsubscribe?x=1",
                        "https://www.opentable.com/my/reservation/view?rid=9"])
    note, texts, links = run(Mail([], [found]))
    assert links == [("Confirmed: American Social Brickell, Thursday 9:30 pm, four, under Felix Betancourt. "
                      "Here's the confirmation.", "https://www.opentable.com/my/reservation/view?rid=9")]
    assert texts == [] and "sent with its link" in note


def test_no_link_sends_the_number_and_nothing_in_time_asks(monkeypatch):
    monkeypatch.setattr("hiremarco.gate.check_model_call", lambda *a, **k: None)
    note, texts, _ = run(Mail([item()]))
    assert texts == ["Confirmed: American Social Brickell, Thursday 9:30 pm, four, under Felix Betancourt. "
                     "Confirmation number AS-1234. It's in your email."]
    note, texts, _ = run(Mail([]))
    assert texts == ["No confirmation email from American Social Brickell yet. Want me to call to confirm?"]


def test_old_mail_other_places_and_non_confirmations_are_skipped(monkeypatch):
    monkeypatch.setattr("hiremarco.gate.check_model_call", lambda *a, **k: None)
    old = item(date="Sat, 31 Oct 2026 20:00:00 +0000")
    assert run(Mail([old]))[1][0].startswith("No confirmation email")
    assert run(Mail([item()]), {**FIELDS, "restaurant": "Harbor Grill"})[1][0].startswith("No confirmation email")
    assert run(Mail([item()]), {**FIELDS, "is_confirmation": False})[1][0].startswith("No confirmation email")


def test_email_links_include_html_hrefs():
    html = '<a href="https://resy.com/reservations/manage?x=1&amp;y=2">Manage</a> see https://resy.com/terms'
    data = base64.urlsafe_b64encode(html.encode()).decode()
    assert body_links({"mimeType": "text/html", "body": {"data": data}}) == (
        "https://resy.com/reservations/manage?x=1&y=2", "https://resy.com/terms")

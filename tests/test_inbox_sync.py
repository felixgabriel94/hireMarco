"""The sync as the 5-minute job runs it: labels added, auto-trash first, and a WhatsApp refusal doesn't stop it."""
import argparse
import json

import pytest

from hiremarco import cli, config, inbox
from hiremarco.google.mail import MailItem
from hiremarco.inbox import cleanup


class FakeMail:
    def __init__(self, items):
        self.items, self.added, self.trashed = items, [], []
        self._labels = {"To Respond": "L_tr", "FYI": "L_fyi", "Invoices": "L_inv", "Notifications": "L_not",
                        "Newsletters": "L_news", "Promotions": "L_promo", "Marco": "L_marco"}

    def everything(self, **kwargs):
        return self.items

    def labels(self):
        return self._labels

    def ensure_label(self, name, colors=None):
        return self._labels.setdefault(name, f"L_{name}")

    def add_label(self, message_id, add, ours):
        assert add in ours
        self.added.append((message_id, add))

    def label_ids(self, message_id):
        return ["INBOX"]

    def trash(self, message_id):
        self.trashed.append(message_id)

    def found(self, q, limit=100):
        return []


class Muse:
    model, joblog = "muse-spark-1.3", None

    def __init__(self):
        self.task_id = ""

    def ask(self, prompt, **kwargs):
        return type("Reply", (), {"text": json.dumps({"label": "Invoices", "task_id": "offer-1"})})()


class RefusingWhatsApp:
    def send_text(self, *a, **k):
        raise RuntimeError("outside the 24 hour window")

    def send_link(self, *a, **k):
        raise RuntimeError("outside the 24 hour window")


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "require", lambda name: "+15550001111")
    monkeypatch.setattr("hiremarco.gate.check_model_call", lambda *a, **k: None)
    monkeypatch.setattr("hiremarco.meta.client.MuseSpark", Muse)
    monkeypatch.setattr("hiremarco.whatsapp.WhatsApp", RefusingWhatsApp)

    def run(mail):
        monkeypatch.setattr("hiremarco.google.Mail", lambda: mail)
        return cli.cmd_inbox(argparse.Namespace(action="sync", days=1, limit=300))
    return run


def mail_item(mid, sender, subject="Your booking"):
    return MailItem(id=mid, sender=sender, sender_name="", subject=subject, date="", text="body")


def test_labels_go_on_only_once_they_are_switched_on(world):
    mail = FakeMail([mail_item("a", "x@shop.com")])
    assert world(mail) == 0 and mail.added == []
    inbox.set_labels(inbox.connect(), True)
    mail = FakeMail([mail_item("b", "x@shop.com")])
    assert world(mail) == 0 and mail.added == [("b", "L_inv")]


def test_a_whatsapp_refusal_does_not_stop_the_sync(world):
    conn = inbox.connect()
    inbox.set_labels(conn, True)
    inbox.open_task(conn, "offer-1", "Test Kitchen booking", {"place": "Test Kitchen"})
    mail = FakeMail([mail_item("a", "x@shop.com")])
    assert world(mail) == 0
    assert mail.added == [("a", "L_Marco/Test Kitchen booking")]


def test_auto_trash_runs_first_and_its_mail_costs_no_model_call_or_label(world):
    conn = inbox.connect()
    inbox.set_labels(conn, True)
    listed = cleanup.connect()
    listed.execute("insert into blocked (sender, how, ts) values ('promo@shop.com', 'link', 'now')")
    listed.commit()
    mail = FakeMail([mail_item("a", "promo@shop.com", "48 hours left")])
    assert world(mail) == 0 and mail.trashed == ["a"] and mail.added == []

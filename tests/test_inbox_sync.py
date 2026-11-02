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
        return cli.cmd_inbox(argparse.Namespace(action="sync", days=1, limit=300, sweep=False, tasks=False))
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


class Forbidden:
    def __init__(self, *a, **k):
        raise AssertionError("this half must not build that")


@pytest.fixture
def half(tmp_path, monkeypatch):
    """The two halves, with the keys each may not have made fatal: a missing key raises, as on the Mini."""
    keys = {}

    def require(name):
        if name not in keys:
            raise RuntimeError(f"{name} is not set")
        return keys[name]

    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "require", require)
    monkeypatch.setattr("hiremarco.gate.check_model_call", lambda *a, **k: None)

    def run(flag, mail=None, muse=Muse, wa=Forbidden):
        monkeypatch.setattr("hiremarco.meta.client.MuseSpark", muse)
        monkeypatch.setattr("hiremarco.whatsapp.WhatsApp", wa)
        monkeypatch.setattr("hiremarco.google.Mail", (lambda: mail) if mail is not None else Forbidden)
        return cli.cmd_inbox(argparse.Namespace(action="sync", days=3, limit=300, sweep=flag == "sweep", tasks=flag == "tasks"))
    return run, keys


def test_the_sweep_needs_no_whatsapp_and_no_owner_and_reads_no_tasks(half):
    run, _ = half
    conn = inbox.connect()
    inbox.set_labels(conn, True)
    inbox.open_task(conn, "offer-1", "Test Kitchen booking", {"place": "Test Kitchen"})
    listed = cleanup.connect()
    listed.execute("insert into blocked (sender, how, ts) values ('promo@shop.com', 'link', 'now')")
    listed.commit()
    mail = FakeMail([mail_item("a", "x@shop.com"), mail_item("b", "promo@shop.com", "48 hours left")])
    assert run("sweep", mail) == 0  # Muse answers task offer-1, and no task was offered to match it
    assert mail.added == [("a", "L_inv")] and mail.trashed == ["b"]
    assert inbox.get_task(conn, "offer-1").status == "open"


def test_with_no_open_task_the_tasks_half_reads_nothing_and_costs_nothing(half):
    run, _ = half
    assert run("tasks", muse=Forbidden) == 0  # no Mail, no model, no WhatsApp, no key


class Texts:
    sent = []

    def send_text(self, to, text, idempotency_key=None):
        Texts.sent.append(text)

    def send_link(self, to, text, url, label, idempotency_key=None):
        Texts.sent.append(text)


def test_the_tasks_half_proves_a_match_labels_only_it_and_checks_each_email_once(half):
    run, keys = half
    keys["OWNER_WHATSAPP"] = "15550001111"
    Texts.sent = []
    conn = inbox.connect()
    inbox.set_labels(conn, True)
    inbox.open_task(conn, "offer-1", "Test Kitchen booking", {"place": "Test Kitchen"})
    asked = []

    class Picky(Muse):
        def ask(self, prompt, **kwargs):
            asked.append(prompt)
            task = "offer-1" if "confirmed" in prompt else ""
            return type("Reply", (), {"text": json.dumps({"label": "Invoices", "task_id": task})})()

    mail = FakeMail([mail_item("a", "x@shop.com", "Hello there"), mail_item("b", "y@shop.com", "Your table is confirmed")])
    assert run("tasks", mail, muse=Picky, wa=Texts) == 0
    assert mail.added == [("b", "L_Marco/Test Kitchen booking")] and len(asked) == 2
    assert len(Texts.sent) == 1 and inbox.get_task(conn, "offer-1").status == "done"
    assert mail.trashed == []  # expiry and auto-trash belong to the sweep


def test_the_tasks_half_doesnt_ask_about_an_email_twice_or_mail_from_before_the_task(half):
    conn = inbox.connect()
    inbox.open_task(conn, "offer-1", "Test Kitchen booking", {"place": "Test Kitchen"})
    asked = []

    class Plain(Muse):
        def ask(self, prompt, **kwargs):
            asked.append(prompt)
            return type("Reply", (), {"text": json.dumps({"label": "FYI", "task_id": ""})})()

    now = MailItem(id="n", sender="a@b.com", sender_name="", subject="new", date="", text="")
    old = MailItem(id="o", sender="a@b.com", sender_name="", subject="old", date="Thu, 01 Jan 2026 10:00:00 +0000", text="")

    class Listing:
        def everything(self, known=None, **kwargs):
            return [i for i in (now, old) if not (known and known(i.id))]

    tasks = inbox.open_tasks(conn)
    assert inbox.match_tasks(Listing(), Plain(), conn, tasks) == [] and len(asked) == 1 and "new" in asked[0]
    assert inbox.match_tasks(Listing(), Plain(), conn, tasks) == [] and len(asked) == 1


def test_the_two_halves_cant_be_asked_for_together():
    with pytest.raises(SystemExit):
        cli.main(["inbox", "sync", "--sweep", "--tasks"])


def test_the_kill_switch_stops_the_whole_sweep_gmail_moves_included(half, tmp_path, monkeypatch):
    run, _ = half
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    (tmp_path / "kill-switch").write_text("stop")
    listed = cleanup.connect()
    listed.execute("insert into blocked (sender, how, ts) values ('promo@shop.com', 'link', 'now')")
    listed.commit()
    # no Mail or model is even built
    assert run("sweep", muse=Forbidden) == 0


def test_a_killed_sweep_writes_nothing_in_its_state_folder(half, tmp_path, monkeypatch):
    run, _ = half
    monkeypatch.setenv("HIREMARCO_STATE", str(tmp_path))
    (tmp_path / "kill-switch").write_text("stop")
    assert run("sweep", muse=Forbidden) == 0
    assert not (tmp_path / "inbox.sqlite").exists() and not (tmp_path / "cleanup.sqlite").exists()


def test_the_sweep_has_its_own_daily_cap_and_auto_trash_goes_on_past_it(half, monkeypatch):
    from hiremarco.joblog import JobLog

    run, _ = half
    monkeypatch.setattr(JobLog, "total_usd", lambda self, day=None: cli.SWEEP_CAP_USD)
    conn = inbox.connect()
    inbox.set_labels(conn, True)
    listed = cleanup.connect()
    listed.execute("insert into blocked (sender, how, ts) values ('promo@shop.com', 'link', 'now')")
    listed.commit()
    mail = FakeMail([mail_item("a", "x@shop.com"), mail_item("b", "promo@shop.com", "48 hours left")])
    assert run("sweep", mail) == 0
    assert mail.added == [] and mail.trashed == ["b"] and not inbox.seen(conn, "a")


def test_a_gmail_only_sign_in_asks_for_gmail_alone_and_writes_only_the_file_it_was_given(tmp_path, monkeypatch):
    import httpx

    from hiremarco.google import auth

    assert "calendar" not in auth.auth_url("id", "http://x", "c", "s", auth.GMAIL_ONLY)
    assert "calendar" in auth.auth_url("id", "http://x", "c", "s")
    home, target = tmp_path / "env", tmp_path / "mini.env"
    home.write_text("GOOGLE_CLIENT_ID=cid\nGOOGLE_CLIENT_SECRET=sec\nGOOGLE_REFRESH_TOKEN=old\nMODEL_API_KEY=mk\nWHATSAPP_TOKEN=wt\n")
    monkeypatch.setenv("HIREMARCO_ENV", str(home))
    monkeypatch.setattr(auth, "_wait_for_code", lambda port, state, timeout: "code")
    monkeypatch.setattr(auth.webbrowser, "open", lambda url: None)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"refresh_token": "new"}))
    auth.signin(transport=transport, scopes=auth.GMAIL_ONLY, write_env=target)
    written = dict(line.split("=", 1) for line in target.read_text().splitlines())
    assert written == {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "sec", "GOOGLE_REFRESH_TOKEN": "new", "MODEL_API_KEY": "mk"}
    assert "GOOGLE_REFRESH_TOKEN=old" in home.read_text() and oct(target.stat().st_mode)[-3:] == "600"

import json
from datetime import date

import httpx
import pytest

from hiremarco import gate
from hiremarco.google.mail import Found, Mail
from hiremarco.inbox import cleanup


class FakeMail:
    def __init__(self, headers):
        self.headers, self.trashed, self.untrashed = headers, [], []

    def latest_from(self, sender):
        return ("m-" + sender, self.headers[sender]) if sender in self.headers else None

    def ids_from(self, sender, keep_starred=True, exclude=""):
        assert keep_starred
        return [f"{sender}-1", f"{sender}-2"] + ([] if exclude else [f"{sender}-receipt"])

    def trash(self, message_id):
        self.trashed.append(message_id)

    def untrash(self, message_id):
        self.untrashed.append(message_id)


ONE_CLICK = {"list-unsubscribe": "<mailto:u@x.com>, <https://x.com/u?id=1>", "list-unsubscribe-post": "List-Unsubscribe=One-Click"}


@pytest.fixture
def plan(tmp_path):
    path = tmp_path / "marked.csv"
    path.write_text("sender,suggested\npromo@shop.com,Unsubscribe and trash\nnews@paper.com,Unsubscribe\n"
                    "friend@gmail.com,Keep\npage@only.com,Unsubscribe\n")
    rules = tmp_path / "RULES.md"
    rules.write_text("send: unsubscribe -> * ; marked senders ; until revoked\n")
    return path, rules


def run(plan, mail, posts, confirm=None, dry_run=False):
    path, rules = plan
    http = httpx.Client(transport=httpx.MockTransport(lambda r: (posts.append((str(r.url), r.content)), httpx.Response(200))[1]))
    return cleanup.run(mail, path, confirm or cleanup.plan_hash(path), cleanup.connect(":memory:"),
                       gate_conn=gate.connect(":memory:"), http=http, rules_path=rules, dry_run=dry_run)


def test_only_marked_senders_are_touched_and_trash_is_logged_and_undone(plan):
    mail, posts = FakeMail({"promo@shop.com": ONE_CLICK, "news@paper.com": ONE_CLICK,
                            "page@only.com": {"list-unsubscribe": "<https://only.com/manage>"}}), []
    path, rules = plan
    conn = cleanup.connect(":memory:")
    http = httpx.Client(transport=httpx.MockTransport(lambda r: (posts.append((str(r.url), r.content)), httpx.Response(200))[1]))
    done = cleanup.run(mail, path, cleanup.plan_hash(path), conn, gate_conn=gate.connect(":memory:"), http=http,
                       rules_path=rules)
    assert done["unsubscribed"] == 2 and done["trashed"] == 2 and done["kept_by_guard"] == 1
    assert posts == [("https://x.com/u?id=1", b"List-Unsubscribe=One-Click")] * 2
    assert mail.trashed == ["promo@shop.com-1", "promo@shop.com-2"]          # Keep and Unsubscribe-only kept
    assert [s for s, _ in done["for_felix"]] == ["page@only.com"] and done["blocked"]["link"] == 1
    assert cleanup.blocked(conn, "page@only.com")
    assert cleanup.undo(mail, conn) == 2 and mail.untrashed == ["promo@shop.com-1", "promo@shop.com-2"]


def test_an_unconfirmed_or_changed_list_does_nothing(plan):
    mail, posts = FakeMail({"promo@shop.com": ONE_CLICK}), []
    with pytest.raises(gate.Refused, match="fingerprint"):
        run(plan, mail, posts, confirm="0" * 64)
    assert mail.trashed == [] and posts == []


def test_without_the_switch_nothing_is_sent(plan):
    path, rules = plan
    rules.write_text("")
    with pytest.raises(gate.Refused):
        run(plan, FakeMail({"promo@shop.com": ONE_CLICK}), [])


def test_a_dry_run_counts_and_changes_nothing(plan):
    mail, posts = FakeMail({"promo@shop.com": ONE_CLICK, "news@paper.com": ONE_CLICK}), []
    done = run(plan, mail, posts, dry_run=True)
    assert done["trashed"] == 2 and done["unsubscribed"] == 0 and posts == [] and mail.trashed == []


class FakeAuth:
    def headers(self):
        return {"Authorization": "Bearer t"}


def test_only_the_lindy_label_can_be_removed_and_no_email_is_deleted(tmp_path):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/labels"):
            return httpx.Response(200, json={"labels": [{"name": "Lindy", "id": "L1"}, {"name": "To Respond", "id": "L2"}]})
        return httpx.Response(204)

    mail = Mail(auth=FakeAuth(), transport=httpx.MockTransport(handler), rules_path=tmp_path / "R.md")
    with pytest.raises(ValueError):
        mail.delete_label("To Respond")
    assert mail.delete_label("Lindy") is True
    assert ("DELETE", "/gmail/v1/users/me/labels/L1") in seen
    assert not any(m == "DELETE" and "/messages" in p for m, p in seen)


def test_new_mail_from_the_auto_trash_list_goes_to_trash_receipts_and_watch_excepted():
    from hiremarco.google.mail import MailItem

    conn, mail = cleanup.connect(":memory:"), FakeMail({})
    conn.execute("insert into blocked (sender, how, ts) values ('promo@shop.com', 'link', 'now')")
    items = [MailItem("a", "promo@shop.com", "", "48 hours left", "", ""),
             MailItem("b", "promo@shop.com", "", "Your order has shipped", "", ""),
             MailItem("c", "friend@gmail.com", "", "48 hours left", "", ""),
             MailItem("d", "hello@lindy.ai", "", "48 hours left", "", "")]
    conn.execute("insert into blocked (sender, how, ts) values ('hello@lindy.ai', 'link', 'now')")
    assert cleanup.trash_blocked(mail, conn, items) == ["a"] and mail.trashed == ["a"]


def test_watch_mail_expires_read_at_30_days_unread_at_60_starred_never_and_can_be_undone():
    conn, mail = cleanup.connect(":memory:"), FakeMail({})
    asked = []

    def search(q, limit=100):
        asked.append(q)
        return [Found("w1", "hello@lindy.ai", "", "", None)] if "is:read" in q else [
            Found("w2", "team@mail.cerebralvalley.ai", "", "", None)]

    mail.found = search
    assert cleanup.expire_watch(mail, conn) == 2 and mail.trashed == ["w1", "w2"]
    assert asked == ["label:Watch -is:starred is:read older_than:30d", "label:Watch -is:starred is:unread older_than:60d"]
    logged = conn.execute("select message_id, detail from cleanup where action = 'trashed' order by id").fetchall()
    assert logged == [("w1", "watch expiry"), ("w2", "watch expiry")]


D = date(2026, 11, 1)


@pytest.mark.parametrize("subject,snippet,arrived,expected", [
    ("Your Upcoming Appointment with Alex", "See you on Dec 10 at 3pm", D, date(2026, 12, 10)),
    ("Appointment reminder: December 10th, 2026", "", D, date(2026, 12, 10)),
    ("Appointment reminder for 12/10", "", D, date(2026, 12, 10)),
    ("Appointment reminder for 12/10/27", "", D, date(2027, 12, 10)),
    ("Appointment reminder: Jan 5", "", D, date(2027, 1, 5)),  # no year: the next one after it arrived
    ("Hey Felix, your appointment is coming up today at 9:30am", "", D, D),
    ("Hey Felix, your appointment is coming up tomorrow at 9:30am", "", D, date(2026, 11, 2)),
    ("Appointment Reminder", "Please arrive 15 minutes early.", D, None),
    ("Appointment reminder: Nov 3", "or rebook by Nov 1", D, date(2026, 11, 3)),  # the subject speaks first
    ("Appointment reminder", "Nov 3, or rebook by Oct 30", D, cleanup.UNCLEAR),  # two dates
    ("Appointment reminder: Feb 31", "", D, cleanup.UNCLEAR),  # no such day
    ("Appointment reminder: 13/45", "", D, cleanup.UNCLEAR),
])
def test_the_appointment_date_is_read_from_the_reminders_words(subject, snippet, arrived, expected):
    assert cleanup.appointment_date(subject, snippet, arrived) == expected


def test_a_reminder_goes_once_its_date_has_passed_and_an_upcoming_one_stays_however_old_the_email():
    conn, mail = cleanup.connect(":memory:"), FakeMail({})
    today = date(2026, 11, 1)
    mail.found = lambda q, limit=100: [
        Found("past", "a@x.com", "Appointment reminder: Oct 30", "", date(2026, 10, 25)),
        Found("yesterday", "a@x.com", "your appointment is coming up tomorrow", "", date(2026, 10, 30)),
        Found("today", "a@x.com", "your appointment is coming up today", "", today),
        Found("far ahead", "a@x.com", "Your upcoming appointment on Dec 10", "", date(2026, 10, 1)),
        Found("no date old", "a@x.com", "Appointment Reminder", "", date(2026, 10, 18)),
        Found("no date new", "a@x.com", "Appointment Reminder", "", date(2026, 10, 19)),
        Found("unclear", "a@x.com", "Appointment reminder: Feb 31", "", date(2026, 1, 1)),
        Found("unknown arrival", "a@x.com", "Appointment reminder: Oct 30", "", None),
        Found("a reply", "kai@x.com", "Re: Appointment reminder: Oct 30", "", date(2026, 10, 25)),
        Found("a forward", "kai@x.com", "Fwd: Appointment Reminder", "", date(2024, 1, 12))]
    assert cleanup.expire_reminders(mail, conn, today=today) == 3
    assert mail.trashed == ["past", "yesterday", "no date old"]
    details = [r[0] for r in conn.execute("select detail from cleanup where action = 'trashed' order by id")]
    assert details[0] == "appointment reminder, its date 2026-10-30 has passed"
    assert details[2] == "old appointment reminder, no date written, 14 days old"
    assert cleanup.undo(mail, conn) == 3 and mail.untrashed == ["past", "yesterday", "no date old"]


def test_the_reminder_search_leaves_starred_mail_out():
    assert "-is:starred" in cleanup.REMINDERS and "older_than:1d" in cleanup.REMINDERS


def test_trash_all_but_the_latest_keeps_only_the_newest_and_sends_nothing(tmp_path):
    path = tmp_path / "marked.csv"
    path.write_text("sender,suggested\nnotifications@sezzle.com,Trash all but the latest\n")
    mail, posts = FakeMail({}), []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: (posts.append(r), httpx.Response(200))[1]))
    done = cleanup.run(mail, path, cleanup.plan_hash(path), cleanup.connect(":memory:"),
                       gate_conn=gate.connect(":memory:"), http=http, rules_path=tmp_path / "none.md")
    assert mail.trashed == ["notifications@sezzle.com-2", "notifications@sezzle.com-receipt"]
    assert done["trashed"] == 2 and posts == []


def test_a_rerun_skips_what_was_done_and_one_refused_move_does_not_stop_it(plan):
    path, rules = plan
    conn, gconn = cleanup.connect(":memory:"), gate.connect(":memory:")
    posts = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: (posts.append(r), httpx.Response(200))[1]))

    class Flaky(FakeMail):
        def trash(self, message_id):
            if message_id.endswith("-1"):
                raise RuntimeError("Gmail refused the move (HTTP 403: something)")
            super().trash(message_id)

    mail = Flaky({"promo@shop.com": ONE_CLICK, "news@paper.com": ONE_CLICK})
    first = cleanup.run(mail, path, cleanup.plan_hash(path), conn, gate_conn=gconn, http=http, rules_path=rules)
    assert first["not_moved"] == 1 and mail.trashed == ["promo@shop.com-2"]
    again = cleanup.run(mail, path, cleanup.plan_hash(path), conn, gate_conn=gconn, http=http, rules_path=rules)
    assert again["already"] == 2 and len(posts) == 2      # no second unsubscribe


def test_trash_waits_out_a_rate_limit_and_reports_another_refusal(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(403, json={"error": {"message": "User-rate limit exceeded"}})
        if "bad" in request.url.path:
            return httpx.Response(403, json={"error": {"message": "Insufficient Permission"}})
        return httpx.Response(200, json={})

    mail = Mail(auth=FakeAuth(), transport=httpx.MockTransport(handler), rules_path=tmp_path / "R.md")
    monkeypatch.setattr(Mail, "_sleep", staticmethod(lambda s: None))
    mail.trash("m1")
    assert len(calls) == 2
    with pytest.raises(RuntimeError, match="Insufficient Permission"):
        mail.trash("bad")

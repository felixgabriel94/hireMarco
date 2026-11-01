import json

import httpx
import pytest

from hiremarco import gate
from hiremarco.google.mail import Mail
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


def test_new_mail_from_a_blocked_sender_goes_to_trash_receipts_excepted():
    from hiremarco.google.mail import MailItem

    conn, mail = cleanup.connect(":memory:"), FakeMail({})
    conn.execute("insert into blocked (sender, how, ts) values ('promo@shop.com', 'link', 'now')")
    items = [MailItem("a", "promo@shop.com", "", "48 hours left", "", ""),
             MailItem("b", "promo@shop.com", "", "Your order has shipped", "", ""),
             MailItem("c", "friend@gmail.com", "", "48 hours left", "", "")]
    assert cleanup.trash_blocked(mail, conn, items) == 1 and mail.trashed == ["a"]


def test_trash_all_but_the_latest_keeps_only_the_newest_and_sends_nothing(tmp_path):
    path = tmp_path / "marked.csv"
    path.write_text("sender,suggested\nnotifications@sezzle.com,Trash all but the latest\n")
    mail, posts = FakeMail({}), []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: (posts.append(r), httpx.Response(200))[1]))
    done = cleanup.run(mail, path, cleanup.plan_hash(path), cleanup.connect(":memory:"),
                       gate_conn=gate.connect(":memory:"), http=http, rules_path=tmp_path / "none.md")
    assert mail.trashed == ["notifications@sezzle.com-2", "notifications@sezzle.com-receipt"]
    assert done["trashed"] == 2 and posts == []

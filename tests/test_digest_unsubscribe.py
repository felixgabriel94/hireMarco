"""His one reply to the digest: "unsubscribe 2" or "unsubscribe all", and nothing else counts."""
import httpx
import pytest

from hiremarco import gate, inbox, server
from hiremarco.inbox import cleanup

TODAY = "2026-11-02"


class FakeMail:
    def __init__(self, headers):
        self.headers, self.trashed = headers, []

    def latest_from(self, sender):
        return ("m-" + sender, self.headers[sender]) if sender in self.headers else None

    def ids_from(self, sender, keep_starred=False, exclude=""):
        return [f"{sender}-1"] if exclude else [f"{sender}-1", f"{sender}-receipt"]

    def trash(self, message_id):
        self.trashed.append(message_id)


class FakeWhatsApp:
    def __init__(self):
        self.sent = []

    def send_text(self, to, text, idempotency_key=None):
        self.sent.append(text)


ONE_CLICK = {"list-unsubscribe": "<https://shop.com/u>", "list-unsubscribe-post": "List-Unsubscribe=One-Click"}


@pytest.fixture
def world(tmp_path):
    rules = tmp_path / "RULES.md"
    rules.write_text("send: unsubscribe -> * ; senders he named ; until revoked\n")
    posts = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: (posts.append(str(r.url)), httpx.Response(200))[1]))
    conn, listed = inbox.connect(":memory:"), cleanup.connect(":memory:")
    inbox.offer_senders(conn, ["a@shop.com", "b@noway.com", "hello@lindy.ai"], TODAY)
    mail, wa = FakeMail({"a@shop.com": ONE_CLICK, "b@noway.com": {}, "hello@lindy.ai": ONE_CLICK}), FakeWhatsApp()

    def reply(said, today=TODAY):
        return server.digest_unsubscribe(said, "owner", "w1", wa, conn=conn, listed=listed, mail=mail, http=http,
                                         gate_conn=gate.connect(":memory:"), rules_path=rules, today=today)
    return reply, mail, wa, posts, listed, conn


@pytest.mark.parametrize("said,asked", [("unsubscribe 2", [2]), ("Unsubscribe all", "all"), ("unsubscribe from 1, 3.", [1, 3]),
                                        ("unsubscribe 1 and 2", [1, 2]), ("UNSUBSCRIBE 1 2", [1, 2])])
def test_the_words_that_count(said, asked):
    assert inbox.unsubscribe_words(said) == asked


@pytest.mark.parametrize("said", ["unsubscribe", "how do I unsubscribe 2 from this?", "unsubscribe me from Chase",
                                  "don't unsubscribe all", "please unsubscribe 2 and call mom", "", None])
def test_anything_else_goes_to_the_brain_and_nothing_moves(world, said):
    reply, mail, wa, posts, *_ = world
    assert reply(said) is None and wa.sent == [] and mail.trashed == [] and posts == []


def test_one_number_unsubscribes_and_trashes_only_that_sender_and_receipts_stay(world):
    reply, mail, wa, posts, listed, _ = world
    assert "1 senders" in reply("unsubscribe 1")
    assert posts == ["https://shop.com/u"] and mail.trashed == ["a@shop.com-1"]
    assert wa.sent == ["shop.com: unsubscribed, 1 email to Trash, 1 receipt stayed."]
    assert not cleanup.blocked(listed, "a@shop.com")


def test_no_working_unsubscribe_goes_on_the_auto_trash_list(world):
    reply, mail, wa, posts, listed, _ = world
    reply("unsubscribe 2")
    assert posts == [] and cleanup.blocked(listed, "b@noway.com") and mail.trashed == ["b@noway.com-1"]
    assert wa.sent[0].startswith("noway.com: no working unsubscribe, so their new mail goes straight to Trash.")


def test_all_takes_the_list_but_a_keep_list_sender_is_left_alone(world):
    reply, mail, wa, posts, listed, _ = world
    reply("unsubscribe all")
    assert "hello@lindy.ai-1" not in mail.trashed and not cleanup.blocked(listed, "hello@lindy.ai")
    assert posts == ["https://shop.com/u"] and "lindy.ai: left alone, you keep that one." in wa.sent[0]


def test_a_number_not_on_the_list_and_no_list_are_said_plainly(world):
    reply, mail, wa, *_ = world
    assert reply("unsubscribe 9") and wa.sent == ["Number 9 isn't on the list."] and mail.trashed == []
    wa.sent.clear()
    assert reply("unsubscribe all", today="2026-11-06") and "no list" in wa.sent[0] and mail.trashed == []


def test_without_the_owners_switch_line_nothing_is_sent(world, tmp_path):
    reply, mail, wa, posts, listed, conn = world
    with pytest.raises(gate.Refused):
        server.digest_unsubscribe("unsubscribe 1", "owner", "w2", wa, conn=conn, listed=listed, mail=mail,
                                  gate_conn=gate.connect(":memory:"), rules_path=tmp_path / "none.md", today=TODAY,
                                  http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
    assert posts == [] and mail.trashed == []


def test_the_digest_numbers_match_what_a_reply_points_at():
    conn = inbox.connect(":memory:")
    inbox.offer_senders(conn, ["a@shop.com", "b@shop.com"], TODAY)
    text = inbox.digest([], [], ["a@shop.com", "b@shop.com"])
    assert "1. a@shop.com\n2. b@shop.com" in text and "unsubscribe all" in text
    assert inbox.offered_senders(conn, [2], TODAY) == (["b@shop.com"], [])
    inbox.offer_senders(conn, [], TODAY)  # a morning with no new senders leaves the numbers standing
    assert inbox.offered_senders(conn, [1], TODAY) == (["a@shop.com"], [])

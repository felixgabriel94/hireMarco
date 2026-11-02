"""'Send it to mix' by text: the brain's master action runs the job beside the webhook, one at a time."""

from types import SimpleNamespace

from hiremarco import server


class FakeWA:
    def __init__(self):
        self.sent = []

    def send_text(self, to, body, **kw):
        self.sent.append((to, body))
        return "wamid"


def test_start_master_runs_the_job_with_the_direction_and_sends():
    wa, seen = FakeWA(), []

    def run(**kw):
        seen.append(kw)
        return SimpleNamespace(stopped="", caption="Master, demo: -10.2 LUFS")

    did = server.start_master(wa, "15550001111", "a touch warmer", run=run, start=lambda f: f())
    assert did == "mastering started"
    assert seen[0]["direction"] == "a touch warmer" and seen[0]["send"] is True
    assert wa.sent == []                                   # the job texts the WAVs itself; nothing to add
    assert not server._MASTERING.locked()


def test_a_stopped_job_texts_why_and_frees_the_lock():
    wa = FakeWA()
    server.start_master(wa, "15550001111", "", run=lambda **kw: SimpleNamespace(stopped="the mix print is silent"),
                        start=lambda f: f())
    assert wa.sent == [("15550001111", "The master stopped: the mix print is silent")]
    assert not server._MASTERING.locked()


def test_a_crash_in_the_job_is_texted_too():
    wa = FakeWA()

    def run(**kw):
        raise RuntimeError("Logic is not in front")

    server.start_master(wa, "15550001111", "", run=run, start=lambda f: f())
    assert wa.sent[0][1].startswith("The master stopped: Logic is not in front")
    assert not server._MASTERING.locked()


def test_only_one_master_at_a_time():
    wa = FakeWA()
    held = []
    assert server.start_master(wa, "1", "", run=lambda **kw: SimpleNamespace(stopped=""), start=held.append) == "mastering started"
    assert server.start_master(wa, "1", "", run=lambda **kw: None, start=held.append) == "a master is already printing"
    held[0]()                                              # the first finishes
    assert not server._MASTERING.locked()

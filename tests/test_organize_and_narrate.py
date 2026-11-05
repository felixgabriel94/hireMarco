"""Organize his session on the copy he opened, and the halo for his spoken lines in the middle of work (Owner
2026-11-04). Every track and song here is made up."""

from hiremarco import config, glow
from hiremarco.studio import organize
from hiremarco.studio.commands import tidy_command
from tests.test_beat_in import booth_with, inbound, whatsapp_line
from tests.test_open_song import song_at


def quiet(monkeypatch):
    from hiremarco import events
    from hiremarco.studio import pad

    rows = []
    monkeypatch.setattr(events, "emit", lambda kind, **k: rows.append((kind, k.get("operation"))) or {})
    monkeypatch.setattr(pad, "start", lambda: None)
    monkeypatch.setattr(pad, "stop", lambda fade=1.0: None)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return rows


def test_the_words():
    assert tidy_command("open my latest session and organize it") .text == "organize"
    assert tidy_command("open my latest track").action == "open_song"
    assert tidy_command("organize my session").action == "organize"
    assert tidy_command("label everything").action == "organize"
    assert tidy_command("open a new session").action == "new_session"


def test_organizing_needs_the_copy_he_opened(monkeypatch):
    quiet(monkeypatch)
    b, said = booth_with(lambda p: "unused")
    b.organize = lambda: (_ for _ in ()).throw(AssertionError("must not run"))
    assert b.organize_session().startswith("organize held") and said == ["Let me open your song first, so I work on a copy."]


def test_open_and_organize_is_one_ask_with_one_line_and_one_text(monkeypatch):
    rows = quiet(monkeypatch)
    texts = []
    b, said = booth_with(lambda p: "unused")
    b.text_owner = lambda body, quote=None: texts.append(body) or "wamid.x"
    b.open_song = lambda: "Made Up Song 2026-11-04.logicx is open, a copy of Made Up Song.logicx"
    b.organize = lambda: "12 of 14 tracks renamed and read back"
    done = b.song_session(then_organize=True)
    assert "12 of 14 tracks renamed" in done and said == ["Your session's labeled and ready."]
    assert texts == ["Session's labeled and ready."]
    assert ("work_started", "organize") in rows and rows.index(("work_ended", "open_song")) < rows.index(("work_started", "organize"))


def test_organize_now_surveys_plans_and_applies():
    layout = type("L", (), {"tracks": [1, 2, 3]})()
    seen = []
    line = organize.organize_now(survey_of=lambda: layout, propose_for=lambda l: seen.append(l) or "plan",
                                 apply_plan=lambda p: [(1, "a", "b"), (2, "c", "d")])
    assert line == "2 of 3 tracks renamed and read back" and seen == [layout]


def test_open_my_latest_session_and_organize_it_by_text(tmp_path, monkeypatch):
    from hiremarco import server
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    config.set_value("HIREMARCO_SONG", str(song_at(tmp_path)), config.env_path())
    words = []
    monkeypatch.setattr(server, "nudge_booth", lambda word, **k: words.append(word))
    handle(inbound(wa, "w1", kind="text", text="Set up my session, open my latest session and organize it"), wa=wa, inbox=tmp_path / "inbox")
    assert words == [b"song organize"] and b"labeling everything" in sent[-1]


def test_the_glow_rests_while_he_speaks_and_is_born_again_after_the_halo():
    state = glow.State(alive=lambda pid: True)
    state.add([{"kind": "job_started", "pid": 7}], 0.0)
    assert state.working(5.0)
    state.add([{"kind": "glow_rest", "pid": 7}], 10.0)
    assert not state.working(10.5) and state.phase(10.5) < 1.0 and state.phase(10.0 + glow.BIRTH_S + 0.01) == 0.0
    state.add([{"kind": "glow_back", "pid": 7}], 20.0)
    assert state.working(20.0) and state.phase(20.0 + glow.HANDOFF_S) == 0.0 and state.phase(20.0 + glow.HANDOFF_S + glow.BIRTH_S) == 1.0
    state.add([{"kind": "job_ended"}], 30.0)
    assert not state.working(30.0) and not state.resting


def test_a_spoken_checkpoint_puts_the_glow_out_first_and_back_after(monkeypatch):
    rows = quiet(monkeypatch)
    b, said = booth_with(lambda p: "unused")
    b.in_logic = True
    seen = []
    b._say = lambda moment, facts, plain: seen.append((b.in_logic, list(rows))) or said.append(plain)
    b._narrate("a moment", {}, "Here's your song before my work, then after.")
    in_logic_while_speaking, rows_then = seen[0]
    assert in_logic_while_speaking is False and rows_then[-1][0] == "glow_rest"
    assert rows[-1][0] == "glow_back" and b.in_logic is True


def test_stacks_are_opened_before_the_survey_and_a_closed_one_is_said(monkeypatch):
    # live 2026-11-04: with the stacks closed he saw 3 of 30 tracks and said "labeled and ready"
    from types import SimpleNamespace

    from hiremarco.studio import organize

    order = []
    layout = SimpleNamespace(tracks=[SimpleNamespace(stack="closed"), SimpleNamespace(stack=""),
                                     SimpleNamespace(stack="open")])
    line = organize.organize_now(unstack=lambda: order.append("open") or {"opened": 4, "still_closed": 1},
                                 survey_of=lambda: order.append("survey") or layout, propose_for=lambda l: "plan",
                                 apply_plan=lambda p: [1, 2], log=lambda line: None)
    assert order == ["open", "survey"]
    assert line == "2 of 3 tracks renamed and read back; 1 stack stayed closed"


def test_the_ready_text_brings_the_live_view_text_behind_it(monkeypatch):
    # Owner 2026-11-04: "Session's ready" comes with the live view card and its link, so he can watch from anywhere
    quiet(monkeypatch)
    sent = []
    b, said = booth_with(lambda p: "unused")
    b.text_owner = lambda body, quote=None: sent.append(("text", body)) or "wamid.x"
    b.send_link = lambda body, url: sent.append(("link", body, url))
    b.live = lambda: "http://192.168.5.196:8800/live"
    b.open_song = lambda: "Made Up Song 2026-11-04.logicx is open, a copy of Made Up Song.logicx"
    b.organize = lambda: "12 of 14 tracks renamed and read back"
    done = b.song_session(then_organize=True)
    assert sent == [("text", "Session's labeled and ready."), ("link", "Live now. Join in. 👨🏻‍💻", "http://192.168.5.196:8800/live")]
    assert done.endswith("live view texted")
    sent.clear()
    b.copy_open = False
    assert "live view texted" in b.song_session()
    assert sent[0] == ("text", "Session's ready.") and sent[1][0] == "link"


def test_no_live_view_text_where_links_are_not_texted_or_it_is_turned_off(monkeypatch):
    quiet(monkeypatch)
    sent = []
    b, said = booth_with(lambda p: "unused")
    b.text_owner = lambda body, quote=None: sent.append(body) or "wamid.x"
    b.live = lambda: "http://192.168.5.196:8800/live"
    b.open_song = lambda: "a copy is open"
    b.send_link = None
    b.song_session()
    assert sent == ["Session's ready."]
    sent.clear()
    b.send_link = lambda body, url: sent.append(url)
    monkeypatch.setattr(config, "get", lambda k, *a: "off" if k == "HIREMARCO_READY_LIVE" else None)
    b.song_session()
    assert sent == ["Session's ready."]

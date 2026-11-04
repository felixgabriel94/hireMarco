"""The session starts on his song (Owner 2026-11-04): "set up my session" with no beat opens a fresh copy of the song
set in HIREMARCO_SONG, never the original. Every song here is made up."""

from pathlib import Path

import pytest

from hiremarco import config
from hiremarco.studio.beat_in import LoadError, his_song
from hiremarco.studio.commands import tidy_command
from tests.test_beat_in import FakeLogic, booth_with, inbound, loader, whatsapp_line


def song_at(folder: Path, name="Made Up Song") -> Path:
    song = folder / "songs" / f"{name}.logicx"
    (song / "Media" / "Audio Files").mkdir(parents=True)
    (song / "Media" / "Audio Files" / "Vocal.wav").write_bytes(b"take")
    (song / "Alternatives" / "000").mkdir(parents=True)
    (song / "Alternatives" / "000" / "ProjectData").write_bytes(b"song")
    return song


def test_a_copy_of_his_song_opens_and_the_original_is_untouched(tmp_path):
    song, logic = song_at(tmp_path), FakeLogic("Made Up Song")
    result = loader(tmp_path, logic).open_song(song)
    copy = tmp_path / "sessions" / "Made Up Song 2026-10-29.logicx"
    assert result == "Made Up Song 2026-10-29.logicx is open, a copy of Made Up Song.logicx"
    assert logic.opened == copy and (copy / "Alternatives" / "000" / "ProjectData").read_bytes() == b"song"
    assert (copy / "Media" / "Audio Files" / "Vocal.wav").read_bytes() == b"take"
    (copy / "Media" / "Audio Files" / "Vocal.wav").write_bytes(b"new take")
    assert (song / "Media" / "Audio Files" / "Vocal.wav").read_bytes() == b"take"


def test_a_second_open_the_same_day_is_a_new_copy(tmp_path):
    song, logic = song_at(tmp_path), FakeLogic("Made Up Song")
    opener = loader(tmp_path, logic)
    opener.open_song(song)
    assert opener.open_song(song).startswith("Made Up Song 2026-10-29 2.logicx is open")
    assert logic.opened == tmp_path / "sessions" / "Made Up Song 2026-10-29 2.logicx"


def test_a_project_folder_song_is_refused_so_nothing_plays_from_the_original(tmp_path):
    song = tmp_path / "Project" / "Made Up Song.logicx"
    (song / "Alternatives").mkdir(parents=True)
    (tmp_path / "Project" / "Audio Files").mkdir()
    with pytest.raises(LoadError, match="project folder"):
        loader(tmp_path, FakeLogic("Made Up Song")).open_song(song)


def test_no_song_set_is_said_plainly(tmp_path):
    assert his_song() is None
    with pytest.raises(LoadError, match="no song is set"):
        loader(tmp_path, FakeLogic("x")).open_song()


def test_his_song_reads_the_setting(tmp_path, monkeypatch):
    song = song_at(tmp_path)
    config.set_value("HIREMARCO_SONG", str(song), config.env_path())
    assert his_song() == song
    config.set_value("HIREMARCO_SONG", str(tmp_path / "gone.logicx"), config.env_path())
    assert his_song() is None


def test_open_my_song_is_a_booth_command():
    assert tidy_command("open my song").action == "open_song"
    assert tidy_command("pull up the song").action == "open_song"
    assert tidy_command("open a new session").action == "new_session"


def test_the_booth_opens_his_song_with_the_halo_first_then_texts_session_ready(monkeypatch):
    from hiremarco import events
    from hiremarco.studio import pad

    rows, played, texts = [], [], []
    monkeypatch.setattr(events, "emit", lambda kind, **k: rows.append((kind, k.get("operation"))) or {})
    monkeypatch.setattr(pad, "start", lambda: played.append("start"))
    monkeypatch.setattr(pad, "stop", lambda fade=1.0: played.append(("fade", fade)))
    monkeypatch.setattr("time.sleep", lambda s: None)
    b, said = booth_with(lambda p: "unused")
    b.text_owner = lambda body, quote=None: texts.append(body) or "wamid.x"
    b.open_song = lambda: "Made Up Song 2026-11-04.logicx is open, a copy of Made Up Song.logicx"
    assert b.song_session().startswith("Made Up Song 2026-11-04.logicx is open")
    assert said == ["Your song's up in Logic."] and texts == ["Session's ready."]
    assert rows == [("work_started", "open_song"), ("stage", "open song"), ("work_ended", "open_song"), ("stage", "waiting")]
    assert played == ["start", ("fade", 2.0)]


def test_a_failed_open_says_so_and_texts_him(monkeypatch):
    from hiremarco import events
    from hiremarco.studio import pad

    monkeypatch.setattr(events, "emit", lambda kind, **k: {})
    monkeypatch.setattr(pad, "start", lambda: None)
    monkeypatch.setattr(pad, "stop", lambda fade=1.0: None)
    monkeypatch.setattr("time.sleep", lambda s: None)
    texts = []
    b, said = booth_with(lambda p: "unused")
    b.text_owner = lambda body, quote=None: texts.append(body) or "wamid.x"

    def broken():
        raise LoadError("the song is missing")

    b.open_song = broken
    assert b.song_session().startswith("song not opened") and b.operating is False
    assert said == ["I couldn't open your song."] and texts == ["I couldn't open your song. Nothing changed on it."]


def test_set_up_my_session_with_no_beat_opens_his_song(tmp_path, monkeypatch):
    from hiremarco import server
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    config.set_value("HIREMARCO_SONG", str(song_at(tmp_path)), config.env_path())
    words = []
    monkeypatch.setattr(server, "nudge_booth", lambda word, **k: words.append(word))
    line = handle(inbound(wa, "w1", kind="text", text="Set up my session"), wa=wa, inbox=tmp_path / "inbox")
    assert "his song asked of the booth" in line and words == [b"song"] and b"Setting up your session" in sent[-1]


def test_set_up_my_session_with_no_song_set_still_asks_for_the_beat(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    line = handle(inbound(wa, "w1", kind="text", text="Set up my session"), wa=wa, inbox=tmp_path / "inbox")
    assert "none is waiting" in line and b"Send me the beat first" in sent[-1]


def old_beat(tmp_path, hours=2.0, name="Old Beat.wav"):
    import os
    import time

    beat = tmp_path / "inbox" / "received" / name
    beat.parent.mkdir(parents=True, exist_ok=True)
    beat.write_bytes(b"RIFF-beat")
    then = time.time() - hours * 3600
    os.utime(beat, (then, then))
    return beat


def three_jobs(tmp_path, monkeypatch):
    from hiremarco import server

    wa, sent = whatsapp_line(tmp_path, monkeypatch)
    config.set_value("HIREMARCO_SONG", str(song_at(tmp_path)), config.env_path())
    words, brain = [], []
    monkeypatch.setattr(server, "nudge_booth", lambda word, **k: words.append(word))
    monkeypatch.setattr(server, "decide", lambda *a, **k: brain.append(a) or (_ for _ in ()).throw(RuntimeError("no brain")))
    return wa, sent, words, brain


def test_an_older_beat_waiting_gets_one_question_and_song_opens_his_song(tmp_path, monkeypatch):
    # Owner 2026-11-04: three jobs, open and wait / open and organize / open with a beat; he asks when unsure
    from hiremarco.server import handle

    wa, sent, words, brain = three_jobs(tmp_path, monkeypatch)
    beat = old_beat(tmp_path)
    line = handle(inbound(wa, "w1", kind="text", text="Marco, set up my session"), wa=wa, inbox=tmp_path / "inbox")
    assert "asked: the beat" in line and b"Is this for the beat you sent at " in sent[-1]
    assert b", or your song?" in sent[-1] and words == [] and brain == []
    line = handle(inbound(wa, "w2", kind="text", text="Song"), wa=wa, inbox=tmp_path / "inbox")
    assert "his song asked of the booth" in line and words == [b"song"] and beat.exists() and brain == []


def test_the_beat_answer_starts_the_beat(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent, words, brain = three_jobs(tmp_path, monkeypatch)
    old_beat(tmp_path)
    handle(inbound(wa, "w1", kind="text", text="Set up my session"), wa=wa, inbox=tmp_path / "inbox")
    line = handle(inbound(wa, "w2", kind="text", text="The beat"), wa=wa, inbox=tmp_path / "inbox")
    assert "session started for Old Beat.wav" in line and words == []
    assert (tmp_path / "inbox" / "Old Beat.wav").exists()


def test_organize_is_always_his_song_and_a_named_beat_is_the_beat(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent, words, brain = three_jobs(tmp_path, monkeypatch)
    old_beat(tmp_path)
    line = handle(inbound(wa, "w1", kind="text", text="Marco, set up my session and organize it please"), wa=wa,
                  inbox=tmp_path / "inbox")
    assert "his song asked of the booth" in line and words == [b"song organize"]
    assert b"labeling everything" in sent[-1]
    line = handle(inbound(wa, "w2", kind="text", text="Set up my session with the beat"), wa=wa, inbox=tmp_path / "inbox")
    assert "session started for Old Beat.wav" in line and brain == []


def test_a_beat_that_just_came_is_the_beat_without_a_question(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent, words, brain = three_jobs(tmp_path, monkeypatch)
    old_beat(tmp_path, hours=0.1, name="New Beat.wav")
    line = handle(inbound(wa, "w1", kind="text", text="Set up my session"), wa=wa, inbox=tmp_path / "inbox")
    assert "session started for New Beat.wav" in line and words == []


def test_set_up_my_session_never_reaches_the_brain_that_only_knows_beats(tmp_path, monkeypatch):
    from hiremarco.server import handle

    wa, sent, words, brain = three_jobs(tmp_path, monkeypatch)
    line = handle(inbound(wa, "w1", kind="text", text="Marco, set up my session pls"), wa=wa, inbox=tmp_path / "inbox")
    assert "his song asked of the booth" in line and words == [b"song"] and brain == []


def test_his_song_is_shown_in_finder_before_the_copy(tmp_path):
    # Owner 2026-11-04: the judges see him find the one song on LaCie, never Logic's recents
    from hiremarco.studio.beat_in import BeatLoader

    song, logic, order = song_at(tmp_path), FakeLogic("Made Up Song"), []
    opener = loader(tmp_path, logic)
    opener.reveal = lambda path: order.append(("reveal", path))
    real_open = opener.open_session
    opener.open_session = lambda *a, **k: order.append(("copy", a[0])) or real_open(*a, **k)
    opener.open_song(song)
    assert order == [("reveal", song), ("copy", song)]
    (tmp_path / "b").mkdir()
    assert loader(tmp_path / "b", logic).reveal is None   # stand-in hands: no Finder during tests

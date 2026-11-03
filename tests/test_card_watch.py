"""The card watcher copies a card once, verified, and reports; an unknown card is reported, not guessed."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import card_watch  # noqa: E402
import offload  # noqa: E402


@pytest.fixture
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setattr(card_watch, "STATE", state / "cards")
    monkeypatch.setattr(card_watch, "notify", lambda *a, **k: None)
    footage = tmp_path / "13-footage"
    footage.mkdir()
    card = tmp_path / "Volumes" / "UNTITLED"
    (card / "DCIM" / "100MSDCF").mkdir(parents=True)
    (card / "DCIM" / "100MSDCF" / "C0001.MP4").write_bytes(os.urandom(50_000))
    (card / "PRIVATE" / "M4ROOT" / "CLIP").mkdir(parents=True)
    (card / "PRIVATE" / "M4ROOT" / "CLIP" / "C0001.XML").write_text("<x/>")
    monkeypatch.setattr(offload, "candidates", lambda: [card])
    return footage, card


def test_card_copied_once_and_verified(world):
    footage, card = world
    out = card_watch.sweep(footage)
    assert len(out) == 1 and out[0].startswith("Card UNTITLED") and "2 copied" in out[0]
    day = card_watch.today_folder(footage)
    copies = list((day / "a7r3").glob("UNTITLED-*/DCIM/100MSDCF/C0001.MP4"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == (card / "DCIM" / "100MSDCF" / "C0001.MP4").read_bytes()
    assert (day / "a7r3" / "offload.jsonl").exists()
    assert "copied and verified" in (footage / "cards.log").read_text()
    # plugged in again: nothing happens
    assert card_watch.sweep(footage) == []
    assert list((day / "a7r3").glob("UNTITLED-*")) .__len__() == 1


def test_unknown_card_is_reported_not_guessed(world, monkeypatch):
    footage, card = world
    other = card.parent / "MYSTERY"
    (other / "DCIM" / "100WEIRD").mkdir(parents=True)
    (other / "DCIM" / "100WEIRD" / "a.mp4").write_bytes(b"x" * 10)
    monkeypatch.setattr(offload, "candidates", lambda: [other])
    out = card_watch.sweep(footage)
    assert len(out) == 1 and "cannot tell which camera" in out[0] and "--device" in out[0]
    assert not list(card_watch.today_folder(footage).rglob("a.mp4"))
    assert card_watch.sweep(footage) == []


def test_screen_recording_mirrored_once_and_kept(world, tmp_path, monkeypatch):
    footage, card = world
    monkeypatch.setattr(offload, "candidates", lambda: [])
    staging = tmp_path / "staging"
    staging.mkdir()
    rec = staging / "Screen Recording 2026-11-03 at 1.00.00 PM.mov"
    rec.write_bytes(os.urandom(20_000))
    old = rec.stat().st_mtime - 60
    os.utime(rec, (old, old))
    (staging / "growing.mov").write_bytes(b"x")  # just written: left for later
    monkeypatch.setattr(card_watch, "STAGING", staging)
    out = card_watch.mirror_screen_recordings(footage, staging)
    assert len(out) == 1 and "verified" in out[0]
    copies = list(footage.rglob("screen/manual/Screen Recording*.mov"))
    assert len(copies) == 1 and copies[0].read_bytes() == rec.read_bytes()
    assert rec.exists()  # local copy kept
    assert card_watch.mirror_screen_recordings(footage, staging) == []


def test_copied_recording_is_not_read_again(world, tmp_path, monkeypatch):
    footage, card = world
    staging = tmp_path / "staging2"
    staging.mkdir()
    rec = staging / "Screen Recording big.mov"
    rec.write_bytes(os.urandom(10_000))
    old = rec.stat().st_mtime - 60
    os.utime(rec, (old, old))
    assert len(card_watch.mirror_screen_recordings(footage, staging)) == 1
    calls = []
    real = offload.sha256
    monkeypatch.setattr(offload, "sha256", lambda p: calls.append(p) or real(p))
    assert card_watch.mirror_screen_recordings(footage, staging) == []
    assert calls == []  # no hashing of a file already copied


def test_talkback_lines_mirrored_with_their_manifest(world, tmp_path):
    import json as _json
    footage, card = world
    cap = tmp_path / "capture"
    cap.mkdir()
    (cap / "2026-11-03T13-05-01.123_marco.wav").write_bytes(os.urandom(4000))
    (cap / "2026-11-03T13-06-00.000_marco.wav").write_bytes(os.urandom(4000))  # still playing: no row yet
    (cap / "2026-11-02T10-00-00.000_marco.wav").write_bytes(os.urandom(4000))
    rows = [{"played_at": "2026-11-03T13:05:01.200-05:00", "file": "2026-11-03T13-05-01.123_marco.wav", "text": "Talk to me."},
            {"played_at": "2026-11-02T10:00:00.100-05:00", "file": "2026-11-02T10-00-00.000_marco.wav", "text": "Yeah?"}]
    (cap / "talkback.jsonl").write_text("".join(_json.dumps(r) + "\n" for r in rows))
    out = card_watch.mirror_talkback(footage, cap)
    assert out == ["2 talkback line(s) from Marco copied to the LaCie and verified"]
    d3 = footage / "2026-11-03" / "audio" / "talkback"
    assert (d3 / "2026-11-03T13-05-01.123_marco.wav").read_bytes() == (cap / "2026-11-03T13-05-01.123_marco.wav").read_bytes()
    assert not (d3 / "2026-11-03T13-06-00.000_marco.wav").exists()
    m = [_json.loads(x) for x in (d3 / "talkback.jsonl").read_text().splitlines()]
    assert [r["file"] for r in m] == ["2026-11-03T13-05-01.123_marco.wav"]
    assert (footage / "2026-11-02" / "audio" / "talkback" / "2026-11-02T10-00-00.000_marco.wav").exists()
    assert card_watch.mirror_talkback(footage, cap) == []

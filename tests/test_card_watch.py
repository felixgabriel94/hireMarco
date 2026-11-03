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

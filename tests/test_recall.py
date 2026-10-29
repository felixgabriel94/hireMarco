from pathlib import Path

import pytest

from hiremarco.studio import recall


def fake(lit_after: bool, lit_before: bool = False):
    state = {"lit": lit_before, "clicks": []}

    def press(x, y):
        state["clicks"].append((round(x, 1), round(y, 1)))
        state["lit"] = lit_after

    parts = dict(frame=lambda name, run: (105.0, 207.0, 465.0, 237.0), find=lambda box: 3396,
                 shoot=lambda wid, path: path, light=lambda png: 0.66 if state["lit"] else 0.35,
                 press=press, run=lambda script: "")
    return state, parts


def test_sync_is_clicked_at_its_place_in_the_window_and_read_back(monkeypatch):
    monkeypatch.setattr(recall.time, "sleep", lambda s: None)
    state, parts = fake(lit_after=True)
    assert recall.ensure_sync(**parts) == "SYNC on (read 0.35 -> 0.66)"
    assert state["clicks"] == [(139.0, 373.5)]          # 105 + 0.0731 x 465, 207 + 0.7025 x 237


def test_sync_already_on_is_not_clicked(monkeypatch):
    monkeypatch.setattr(recall.time, "sleep", lambda s: None)
    state, parts = fake(lit_after=True, lit_before=True)
    assert recall.ensure_sync(**parts).startswith("SYNC already on") and state["clicks"] == []


def test_a_click_that_does_not_light_it_is_an_error(monkeypatch):
    monkeypatch.setattr(recall.time, "sleep", lambda s: None)
    state, parts = fake(lit_after=False)
    with pytest.raises(RuntimeError, match="still reads off"):
        recall.ensure_sync(**parts)

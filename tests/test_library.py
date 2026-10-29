import pytest

from hiremarco.studio import library


def test_bus_track_selects_the_strip_then_uses_the_mixer_menu(monkeypatch):
    monkeypatch.setattr(library.time, "sleep", lambda s: None)
    calls, clicks = [], []

    def run(args):
        calls.append(args)
        if args[0] == "-e" and len(args) == 3:
            return "150.0, -88.0"
        if args[0] == "-e":
            return "Aux 1"
        return "clicked Create Tracks for Selected Channel Strips"

    assert library.bus_track("Aux 1", run=run, press=lambda x, y: clicks.append((x, y))).startswith("clicked")
    assert clicks == [(150.0, -88.0)] and calls[-1][1:] == ["Options", "Create Tracks for Selected Channel Strips"]


def test_bus_track_stops_when_another_strip_has_focus(monkeypatch):
    monkeypatch.setattr(library.time, "sleep", lambda s: None)

    def run(args):
        if args[0] == "-e" and len(args) == 3:
            return "150.0, -88.0"
        return "OS_6ix_149_vocal_remnants_Em"

    with pytest.raises(RuntimeError, match="no track made"):
        library.bus_track("Aux 1", run=run, press=lambda x, y: None)


def test_save_patch_passes_the_track_and_name():
    seen = []
    library.save_patch("Verb Bus", "006-VERB BUS!", run=lambda args: seen.append(args) or "saved")
    assert seen[0][1:] == ["Verb Bus", "006-VERB BUS!"] and seen[0][0].endswith("library_io.applescript")

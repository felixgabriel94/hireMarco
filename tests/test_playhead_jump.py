"""The playhead moves in one jump, never by sliding a bar at a time (Owner 2026-11-02)."""

from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "src" / "hiremarco" / "studio" / "scripts" / "markers_io.applescript"


def test_the_marker_script_jumps_through_the_dialog_and_never_steps():
    text = SCRIPT.read_text()
    assert 'window "Go To Position"' in text and 'menu item "Position…"' in text
    assert 'click menu bar item "Navigate"' in text          # the menu opened for real, or Logic ignores the click
    assert "repeat 600 times" not in text and "set value of s to target" not in text   # the bar-by-bar stepping
    for cmd in ("goto", "gotoexact", "where", "whereexact"):
        assert f'if cmd is "{cmd}"' in text
    assert "gotoPosition" not in text

"""The Owner is FEGA to Marco, in capitals, said "Feyga"; to anyone else, on a call or a booking, he is Felix Gabriel
(Owner 2026-11-04)."""

import pytest

from hiremarco import calls, gate
from hiremarco.style import to_owner, written
from hiremarco.voice.tts import speakable


@pytest.mark.parametrize("said, out", [
    ("Morning, Felix.", "Morning, FEGA."),
    ("Morning, Fega. Session's up.", "Morning, FEGA. Session's up."),
    ("fega, your master is ready", "FEGA, your master is ready"),
    ("Felix, want me to book it?", "FEGA, want me to book it?"),
    ("I booked it for Felix Gabriel at 8pm.", "I booked it for Felix Gabriel at 8pm."),
    ("Sent from felix@hiremarco.ai.", "Sent from felix@hiremarco.ai."),
    ("Felix's table is at 8pm.", "Felix's table is at 8pm."),
    ("Mexican Felix Betancourt", "Mexican Felix Betancourt"),
])
def test_his_name_to_him_is_fega_in_capitals(said, out):
    assert to_owner(said) == out


def test_whatsapp_text_goes_through_it():
    assert written("Morning, fega. See you at 8:00 pm") .startswith("Morning, FEGA.")


def test_the_voice_says_feyga_and_the_screen_shows_fega():
    assert speakable("Morning, FEGA.") == "Morning, Feyga."
    assert speakable("Let's go, Fega") == "Let's go, Feyga"


def test_calls_and_bookings_say_felix_gabriel():
    assert gate.RECORDING_NOTICE == "Hi, just so you know, this call is recorded. I'm calling to book a table for Felix Gabriel."
    assert calls.OPENING.format(purpose="book a table") == gate.RECORDING_NOTICE


def test_the_booth_says_fega(tmp_path):
    from hiremarco.studio.booth import Booth, Tape
    from hiremarco.studio.commands import understand

    said = []
    b = Booth(understand=lambda line: understand(line, client=None), logic=lambda c: c.describe(), say=said.append,
              feedback=None, tape=Tape(1000, seconds=1), log=lambda line: None)
    b._speak("Morning, Felix. Your session's up.")
    assert said == ["Morning, FEGA. Your session's up."]

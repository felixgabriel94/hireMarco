from pathlib import Path

import pytest

from hiremarco import config
from hiremarco.calls import brief as briefs

FILLED = {"full_name": "Felix Example", "email": "f@example.com", "seating": "indoor", "special_requests": "none",
          "time_window": "plus or minus 30 minutes"}


def test_reservation_needs_every_predictable_question():
    with pytest.raises(briefs.BriefIncomplete) as gap:
        briefs.build("reservation", {}, profile=dict(briefs.PROFILE_FIELDS))
    # the callback and the card answer are fixed; everything else must be given before dialing
    assert gap.value.missing == ["name", "party_size", "date", "time", "time_window", "seating", "occasion",
                                 "special_requests", "email"]


def test_profile_fills_standing_facts_and_the_call_fills_the_rest():
    full = briefs.build("reservation", {"party_size": "4", "date": "Thursday", "time": "8 pm", "occasion": "none"},
                        profile=FILLED)
    assert full["name"] == "Felix Example" and full["email"] == "f@example.com"
    assert "never read out card details" in full["card_hold"] and "calling from" in full["callback"]
    text = briefs.render(full)
    assert "- name on the booking (first and last): Felix Example" in text and "- party size: 4" in text


def test_given_values_override_the_profile_and_extras_are_kept():
    full = briefs.build("reservation", {"party_size": "2", "date": "Fri", "time": "7 pm", "occasion": "birthday",
                                        "seating": "outdoor", "parking": "valet if any"}, profile=FILLED)
    assert full["seating"] == "outdoor" and full["parking"] == "valet if any"


def test_kind_from_purpose_and_generic_template():
    assert briefs.kind_for("book a table") == "reservation"
    assert briefs.kind_for("ask about their opening hours") == "generic"
    assert briefs.kind_for("ask about booking a studio session") == "generic"
    assert briefs.kind_for("make a dinner reservation") == "reservation"
    assert briefs.kind_for("book lunch for two") == "reservation"
    with pytest.raises(briefs.BriefIncomplete) as gap:
        briefs.build("generic", {}, profile=FILLED)
    assert gap.value.missing == ["ask", "if_unavailable"]
    with pytest.raises(ValueError):
        briefs.build("haircut", {}, profile=FILLED)


def test_pairs_and_profile_stay_outside_the_repo(tmp_path):
    assert briefs.parse_pairs(["party_size=4", "time = 8 pm "]) == {"party_size": "4", "time": "8 pm"}
    with pytest.raises(ValueError):
        briefs.parse_pairs(["party_size"])
    path = briefs.save_profile(FILLED, tmp_path / "profile.json")
    assert briefs.load_profile(path)["email"] == "f@example.com" and oct(path.stat().st_mode)[-3:] == "600"
    # beside the private env file, never inside the repository
    assert briefs.profile_path() == config.env_path().parent / "profile.json"
    assert not briefs.profile_path().resolve().is_relative_to(Path(briefs.__file__).resolve().parents[3])

"""A time Marco writes is exact, because "eight" could be morning or night (Owner 2026-11-02). What the voice says on a
call is not this: the brief and the call's own words stay as they were."""

from datetime import date, datetime, time, timezone

import pytest

from hiremarco.calls import offers
from hiremarco.calls.confirm import confirmed_text
from hiremarco.offer import Place, offer_line
from hiremarco.proof import Booking
from hiremarco.style import NAME_RULE, TIME_RULE, clock_time, times_settled_on, written, written_times

KITCHEN = Place("kitchen", "Test Kitchen", "15557770000")


@pytest.mark.parametrize("hour, minute, shown", [
    (20, 0, "8pm"), (20, 30, "8:30pm"), (0, 30, "12:30am"), (12, 35, "12:35pm"), (12, 25, "12:25pm"), (0, 25, "12:25am"),
    (12, 0, "noon"), (0, 0, "midnight"), (8, 0, "8am"), (8, 5, "8:05am"), (23, 59, "11:59pm"), (1, 0, "1am"), (13, 0, "1pm"),
])
def test_the_exact_forms(hour, minute, shown):
    assert clock_time(hour, minute) == shown


@pytest.mark.parametrize("before, after", [
    ("Dinner at 8 PM.", "Dinner at 8pm."), ("at 8:30 p.m. sharp", "at 8:30pm sharp"), ("9 a.m. works", "9am works"),
    ("Thursday at 12:00 PM", "Thursday at noon"), ("at 12 am", "at midnight"), ("by 12 pm", "by noon"),
    ("Thursday, 12:30 AM", "Thursday, 12:30am"), ("twelve noon", "noon"), ("12 midnight", "midnight"),
    ("See you at eight pm.", "See you at 8pm."), ("eight thirty p.m. tonight", "8:30pm tonight"),
    ("at nine am", "at 9am"), ("at twelve pm", "at noon"),
])
def test_the_guard_fixes_what_already_says_am_or_pm(before, after):
    assert written_times(before) == after


@pytest.mark.parametrize("line", [
    "Which one am I?", "We did eight takes.", "Eight bars in, punch it.", "It's at 120 BPM in A minor.", "Take 12 is the one.",
    "Room 8 AM radio", "A 35 mm lens.", "for four at the table", "I was 8 am I right", "track 8, take 2",
    "Nov 2 at 2026", "Set it at eight bars.",
])
def test_the_guard_leaves_counts_lyrics_and_numbers(line):
    keep = "Room 8 AM radio"
    assert written_times(line) == (line if line != keep else "Room 8am radio")  # with am after a digit, it reads as a time


def test_a_quoted_subject_or_a_bare_twelve_is_not_rewritten():
    assert written_times('Dana emailed about "Call at 8 PM". Dinner at 8 PM.') == 'Dana emailed about "Call at 8 PM". Dinner at 8pm.'
    assert written_times("Setting up 12 AM.") == "Setting up 12am."  # a song can be called that; never "midnight" alone


def test_a_spelled_time_with_no_am_or_pm_is_left_for_the_writers():
    assert written_times("Thursday at eight") == "Thursday at eight"  # the guard can't know which; see TIME_RULE


def test_it_goes_out_with_capitals_kept_and_the_time_exact():
    assert written("Booked at Test Kitchen for Thursday at 8:30 PM. Lucie's table for four.") == (
        "Booked at Test Kitchen for Thursday at 8:30pm. Lucie's table for four.")


@pytest.mark.parametrize("before, after", [
    ("HireMarco is live.", "hireMarco is live."), ("I work at HIREMARCO.", "I work at hireMarco."),
    ("hiremarco, tonight", "hireMarco, tonight"), ("(Hiremarco)", "(hireMarco)"), ("hireMarco stays.", "hireMarco stays."),
    ("See https://hiremarco.com/x and a@hiremarco.com", "See https://hiremarco.com/x and a@hiremarco.com"),
    ("Hiremarco.com is the site", "Hiremarco.com is the site"), ("Marco is here.", "Marco is here."),
])
def test_the_name_is_spelled_one_way_and_a_link_is_left_alone(before, after):
    assert written(before) == after


def test_what_a_call_settled_takes_its_half_of_the_day_from_the_booking():
    assert times_settled_on("Thursday at nine thirty, four, outdoor", True) == "Thursday at 9:30pm, four, outdoor"
    assert times_settled_on("Thursday at 9:30, four", True) == "Thursday at 9:30pm, four"
    assert times_settled_on("Saturday at eleven", False) == "Saturday at 11am"
    assert times_settled_on("Thursday at 9 pm", False) == "Thursday at 9pm"       # its own word wins
    assert times_settled_on("four at the bar, then eight seats", True) == "four at the bar, then eight seats"


def offer_at(hour, minute=0, party=4):
    return offers.CallOffer(1, datetime(2026, 11, 2, tzinfo=timezone.utc), "kitchen", "thursday", "2026-11-05", hour, party, "",
                            "pending", minute=minute)


@pytest.mark.parametrize("hour, minute, shown", [(20, 0, "8pm"), (20, 30, "8:30pm"), (12, 0, "noon"), (12, 35, "12:35pm")])
def test_the_offer_and_its_questions_say_the_exact_time(hour, minute, shown):
    offer = offer_at(hour, minute)
    assert offer.text(KITCHEN) == f"Want me to call Test Kitchen to book Thursday at {shown} for four?"
    assert f"If Thursday at {shown} is gone" in offers.questions_text(offer)


def test_the_email_offer_keeps_the_minutes_and_spells_the_party():
    data = {"kind": "table", "who": "Dana", "says": "Dana wants dinner.", "place_id": "kitchen", "weekday": "thursday",
            "hour": 20, "minute": 30, "party_size": 4}
    assert offer_line(data, [KITCHEN])[1] == "Dana wants dinner. Want me to call Test Kitchen to book Thursday at 8:30pm for four?"


def test_what_the_voice_says_on_a_call_has_not_changed(monkeypatch):
    monkeypatch.setattr(offers.briefs, "load_profile", lambda: {})
    assert offers.brief_for(offer_at(20))["time"] == "eight pm"
    assert offers.brief_for(offer_at(20, 30))["time"] == "eight 30 pm"


def test_a_confirmation_and_a_proof_card_are_exact():
    noon = Booking("Test Kitchen", date(2026, 11, 5), time(12, 0), 4, "Felix")
    late = Booking("Test Kitchen", date(2026, 11, 5), time(20, 30), 4, "Felix")
    assert confirmed_text(KITCHEN, noon).startswith("Confirmed: Test Kitchen, Thursday noon, four")
    assert confirmed_text(KITCHEN, late).startswith("Confirmed: Test Kitchen, Thursday 8:30pm, four")
    assert "8:30pm" in late.card() and "noon" in noon.card()


def test_every_writer_gets_the_rule():
    from hiremarco.inbox.outbox import WRITER
    from hiremarco.offer import READ_INSTRUCTIONS
    from hiremarco.server import ENGLISH

    assert all(TIME_RULE in text for text in (ENGLISH, READ_INSTRUCTIONS, WRITER))
    assert all(NAME_RULE in text for text in (ENGLISH, WRITER))
    assert "{" not in TIME_RULE  # the email writer's prompt goes through format


def test_nothing_on_the_way_out_changes_a_letter_case():
    import hiremarco.style

    assert not hasattr(hiremarco.style, "casual")
    line = 'Heads up. Tim Hale emailed about "Contract Questions". Let me know if I can help.'
    assert written(line) == line

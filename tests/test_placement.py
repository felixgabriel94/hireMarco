"""A new part's track lands inside its stack (Owner 2026-11-04). Every track name here is made up."""

import pytest

from hiremarco.studio.commands import Command, understand
from hiremarco.studio.placement import Row, place, rows_from, stack_end

LAYOUT = [  # the indent is the x of each name: members sit right of their stack
    Row(1, "BEAT", "closed", 100.0), Row(7, "VOCALS", "open", 100.0), Row(8, "LEAD", "open", 112.0),
    Row(9, "Lead 1", "", 124.0), Row(10, "Lead 2", "", 124.0), Row(28, "HARMONIES", "open", 112.0),
    Row(29, "Harmony 1", "", 124.0), Row(30, "Harmony 2", "", 124.0), Row(31, "AD-LIBS", "open", 112.0),
    Row(40, "FX Return", "", 100.0),
]


@pytest.mark.parametrize("line, kind", [
    ("Marco, create a new harmony.", "harmony"), ("Marco, create a new lead", "lead"),
    ("Marco, make a new ad-lib track", "ad-lib"), ("Marco, another harmony", "harmony"),
    ("Marco, new double", "double"), ("Marco, create a new lead vocal", "lead"),
])
def test_create_a_new_part_is_a_new_track_for_that_part(line, kind):
    assert understand(line, client=None) == Command("new_track", text=kind)


def test_the_last_track_of_the_parts_stack_is_the_one_to_follow():
    assert stack_end("harmony", LAYOUT) == (LAYOUT[5], LAYOUT[7])
    assert stack_end("lead", LAYOUT) == (LAYOUT[2], LAYOUT[4])
    assert stack_end("ad-lib", LAYOUT) == (LAYOUT[8], LAYOUT[8])   # an empty stack: right after it
    assert stack_end("double", LAYOUT) is None


def test_place_selects_inside_the_stack_or_says_there_is_none():
    picked, opened = [], []
    line = place("harmony", select=picked.append, select_last=lambda: pytest.fail("a stack is there"),
                 unstack=lambda: opened.append(1) or {}, read=lambda: LAYOUT)
    assert opened == [1] and picked == ["Track 30"] and line == "inside HARMONIES, after Harmony 2"
    line = place("double", select=picked.append, select_last=lambda: "FX Return", unstack=lambda: {}, read=lambda: LAYOUT)
    assert line == "no stack for double: after FX Return, outside every stack" and picked == ["Track 30"]
    assert place("reference", select=picked.append, select_last=lambda: "x", unstack=lambda: {}, read=lambda: LAYOUT) == ""


def test_headers_read_as_rows():
    raw = [{"desc": "Track 28 “HARMONIES”", "triangle": "1", "name_x": 112.0},
           {"desc": "Track 29 “Harmony 1”", "triangle": None, "name_x": 124.0}, {"desc": "Arrangement"}]
    assert rows_from(raw) == [LAYOUT[5], LAYOUT[6]]

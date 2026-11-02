"""The mixing rulebook cites its sources line by line, like the mastering one (Owner 2026-11-02: one bar for both)."""

import re

from hiremarco.mix import rules


def cited_keys(text: str) -> set[str]:
    keys = set()
    for group in re.findall(r"\[([^\]]+)\]", text):
        for part in group.split(";"):
            keys.add(part.strip().split(" ")[0].split(",")[0].strip())
    return keys


def test_every_source_is_cited_and_every_citation_is_a_source():
    cited = cited_keys(rules.RULEBOOK)
    for key in rules.SOURCES:
        assert key in cited, f"{key} is listed as a source but never cited"
    unknown = {k for k in cited if k not in rules.SOURCES and k != "mastering"}
    assert not unknown, f"cited but not in SOURCES: {sorted(unknown)}"


def test_the_numbers_the_review_flagged_are_fixed():
    assert "character 220-300 Hz" in rules.RULEBOOK           # the bass range the old line missed
    assert "a low shelf can do a more musical job" in rules.RULEBOOK
    assert "120 Hz line is a starting point" in rules.RULEBOOK
    assert "parallel compression" in rules.RULEBOOK.lower()


def test_kinds_still_name_plugins():
    assert rules.kind("ValhallaVintageVerb") == "reverb" and rules.belongs_on("reverb") == "bus"
    assert rules.kind("Pro-DS") == "de-esser" and rules.belongs_on("de-esser") == "insert"
    assert rules.kind("Mystery", {"Ratio": 1, "Attack": 2}) == "compressor"

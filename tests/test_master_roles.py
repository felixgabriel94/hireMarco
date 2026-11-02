"""Roles, not plugin names: the chain is filled from what is in the room, stock Logic last."""

import json
import re

from hiremarco.master import roles, rules


def test_the_rulebook_cites_its_sources_and_keeps_the_line():
    assert "No limiter" in rules.RULEBOOK or "no limiter" in rules.RULEBOOK
    cited = {k.strip() for group in re.findall(r"\[([^\]]+)\]", rules.RULEBOOK) for k in group.split(";")}
    cited = {k.split(" (")[0].split(",")[0] for k in cited}
    for key in rules.SOURCES:
        assert key in cited, f"{key} is listed as a source but never cited"
    assert rules.PURPOSES["mix"]["limiter"] is False and rules.PURPOSES["demo"]["ceiling_dbtp"] == -1.0
    assert "audit" in rules.quick_master_means()


def test_every_role_ends_in_a_stock_plugin():
    for role, names in roles.CANDIDATES.items():
        assert names[-1] in roles.STOCK, f"{role} has no stock fallback"
    assert set(roles.CANDIDATES) == set(roles.ORDER)


def test_the_room_decides_the_chain():
    room = {"Pro-Q 3", "Pro-L 2", "Channel EQ", "Compressor", "Adaptive Limiter", "Loudness Meter", "Gain",
            "Shadow Hills Mastering Compress"}
    chain = roles.chain(room)
    assert list(chain) == ["gain", "corrective_eq", "glue", "tonal_eq", "limiter", "meter"]
    assert chain["corrective_eq"] == "Pro-Q 3" and chain["limiter"] == "Pro-L 2"
    assert chain["glue"] == "Shadow Hills Mastering Compress"
    stock = roles.chain(room, stock_only=True)
    assert stock["corrective_eq"] == "Channel EQ" and stock["limiter"] == "Adaptive Limiter"
    assert stock["glue"] == "Compressor"


def test_a_role_nothing_fills_is_left_out():
    room = {"Channel EQ", "Adaptive Limiter"}
    assert roles.chain(room) == {"corrective_eq": "Channel EQ", "tonal_eq": "Channel EQ", "limiter": "Adaptive Limiter"}
    assert roles.fill("glue", room) is None


def test_the_room_is_read_from_logic_and_the_ledger(tmp_path):
    (tmp_path / "logic_plugins.json").write_text(json.dumps(["Pro-Q 3 (s/s)", "Channel EQ (s/s)", "Rented (s/s)"]))
    (tmp_path / "license_ledger.json").write_text(json.dumps({"Rented (s/s)": {"status": "not_owned"},
                                                               "Pro-Q 3 (s/s)": {"status": "owned"}}))
    room = roles.in_the_room(tmp_path)
    assert room == {"Pro-Q 3", "Channel EQ"}
    assert roles.in_the_room(tmp_path / "nowhere") == set()


def test_what_the_planner_may_name():
    room = {"Pro-Q 3", "Channel EQ", "Adaptive Limiter", "The God Particle"}
    view = roles.for_model(room)
    assert view["candidates"]["corrective_eq"] == ["Pro-Q 3", "Channel EQ"]
    assert view["stock_fallbacks"]["limiter"] == "Adaptive Limiter" and view["stock_fallbacks"]["glue"] is None
    assert view["whole_chain"] == ["The God Particle"]
    assert view["roles_in_order"][0] == "gain" and view["roles_in_order"][-1] == "meter"

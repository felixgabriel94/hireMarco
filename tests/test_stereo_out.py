"""The Stereo Out hands: the strip read, Marco's inserts told from the artist's, bypass and insert through fakes."""

import json

import pytest

from hiremarco.studio import stereo_out


def strip_json(inserts, slot=(585, 196, 58, 9)):
    return json.dumps({"slot": list(slot), "inserts": inserts, "assistant": [585, 205, 58, 18]})


def test_the_strip_is_read_with_console_recall_left_alone():
    strip = stereo_out.parse_strip(strip_json([["Console Re", False, 585, 163], ["Gain", True, 585, 180]]))
    assert [(i.name, i.bypassed) for i in strip.inserts] == [("Console Re", False), ("Gain", True)]
    assert not strip.inserts[0].marcos and strip.inserts[1].marcos
    assert strip.slot == (585, 196, 58, 9) and strip.assistant == (585, 205, 58, 18)


def test_bypass_clicks_only_marcos_inserts_that_need_it(monkeypatch):
    reads = iter([strip_json([["Console Re", False, 585, 163], ["Gain", False, 585, 180], ["Pro-L 2", True, 585, 197]]),
                  strip_json([["Console Re", False, 585, 163], ["Gain", True, 585, 180], ["Pro-L 2", True, 585, 197]])])
    clicked = []

    def jxa(script, *args):
        if script == "stereo_out.js":
            return next(reads)
        clicked.append(args[0])
        return "true"

    monkeypatch.setattr(stereo_out, "front_is_logic", lambda: None)
    monkeypatch.setattr(stereo_out.gate, "execute_effect", lambda conn, fn, **kw: fn())
    so = stereo_out.StereoOut(jxa=jxa, osa=lambda s: "", click=lambda x, y: None, conn=object(), sleep=lambda s: None)
    after = so.bypass(True)
    assert clicked == ["Gain"]                       # Console Recall untouched, Pro-L 2 already bypassed
    assert [i.bypassed for i in after.inserts] == [False, True, True]


def test_bypass_that_does_not_take_is_an_error(monkeypatch):
    same = strip_json([["Gain", False, 585, 180]])
    monkeypatch.setattr(stereo_out, "front_is_logic", lambda: None)
    monkeypatch.setattr(stereo_out.gate, "execute_effect", lambda conn, fn, **kw: fn())
    so = stereo_out.StereoOut(jxa=lambda script, *a: same if script == "stereo_out.js" else "false",
                              osa=lambda s: "", click=lambda x, y: None, conn=object(), sleep=lambda s: None)
    with pytest.raises(RuntimeError):
        so.bypass(True)


def test_insert_walks_the_menu_and_checks_the_strip_grew(monkeypatch):
    reads = iter([strip_json([["Gain", False, 585, 180]]), strip_json([["Gain", False, 585, 180], ["Pro-L 2", False, 585, 197]])])
    # read after the slot click, after the search click, after typing (the list shrinks), after the first result (its
    # submenu beside it), after the pick
    menus = iter(["[[586, 195, 230, 527]]", "[[586, 195, 230, 527]]", "[[586, 195, 230, 109]]",
                  "[[586, 195, 230, 109], [816, 240, 120, 60]]", "[]"])
    clicks, typed = [], []

    def jxa(script, *args):
        return next(reads) if script == "stereo_out.js" else next(menus)

    def osa(script):
        if "keystroke" in script:
            typed.append(script.split('keystroke "')[1].rstrip('"'))
        return "Logic Pro" if "frontmost" in script else ""

    monkeypatch.setattr(stereo_out, "front_is_logic", lambda: None)
    monkeypatch.setattr(stereo_out.gate, "execute_effect", lambda conn, fn, **kw: fn())
    so = stereo_out.StereoOut(jxa=jxa, osa=osa, click=lambda x, y: clicks.append((x, y)), conn=object(), sleep=lambda s: None)
    after = so.insert("Pro-L 2")
    assert [i.name for i in after.inserts] == ["Gain", "Pro-L 2"]
    assert typed == ["Pro-L 2"]
    assert clicks[0] == (585 + 29, 196 + 4.5)         # the empty slot
    assert clicks[1] == (586 + 115, 195 + 18)         # the search field
    assert clicks[2] == (586 + 40, 195 + 49)          # the first result
    assert clicks[3] == (816 + 30, 240 + 12)          # its first variant


def test_a_recent_entry_goes_straight_in_without_a_submenu(monkeypatch):
    reads = iter([strip_json([["Gain", False, 585, 180]]), strip_json([["Gain", False, 585, 180], ["Gain", False, 585, 197]])])
    menus = iter(["[[586, 195, 230, 527]]", "[[586, 195, 230, 527]]", "[[586, 195, 230, 109]]", "[]"])
    clicks = []
    monkeypatch.setattr(stereo_out, "front_is_logic", lambda: None)
    monkeypatch.setattr(stereo_out.gate, "execute_effect", lambda conn, fn, **kw: fn())
    so = stereo_out.StereoOut(jxa=lambda s, *a: next(reads) if s == "stereo_out.js" else next(menus), osa=lambda s: "",
                              click=lambda x, y: clicks.append((x, y)), conn=object(), sleep=lambda s: None)
    after = so.insert("Gain")
    assert [i.name for i in after.inserts] == ["Gain", "Gain"] and len(clicks) == 3


def test_dry_run_plans_the_insert():
    so = stereo_out.StereoOut(jxa=lambda *a: "", osa=lambda s: "", click=lambda x, y: None, dry_run=True)
    so.insert("Pro-L 2")
    assert so.planned == ["insert Pro-L 2 on the Stereo Out"]

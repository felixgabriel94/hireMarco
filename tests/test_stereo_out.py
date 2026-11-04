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


def test_insert_types_in_pieces_then_walks_the_list_by_keyboard(monkeypatch):
    # read before, again just before the slot click (windows closed, Mixer raised), and after the pick
    reads = iter([strip_json([["Gain", False, 585, 180]]), strip_json([["Gain", False, 585, 180]]),
                  strip_json([["Gain", False, 585, 180], ["UAD Shadow", False, 585, 197]])])
    # read before anything (nothing open), after the slot click, after the search click, after typing, after Return
    menus = iter(["[]", "[[586, 195, 230, 527]]", "[[586, 195, 230, 527]]", "[[586, 195, 230, 527]]", "[]"])
    clicks, typed, keys = [], [], []

    def jxa(script, *args):
        if script == "close_plugin_windows.js":
            return "1"
        return next(reads) if script == "stereo_out.js" else next(menus)

    def osa(script):
        if 'keystroke "' in script:
            typed.append(script.split('keystroke "')[1].rstrip('"'))
        if "key code" in script:
            keys.append(int(script.split("key code ")[1]))
        return "Logic Pro" if "frontmost" in script else ""

    monkeypatch.setattr(stereo_out, "front_is_logic", lambda: None)
    monkeypatch.setattr(stereo_out.gate, "execute_effect", lambda conn, fn, **kw: fn())
    so = stereo_out.StereoOut(jxa=jxa, osa=osa, click=lambda x, y: clicks.append((x, y)), conn=object(), sleep=lambda s: None)
    after = so.insert("Shadow Hills Mastering Compress")
    assert [i.name for i in after.inserts] == ["Gain", "UAD Shadow"]
    assert "".join(typed) == "Shadow Hills Mastering Compress" and max(len(t) for t in typed) <= 6
    assert keys == [48, 125, 124, 36]                 # Tab, Down, Right, Return
    assert clicks == [(585 + 29, 196 + 4.5), (586 + 115, 195 + 18)]   # the empty slot, then the search field


def test_a_menu_left_open_after_the_pick_is_closed_and_the_strip_decides(monkeypatch):
    reads = iter([strip_json([["Gain", False, 585, 180]]), strip_json([["Gain", False, 585, 180]]),
                  strip_json([["Gain", False, 585, 180], ["Gain", False, 585, 197]])])
    menus = iter(["[]", "[[586, 195, 230, 527]]", "[[586, 195, 230, 527]]", "[[586, 195, 230, 527]]",
                  "[[586, 195, 230, 109]]", "[]"])
    keys = []
    monkeypatch.setattr(stereo_out, "front_is_logic", lambda: None)
    monkeypatch.setattr(stereo_out.gate, "execute_effect", lambda conn, fn, **kw: fn())

    def jxa(s, *a):
        if s == "close_plugin_windows.js":
            return "1"
        return next(reads) if s == "stereo_out.js" else next(menus)

    def osa(script):
        if "key code" in script:
            keys.append(int(script.split("key code ")[1]))
        return ""

    so = stereo_out.StereoOut(jxa=jxa, osa=osa, click=lambda x, y: None, conn=object(), sleep=lambda s: None)
    after = so.insert("Gain")
    assert [i.name for i in after.inserts] == ["Gain", "Gain"]
    assert keys[:4] == [48, 125, 124, 36] and keys[-1] == 53


def test_dry_run_plans_the_insert():
    so = stereo_out.StereoOut(jxa=lambda *a: "", osa=lambda s: "", click=lambda x, y: None, dry_run=True)
    so.insert("Pro-L 2")
    assert so.planned == ["insert Pro-L 2 on the Stereo Out"]


def test_a_wrong_plugin_landing_is_bypassed_and_named():
    from hiremarco.studio.stereo_out import same_plugin

    assert same_plugin("UAD Shadow Hills Mastering Comp", "UAD Shadow") and same_plugin("Pro-Q 3", "Pro-Q 3")
    assert same_plugin("Shadow Hills Mastering Compress", "UAD Shadow")   # the cousin the search lands first
    assert not same_plugin("Gain", "Kickstart ") and not same_plugin("Pro-L 2", "Pro-Q 3")


def test_remove_is_planned_in_a_dry_run_and_refuses_a_row_that_is_not_there(tmp_path):
    from hiremarco.studio.stereo_out import StereoOut
    import json, pytest

    report = json.dumps({"name": "FG Master", "slot": [317, 436, 58, 9],
                         "inserts": [["Gain", False, 317, 334], ["Kickstart ", True, 317, 420]], "assistant": None})
    so = StereoOut(jxa=lambda script, *a: report, osa=lambda s: "", dry_run=True)
    so.remove("Kickstart ", 420)
    assert so.planned == ["remove Kickstart  from the Stereo Out"]
    with pytest.raises(RuntimeError, match="no insert named"):
        so.remove("Pro-L 2", 500)


def test_logic_behind_another_app_is_brought_back_not_stopped(tmp_path, monkeypatch):
    # Owner 2026-11-03: three runs ended because the Owner was reading the thread on the Mac; Marco brings Logic back
    # with activate and carries on, and stops only when Logic will not come back
    import json

    from hiremarco import config, events

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    fronts, scripts = iter(["Claude", "Logic Pro"]), []

    def osa(script):
        scripts.append(script)
        return next(fronts) if script == stereo_out.FRONT else ""

    stereo_out.front_is_logic(osa=osa, sleep=lambda s: None)
    assert scripts == [stereo_out.FRONT, stereo_out.ACTIVATE, stereo_out.FRONT]
    rows = [json.loads(l) for l in (tmp_path / "state" / events.NAME).read_text().splitlines()]
    assert rows[-1]["summary"] == "Claude was in front; Marco brought Logic back." and rows[-1]["plain"].startswith("Marco brings Logic back")

    stuck = []
    with pytest.raises(RuntimeError, match="would not come back"):
        stereo_out.front_is_logic(osa=lambda s: stuck.append(s) or ("Claude" if s == stereo_out.FRONT else ""), sleep=lambda s: None)
    assert stuck == [stereo_out.FRONT, stereo_out.ACTIVATE, stereo_out.FRONT]

    quiet = []
    stereo_out.front_is_logic(osa=lambda s: quiet.append(s) or "Logic Pro", sleep=lambda s: None)
    assert quiet == [stereo_out.FRONT]   # Logic already in front: no call, no line on the screen


def test_a_plugin_window_is_moved_inside_the_main_window_so_all_of_it_shows():
    # Owner 2026-11-03: Logic opens a plug-in where it last sat, often off the bottom; Marco moves it where the audience sees it
    main = (0.0, 33.0, 1512.0, 874.0)
    assert stereo_out.fit_inside((350.0, 300.0, 460.0, 560.0), main) == (350.0, 300.0)              # already inside: left alone
    assert stereo_out.fit_inside((350.0, 800.0, 460.0, 560.0), main) == (350.0, 33.0 + 874.0 - 24.0 - 560.0)   # off the bottom: up
    assert stereo_out.fit_inside((1300.0, 300.0, 460.0, 560.0), main) == (1512.0 - 24.0 - 460.0, 300.0)   # off the right: left
    assert stereo_out.fit_inside((100.0, 500.0, 460.0, 900.0), main) == (100.0, 33.0 + 24.0)          # taller than the window: top-aligned
    assert stereo_out.plugin_window("Stereo Out") and stereo_out.plugin_window("Pro-Q 3")
    assert not stereo_out.plugin_window("song - Tracks") and not stereo_out.plugin_window("song - Mixer: Single") and not stereo_out.plugin_window("")

    scripts = []

    def osa(script):
        scripts.append(script)
        if "repeat with w in (every window)" in script:
            return "song - Mixer: Single|20,33,1024,874\nsong - Tracks|0,33,1512,874\nStereo Out|420,760,470,610\n"
        return ""

    strip = stereo_out.StereoOut(jxa=lambda *a: "", osa=osa, click=lambda *a, **k: None, sleep=lambda s: None)
    assert strip.place_inside() is True
    assert scripts[-1].endswith('set position of (first window whose name is "Stereo Out") to {420, 273}')
    quiet = []
    strip = stereo_out.StereoOut(jxa=lambda *a: "", osa=lambda s: quiet.append(s) or "song - Tracks|0,33,1512,874\nStereo Out|300,200,470,610\n",
                                 click=lambda *a, **k: None, sleep=lambda s: None)
    assert strip.place_inside() is False and len(quiet) == 1   # inside already: read once, nothing moved

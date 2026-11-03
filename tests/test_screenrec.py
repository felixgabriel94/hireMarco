"""The recorder's plan: which Logic window is the main one, and one named stream for every other window."""

from types import SimpleNamespace as NS

from hiremarco.studio import screenrec


def window(wid, w, h, title="", app="com.apple.logic10", layer=0, on=True):
    frame = NS(size=NS(width=w, height=h), origin=NS(x=0, y=0))
    owner = NS(bundleIdentifier=lambda: app)
    return NS(windowID=lambda: wid, frame=lambda: frame, title=lambda: title, owningApplication=lambda: owner,
              windowLayer=lambda: layer, isOnScreen=lambda: on)


def test_logic_windows_are_real_windows_of_logic_biggest_first():
    found = screenrec.logic_windows([window(1, 800, 600, "Mixer"), window(2, 1800, 1100, "Session - Tracks"),
                                     window(3, 40, 20, "tip"), window(4, 900, 700, app="com.apple.Terminal"),
                                     window(5, 500, 400, layer=3), window(6, 500, 400, on=False)])
    assert [w.windowID() for w in found] == [2, 1]


def test_the_main_window_stays_main_and_each_other_window_is_named_once():
    windows = screenrec.logic_windows([window(2, 1800, 1100, "Session - Tracks"), window(1, 800, 600, "Mixer: Vocal")])
    main, names = screenrec.plan_logic(windows, None, {}, 1_800_000_000)
    assert main == 2 and list(names) == [1] and names[1].startswith("logic-window-mixer-vocal-")
    bigger = screenrec.logic_windows([window(9, 2500, 1400, "Pro-Q 3"), *windows])
    main2, names2 = screenrec.plan_logic(bigger, main, names, 1_800_000_100)
    assert main2 == 2 and names2[1] == names[1] and names2[9].startswith("logic-window-pro-q-3-")
    gone = screenrec.logic_windows([window(1, 800, 600, "Mixer: Vocal")])
    assert screenrec.plan_logic(gone, 2, names, 1_800_000_200)[0] == 1     # main closed: the next biggest


def test_names_and_stamps_are_safe_for_files():
    assert screenrec.slug("Mixer: Vocal / Lead #1") == "mixer-vocal-lead-1" and screenrec.slug("") == "untitled"
    assert screenrec.even(1001.7) == 1000

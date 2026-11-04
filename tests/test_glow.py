"""The glow: Logic's front window in soft blue light while a job runs, born out of the halo, following Marco with no lag."""

from hiremarco import events, glow


def test_the_brand_blue_is_a_blue_and_the_breath_stays_in_its_band():
    r, g, b = glow.oklch_to_srgb(*glow.ACCENT_OKLCH)
    assert b > 0.9 and b > g > r and 0.0 <= r <= 1.0
    samples = [glow.breath(t / 10) for t in range(0, 80)]
    assert min(samples) >= glow.ALPHA_LOW - 1e-9 and max(samples) <= glow.ALPHA_HIGH + 1e-9
    assert glow.pulse(None) == 0.0 and glow.pulse(0.0) > glow.pulse(glow.PULSE_S / 2) > glow.pulse(glow.PULSE_S) == 0.0
    assert glow.LAYERS[0][0] > glow.LAYERS[-1][0] and glow.LAYERS[-1][1] < 0.5 and glow.LAYERS[-1][0] >= 6.0   # an aura, no hard core (Owner 2026-11-03)


def test_the_glow_is_born_at_a_start_lives_while_the_job_does_and_draws_back_at_the_end():
    alive = {"on": True}
    state = glow.State(alive=lambda pid: alive["on"])
    assert state.alpha(0.0) == 0.0 and state.phase(0.0) == 0.0
    state.add([{"kind": "job_started", "pid": 4242}], 10.0)
    assert 0.0 < state.phase(10.0 + glow.BIRTH_S / 2) < 1.0 and state.phase(10.0 + glow.BIRTH_S) == 1.0
    assert state.alpha(10.0 + glow.BIRTH_S + 1.0) == glow.breath(10.0 + glow.BIRTH_S + 1.0)
    state.add([{"kind": "stage", "plain": "Marco's goal: ..."}], 15.0)
    assert state.alpha(15.0) > glow.breath(15.0) and state.alpha(15.0) <= 1.0
    state.add([{"kind": "model_call_completed", "model": events.VOICE_MODEL}], 19.0)   # talk in the room is not his work
    assert state.pulsed_at == 15.0
    state.add([{"kind": "job_ended"}], 20.0)
    assert not state.working(20.0) and 0.0 < state.phase(20.0 + glow.BIRTH_S / 2) < 1.0 and state.phase(20.0 + glow.BIRTH_S + 0.1) == 0.0
    state.add([{"kind": "job_started", "pid": 4343}], 30.0)
    alive["on"] = False
    assert not state.working(31.0) and state.ended_at == 31.0   # a job that died without its last row draws back too


def test_the_front_logic_window_comes_from_the_window_server_plug_ins_included():
    infos = [
        {"kCGWindowOwnerName": "Claude", "kCGWindowLayer": 0, "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 900, "Height": 700}},
        {"kCGWindowOwnerName": "Logic Pro", "kCGWindowLayer": 0, "kCGWindowBounds": {"X": 40, "Y": 60, "Width": 120, "Height": 40}},   # a palette
        {"kCGWindowOwnerName": "Logic Pro", "kCGWindowLayer": 3, "kCGWindowBounds": {"X": 350, "Y": 300, "Width": 460, "Height": 560}},   # a plug-in
        {"kCGWindowOwnerName": "Logic Pro", "kCGWindowLayer": 0, "kCGWindowBounds": {"X": 0, "Y": 33, "Width": 1512, "Height": 874}},
    ]
    assert glow.front_logic_window(infos) == (350.0, 300.0, 460.0, 560.0)
    assert glow.front_logic_window(infos[:2]) is None and glow.front_logic_window([]) is None
    # Logic's Tracks window at (0, 33) 1512 by 874 on a 982-point screen sits 75 points up from the bottom in AppKit's frame
    assert glow.view_rect((0.0, 33.0, 1512.0, 874.0), 982.0) == (0.0, 75.0, 1512.0, 874.0)


def test_the_outline_slides_to_a_new_window_and_the_birth_stretches_from_the_halos_ring():
    first = glow.ease(None, (0.0, 0.0, 100.0, 100.0))
    assert first == (0.0, 0.0, 100.0, 100.0)
    step = glow.ease(first, (100.0, 0.0, 100.0, 100.0))
    assert 0.0 < step[0] < 100.0 and step[2] == 100.0
    r = first
    for _ in range(12):
        r = glow.ease(r, (100.0, 0.0, 100.0, 100.0))
    assert abs(r[0] - 100.0) < 0.5   # settled in under half a second at 30 ticks a second
    ring, radius = glow.birth(0.0, (756.0, 491.0), (0.0, 75.0, 1512.0, 874.0))
    assert ring == (756.0 - glow.BIRTH_R, 491.0 - glow.BIRTH_R, 2 * glow.BIRTH_R, 2 * glow.BIRTH_R) and radius == glow.BIRTH_R
    landed, radius = glow.birth(1.0, (756.0, 491.0), (0.0, 75.0, 1512.0, 874.0))
    assert landed == (0.0, 75.0, 1512.0, 874.0) and radius == glow.RADIUS
    mid, _ = glow.birth(0.5, (756.0, 491.0), (0.0, 75.0, 1512.0, 874.0))
    assert ring[2] < mid[2] < landed[2]
    # Owner 2026-11-03: a genie, not lines: smoothstep both ways, born at the window's own centre where the halo floats,
    # wider and fainter while still the orb
    assert glow.smooth(0.0) == 0.0 and glow.smooth(1.0) == 1.0 and abs(glow.smooth(0.5) - 0.5) < 1e-9
    assert glow.smooth(0.1) < 0.1 and glow.smooth(0.9) > 0.9
    assert glow.centre_of((0.0, 75.0, 1512.0, 874.0)) == (756.0, 512.0)
    assert glow.softness(0.0) > glow.softness(0.5) > glow.softness(1.0) == 1.0
    assert not hasattr(glow, "TRAIL")


def test_the_booth_at_work_lights_the_glow_and_a_job_inside_keeps_one_light():
    # Owner 2026-11-03: talking is the halo, work in Logic is the glow, for every command, not only a master
    state = glow.State(alive=lambda pid: True)
    state.add([{"kind": "work_started", "pid": 7, "operation": "arrange"}], 10.0)
    assert state.working(10.0) and state.began_at == 10.0
    state.add([{"kind": "work_ended", "pid": 7, "operation": "arrange"}], 12.0)
    assert not state.working(12.0) and state.ended_at == 12.0
    state.add([{"kind": "work_started", "pid": 7, "operation": "export"}], 20.0)
    state.add([{"kind": "job_started", "pid": 7}], 20.5)       # the master's own rows, inside the command's
    assert state.began_at == 20.0                               # one light, no second birth
    state.add([{"kind": "work_ended", "pid": 7, "operation": "export"}], 21.0)
    assert state.working(21.0)                                  # the command returned; the job still runs
    state.add([{"kind": "job_ended"}], 40.0)
    assert not state.working(40.0) and state.ended_at == 40.0


def test_a_modal_panel_of_logics_is_followed_like_a_window():
    # Owner 2026-11-03: "Choose a Project" sat at the window server's layer 8 and the light stayed on the Tracks window
    infos = [
        {"kCGWindowOwnerName": "Logic Pro", "kCGWindowLayer": 8, "kCGWindowBounds": {"X": 120, "Y": 140, "Width": 980, "Height": 620}},
        {"kCGWindowOwnerName": "Logic Pro", "kCGWindowLayer": 0, "kCGWindowBounds": {"X": 0, "Y": 33, "Width": 1512, "Height": 874}},
    ]
    assert glow.front_logic_window(infos) == (120.0, 140.0, 980.0, 620.0)
    infos[0]["kCGWindowLayer"] = 25   # a menu or a tooltip, not a window
    assert glow.front_logic_window(infos) == (0.0, 33.0, 1512.0, 874.0)


def test_a_window_logic_has_not_drawn_yet_is_not_framed_and_a_loading_banner_is():
    # Owner 2026-11-03: the light came up before Logic's banner showed, and did not move to the thin loading window
    unseen = {"kCGWindowOwnerName": "Logic Pro", "kCGWindowLayer": 0, "kCGWindowAlpha": 0.0,
              "kCGWindowBounds": {"X": 300, "Y": 200, "Width": 900, "Height": 600}}
    banner = {"kCGWindowOwnerName": "Logic Pro", "kCGWindowLayer": 3, "kCGWindowAlpha": 1.0,
              "kCGWindowBounds": {"X": 480, "Y": 400, "Width": 520, "Height": 130}}
    assert glow.front_logic_window([unseen]) is None
    assert glow.front_logic_window([unseen, banner]) == (480.0, 400.0, 520.0, 130.0)


def test_the_birth_waits_for_the_halo_to_go_first():
    # Owner 2026-11-04: the halo fades out completely, then the glow is born
    state = glow.State(alive=lambda pid: True)
    state.add([{"kind": "work_started", "pid": 7}], 10.0)
    state.began_at = 10.0 + glow.HANDOFF_S
    assert state.phase(10.0 + glow.HANDOFF_S / 2) == 0.0 and state.alpha(10.0 + glow.HANDOFF_S / 2) == 0.0
    assert state.phase(10.0 + glow.HANDOFF_S + glow.BIRTH_S) == 1.0

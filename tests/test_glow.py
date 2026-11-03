"""The glow: Logic's window outlined in the brand's blue while a job runs, breathing, pulsing on each event, gone between jobs."""

import json

from hiremarco import events, glow


def test_the_brand_blue_is_a_blue_and_the_breath_stays_in_its_band():
    r, g, b = glow.oklch_to_srgb(*glow.ACCENT_OKLCH)
    assert b > 0.9 and b > g > r and 0.0 <= r <= 1.0
    samples = [glow.breath(t / 10) for t in range(0, 80)]
    assert min(samples) >= glow.ALPHA_LOW - 1e-9 and max(samples) <= glow.ALPHA_HIGH + 1e-9
    assert abs(glow.breath(0.0) - glow.ALPHA_LOW) < 1e-9 and abs(glow.breath(glow.BREATH_S / 2) - glow.ALPHA_HIGH) < 1e-9
    assert glow.pulse(None) == 0.0 and glow.pulse(0.0) > glow.pulse(glow.PULSE_S / 2) > glow.pulse(glow.PULSE_S) == 0.0


def test_the_glow_is_on_only_while_a_job_lives_and_pulses_on_its_events():
    alive = {"on": True}
    state = glow.State(alive=lambda pid: alive["on"])
    assert state.alpha(0.0) == 0.0
    state.add([{"kind": "job_started", "pid": 4242}], 0.0)
    assert state.working() and state.alpha(1.0) == glow.breath(1.0)
    state.add([{"kind": "stage", "plain": "Marco's goal: ..."}], 5.0)
    assert state.alpha(5.0) > glow.breath(5.0) and state.alpha(5.0) <= 1.0
    state.add([{"kind": "model_call_completed", "model": events.VOICE_MODEL}], 9.0)   # talk in the room is not his work
    assert state.pulsed_at == 5.0
    alive["on"] = False
    assert not state.working() and state.alpha(10.0) == 0.0    # a job that died without its last row
    alive["on"] = True
    state.add([{"kind": "job_started", "pid": 4343}, {"kind": "job_ended"}], 11.0)
    assert not state.working()


def test_the_panel_follows_logics_front_window_in_appkits_coordinates():
    # System Events: top-left origin, y down; AppKit: bottom-left origin, y up. Logic's Tracks window at (0, 33) 1512 by 875
    # on a 982-point screen sits 74 points up from the bottom
    assert glow.panel_rect((0.0, 33.0, 1512.0, 875.0), 982.0, margin=6.0) == (-6.0, 68.0, 1524.0, 887.0)
    assert glow.front_window(lambda script: "20, 33, 1024, 874") == (20.0, 33.0, 1024.0, 874.0)
    assert glow.front_window(lambda script: "") is None
    assert glow.front_window(lambda script: (_ for _ in ()).throw(RuntimeError("no window"))) is None
    assert "window 1" in glow.FRONT_WINDOW

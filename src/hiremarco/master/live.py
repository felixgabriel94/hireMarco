"""The master job with Marco's real hands: the one wiring the CLI, the booth and WhatsApp all use.

The job itself (``master.job``) takes its hands as arguments so it runs in
tests through fakes. This module gives it the live ones: the Stereo Out in
the Mixer window, the Bounce dialog, the output strip's chain, the locators
and Cycle through the gate, the track selected for the Inspector, the critic
at its deepest effort, and the delivery to the Owner's WhatsApp when asked.
Where the song and its length are not given, they come from the booth's last
setup record (the beat file) and Logic's own tempo reading.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from hiremarco import config, gate
from hiremarco.master import job as jobs

BOUNCES = Path.home() / "Music" / "hireMarco Bounces"


def song_and_length(inbox: Path | None = None) -> tuple[str, int]:
    """The song's name and end bar from the last setup record and Logic's tempo: the beat's file name is the song
    unless a name was asked for; its seconds at the session's tempo give the bars."""
    import soundfile as sf

    from hiremarco.studio.beat_in import INBOX, last_setup, requested_name
    from hiremarco.studio.tracks import Tracks

    setup = last_setup(inbox or INBOX)
    beat = Path(str(setup.get("beat", "")))
    if not setup or not beat.name:
        raise RuntimeError("no session was set up from a beat; say the song and how long it is")
    candidates = [beat, (inbox or INBOX) / "loaded" / beat.name, (inbox or INBOX) / beat.name]
    found = next((p for p in candidates if p.exists()), None)
    if found is None:
        raise RuntimeError(f"the beat {beat.name} is not where it was; say how long the song is")
    song = requested_name(found) or found.stem
    seconds = sf.info(found).duration
    bpm = float(setup.get("bpm") or 0) or float(Tracks().where()[1])
    return song, jobs.end_bar_for(seconds, bpm)


def run_live(song: str | None = None, end_bar: int | None = None, *, purpose: str = "demo", direction: str = "",
             stock_only: bool = False, references: Path | None = None, track: str = "PROD", send: bool = False,
             bounces: Path | None = None, log: Callable[[str], None] = print, conn=None) -> jobs.Result:
    from hiremarco.critic import Critic
    from hiremarco.studio.arrange import live_arranger
    from hiremarco.studio.beat_in import BeatLoader
    from hiremarco.studio.bounce import Bouncer
    from hiremarco.studio.chain import Channel
    from hiremarco.studio.logic import Press, _osascript as press_keys, _script
    from hiremarco.studio.stereo_out import StereoOut, front_is_logic

    conn = conn or gate.connect()
    if song is None or end_bar is None:
        found_song, found_end = song_and_length()
        song, end_bar = song or found_song, end_bar or found_end

    def toggle_cycle() -> None:
        def run() -> str:
            subprocess.run(["osascript", "-e", 'tell application "Logic Pro" to activate'], check=False, timeout=10)
            time.sleep(0.3)
            front_is_logic()
            press_keys(_script(Press("c", ())))
            return "cycle toggled"
        gate.execute_effect(conn, run, tenant_id="owner", idempotency_key=f"logic:{time.time_ns()}",
                            capability="cycle", channel="logic", target="*", message="toggle Cycle", department="studio")

    if send:
        from hiremarco.whatsapp.client import WhatsApp

        wa, owner = WhatsApp(), config.require("OWNER_WHATSAPP")

        def deliver(path: Path, caption: str) -> str:
            wa.send_document(owner, path.read_bytes(), path.name, caption, mime="audio/wav",
                             idempotency_key=f"master:{path.name}")
            return f"sent {path.name} to the Owner"
    else:
        def deliver(path: Path, caption: str) -> str:
            return f"{path} ({caption})"

    def select_track() -> None:
        # the tall Mixer window sits over the track headers (live 2026-11-02: the click landed on the Mixer and
        # selected nothing), so the Tracks window comes to the front first
        subprocess.run(["osascript", "-e", 'tell application "Logic Pro" to activate'], check=False, timeout=10)
        time.sleep(0.3)
        subprocess.run(["osascript", "-e", 'tell application "System Events" to tell process "Logic Pro"\n'
                        'repeat with w in (every window)\nif (name of w) ends with " - Tracks" then perform action '
                        '"AXRaise" of w\nend repeat\nend tell'], check=False, timeout=15)
        time.sleep(0.5)
        BeatLoader().select(track)

    job = jobs.Job(song, end_bar, (bounces or BOUNCES / song), purpose=purpose, direction=direction,
                   stock_only=stock_only, references=references)
    from hiremarco.studio.face import look as look_at_face

    return jobs.run(job, strip=StereoOut(conn=conn), bouncer=Bouncer(conn=conn), channel=Channel(conn=conn, strip="output"),
                    locators=live_arranger(conn).locators, toggle_cycle=toggle_cycle, select_track=select_track,
                    look_at_face=lambda: look_at_face("Stereo Out"),
                    critic=Critic(effort="max", tokens=4000, timeout=600.0),
                    deliver=deliver, log=log)

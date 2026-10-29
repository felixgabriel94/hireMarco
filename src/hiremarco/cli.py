"""The ``marco`` command. One labelled command per thing worth filming.

    uv run marco env                     which keys are set (never their values)
    uv run marco gate status             kill switch and today's counts
    uv run marco gate kill on|off        stop or resume everything
    uv run marco demo first-answer       Marco's first live answer on Muse Spark
    uv run marco serve                   the WhatsApp webhook on 127.0.0.1:8787
    uv run marco serve --listen-only     hear the Owner, reply to nothing (opens the 24-hour window)
    uv run marco whatsapp send "text"    one message to the Owner (manual trigger)
    uv run marco whatsapp verify-token   make the webhook token, copy it to the clipboard
    uv run marco whatsapp subscribe      point the WhatsApp account's webhooks at the app
    uv run marco google signin           one Google sign-in for mail (read) and calendar
    uv run marco mail check              granted senders' mail from the last two days
    uv run marco relay token             make the call relay's token, copy it to the clipboard for ElevenLabs
    uv run marco say "text"              one talkback line in the headphones, kept as a WAV
    uv run marco say --tone              a one-second tone on the talkback output, to test the routing
    uv run marco say --fresh "text"      a new take of a line Marco has said before
    uv run marco voicenote prepare "t"   make the voice note (OGG/OPUS) and keep it, no send
    uv run marco voicenote send FILE     send a prepared voice note to the Owner on Return
    uv run marco film devices            the audio devices and their channel counts
    uv run marco film record             the booth on one clock until Ctrl+C, in 15-minute segments
    uv run marco export-dialog FOLDER    Muse Wonder fills Logic's export dialog (--dry-run: looks, clicks nothing)
    uv run marco booth                   the session by voice: mic, commands, Logic, talkback (--dry-run: plans only)
    uv run marco routing                 tone and mic test of the interface's virtual channels and inputs
    uv run marco logic play|stop|...     one transport key command into Logic, no model call
    uv run marco knobs learn reverb      open "Marco Knobs" and send its CC for Logic's Learn mode
    uv run marco knobs up|down reverb    one bounded knob step, through the gate
    uv run marco knobs set reverb 60     the knob to an exact percent
    uv run marco preset my chain         load a saved Performance on the selected track (--list shows them)
    uv run marco sound more spacey       Muse Spark sets the open plugin (Controls view) from a description
    uv run marco sound --read            every parameter of the open plugin and its value
    uv run marco chain list|read         the selected track's inserts, and every active plugin's settings
    uv run marco chain sound warmer      Muse Wonder sets the whole chain from a description
    uv run marco chain back              put every control the last change moved back where it was
    uv run marco ears FOLDER [--mix F]   each exported track's loudness, bands and collisions; the mix's headroom
    uv run marco hearing hear --song S --folder STEMS       the full read, spoken, and Marco's question
    uv run marco hearing answer --song S --folder STEMS "the lead is right, 808 harder"   the artist's guardrails
    uv run marco hearing reference --song S [--file ref.wav] "Travis Scott"               the reference sound
    uv run marco show ["caption"]        a picture of Logic's window to the Owner's WhatsApp, for the ISO box
    uv run marco live                    Logic's window live on the phone, video with pictures as fallback; prints the link
    uv run marco tracks list             every track with its region count, and whether this is recording or mixing
    uv run marco tracks rename "Lead Vox"  rename the selected track, read back
    uv run marco session FOLDER          the session view: each track's role and reading, the ranked fights,
                                         what is masked, each track against its role's target, the hardware
    uv run marco handoff mix-ready FOLDER --song S      the session folder a mix engineer expects, measured
    uv run marco handoff master-ready MIX.wav --song S  the mix checked and filed for mastering, or what stops it
    uv run marco run-check FILE --key "F minor" [--start S --end S] [--play] [--midi out.mid]
                                         the notes of a vocal run, cents off each, and the corrected guide
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import subprocess
import sys
from datetime import date

from hiremarco import config, gate
from hiremarco.livelog import Trace

FIRST_QUESTION = "Marco, are you there?"


def cmd_env(args) -> int:
    for key, present in config.describe().items():
        print(f"{key:28} {'set' if present else 'missing'}")
    return 0


def cmd_gate(args) -> int:
    if args.action == "kill":
        gate.set_kill_switch(args.state == "on", "by the Owner")
        print(f"kill switch {args.state}")
        return 0
    conn = gate.connect()
    today = date.today().isoformat()
    rows = conn.execute(
        "select channel, count(*) from effects where ok = 1 and day = ? group by channel", (today,)
    ).fetchall()
    print(f"kill switch {'ON' if gate.kill_switch_on() else 'off'}")
    for channel, count in rows:
        print(f"{channel:10} {count} today")
    return 0


def cmd_first_answer(args) -> int:
    from hiremarco.marco import Marco

    question = " ".join(args.prompt) or FIRST_QUESTION
    trace = Trace(f"heard: {question}")
    try:
        reply = Marco().answer(question, job="first-answer", max_completion_tokens=80)
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    print(reply.text.strip())
    trace.done(f"muse spark, {reply.cost_usd:.5f} USD")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from hiremarco.server import build_app

    uvicorn.run(build_app(reply=not args.listen_only), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_whatsapp(args) -> int:
    if args.action == "verify-token":
        path = config.env_path()
        if config.get("WHATSAPP_VERIFY_TOKEN"):
            token = config.require("WHATSAPP_VERIFY_TOKEN")
        else:
            token = secrets.token_urlsafe(24)
            config.set_value("WHATSAPP_VERIFY_TOKEN", token, path)
        subprocess.run(["pbcopy"], input=token.encode(), check=True)
        print("WHATSAPP_VERIFY_TOKEN copied to the clipboard; paste it into Meta's Verify token field")
        return 0

    from hiremarco.whatsapp import WhatsApp

    wa = WhatsApp()
    if args.action == "subscribe":
        ok = wa.subscribe_app(config.require("WHATSAPP_WABA_ID"))
        print("subscribed" if ok else "not subscribed")
        return 0 if ok else 1
    text = " ".join(args.text)
    owner = config.require("OWNER_WHATSAPP")
    key = "manual:" + hashlib.sha256(f"{date.today()}:{text}".encode()).hexdigest()[:16]
    trace = Trace(f"send: {text}")
    try:
        message_id = wa.send_text(owner, text, idempotency_key=key)
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    trace.done(f"sent {message_id[-6:]}")
    return 0


def cmd_google(args) -> int:
    from hiremarco.google.auth import signin

    signin()
    print("Google signed in; refresh token stored in the secrets file")
    return 0


def cmd_mail(args) -> int:
    from hiremarco.google import Mail

    items = Mail().recent()
    if not items:
        Trace("mail: checked").done("nothing from a granted sender")
        return 0
    for item in items:
        Trace(f"mail: {item.sender_name or item.sender}").done(item.subject[:60])
    return 0


def cmd_relay(args) -> int:
    if config.get("RELAY_TOKEN"):
        token = config.require("RELAY_TOKEN")
    else:
        token = secrets.token_urlsafe(32)
        config.set_value("RELAY_TOKEN", token)
    subprocess.run(["pbcopy"], input=token.encode(), check=True)
    print("RELAY_TOKEN copied to the clipboard; paste it as the custom LLM's API key secret in ElevenLabs")
    return 0


def cmd_say(args) -> int:
    """One talkback line in the headphones. ``--tone`` tests the routing with no speech and no cost."""
    from hiremarco.voice import Talkback, TakeRolling
    from hiremarco.voice.talkback import device_player
    from hiremarco.voice.tts import RATE

    if args.tone:
        import numpy as np

        t = np.arange(RATE) / RATE
        device_player()((np.sin(2 * np.pi * 440 * t) * 6000).astype("<i2"), RATE)
        print("tone played on the talkback output")
        return 0
    text = " ".join(args.text)
    trace = Trace(f"say: {text}" + (" (fresh take)" if args.fresh else ""))
    talkback = Talkback(lambda: False)
    if args.fresh:
        talkback._cache_path(text).unlink(missing_ok=True)  # a new take of the line; the old WAVs stay in capture
    # Standalone, nothing is rolling; in the booth the studio loop passes Logic's transport state.
    try:
        path = talkback.say(text)
    except (gate.Refused, TakeRolling) as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    trace.done(f"spoke, kept {path.name}")
    return 0


def cmd_voicenote(args) -> int:
    from pathlib import Path

    from hiremarco.voice import VoiceNote, prepare_voice_note

    if args.action == "prepare":
        note = prepare_voice_note(" ".join(args.text))
        print(f"ready: {note.ogg} ({note.seconds:.1f} s). Listen to the .wav beside it before sending.")
        return 0
    from hiremarco.critic import Critic
    from hiremarco.whatsapp import WhatsApp

    note = VoiceNote.load(Path(args.text[0]))
    owner = config.require("OWNER_WHATSAPP")
    print(f"voice note, {note.seconds:.1f} s: {note.text}")
    input("Press Return to send it to you on WhatsApp (Ctrl+C to stop) ")
    trace = Trace("voice note")
    key = "voicenote:" + hashlib.sha256(note.ogg.read_bytes()).hexdigest()[:16]
    try:
        message_id = WhatsApp().send_voice(owner, note.ogg.read_bytes(), note.text, idempotency_key=key,
                                           critic=Critic())
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    trace.done(f"sent {message_id[-6:]}")
    return 0


def cmd_film(args) -> int:
    if args.action == "devices":
        import sounddevice as sd

        for i, d in enumerate(sd.query_devices()):
            print(f"{i:>2}  in {d['max_input_channels']:>2}  out {d['max_output_channels']:>2}  {d['name']}")
        return 0
    import time

    from hiremarco.film import FilmRecorder

    rec = FilmRecorder()
    rec.start()
    print(f"film recording {len(rec.channels)} channels at {rec.rate} Hz into {rec.segmenter.folder}; Ctrl+C stops")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    files = rec.stop()
    print(f"stopped: {rec.seconds:.0f} s in {len(files)} segment(s), {rec.dropped} overflow(s)")
    return 0 if rec.dropped == 0 else 1


def cmd_export_dialog(args) -> int:
    from hiremarco.studio.export_cu import HandBack, export_by_computer_use

    trace = Trace(f"export dialog: {args.folder}" + (" (dry run)" if args.dry_run else ""))
    try:
        run = export_by_computer_use(args.folder, dry_run=args.dry_run)
    except HandBack as stop:
        trace.done(f"handed back: {stop.reason}")
        return 1
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    for action in run.actions:
        print("  ", action)
    trace.done(f"{run.steps} step(s): {run.final_text or 'no closing word'}")
    return 0


def cmd_booth(args) -> int:
    from hiremarco.studio.booth import run_booth

    return run_booth(dry_run=args.dry_run)


def cmd_routing(args) -> int:
    import sounddevice as sd

    from hiremarco.routing import mic_levels, probe

    device = config.get("HIREMARCO_TALKBACK_DEVICE") or "Universal Audio Thunderbolt"
    info = sd.query_devices(device)
    ins, outs = info["max_input_channels"], info["max_output_channels"]
    print(f"{device}: {ins} in, {outs} out. A quiet tone plays for one second per pair.")
    # What matters: both reach the headphone mix (MON L/R, inputs 3-4) at about the same level.
    # Marco's voice is also kept clean as one WAV per line, so its own loopback is not needed.
    ok, mon = True, {}
    from hiremarco.voice.talkback import channel_pair

    marco = tuple(channel_pair(config.get("HIREMARCO_TALKBACK_CHANNELS")) or (5, 6))
    for label, pair in (("Marco's voice", marco), ("Logic's output", (5, 6))):
        heard = probe(device, pair, outs, ins)
        print(f"  {label}, out {pair[0]}-{pair[1]}: heard on inputs {heard or 'none'}")
        ok = ok and {3, 4} <= set(heard)
        mon[label] = heard.get(3, -180.0)
    gap = mon["Logic's output"] - mon["Marco's voice"]
    print(f"  in the headphone mix Marco sits {gap:+.1f} dB below Logic for the same tone"
          + (" (within 6 dB, good)" if abs(gap) <= 6 else "; move Console's Virtual 3-4 fader to close the gap"))
    ok = ok and abs(gap) <= 6
    input("Now say a few words into the vocal mic for three seconds. Press Return to start. ")
    quiet = mic_levels(device, ins, threshold=-200)
    print(f"  mic: inputs with signal {dict((k, v) for k, v in quiet.items() if v > -60) or 'none'}")
    print("  every input, dBFS (below -90 is silence):", ", ".join(f"{k}: {v}" for k, v in quiet.items()))
    return 0 if ok else 1


def cmd_logic(args) -> int:
    """One transport command into Logic, no model call: the live key-command test."""
    from hiremarco.studio.commands import Command
    from hiremarco.studio.logic import Logic

    command = Command(args.action)
    trace = Trace(f"logic: {command.describe()}" + (" (dry run)" if args.dry_run else ""))
    try:
        result = Logic(dry_run=args.dry_run).do(command)
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    except subprocess.CalledProcessError as failed:
        trace.done(f"osascript failed (exit {failed.returncode}); check Accessibility for this terminal")
        return 1
    trace.done(result)
    return 0


def cmd_knobs(args) -> int:
    """Set up and test the three plugin knobs on the "Marco Knobs" MIDI port."""
    import time

    from hiremarco.studio.commands import Command
    from hiremarco.studio.logic import KNOB_CC, KNOB_RANGE, Knobs, Logic

    if args.action == "learn":
        knobs = Knobs()
        low, high = KNOB_RANGE[args.knob]
        knobs._midi(KNOB_CC[args.knob], int(knobs.values.get(args.knob, 64)))  # opens the port
        print(f'"Marco Knobs" is open. In Logic, start Learn on the {args.knob} parameter, then come back.')
        input("Press Return to send the knob (CC %d) for Logic to learn " % KNOB_CC[args.knob])
        middle = (low + high) // 2
        for value in [*range(middle - 16, middle + 17, 4), middle]:
            knobs._midi(KNOB_CC[args.knob], value)
            time.sleep(0.15)
        knobs.values[args.knob] = middle
        knobs.state_path.parent.mkdir(parents=True, exist_ok=True)
        knobs.state_path.write_text(__import__("json").dumps(knobs.values))
        input("Sent. End Learn in Logic, then press Return to close the port ")
        return 0
    knobs = Knobs()
    trace = Trace(f"knob: {args.knob} {args.action}")
    try:
        if args.action == "set":
            if args.percent is None or not 0 <= args.percent <= 100:
                trace.done("held: set needs a percent from 0 to 100")
                return 1
            command = Command("knob", knob=args.knob, direction="set", percent=args.percent)
        else:
            command = Command("knob", knob=args.knob, direction=args.action, steps=1)
        result = Logic(knobs=knobs).do(command)
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    time.sleep(0.5)  # let the message leave before the port closes
    trace.done(result)
    return 0


def cmd_preset(args) -> int:
    """Load a saved Performance on Logic's selected track by name, or list them."""
    from hiremarco.studio.commands import Command
    from hiremarco.studio.logic import Logic
    from hiremarco.studio.presets import PresetError, list_presets

    if args.list or not args.name:
        for name in list_presets():
            print(name)
        return 0
    said = " ".join(args.name)
    trace = Trace(f"preset: {said}" + (" (dry run)" if args.dry_run else ""))
    try:
        result = Logic(dry_run=args.dry_run).do(Command("preset", text=said))
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    except PresetError as failed:
        trace.done(f"stopped: {failed}")
        return 1
    trace.done(result)
    return 0


def cmd_run_check(args) -> int:
    """Measure a vocal run from a file: the notes, how far off, and the guide in the headphones."""
    import soundfile as sf

    from hiremarco.studio import pitch

    audio, rate = sf.read(args.file, dtype="float32")
    if args.start is not None or args.end is not None:
        window = (args.start or 0.0, args.end if args.end is not None else len(audio) / rate)
    else:
        window = None
    run = pitch.run_in(audio, rate, args.key, window)
    for i, n in enumerate(run, 1):
        print(f"  {i:>2}  {n.start:7.2f}-{n.end:7.2f} s  {n.name:>4}  {n.cents_off:+4d} cents")
    print(pitch.describe(run))
    if args.play and run:
        from hiremarco.voice import Talkback

        Talkback(lambda: False).play_clip(pitch.guide(run), "guide from file")
    if args.midi and run:
        pitch.to_midi(run, args.midi, bpm=args.bpm)
        print(f"MIDI written: {args.midi}")
    return 0


def cmd_sound(args) -> int:
    """Read the open plugin, or set it from a description (Controls view), or put the last change back."""
    from hiremarco.studio.plugins import Plugin, PluginError

    plugin = Plugin(args.plugin or "-")
    try:
        if args.read or not args.words:
            state = plugin.read()
            print(state.plugin)
            for name, value in state.params.items():
                print(f"  {name:<16} {value:g}")
            return 0
        trace = Trace(f"sound: {' '.join(args.words)}")
        state, said = plugin.design(" ".join(args.words))
    except (PluginError, gate.Refused) as stopped:
        print(f"stopped: {getattr(stopped, 'reason', stopped)}")
        return 1
    for name, value in state.params.items():
        before = plugin.before.params.get(name) if plugin.before else None
        if before is not None and abs(before - value) > 0.05:
            print(f"  {name:<16} {before:g} -> {value:g}")
    trace.done(said)
    return 0


def cmd_chain(args) -> int:
    """The selected track's whole insert chain: list it, read it, set it from a description, put it back."""
    from hiremarco.studio.chain import Channel
    from hiremarco.studio.plugins import PluginError

    channel = Channel()
    try:
        if args.action in ("list", "read"):
            chain = channel.read() if args.action == "read" else None
            if chain is None:
                from hiremarco.studio.chain import parse_list

                for slot in parse_list(channel.run(["list"])):
                    print(f"  {slot.number:>2}  {slot.name:<20} {'bypassed' if slot.bypassed else 'on'}")
                return 0
            for slot in chain.slots:
                print(f"{slot.number:>2}  {slot.name}  ({'bypassed' if slot.bypassed else 'on'})")
                for name, value in (slot.state.params.items() if slot.state else []):
                    lo, hi = slot.state.ranges.get(name, (None, None))
                    span = f"  ({lo:g} to {hi:g}, {slot.state.percent(name):g}%)" if lo is not None and hi > lo else \
                        "  (no range: read only)"
                    print(f"      {name:<26} {value:g}{span}")
            return 0
        if args.action == "back":
            restored = channel.put_back()
            print(f"put back: {', '.join(state.plugin for state in restored.values())}")
            return 0
        trace = Trace(f"chain sound: {' '.join(args.words)}")
        channel.read(fresh=False)  # the last full read, while the slot list still matches it
        before = {s.number: dict(s.state.params) for s in channel.chain.active() if s.state}
        changed, said = channel.design(" ".join(args.words))
    except (PluginError, gate.Refused) as stopped:
        print(f"stopped: {getattr(stopped, 'reason', stopped)}")
        return 1
    for number, state in changed.items():
        for name, value in state.params.items():
            old = before.get(number, {}).get(name)
            if old is not None and abs(old - value) > 0.05:
                print(f"  {state.plugin:<20} {name:<24} {old:g} -> {value:g}")
                why = channel.reasons.get((number, name))
                if why:
                    print(f"      why: {why}")
    trace.done(said)
    return 0


def cmd_ears(args) -> int:
    """Measure a folder of exported tracks, and the mix if given."""
    import json
    from pathlib import Path

    from hiremarco.mix.ears import listen, summary

    report = listen(Path(args.folder), Path(args.mix) if args.mix else None)
    if not report.tracks and not report.mix:
        print("no WAV or AIFF files in that folder")
        return 1
    print(summary(report))
    if args.picture:
        import soundfile as sf

        from hiremarco.mix.picture import draw

        first, second = args.picture
        files = {p.stem: p for p in Path(args.folder).glob("*.wav")}
        if first not in files or second not in files:
            print(f"--picture needs two track names from: {', '.join(sorted(files))}")
            return 1
        a, ra = sf.read(files[first], dtype="float32")
        b, rb = sf.read(files[second], dtype="float32")
        out = Path(args.folder) / f"collision_{first}_{second}.svg".replace(" ", "_")
        spans = draw((first, a, ra), (second, b, rb), out)
        print(f"picture: {out} ({len(spans)} shaded region(s))")
    if args.json:
        Path(args.json).write_text(json.dumps(report.as_dict(), indent=1))
        print(f"report written: {args.json}")
    return 0


def cmd_handoff(args) -> int:
    """The session ready for a mix engineer, or the mix ready for mastering."""
    from pathlib import Path

    from hiremarco.mix.handoff import ready_for_mastering, ready_to_mix

    dest = Path(args.dest).expanduser()
    if args.kind == "mix-ready":
        folder = ready_to_mix(Path(args.path).expanduser(), dest, song=args.song)
        print(f"ready to mix: {folder}")
        return 0
    check = ready_for_mastering(Path(args.path).expanduser(), dest, song=args.song)
    for name, value in check.facts.items():
        print(f"  {name:<14} {value}")
    if not check.ready:
        print("not ready for mastering:")
        for problem in check.problems:
            print(f"  - {problem}")
        return 1
    print(f"ready for mastering: {check.folder}")
    return 0


def cmd_session(args) -> int:
    """Marco's session view of a folder of exported tracks: roles, fights, masking, targets, hardware."""
    from pathlib import Path

    from hiremarco.mix.ears import listen
    from hiremarco.mix.session import build, save, summary

    report = listen(Path(args.folder).expanduser(), Path(args.mix).expanduser() if args.mix else None)
    if not report.tracks:
        print("no WAV or AIFF files in that folder")
        return 1
    view = build(report)
    print(summary(view))
    if args.json:
        save(view, Path(args.json).expanduser())
        print(f"session view written: {args.json}")
    return 0


def cmd_tracks(args) -> int:
    """The session's tracks and mode, or rename the selected track."""
    from hiremarco.studio.tracks import Tracks

    tracks = Tracks(dry_run=args.dry_run)
    if args.action == "list":
        state = tracks.scan()
        for t in state.tracks:
            print(f"  {t.number:>3}  {t.name:<32} {t.regions} region(s)")
        print(f"{len(state.tracks)} track(s): {state.mode} mode")
        return 0
    trace = Trace(f"rename: {' '.join(args.name)}")
    try:
        trace.done(tracks.rename(" ".join(args.name)))
    except (gate.Refused, RuntimeError) as stopped:
        trace.done(f"held: {getattr(stopped, 'reason', stopped)}")
        return 1
    return 0


def cmd_show(args) -> int:
    """Send a picture of Logic's main window to the Owner's WhatsApp."""
    from hiremarco.studio.show import show

    trace = Trace("show")
    try:
        message_id = show(" ".join(args.caption) or "Here's the session.")
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    trace.done(f"sent {message_id[-6:]}")
    return 0


def cmd_live(args) -> int:
    """Serve Logic's window as a live view on this Mac's network, and print the link for the phone."""
    from functools import partial

    import uvicorn

    from hiremarco.studio import live

    token = live.link_token(new=args.new_link)
    width = int(config.get("HIREMARCO_LIVE_WIDTH") or 1600)
    frames = live.Frames(partial(live.grab_logic, width), fps=float(config.get("HIREMARCO_LIVE_FPS") or 4))
    frames.capture_once()
    if frames.error:
        print(f"first frame failed: {frames.error}")
        print("allow the terminal in System Settings > Privacy & Security > Screen Recording, then run this again")
        return 1
    peers = None
    if not args.pictures:
        from hiremarco.studio import webrtc

        video = webrtc.LogicVideo(max_width=width)
        probed = video.probe()
        print(probed)
        if probed.startswith("video on"):
            webrtc.tune_h264()
            peers = webrtc.Peers(video.latest, on_first=video.start, on_last=video.stop)
    address = live.lan_address() or "127.0.0.1"
    link = f"http://{address}:{args.port}/?t={token}"
    subprocess.run(["pbcopy"], input=link.encode(), check=True)
    print(f"live view: {link}")
    print("copied to the clipboard; open it on the phone on the same Wi-Fi. Ctrl+C stops it.")
    Trace("live").done(f"serving on port {args.port}, frame {len(frames.latest) // 1024} KB")
    uvicorn.run(live.make_app(frames, token, peers=peers), host="0.0.0.0", port=args.port, log_level="warning")
    return 0


def cmd_hearing(args) -> int:
    """The mix hearing: read the exported tracks, say what Marco hears, keep the artist's answer or a reference."""
    from pathlib import Path

    from hiremarco.mix import hearing

    if args.action == "answer":
        from hiremarco.mix.ears import listen

        names = [t.name for t in listen(Path(args.folder).expanduser()).tracks]
        prefs = hearing.answer(args.song, " ".join(args.words), names)
    elif args.action == "reference":
        prefs = hearing.reference(args.song, " ".join(args.words),
                                  reference_file=Path(args.file).expanduser() if args.file else None)
        print(prefs.signature)
    else:
        from hiremarco.mix.ears import listen

        _, prefs = hearing.hear(listen(Path(args.folder).expanduser()), args.song)
        print(prefs.heard)
    rails = prefs.guardrails()
    print(f"keep: {', '.join(rails['keep_as_is']) or 'nothing yet'}")
    for track, wish in rails["wishes"].items():
        print(f"wish: {track}: {wish}")
    if rails["reference"]:
        print(f"reference: {rails['reference']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marco")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("env").set_defaults(func=cmd_env)

    g = sub.add_parser("gate")
    g.add_argument("action", choices=["status", "kill"])
    g.add_argument("state", nargs="?", choices=["on", "off"])
    g.set_defaults(func=cmd_gate)

    d = sub.add_parser("demo")
    dsub = d.add_subparsers(dest="moment", required=True)
    fa = dsub.add_parser("first-answer")
    fa.add_argument("prompt", nargs="*")
    fa.set_defaults(func=cmd_first_answer)

    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--listen-only", action="store_true")
    s.set_defaults(func=cmd_serve)

    w = sub.add_parser("whatsapp")
    w.add_argument("action", choices=["send", "verify-token", "subscribe"])
    w.add_argument("text", nargs="*")
    w.set_defaults(func=cmd_whatsapp)

    gg = sub.add_parser("google")
    gg.add_argument("action", choices=["signin"])
    gg.set_defaults(func=cmd_google)

    m = sub.add_parser("mail")
    m.add_argument("action", choices=["check"])
    m.set_defaults(func=cmd_mail)

    r = sub.add_parser("relay")
    r.add_argument("action", choices=["token"])
    r.set_defaults(func=cmd_relay)

    sy = sub.add_parser("say")
    sy.add_argument("--tone", action="store_true")
    sy.add_argument("--fresh", action="store_true")
    sy.add_argument("text", nargs="*")
    sy.set_defaults(func=cmd_say)

    vn = sub.add_parser("voicenote")
    vn.add_argument("action", choices=["prepare", "send"])
    vn.add_argument("text", nargs="+")
    vn.set_defaults(func=cmd_voicenote)

    fm = sub.add_parser("film")
    fm.add_argument("action", choices=["devices", "record"])
    fm.set_defaults(func=cmd_film)

    ed = sub.add_parser("export-dialog")
    ed.add_argument("folder")
    ed.add_argument("--dry-run", action="store_true")
    ed.set_defaults(func=cmd_export_dialog)

    bo = sub.add_parser("booth")
    bo.add_argument("--dry-run", action="store_true")
    bo.set_defaults(func=cmd_booth)

    sub.add_parser("routing").set_defaults(func=cmd_routing)

    lg = sub.add_parser("logic")
    lg.add_argument("action", choices=["play", "stop", "record", "go_to_start", "new_track"])
    lg.add_argument("--dry-run", action="store_true")
    lg.set_defaults(func=cmd_logic)

    kn = sub.add_parser("knobs")
    kn.add_argument("action", choices=["learn", "up", "down", "set"])
    kn.add_argument("knob", choices=["tuning", "reverb", "delay"])
    kn.add_argument("percent", nargs="?", type=int)
    kn.set_defaults(func=cmd_knobs)

    pr = sub.add_parser("preset")
    pr.add_argument("name", nargs="*")
    pr.add_argument("--list", action="store_true")
    pr.add_argument("--dry-run", action="store_true")
    pr.set_defaults(func=cmd_preset)

    rc = sub.add_parser("run-check")
    rc.add_argument("file")
    rc.add_argument("--key", required=True)
    rc.add_argument("--start", type=float)
    rc.add_argument("--end", type=float)
    rc.add_argument("--play", action="store_true")
    rc.add_argument("--midi")
    rc.add_argument("--bpm", type=float, default=120.0)
    rc.set_defaults(func=cmd_run_check)

    so = sub.add_parser("sound")
    so.add_argument("words", nargs="*")
    so.add_argument("--read", action="store_true")
    so.add_argument("--plugin")
    so.set_defaults(func=cmd_sound)

    ch = sub.add_parser("chain")
    ch.add_argument("action", choices=["list", "read", "sound", "back"])
    ch.add_argument("words", nargs="*")
    ch.set_defaults(func=cmd_chain)

    ea = sub.add_parser("ears")
    ea.add_argument("folder")
    ea.add_argument("--mix")
    ea.add_argument("--json")
    ea.add_argument("--picture", nargs=2, metavar=("TRACK_A", "TRACK_B"))
    ea.set_defaults(func=cmd_ears)

    ho = sub.add_parser("handoff")
    ho.add_argument("kind", choices=["mix-ready", "master-ready"])
    ho.add_argument("path", help="the exported tracks folder, or the bounced mix")
    ho.add_argument("--song", required=True)
    ho.add_argument("--dest", default="~/Desktop")
    ho.set_defaults(func=cmd_handoff)

    sv = sub.add_parser("session")
    sv.add_argument("folder")
    sv.add_argument("--mix")
    sv.add_argument("--json")
    sv.set_defaults(func=cmd_session)

    tr = sub.add_parser("tracks")
    tr.add_argument("action", choices=["list", "rename"])
    tr.add_argument("name", nargs="*")
    tr.add_argument("--dry-run", action="store_true")
    tr.set_defaults(func=cmd_tracks)

    he = sub.add_parser("hearing")
    he.add_argument("action", choices=["hear", "answer", "reference"])
    he.add_argument("--song", required=True)
    he.add_argument("--folder", help="the exported tracks (hear, answer)")
    he.add_argument("--file", help="a reference track to measure (reference)")
    he.add_argument("words", nargs="*")
    he.set_defaults(func=cmd_hearing)

    sh = sub.add_parser("show")
    sh.add_argument("caption", nargs="*")
    sh.set_defaults(func=cmd_show)

    lv = sub.add_parser("live")
    lv.add_argument("--port", type=int, default=8788)
    lv.add_argument("--new-link", action="store_true")
    lv.add_argument("--pictures", action="store_true", help="pictures only, no video")
    lv.set_defaults(func=cmd_live)

    args = parser.parse_args(argv)
    if args.command == "tracks" and args.action == "rename" and not args.name:
        parser.error("tracks rename needs the new name")
    if args.command == "say" and not (args.tone or args.text):
        parser.error("say needs the text, or --tone")
    if args.command == "gate" and args.action == "kill" and not args.state:
        parser.error("gate kill needs on or off")
    if args.command == "whatsapp" and args.action == "send" and not args.text:
        parser.error("whatsapp send needs the text")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

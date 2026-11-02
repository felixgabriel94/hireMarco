"""The ``marco`` command. One labelled command per thing worth filming.

    uv run marco env                     which keys are set (never their values)
    uv run marco gate status             kill switch and today's counts
    uv run marco gate kill on|off        stop or resume everything
    uv run marco demo first-answer       Marco's first live answer on Muse Spark
    uv run marco serve                   the WhatsApp webhook on 127.0.0.1:8787
    uv run marco serve --listen-only     hear the Owner, reply to nothing (opens the 24-hour window)
    uv run marco whatsapp send "text"    one message to the Owner (manual trigger)
    uv run marco whatsapp opened         the Owner has just written to Marco's number (until the webhook runs)
    uv run marco whatsapp verify-token   make the webhook token, copy it to the clipboard
    uv run marco whatsapp subscribe      point the WhatsApp account's webhooks at the app
    uv run marco google signin           one Google sign-in for mail (read) and calendar
    uv run marco mail check              granted senders' mail from the last two days
    uv run marco relay token             make the call relay's token, copy it to the clipboard for ElevenLabs
    uv run marco inbox dry-run --days 14 sort the inbox without labelling: counts and examples per label
    uv run marco inbox sync              sort new mail, label it (once labels are on), link it to his tasks
    uv run marco inbox sync --sweep      the always-on half: sort, label, auto-trash, expire; only Google and model keys
    uv run marco inbox sync --tasks      the half beside serve: match mail to open tasks; nothing read when none is open
    uv run marco inbox offers            a direct email becomes one WhatsApp to him, an offer or a heads-up; --dry-run sends nothing
    uv run marco inbox labels on|off     labels in Gmail, after the Owner saw a dry run
    uv run marco inbox digest            the morning WhatsApp: what needs a reply, what came in for tasks
    uv run marco inbox cleanup --list F --confirm SHA   unsubscribe and trash the senders the Owner marked
    uv run marco inbox undo              take every email the cleanup moved back out of Trash
    uv run marco inbox lindy-off         remove the Lindy label (not its emails) and make the Marco label
    uv run marco call setup [--relay-url URL]  the "Marco (calls)" agent on ElevenLabs, made or brought up to date
    uv run marco call place --to +1... --purpose "book a table" [--details "..."]   one call, through the gate
                                         (anyone but the Owner: --owner-said "his words, with the full number")
    uv run marco call transcript ID      the call's transcript and cost, into the state folder
    uv run marco call profile [set F V]  Felix's standing facts for call briefs, kept outside the repo
    uv run marco call offer PLACE_ID --day thursday --hour 20 --party 4   ask him on WhatsApp to call a place
    uv run marco twilio check            read only: the verified caller IDs and the last calls' status
    uv run marco say "text"              one talkback line in the headphones, kept as a WAV
    uv run marco say --tone              a one-second tone on the talkback output, to test the routing
    uv run marco say --fresh "text"      a new take of a line Marco has said before
    uv run marco voicenote prepare "t"   make the voice note (OGG/OPUS) and keep it, no send
    uv run marco voicenote send FILE     send a prepared voice note to the Owner on Return
    uv run marco film devices            the audio devices and their channel counts
    uv run marco film record             the booth on one clock until Ctrl+C, in 15-minute segments
    uv run marco dress PHOTO --say "..." Dress me from a photo on this Mac: what SAM sees and the board to the
                                         Owner's WhatsApp, his pick there (--dry-run: the pictures only, nothing sent)
    uv run marco dress --backdrop        Muse Image paints the board's paper once (0.01 USD), kept in the state dir
    uv run marco selects FOLDER --say "..." the selects from a folder of frames: what SAM sees, then his three, one at a
                                         time, to the Owner's WhatsApp (--dry-run: the files only, nothing sent)
    uv run marco drums train             teach Marco's drum ear on beats built from the Maschine library (once)
    uv run marco drums read FILE --bpm N  a drums stem's pattern: its main groove as a grid and a MIDI file
    uv run marco samples scan             catalog My Packs: each sound's kind, its pack's genre, loop tempo and key
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
    uv run marco app build|install|uninstall   hireMarco, the menu-bar app that starts with Logic (install: at login)
    uv run marco tune FILE --key "F minor"   Marco's first tuning pass: a "(Marco tuned)" file beside the take
    uv run marco beat FILE               the key and tempo of a beat or loop (an estimate)
    uv run marco place booth|desk        where the running booth listens: the vocal mic, or the MacBook mic and speakers
    uv run marco halo                    Marco's halo over Logic: a short exchange, then a take (--preview DIR: pictures)
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
        reply = Marco().answer(question, job="first-answer", max_completion_tokens=400, reasoning_effort="minimal")
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    print(reply.text.strip())
    trace.done(f"muse spark, {reply.cost_usd:.5f} USD")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from hiremarco.server import admit_only, build_app

    app = build_app(reply=not args.listen_only)
    if args.host not in ("127.0.0.1", "localhost"):
        # D-0048: on the home network for the Mini's relay, and only for the addresses named
        allowed = {a.strip() for a in args.allow.split(",") if a.strip()} | {"127.0.0.1"}
        if allowed == {"127.0.0.1"}:
            print("listening beyond this Mac needs --allow with the relay's address")
            return 2
        app = admit_only(app, allowed)
    # the allowlist judges the connection's own address: uvicorn would otherwise take the X-Forwarded-For a tunnel
    # sets as the caller (live 2026-10-30: the tunnel's calls were refused as the public address)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", proxy_headers=False)
    return 0


def cmd_wake_relay(args) -> int:
    """On the always-on Mini (D-0048): Meta's calls in, a magic packet to the MacBook, the call on to Marco."""
    import uvicorn

    from hiremarco.wake_relay import make_app, serve_both

    if args.internal_port == 0:
        uvicorn.run(make_app(), host="127.0.0.1", port=args.port, log_level="warning")
        return 0
    import asyncio

    asyncio.run(serve_both(args.port, args.internal_port))
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

    if args.action == "opened":
        # Until the webhook runs, the Owner says at the desk that he has just written to Marco's number. Meta keeps
        # its own 24-hour window and refuses a free-form text outside it at no charge, so a wrong claim only fails.
        from datetime import datetime, timezone

        from hiremarco.whatsapp.client import record_inbound

        owner = config.require("OWNER_WHATSAPP")
        record_inbound(gate.connect(), f"desk:{datetime.now(timezone.utc).isoformat()}", owner, "owner-said-at-desk")
        Trace("whatsapp: window").done("recorded as opened by the Owner at the desk; Meta's own window still rules")
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
    from pathlib import Path

    from hiremarco.google.auth import GMAIL_ONLY, SCOPES, signin

    if args.write_env and not args.gmail_only:
        print("--write-env is for a --gmail-only sign-in")
        return 2
    target = Path(args.write_env).expanduser() if args.write_env else None
    signin(scopes=GMAIL_ONLY if args.gmail_only else SCOPES, write_env=target)
    print(f"Google signed in; keys written to {target}" if target else "Google signed in; refresh token stored in the secrets file")
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


def cmd_inbox(args) -> int:
    if args.action == "offers":
        return _inbox_offers(args)
    from datetime import datetime, timedelta, timezone

    from hiremarco import inbox
    from hiremarco.google import Mail
    from hiremarco.meta.client import MuseSpark
    from hiremarco.whatsapp import WhatsApp

    if args.action == "sync" and args.sweep and _sweep_killed():
        return 0
    conn = inbox.connect()
    if args.action in ("cleanup", "undo", "lindy-off"):
        from pathlib import Path

        from hiremarco.inbox import cleanup

        mail = Mail()
        if args.action == "lindy-off":
            gone = mail.delete_label("Lindy")
            mail.ensure_label("Marco", inbox.LABELS["Marco"])
            print(("Lindy label removed" if gone else "no Lindy label") + "; Marco label ready")
            return 0
        if args.action == "undo":
            print(f"{cleanup.undo(mail, cleanup.connect())} emails taken back out of Trash")
            return 0
        if not args.list or not args.confirm:
            print("cleanup needs --list FILE and --confirm SHA256 of that file")
            return 1
        try:
            done = cleanup.run(mail, Path(args.list), args.confirm, cleanup.connect(), dry_run=args.dry_run)
        except gate.Refused as refused:
            print(f"not run: {refused.reason}")
            return 1
        b = done["blocked"]
        print(f"one-click unsubscribes {'to send' if args.dry_run else 'sent'}: "
              f"{done['one_click'] if args.dry_run else done['unsubscribed']}; "
              f"{'for' if args.dry_run else 'on'} the auto-trash list (web link / email only / none): {b['link']} / {b['email']} /"
              f" {b['none']}; {'to trash' if args.dry_run else 'trashed'}: {done['trashed']}; kept by the receipt guard:"
              f" {done['kept_by_guard']}; no mail found: {done['skipped']}; unsubscribed before (a resume):"
              f" {done.get('already', 0)}; emails Gmail would not move (logged): {done.get('not_moved', 0)}")
        for sender, how in done["for_felix"]:
            print(f"  web link: {sender}: {how}")
        return 0
    if args.action == "labels":
        inbox.set_labels(conn, args.state == "on")
        print(f"labels {'on' if args.state == 'on' else 'off'}")
        return 0
    if args.action == "sync" and args.sweep:
        return _inbox_sweep(args, conn)
    if args.action == "sync" and args.tasks:
        return _inbox_tasks(args, conn)
    owner = config.require("OWNER_WHATSAPP")
    if args.action == "digest":
        from hiremarco.inbox import cleanup as _cleanup

        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        listed = _cleanup.connect()
        promos = inbox.new_promo_senders(conn, since, lambda s: _cleanup.blocked(listed, s))
        inbox.offer_senders(conn, promos, datetime.now().date().isoformat())
        text = inbox.digest(inbox.unanswered(Mail(), inbox.todays_reply(conn, since)), inbox.closed_since(conn, since), promos)
        try:
            WhatsApp().send_text(owner, text, idempotency_key=f"digest:{datetime.now().date()}")
        except Exception as exc:  # WhatsApp refuses outside its 24 hour window; the job log keeps the reason
            print(f"digest not sent: {type(exc).__name__}: {exc}")
            return 1
        print("digest sent")
        return 0
    mail = Mail()
    if args.action == "dry-run":
        pairs = inbox.sort_inbox(mail, MuseSpark(), conn, newer_than=f"{args.days}d", limit=args.limit, dry_run=True)
        if not pairs:
            print("read nothing: the read-all line is not in RULES.md yet")
            return 1
        print(inbox.summary(pairs))
        return 0
    wa = WhatsApp()
    from hiremarco.inbox import cleanup as _cleanup

    listed, moved, status, unsent = _cleanup.connect(), [], {}, []

    def auto_trash(items):
        moved.extend(_cleanup.trash_blocked(mail, listed, items))
        return moved

    def sent(send):
        """A send WhatsApp refuses (its 24 hour window) is noted and the run goes on: the sort and labels still count."""
        def attempt(*a, **k):
            try:
                return send(*a, **k)
            except Exception as exc:
                unsent.append(type(exc).__name__)
        return attempt

    pairs = inbox.sort_inbox(mail, MuseSpark(), conn, newer_than=f"{args.days}d", limit=args.limit,
                             before=auto_trash, status=status)
    labelled = inbox.apply_labels(mail, conn, pairs)
    learned = inbox.learn_corrections(mail, conn)
    expired = _cleanup.expire_watch(mail, listed) + _cleanup.expire_reminders(mail, listed)
    proof_text = sent(lambda tid, text: wa.send_text(owner, text, idempotency_key=f"task-proof:{tid}", **inbox.asked_of(conn, tid)))
    proof_link = sent(lambda tid, text, url: wa.send_link(owner, text, url, "View booking", idempotency_key=f"task-proof:{tid}",
                                                          **inbox.asked_of(conn, tid)))
    closed = inbox.link_tasks(conn, pairs, proof_text, proof_link)
    for task, _ in closed:
        sent(_proved)(wa, owner, conn, task.id)
    nudged = inbox.nudge_stale(conn, sent(lambda tid, text: wa.send_text(owner, text, idempotency_key=f"task-nudge:{tid}")))
    Trace("inbox: sorted").done(f"{len(pairs)} new, {len(moved)} from the auto-trash list to Trash, {expired} expired,"
                                f" {labelled} labelled, {len(closed)} tasks proved, {nudged} nudged, {learned} corrections"
                                f" learned" + (f", stopped sorting: {status['capped']}" if "capped" in status else "")
                                + (f", {status['unread']} left for the next run" if "unread" in status else "")
                                + (f", {len(unsent)} WhatsApp not sent" if unsent else ""))
    return 0


def _proved(wa, owner: str, conn, task_id: str) -> None:
    """A booking's proof came in: the page is out, on the message of his that asked."""
    from hiremarco import inbox
    from hiremarco.whatsapp import reactions

    asked = inbox.asked_of(conn, task_id).get("quote")
    if asked:
        reactions.react(wa, owner, asked, reactions.RESULT)


def _sent(send, unsent: list):
    """A send WhatsApp refuses (its 24 hour window) is noted and the run goes on."""
    def attempt(*a, **k):
        try:
            return send(*a, **k)
        except Exception as exc:
            unsent.append(type(exc).__name__)
    return attempt


def _sweep_killed() -> bool:
    """Checked before anything opens, so a killed sweep leaves nothing behind in its state folder."""
    from hiremarco.gate.kill import kill_switch_on

    if not kill_switch_on():
        return False
    Trace("inbox: swept").done("stopped by the kill switch")
    return True


def _inbox_offers(args) -> int:
    """The kill switch first, before any state opens or any model call. The log line carries counts only; --dry-run
    prints ids and kinds, and the words he would get only with --show, on his own terminal."""
    from hiremarco.gate.kill import kill_switch_on

    if kill_switch_on():
        Trace("inbox: offers").done("stopped by the kill switch")
        return 0
    from hiremarco.google import Mail
    from hiremarco.inbox import offers_job
    from hiremarco.meta.client import MuseSpark
    from hiremarco.offer import load_places

    if not args.dry_run and not config.get("HIREMARCO_OFFER_TOKEN"):
        Trace("inbox: offers").done("no HIREMARCO_OFFER_TOKEN in the env file, so nothing read or handed off")
        return 1
    state = config.STATE_DIR / "inbox-offers.sqlite"
    conn = offers_job.connect(state if not args.dry_run or state.exists() else ":memory:")
    counts, would = offers_job.run(Mail(), MuseSpark(), conn, places=load_places(), dry_run=args.dry_run,
                                   limit=min(args.limit, 50))
    for row in would:
        print(f"would hand off: id {row['id']}, read as {row['read_as']}, sends as {row['kind']}"
              + (f": {row['line']}" if args.show else ""))
    Trace("inbox: offers" + (" (dry run, nothing sent)" if args.dry_run else "")).done(
        (f"{len(would)} to hand off; " if args.dry_run else "") + offers_job.summary(counts))
    return 0


SWEEP_CAP_USD = 1.0  # a day, on the sweep's own job log, far under the gate's cap for everything


def _inbox_sweep(args, conn) -> int:
    """The always-on half: sort, label, learn, auto-trash and expire. No WhatsApp, no task ledger: it needs only the
    Google and model keys, and tells nobody anything. The kill switch in its own state folder stops all of it, Gmail
    moves included; at its daily cap it stops sorting, and auto-trash and expiry, which cost nothing, go on."""
    from datetime import date

    from hiremarco import inbox
    from hiremarco.google import Mail
    from hiremarco.inbox import cleanup
    from hiremarco.joblog import JobLog
    from hiremarco.meta.client import MuseSpark

    mail, listed, moved, status = Mail(), cleanup.connect(), [], {}

    def over_cap() -> str | None:
        spent = JobLog().total_usd(date.today().isoformat())
        return f"sweep cap {SWEEP_CAP_USD:.2f} USD a day reached" if spent >= SWEEP_CAP_USD else None

    def auto_trash(items):
        moved.extend(cleanup.trash_blocked(mail, listed, items))
        return moved

    pairs = inbox.sort_inbox(mail, MuseSpark(), conn, newer_than=f"{args.days}d", limit=args.limit, before=auto_trash,
                             status=status, with_tasks=False, stop=over_cap)
    labelled = inbox.apply_labels(mail, conn, pairs)
    learned = inbox.learn_corrections(mail, conn)
    expired = cleanup.expire_watch(mail, listed) + cleanup.expire_reminders(mail, listed)
    Trace("inbox: swept").done(f"{len(pairs)} new, {len(moved)} from the auto-trash list to Trash, {expired} expired,"
                               f" {labelled} labelled, {learned} corrections learned"
                               + (f", stopped sorting: {status['capped']}" if "capped" in status else "")
                               + (f", {status['unread']} left for the next run" if "unread" in status else ""))
    return 0


def _inbox_tasks(args, conn) -> int:
    """The half that stays beside marco serve, which opens the tasks: with none open it reads nothing and costs nothing."""
    from hiremarco import inbox

    tasks = inbox.open_tasks(conn)
    if not tasks:
        Trace("inbox: tasks").done("none open")
        return 0
    from hiremarco.google import Mail
    from hiremarco.meta.client import MuseSpark
    from hiremarco.whatsapp import WhatsApp

    owner, wa, mail, status, unsent = config.require("OWNER_WHATSAPP"), WhatsApp(), Mail(), {}, []
    pairs = inbox.match_tasks(mail, MuseSpark(), conn, tasks, newer_than=f"{args.days}d", limit=args.limit, status=status)
    labelled = inbox.apply_labels(mail, conn, pairs)
    closed = inbox.link_tasks(conn, pairs,
                              _sent(lambda tid, text: wa.send_text(owner, text, idempotency_key=f"task-proof:{tid}", **inbox.asked_of(conn, tid)), unsent),
                              _sent(lambda tid, text, url: wa.send_link(owner, text, url, "View booking", idempotency_key=f"task-proof:{tid}",
                                                                        **inbox.asked_of(conn, tid)), unsent))
    for task, _ in closed:
        _sent(_proved, unsent)(wa, owner, conn, task.id)
    nudged = inbox.nudge_stale(conn, _sent(lambda tid, text: wa.send_text(owner, text, idempotency_key=f"task-nudge:{tid}"), unsent))
    Trace("inbox: tasks").done(f"{len(tasks)} open, {labelled} labelled, {len(closed)} proved, {nudged} nudged"
                               + (f", stopped: {status['capped']}" if "capped" in status else "")
                               + (f", {status['unread']} left for the next run" if "unread" in status else "")
                               + (f", {len(unsent)} WhatsApp not sent" if unsent else ""))
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


def cmd_call(args) -> int:
    import json

    from hiremarco.calls import CallError, Calls, off_brief, transcript_lines
    from hiremarco.calls import brief as briefs
    from hiremarco.critic import Critic

    if args.action == "offer":
        from datetime import date

        from hiremarco.calls import offers
        from hiremarco.offer import load_places, next_weekday
        from hiremarco.whatsapp import WhatsApp

        place = next((p for p in load_places() if p.id == args.id), None)
        if place is None:
            print(f"no place {args.id!r} in the places file")
            return 1
        day = next_weekday(args.day.lower(), date.today())
        offer = offers.record_offer(offers.connect(), place, weekday=args.day, day=day.isoformat(), hour=args.hour,
                                    minute=args.minute, party_size=args.party)
        try:
            offers.add_message(offers.connect(), offer.id, WhatsApp().send_text(
                config.require("OWNER_WHATSAPP"), offer.text(place), idempotency_key=f"offer:{offer.id}"))
        except gate.Refused as refused:
            print(f"offer {offer.id} not sent: {refused.reason}")
            return 1
        print(f"offer {offer.id} sent: {offer.text(place)}")
        return 0
    if args.action == "profile":
        profile = briefs.load_profile()
        if args.id == "set":
            if len(args.rest) < 2 or args.rest[0] not in briefs.PROFILE_FIELDS:
                print(f"call profile set FIELD VALUE, FIELD one of {', '.join(briefs.PROFILE_FIELDS)}")
                return 1
            profile[args.rest[0]] = " ".join(" ".join(args.rest[1:]).split())
            path = briefs.save_profile(profile)
            print(f"{args.rest[0]} set in {path}")
            return 0
        for key, value in profile.items():
            print(f"  {key:<17} {'set' if value else 'EMPTY'}")
        print(f"profile: {briefs.profile_path()} (outside the repo)")
        return 0
    calls = Calls()
    try:
        if args.action == "setup":
            url = args.relay_url or config.get("CALL_RELAY_URL")
            if not url:
                print("no relay address: pass --relay-url https://<tunnel>/llm/v1 once; it is kept in the env file")
                return 1
            made = calls.setup(url)
            print(f"agent {made['agent_id']} ready, voice model {made['tts_model']}; line id stored in the env file")
            return 0
        if args.action == "place":
            given = json.loads(open(args.brief_file).read()) if args.brief_file else {}
            given = {**{k: str(v) for k, v in given.items()}, **briefs.parse_pairs(args.brief)}
            trace = Trace(f"call: {args.purpose}")
            try:
                placed = calls.place(args.to, args.purpose, args.details, critic=None if args.no_critic else Critic(),
                                     owner_request=args.owner_said or None, brief=given, kind=args.kind or None)
            except briefs.BriefIncomplete as gap:
                trace.done(f"not dialed: {gap}")
                print("fill them with --brief FIELD=VALUE, or the standing ones with `marco call profile set`")
                return 1
            except gate.Refused as refused:
                trace.done(f"held: {refused.reason}")
                return 1
            trace.done(f"ringing: conversation {placed['conversation_id']} callSid {placed['callSid']}")
            return 0
        path = calls.transcript(args.id)
        import json

        data = json.loads(path.read_text())
        print("\n".join(transcript_lines(data)) or "(no transcript yet)")
        if off_brief(data):
            print(f"asked beyond the brief, for Felix:\n{off_brief(data)}")
        meta = data.get("metadata") or {}
        print(f"status {data.get('status')}, {meta.get('call_duration_secs')} s, cost {meta.get('cost_fiat')} USD;"
              f" saved to {path}")
        return 0
    except CallError as err:
        print(f"call: {err}")
        return 1


def cmd_twilio(args) -> int:
    from hiremarco.calls.twilio import TwilioCheck, TwilioError

    try:
        check = TwilioCheck()
        ids, recent = check.caller_ids(), check.recent_calls(args.last)
    except TwilioError as err:
        print(f"twilio: {err}")
        return 1
    print("verified caller IDs:")
    for c in ids:
        print(f"  {c['label']}  {c['number']}")
    print(f"last {len(recent)} calls:")
    for c in recent:
        print(f"  {c['start']}  {c['direction']}  {c['status']}  {c['seconds']} s  to {c['to']}  {c['sid']}")
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


def cmd_look(args) -> int:
    """Marco studies the pictures of Felix's mood board once and keeps his look as facts."""
    from pathlib import Path

    from hiremarco.look import run

    print(run(Path(args.folder).expanduser(), args.board))
    return 0


def photo_bytes(path) -> bytes:
    """A photo file as JPEG-readable bytes: an iPhone HEIC is turned into JPEG by macOS's own sips first."""
    import io
    import tempfile
    from pathlib import Path

    from PIL import Image, UnidentifiedImageError

    data = Path(path).read_bytes()
    try:
        Image.open(io.BytesIO(data)).verify()
        return data
    except UnidentifiedImageError:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "photo.jpg"
            subprocess.run(["sips", "-s", "format", "jpeg", str(path), "--out", str(out)], check=True,
                           capture_output=True, timeout=60)
            return out.read_bytes()


def cmd_dress(args) -> int:
    """Dress me from a photo on this Mac, the same steps as a photo on WhatsApp: for dry runs and the film's backup.
    Without --dry-run the two pictures go to the Owner's WhatsApp and the board waits for his pick there."""
    from datetime import datetime, timezone
    from pathlib import Path

    from hiremarco import dress
    from hiremarco.joblog import JobLog
    from hiremarco.whatsapp import photos

    if args.backdrop:
        from hiremarco.meta.image import MuseImageError, generate

        trace = Trace("dress: backdrop")
        try:
            dress.backdrop(generate, refresh=True)
        except (gate.Refused, MuseImageError) as held:
            trace.done(f"held: {getattr(held, 'reason', held)}")
            return 1
        trace.done(f"painted {config.STATE_DIR / 'dress' / dress.BACKDROP}")
        return 0
    if not args.photo:
        print("name the photo: marco dress PHOTO --say \"...\"")
        return 2
    said = args.say or "Marco, dress me."
    started = datetime.now(timezone.utc)
    stamp = started.astimezone().strftime("%Y%m%d-%H%M%S")
    trace = Trace(f"dress: {Path(args.photo).name}: {said[:50]}")
    conn = gate.connect()
    data = photo_bytes(Path(args.photo).expanduser())
    send, wa = None, None
    if args.dry_run:
        upright = config.STATE_DIR / "dress" / f"{stamp}-photo.jpg"
        upright.parent.mkdir(parents=True, exist_ok=True)
        upright.write_bytes(photos.upright(data))
    else:
        from hiremarco.whatsapp import WhatsApp

        wa, owner = WhatsApp(conn=conn), config.require("OWNER_WHATSAPP")
        upright = photos.keep(conn, data, f"desk:{stamp}", said).path

        def send(picture: bytes, caption: str, step: str) -> None:
            wa.send_image(owner, picture, caption, idempotency_key=f"dress-{step}:desk:{stamp}", mime="image/jpeg")
    try:
        done = dress.dress(upright, said, conn=conn, send=send, film=dress.film_dir())
    except gate.Refused as held:
        trace.done(f"held: {held.reason}")
        return 1
    except (dress.NoClothesFound, dress.LooksError) as bad:
        trace.done(f"stopped: {bad}")
        return 1
    spent = sum(r.get("cost_usd", 0.0) for r in JobLog().rows() if r.get("ts", "") >= started.astimezone()
                .isoformat(timespec="seconds"))
    for p in done.pieces:
        print(f"  {p.number:>2} {p.label:<11} confidence {p.confidence:.2f}  {'mask' if p.mask is not None else 'box'}")
    for look in done.looks.looks:
        mark = "  <- pick" if look.letter == done.looks.recommend else ""
        print(f"  {look.letter}: {look.name}: pieces {look.pieces}: {look.line}{mark}")
    if done.looks.dropped:
        print(f"  thrown out (not in the photo): {done.looks.dropped}")
    print(f"  caption: {done.looks.caption}")
    print(f"  what SAM sees: {done.seen}")
    print(f"  board:         {done.board}")
    for copy in done.copies:
        print(f"  film copy:     {copy}")
    trace.done(f"{len(done.pieces)} pieces, {'sent' if send else 'dry run, nothing sent'}, {spent:.4f} USD")
    return 0


def cmd_selects(args) -> int:
    """The selects from a folder of frames, the same steps as a shoot on WhatsApp: for dry runs and the film's backup.
    Without --dry-run the contact sheet and the three picks go to the Owner's WhatsApp."""
    from datetime import datetime, timezone
    from pathlib import Path

    from hiremarco import dress, selects
    from hiremarco.joblog import JobLog
    from hiremarco.sam import SamError
    from hiremarco.whatsapp import photos

    source = Path(args.folder).expanduser()
    if not source.is_dir():
        print(f"not a folder: {source}")
        return 2
    files = sorted(p for p in source.iterdir() if p.is_file() and not p.name.startswith(".")
                   and p.suffix.lower() in photos.PHOTO_FILES)
    stems = {p.stem for p in files if p.suffix.lower() not in photos.RAW}
    files = [p for p in files if p.suffix.lower() not in photos.RAW or p.stem not in stems]  # RAW+JPEG: the JPEG
    if not files:
        print(f"no frames in {source}")
        return 2
    started = datetime.now(timezone.utc)
    stamp = started.astimezone().strftime("%Y-%m-%d-%H%M%S")
    said = args.say or "Marco, pick my selects."
    trace = Trace(f"selects: {source.name}: {len(files)} frames: {said[:50]}")
    work = config.STATE_DIR / "selects" / stamp / "frames"
    work.mkdir(parents=True, exist_ok=True)
    noted = f"You sent {len(files)}, so I'm working from the first {selects.CAP}. " if len(files) > selects.CAP else ""
    frames = []
    for i, path in enumerate(files[:selects.CAP], 1):
        try:
            made = photos.upright(path.read_bytes(), suffix=path.suffix.lower())
        except photos.Unreadable as bad:
            print(f"  skipped {path.name}: {bad}")
            continue
        (work / f"{i:02d}.jpg").write_bytes(made)
        frames.append((work / f"{i:02d}.jpg", path))
    if not frames:
        trace.done("stopped: no frame could be read; send JPEG")
        return 1
    conn = gate.connect()
    send = None
    if not args.dry_run:
        from hiremarco.whatsapp import WhatsApp

        wa, owner = WhatsApp(conn=conn), config.require("OWNER_WHATSAPP")

        def send(picture: bytes | None, text: str, step: str) -> None:
            key = f"selects-{step}:desk:{stamp}"
            if picture is None:
                wa.send_text(owner, text, idempotency_key=key)
            else:
                wa.send_image(owner, picture, text, idempotency_key=key, mime="image/jpeg")
    try:
        done = selects.run(frames, said, conn=conn, send=send, film=dress.film_dir(), now=started, noted=noted)
    except gate.Refused as held:
        trace.done(f"held: {held.reason}")
        return 1
    except (selects.NoOneFound, selects.PickError, SamError) as bad:
        trace.done(f"stopped: {bad}")
        return 1
    spent = sum(r.get("cost_usd", 0.0) for r in JobLog().rows() if r.get("ts", "") >= started.astimezone()
                .isoformat(timespec="seconds"))
    for f in done.frames:
        print(f"  {f.number:>2} {f.original.name:<24} " + (
            f"fills {f.fill:4.0%}  cut {','.join(f.cut) or '-':<14} sharp {f.sharp:8.1f}  light {f.light:.2f}  "
            f"blown {f.blown:.0%}  people {f.people}" if f.usable else "no one usable"))
    for line in done.log:
        print(f"  log: {line}")
    for number, line in done.picks.picks:
        print(f"  pick {number}: {line}")
    print(f"  the others: {done.picks.others}")
    print(f"  contact sheet: {done.sheet}")
    print(f"  together:      {done.together}")
    for kept in done.originals:
        print(f"  original:      {kept}")
    for copy in done.copies:
        print(f"  film copy:     {copy}")
    print("  seconds: " + ", ".join(f"{k} {v:.1f}" for k, v in done.seconds.items()))
    trace.done(f"{len(done.frames)} frames, {'sent' if send else 'dry run, nothing sent'}, {spent:.4f} USD")
    return 0


def cmd_drums(args) -> int:
    """The drum ear: trained once on beats built from his library, then reads a drums stem into a pattern."""
    from pathlib import Path

    from hiremarco.studio import drums

    if args.action == "train":
        print(drums.train(beats=args.beats))
        return 0
    if not args.file or not args.bpm:
        print("read needs a FILE and --bpm")
        return 2
    import librosa

    audio = Path(args.file).expanduser()
    y, rate = librosa.load(str(audio), sr=drums.RATE, mono=True)
    one = args.one
    if one is None:
        from hiremarco.studio import the_one

        found = the_one.find(y, rate, the_one.downbeats(audio), args.bpm)
        one = found.seconds
        print(f"the 1 at {one:.3f} s ({'sure' if found.sure else 'not sure, check it'})")
    hits = drums.transcribe(y, rate, args.bpm, one)
    loop = drums.groove(hits, bars=args.bars)
    print(drums.grid(loop, bars=args.bars))
    target = Path(args.out).expanduser() if args.out else audio.with_name(f"{audio.stem} groove {args.bpm:g} bpm.mid")
    print(drums.to_midi(loop, target, args.bpm, length_steps=args.bars * 16))
    return 0


def cmd_samples(args) -> int:
    """The catalog of his packs, rebuilt after he corrects a genre in packs.tsv."""
    from hiremarco.studio import samples

    counts = samples.scan(ear=samples.drum_ear())
    print(", ".join(f"{kind} {n}" for kind, n in sorted(counts.items(), key=lambda kv: -kv[1])))
    return 0


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


def cmd_console(args) -> int:
    """UAD Console on one input: list its slots, load or unload a plug-in, set a control, point Auto-Tune at a key."""
    from hiremarco.studio.console import Console, ConsoleError

    console = Console()
    words = " ".join(args.words)
    try:
        if args.action == "slots":
            print(console.channel_name(args.channel))
            for slot in console.slots(args.channel):
                label = "Unison" if slot.number == 0 else f"insert {slot.number}"
                print(f"  {label:<9} {slot.name or '(empty)'}{'' if slot.power or not slot.name else '  (off)'}")
        elif args.action == "params":
            for name, control in console.params(args.channel, args.slot).items():
                print(f"  {name:<22} {control['shown']}")
        elif args.action == "load":
            print(f"loaded {console.load(args.channel, args.slot, words)} in slot {args.slot}")
        elif args.action == "unload":
            console.unload(args.channel, args.slot)
            print(f"slot {args.slot} is empty")
        elif args.action == "set":
            name, _, value = words.rpartition(" ")
            print(f"{name} = {console.set_param(args.channel, args.slot, name, value)}")
        elif args.action == "tune":
            key, scale = (args.words + ["minor"])[:2]
            for name, shown in console.tune(args.channel, key, scale).items():
                print(f"  {name:<16} {shown}")
    except (ConsoleError, OSError) as stopped:
        print(f"stopped: {stopped}")
        return 1
    return 0


def cmd_mcu(args) -> int:
    """Marco as a Mackie Control surface: ``serve`` holds the ports, anything else is sent to the running surface."""
    import os
    from pathlib import Path

    from hiremarco import config
    from hiremarco.studio import mcu

    state = Path(os.environ.get("HIREMARCO_STATE", config.STATE_DIR))
    sock, log = state / "mcu.sock", state / "mcu.log"
    if args.action == "serve":
        mcu.serve(sock, log)
        return 0
    try:
        print(mcu.ask(sock, " ".join([args.action, *args.words])), end="")
    except OSError:
        print("the surface is not running: start it with `marco mcu serve`")
        return 1
    return 0


def cmd_takes(args) -> int:
    """Abnormal peaks on a take, named by note and key: ``marco takes FILE [--key "C major"]``."""
    from pathlib import Path

    import soundfile as sf

    from hiremarco.mix import audit, takes

    path = Path(args.file).expanduser()
    audio, rate = sf.read(str(path), always_2d=True)
    song_key, confidence = (args.key, 1.0) if args.key else audit.read_key(audio, rate)
    print(f"{path.name}: key {song_key or 'not read'}" + (f" (confidence {confidence:.2f})" if song_key and not args.key else ""))
    found = takes.peaks(audio, rate, song_key, above_db=args.above)
    if not found:
        print("   no peak stands over its octave in a fifth of the take or more")
    for line in takes.describe(found, song_key):
        print("   " + line)
    return 0


def cmd_log(args) -> int:
    """Marco's running log: ``marco log [N]`` prints the last N lines; ``--window`` opens the film's window."""
    from pathlib import Path

    from hiremarco import stream

    at = Path(args.at).expanduser() if args.at else None
    if args.window:
        from hiremarco import logwindow

        logwindow.show(at, lines=args.lines)
        return 0
    rows = stream.tail(args.lines, at=at)
    if not rows:
        print(f"nothing in {at or stream.path()} yet")
        return 0
    for row in rows:
        print(stream.line(row))
    return 0


def cmd_ledger(args) -> int:
    """The license ledger: ``build`` reads the evidence on this Mac, ``show [status]`` lists it."""
    import json
    import os
    from collections import Counter
    from pathlib import Path

    from hiremarco import config
    from hiremarco.studio import ledger

    maps = Path(os.environ.get("HIREMARCO_STATE", config.STATE_DIR)) / "maps"
    path, refused = maps / "license_ledger.json", maps / "not_owned.json"
    if args.action == "build":
        from hiremarco.studio.console import Console, ConsoleError

        names = json.loads((maps / "logic_plugins.json").read_text())
        if not refused.exists():
            refused.write_text(json.dumps(["Melodyne"]))  # trial ended (Owner, 2026-10-29)
        from hiremarco.studio import uad_panel

        try:
            engine = Console().statuses()
        except (ConsoleError, OSError):
            print("UAD Console is not reachable; UAD plug-ins stay unknown")
            engine = {}
        panel_path = maps / "uad_panel.json"
        panel = json.loads(panel_path.read_text()) if panel_path.exists() else None
        if panel:
            print(f"the UAD Control Panel as read {panel['read_at']} ({len(panel['rows'])} rows)")
        uad_rows = uad_panel.reconcile(engine, panel["rows"] if panel else None)
        uad_ok = {n for n, r in uad_rows.items() if r["status"] in ("owned", "demo")}
        wanted = {ledger.base_name(n) for n in names}
        rows = ledger.build(names, uad_ok, set(engine), set(json.loads(refused.read_text())),
                            ledger.strings_in(ledger.used_files(), wanted), ledger.preset_folders(),
                            ledger.registered_ni(), ledger.installed(), uad_rows=uad_rows)
        plans_path = maps / "plans.json"
        plans = json.loads(plans_path.read_text()) if plans_path.exists() else []
        covered = ledger.apply_plans(rows, plans)
        old = ledger.read_ledger(path)
        for name, row in old.items():  # what a scratch test settled stays settled
            if name in rows and any(e.startswith("tried") for e in row["evidence"]):
                rows[name] = row
        path.write_text(json.dumps(rows, indent=1))
        counts = Counter(row["status"] for row in rows.values())
        print(f"{len(rows)} plug-ins: " + ", ".join(f"{counts[s]} {s}" for s in ("owned", "demo", "unknown", "not_owned", "inactive"))
              + f" ({covered} covered by subscriptions)")
        for name, row in sorted(rows.items()):
            if any(e.startswith(("the panel shows", "the engine and the panel", "demo ends")) for e in row["evidence"]):
                print(f"  {row['status']:<9} {name:<48} {'; '.join(row['evidence'])}")
        return 0
    if args.action == "panel":
        import time
        from collections import Counter

        from hiremarco.studio import uad_panel
        from hiremarco.studio.console import Console, ConsoleError

        shown = uad_panel.read_panel(log=print)
        maps.mkdir(parents=True, exist_ok=True)
        (maps / "uad_panel.json").write_text(json.dumps({"read_at": time.strftime("%Y-%m-%d %H:%M %Z"), "rows": shown}, indent=1))
        kinds = Counter(uad_panel.kind_of(s)[0] for s in shown.values())
        print(f"{len(shown)} rows read off the panel: " + ", ".join(f"{kinds[k]} {k}" for k in ("owned", "demo", "not_owned", "inactive", "unknown")))
        unread = [t for t in uad_panel.ini_titles() if t not in shown]
        if unread:
            print(f"  {len(unread)} of UA's titles not seen: {', '.join(unread)}")
        for title, status in shown.items():
            if uad_panel.kind_of(status)[0] in ("demo", "inactive", "unknown"):
                print(f"  {title}: {status}")
        try:
            engine = Console().statuses()
        except (ConsoleError, OSError):
            print("UAD Console is not reachable; no engine reading to compare")
            return 0
        for name, row in uad_panel.reconcile(engine, shown).items():
            if len(row["evidence"]) > 2:
                print(f"  {row['status']:<9} {name}: {'; '.join(row['evidence'])}")
        return 0
    if args.action == "face":
        # one plug-in's license read off its own window in Logic, the last word when the engine and the panel
        # disagree or an authorization just landed (2026-11-02)
        from hiremarco import gate
        from hiremarco.master.job import mark_in_ledger
        from hiremarco.studio import facecheck
        from hiremarco.studio.face import look as look_at_face
        from hiremarco.studio.stereo_out import StereoOut

        if not args.words:
            print("name the plug-in as Logic lists it: marco ledger face 'UAD Shadow Hills Class A Master'")
            return 2
        name = " ".join(args.words)
        strip = StereoOut(conn=gate.connect())
        status = facecheck.check(name, strip, lambda: look_at_face(strip.name, log=print), mark_in_ledger, print)
        return 0 if status != "unknown" else 1
    if args.action == "renewals":
        from datetime import date

        plans_path = maps / "plans.json"
        plans = json.loads(plans_path.read_text()) if plans_path.exists() else []
        days = int(args.words[0]) if args.words else 30
        for plan in ledger.renewals(plans, date.today(), days):
            print(f"  {plan['vendor']} {plan['plan']}: renews {plan['renews']} (in {plan['days_left']} days), {plan['price']}")
        return 0
    rows = ledger.read_ledger(path)
    for name, row in sorted(rows.items()):
        if not args.words or row["status"] in args.words:
            print(f"  {row['status']:<9} {name:<48} {', '.join(row['evidence'])}")
    return 0


def cmd_vault(args) -> int:
    """Serials: ``keep`` reads granted receipts into the Keychain, ``list`` shows pointers, ``show ITEM`` asks first."""
    import os
    from pathlib import Path

    from hiremarco import config
    from hiremarco.studio.vault import Vault

    state = Path(os.environ.get("HIREMARCO_STATE", config.STATE_DIR))
    vault = Vault(log_path=state / "vault.jsonl")
    if args.action == "keep":
        from hiremarco.google import Mail

        mail = Mail()
        try:
            items = mail.recent(newer_than="15y", limit=200, purpose="license receipts")
        finally:
            mail.close()
        import json

        from hiremarco.studio.ledger import base_name

        index = state / "maps" / "logic_plugins.json"
        known = {base_name(n) for n in json.loads(index.read_text())} if index.exists() else set()
        pointers = vault.keep([(item.sender.rpartition("@")[2], item.subject, item.text) for item in items], known)
        print(f"read {len(items)} receipt(s); kept {len(pointers)} serial(s)")
        for line in pointers:
            print(f"  {line}")
    elif args.action == "list":
        for item in vault.keychain.items():
            print(f"  {item}")
    elif args.action == "show":
        value = vault.show(" ".join(args.words))
        print(value if value else "not shown")
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
        if state.scan_error:
            print(f"scan failed: {state.scan_error}")
            return 1
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


def cmd_app(args) -> int:
    from hiremarco.studio import app

    try:
        if args.action == "build":
            print(f"built {app.build()}")
        elif args.action == "install":
            print(app.install())
        else:
            print(app.uninstall())
    except RuntimeError as why:
        print(why)
        return 1
    return 0


def cmd_tune(args) -> int:
    from pathlib import Path

    from hiremarco.studio import tune

    target, before, after = tune.first_pass(Path(args.file), args.key, center=args.center, drift=args.drift)
    print(f"before: {before}")
    print(f"after:  {after}")
    print(f"wrote {target}")
    return 0


def cmd_beat(args) -> int:
    from pathlib import Path

    from hiremarco.studio import analyze

    reading = analyze.read(Path(args.file))
    print(f"{reading.spoken()} (estimate; next most likely key {reading.runner_up}, strength {reading.key_strength})")
    return 0


def cmd_load_beat(args) -> int:
    """A beat onto the Beat track of a new session from the template, as when it lands in his inbox."""
    from pathlib import Path

    from hiremarco.studio.beat_in import BeatLoader, LoadError

    trace = Trace(f"load beat: {Path(args.file).name}")
    try:
        trace.done(BeatLoader().load(Path(args.file).expanduser()))
    except (LoadError, gate.Refused, RuntimeError) as stopped:
        trace.done(f"stopped: {getattr(stopped, 'reason', stopped)}")
        return 1
    return 0


def cmd_audit(args) -> int:
    """The mastering engineer's read of a file, measured, and its deltas against reference masters in a folder."""
    from pathlib import Path

    from hiremarco.mix import audit

    track = audit.audit_file(Path(args.file).expanduser())
    refs = audit.references(Path(args.references).expanduser()) if args.references else []
    print(audit.summary(track, audit.compare(track, refs)))
    return 0


def cmd_organize(args) -> int:
    import json as _json
    import time as _time
    from pathlib import Path as _Path

    from hiremarco.studio import organize

    out = _Path(args.out) if args.out else _Path.home() / "Music" / "hireMarco Bounces" / "organize"
    out.mkdir(parents=True, exist_ok=True)
    if args.plan:
        done = organize.live_apply(organize.load_plan(_Path(args.plan)))
        print(f"organize: {len(done)} tracks renamed and read back")
        return 0
    stamp = _time.strftime("%Y-%m-%d_%H-%M")
    layout = organize.survey()
    (out / f"survey {stamp}.json").write_text(_json.dumps(layout.as_dict(), indent=1))
    print(f"organize: {len(layout.tracks)} tracks surveyed")
    plan = organize.propose(layout, direction=args.direction)
    (out / f"plan {stamp}.json").write_text(_json.dumps(plan.as_dict(), indent=1))
    (out / f"plan {stamp}.md").write_text("## Sections\n" + "\n".join(
        f"- {s['name']}: bars {s['start_bar']:g} to {s['end_bar']:g}. {s['evidence']}" for s in plan.sections)
        + "\n\n## Tracks\n" + plan.table() + f"\n\n{plan.said}\n")
    print(f"organize: {len(plan.changes())} renames proposed; the plan is {out / f'plan {stamp}.json'}")
    return 0


def cmd_taste(args) -> int:
    from pathlib import Path as _Path

    from hiremarco.studio import taste

    parts = []
    for pair in str(args.parts).split(","):
        name, _, number = pair.strip().rpartition("=")
        parts.append((name.strip(), int(number), name.strip()))
    prof, path = taste.run_live(parts, _Path(args.mix_print) if args.mix_print else None, artist=args.artist, out=_Path(args.out))
    print(f"taste: {path}")
    print(prof.summary)
    return 0


def cmd_master(args) -> int:
    """Marco masters the open session: the mix print, the audit, the plan, the chain on the Stereo Out, the master
    print read back, and both WAVs to the Owner (Owner 2026-11-02: the film's ending)."""
    from pathlib import Path

    from hiremarco.master.live import run_live
    from hiremarco.studio.plugins import PluginError

    trace = Trace(f"master: {args.song or 'the session'}")
    try:
        result = run_live(args.song, args.end_bar, purpose=args.purpose, direction=args.direction or "",
                          stock_only=args.stock_only,
                          references=Path(args.references).expanduser() if args.references else None,
                          track=args.track, send=args.send,
                          bounces=Path(args.bounces).expanduser() if args.bounces else None,
                          log=lambda line: print(line, flush=True))
    except (gate.Refused, PluginError, RuntimeError, TimeoutError, FileExistsError) as stopped:
        trace.done(f"stopped: {getattr(stopped, 'reason', stopped)}")
        return 1
    trace.done(result.stopped or result.caption)
    return 1 if result.stopped else 0


def cmd_stage(args) -> int:
    """The Mac waits dark while he is away (Owner 2026-10-30): on keeps it awake with the screen off, so his text
    can wake the screen and Marco opens Logic; off lets it sleep again. The lock-screen setting stays his own hand."""
    import os
    from pathlib import Path

    agent = Path.home() / "Library" / "LaunchAgents" / "com.hiremarco.awake.plist"
    domain = f"gui/{os.getuid()}"
    if args.action == "on":
        agent.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
            '<key>Label</key><string>com.hiremarco.awake</string>'
            '<key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-i</string>'
            '<string>-s</string></array><key>RunAtLoad</key><true/><key>KeepAlive</key><true/></dict></plist>\n')
        subprocess.run(["launchctl", "bootstrap", domain, str(agent)], check=False)
        subprocess.run(["pmset", "displaysleepnow"], check=False)
        print("stage on: the Mac stays awake with the screen dark; a text lights it and Marco opens Logic")
        return 0
    subprocess.run(["launchctl", "bootout", f"{domain}/com.hiremarco.awake"], check=False)
    agent.unlink(missing_ok=True)
    print("stage off: the Mac sleeps as usual again")
    return 0


def cmd_place(args) -> int:
    """Tell the running booth where you are, the same as the menu bar's Listen in the booth / at the desk."""
    import socket

    socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(f"place {args.where}".encode(), ("127.0.0.1", 8790))
    print(f"asked the booth to listen at the {args.where}; its own window says when it has moved")
    return 0


def cmd_halo(args) -> int:
    """Show the halo over Logic on its own, cycling through its three states, so the look can be judged."""
    import math
    import time

    from hiremarco.studio import halo

    path = halo.build()
    if args.preview:
        subprocess.run([str(path), "--preview", args.preview], check=True)
        print(f"pictures in {args.preview}")
        return 0
    started = time.monotonic()

    def demo() -> tuple[str, float]:
        t = time.monotonic() - started
        if args.steady:  # stays up: floating, then speaking, so the look can be judged without the fade
            return ("speaking", abs(math.sin(t * 7)) * 0.6 + 0.1) if t % 8 >= 4 else ("thinking", 0.0)
        phase = t % 20  # he answers, you talk back, he answers again, then a take records and he steps away
        if phase < 2:
            return "thinking", 0.0
        if phase < 6:
            return "speaking", abs(math.sin(t * 7)) * 0.6 + abs(math.sin(t * 2.3)) * 0.3
        if phase < 9:
            return "listening", 0.2 + 0.15 * math.sin(t * 5)
        if phase < 12:
            return "speaking", abs(math.sin(t * 6)) * 0.5 + 0.1
        return "recording", 0.0

    link = halo.Halo(demo)
    link.start()
    print("halo over Logic: a 12-second exchange, then 8 seconds of recording with it away. Ctrl+C stops it.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    link.stop()
    return 0


def cmd_live(args) -> int:
    """Serve Logic's window as a live view on this Mac's network, and print the link for the phone."""
    from hiremarco.studio import live

    try:
        view = live.LiveView.prepare(port=args.port, new_link=args.new_link, pictures=args.pictures)
    except live.NotReady as why:
        print(why)
        return 1
    print(view.video_line)
    print(f"live view: {view.link}")
    if view.server is None:
        print("copied to the clipboard; that window keeps serving it")
        return 0
    print("copied to the clipboard; open it on the phone on the same Wi-Fi. Ctrl+C stops it.")
    Trace("live").done(f"serving on port {args.port}")
    try:
        view.server.run()
    except KeyboardInterrupt:  # uvicorn hands Ctrl+C back once it has closed everything
        pass
    print("live view stopped")
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
    s.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to take the Mini relay's calls on the home network")
    s.add_argument("--allow", default="", help="comma-separated addresses admitted when not on 127.0.0.1")
    s.set_defaults(func=cmd_serve)

    w = sub.add_parser("whatsapp")
    w.add_argument("action", choices=["send", "verify-token", "subscribe", "opened"])
    w.add_argument("text", nargs="*")
    w.set_defaults(func=cmd_whatsapp)

    gg = sub.add_parser("google")
    gg.add_argument("action", choices=["signin"])
    gg.add_argument("--gmail-only", action="store_true", help="a sign-in with Gmail alone, no calendar")
    gg.add_argument("--write-env", help="write the keys a sweep needs to this file, mode 600, not to the secrets file")
    gg.set_defaults(func=cmd_google)

    m = sub.add_parser("mail")
    m.add_argument("action", choices=["check"])
    m.set_defaults(func=cmd_mail)

    ib = sub.add_parser("inbox")
    ib.add_argument("action", choices=["dry-run", "sync", "digest", "labels", "cleanup", "undo", "lindy-off",
                                               "offers"])
    ib.add_argument("--list", default="", help="cleanup: the marked sender list (CSV)")
    ib.add_argument("--confirm", default="", help="cleanup: the sha256 of that list, as the Owner confirmed it")
    ib.add_argument("--dry-run", action="store_true", help="cleanup, offers: count only, change nothing, send nothing")
    ib.add_argument("--show", action="store_true", help="offers --dry-run: print the words he would get")
    ib.add_argument("state", nargs="?", choices=["on", "off"])
    split = ib.add_mutually_exclusive_group()
    split.add_argument("--sweep", action="store_true", help="sync only: sort, label, auto-trash and expire; no WhatsApp, no tasks")
    split.add_argument("--tasks", action="store_true", help="sync only: match new mail to open tasks; nothing read when none is open")
    ib.add_argument("--days", type=int, default=3)
    ib.add_argument("--limit", type=int, default=300)
    ib.set_defaults(func=cmd_inbox)

    r = sub.add_parser("relay")
    r.add_argument("action", choices=["token"])
    r.set_defaults(func=cmd_relay)

    ca = sub.add_parser("call")
    ca.add_argument("action", choices=["setup", "place", "transcript", "profile", "offer"])
    ca.add_argument("id", nargs="?", help="the conversation id, for transcript; set, for profile")
    ca.add_argument("rest", nargs="*", help="profile set FIELD VALUE")
    ca.add_argument("--relay-url", default="", help="https://<tunnel>/llm/v1, for setup")
    ca.add_argument("--to", default="", help="E.164 with the plus")
    ca.add_argument("--purpose", default="")
    ca.add_argument("--details", default="")
    ca.add_argument("--brief", action="append", default=[], help="FIELD=VALUE, one per field the call needs")
    ca.add_argument("--brief-file", default="", help="a JSON file of brief fields")
    ca.add_argument("--kind", default="", help="reservation or generic (default: from the purpose)")
    ca.add_argument("--day", default="thursday", help="for offer: the weekday")
    ca.add_argument("--hour", type=int, default=20, help="for offer: the hour, 24-hour clock")
    ca.add_argument("--minute", type=int, default=0, help="for offer: the minutes of that hour")
    ca.add_argument("--party", type=int, default=4, help="for offer: everyone at the table")
    ca.add_argument("--no-critic", action="store_true", help="skip the critic's second look")
    ca.add_argument("--owner-said", default="", help="the Owner's own words naming the number, for anyone but him")
    ca.set_defaults(func=cmd_call)

    tw = sub.add_parser("twilio")
    tw.add_argument("action", choices=["check"])
    tw.add_argument("--last", type=int, default=5)
    tw.set_defaults(func=cmd_twilio)

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

    dr = sub.add_parser("drums", help="the drum ear: train it once, then read a drums stem into a MIDI groove")
    dr.add_argument("action", choices=["train", "read"])
    dr.add_argument("file", nargs="?")
    dr.add_argument("--bpm", type=float, default=0.0)
    dr.add_argument("--one", type=float, default=None, help="where the 1 is, in seconds; found by ear when left out")
    dr.add_argument("--bars", type=int, default=2)
    dr.add_argument("--beats", type=int, default=1500, help="how many built beats to train on")
    dr.add_argument("--out")
    dr.set_defaults(func=cmd_drums)

    sm = sub.add_parser("samples", help="catalog My Packs by genre and kind (nothing moves)")
    sm.add_argument("action", choices=["scan"])
    sm.set_defaults(func=cmd_samples)

    lk = sub.add_parser("look", help="study the mood board's pictures and keep Felix's look as facts")
    lk.add_argument("folder")
    lk.add_argument("--board", required=True, help="the board's link, kept beside the look")
    lk.set_defaults(func=cmd_look)
    dm = sub.add_parser("dress", help="Dress me from a photo on this Mac: what SAM sees, then the board of three looks")
    dm.add_argument("photo", nargs="?")
    dm.add_argument("--say", default="", help="his words, as he would send them")
    dm.add_argument("--dry-run", action="store_true", help="write the pictures only; nothing is sent")
    dm.add_argument("--backdrop", action="store_true", help="paint the board's paper with Muse Image (0.01 USD)")
    dm.set_defaults(func=cmd_dress)
    se = sub.add_parser("selects", help="The selects from a folder of frames: what SAM sees, then his three")
    se.add_argument("folder")
    se.add_argument("--say", default="", help="his words, as he would send them")
    se.add_argument("--dry-run", action="store_true", help="write the files only; nothing is sent")
    se.set_defaults(func=cmd_selects)

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

    co = sub.add_parser("console", help="UAD Console: slots, params, load, unload, set NAME VALUE, tune KEY SCALE")
    co.add_argument("action", choices=["slots", "params", "load", "unload", "set", "tune"])
    co.add_argument("words", nargs="*")
    co.add_argument("--channel", type=int, default=0, help="Console input, 0 = ANALOG 1")
    co.add_argument("--slot", type=int, default=1, help="1 to 4 for inserts, 0 for Unison")
    co.set_defaults(func=cmd_console)

    va = sub.add_parser("vault", help="serials in the Keychain: keep | list | show ITEM")
    va.add_argument("action", choices=["keep", "list", "show"])
    va.add_argument("words", nargs="*")
    va.set_defaults(func=cmd_vault)

    tk = sub.add_parser("takes", help="abnormal peaks on one take, by note and key: FILE [--key 'C major']")
    tk.add_argument("file")
    tk.add_argument("--key", help="the song's key when known; read from the take otherwise")
    tk.add_argument("--above", type=float, default=5.0, help="dB over its octave a line must stand, per window (5)")
    tk.set_defaults(func=cmd_takes)

    lg = sub.add_parser("log", help="Marco's running log, one line per step all day: the last lines, or --window for the film's window")
    lg.add_argument("lines", nargs="?", type=int, default=8)
    lg.add_argument("--window", action="store_true", help="the fixed dark window the film watches: last eight steps, 24 point")
    lg.add_argument("--at", help="another log file (a dry run's), instead of the real one")
    lg.set_defaults(func=cmd_log)

    le = sub.add_parser("ledger", help="license ledger: build | panel | show [owned|demo|unknown|not_owned|inactive] | renewals [days]")
    le.add_argument("action", choices=["build", "panel", "face", "show", "renewals"])
    le.add_argument("words", nargs="*")
    le.set_defaults(func=cmd_ledger)

    mc = sub.add_parser("mcu", help="Marco as a Mackie Control surface: serve | press NAME [I] | turn STRIP CLICKS | screen")
    mc.add_argument("action", choices=["serve", "press", "turn", "screen", "seek", "confirm", "scan", "jump", "insert", "replace", "remove", "learned", "best", "select", "send"])
    mc.add_argument("words", nargs="*")
    mc.set_defaults(func=cmd_mcu)

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

    ap = sub.add_parser("app")
    ap.add_argument("action", choices=["build", "install", "uninstall"])
    ap.set_defaults(func=cmd_app)

    tn = sub.add_parser("tune")
    tn.add_argument("file")
    tn.add_argument("--key", required=True)
    tn.add_argument("--center", type=float, default=80)
    tn.add_argument("--drift", type=float, default=30)
    tn.set_defaults(func=cmd_tune)

    bt = sub.add_parser("beat")
    bt.add_argument("file")
    bt.set_defaults(func=cmd_beat)

    wr = sub.add_parser("wake-relay", help="on the always-on Mini: wake the MacBook and pass Meta's calls on")
    wr.add_argument("--port", type=int, default=8787)
    wr.add_argument("--internal-port", type=int, default=8789, help="loopback only: a Mini job's /internal/* calls; 0 is off")
    wr.set_defaults(func=cmd_wake_relay)

    lb = sub.add_parser("load-beat", help="a beat onto the Beat track of a new session from the template")
    lb.add_argument("file")
    lb.set_defaults(func=cmd_load_beat)

    au = sub.add_parser("audit", help="the mastering engineer's read of a file, and its deltas against references you own")
    au.add_argument("file")
    au.add_argument("--references", metavar="DIR")
    au.set_defaults(func=cmd_audit)

    og = sub.add_parser("organize", help="organize the open session: survey every track and region, plan the names, rename on go")
    og.add_argument("--plan", metavar="JSON", help="apply this plan's renames (the Owner's go); without it, survey and propose")
    og.add_argument("--out", metavar="DIR", help="where the survey and the plan are written (default ~/Music/hireMarco Bounces/organize)")
    og.add_argument("--direction", default="", help="the Owner's words for this pass, if any")
    og.set_defaults(func=cmd_organize)

    ta = sub.add_parser("taste", help="what Marco learns about the artist from the open session: one track per part, the print, the profile")
    ta.add_argument("--parts", required=True, help="part=track number pairs, comma separated: 'Lead Chorus=7,BGV Chorus 1=14'")
    ta.add_argument("--print", dest="mix_print", metavar="WAV", help="the mix print to audit and listen to")
    ta.add_argument("--artist", default="the artist")
    ta.add_argument("--out", metavar="DIR", required=True, help="where the profile and the reads are written")
    ta.set_defaults(func=cmd_taste)

    ma = sub.add_parser("master", help="master the open session: audit, plan, chain on the Stereo Out, both prints, the WAVs")
    ma.add_argument("--song", help="the song's name, used in the file names (default: the beat the session was set up from)")
    ma.add_argument("--end-bar", type=int, help="the bar the bounce ends on (default: the beat's length at the session's tempo)")
    ma.add_argument("--purpose", choices=["demo", "streaming", "mix"], default="demo")
    ma.add_argument("--direction", default="", help="the artist's words for this master, if any")
    ma.add_argument("--stock-only", action="store_true", help="Logic's own plugins only, as an artist without premium ones")
    ma.add_argument("--references", metavar="DIR", help="reference masters the artist owns, WAV or AIFF or FLAC")
    ma.add_argument("--track", default="PROD", help="a track that goes straight to the Stereo Out, selected for the Inspector")
    ma.add_argument("--bounces", metavar="DIR", help="where the prints go (default ~/Music/hireMarco Bounces/<song>)")
    ma.add_argument("--send", action="store_true", help="text both WAVs to the Owner on WhatsApp when done")
    ma.set_defaults(func=cmd_master)

    st = sub.add_parser("stage", help="on: the Mac waits awake with the screen dark for his text; off: back to normal")
    st.add_argument("action", choices=["on", "off"])
    st.set_defaults(func=cmd_stage)

    pl = sub.add_parser("place")
    pl.add_argument("where", choices=["booth", "desk"])
    pl.set_defaults(func=cmd_place)

    ha = sub.add_parser("halo")
    ha.add_argument("--preview", metavar="DIR")
    ha.add_argument("--steady", action="store_true", help="stay up: floating, then speaking, no fade")
    ha.set_defaults(func=cmd_halo)

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
    if args.command == "call" and args.action == "place" and not (args.to and args.purpose):
        parser.error("call place needs --to and --purpose")
    if args.command == "call" and args.action == "transcript" and not args.id:
        parser.error("call transcript needs the conversation id")
    if args.command == "whatsapp" and args.action == "send" and not args.text:
        parser.error("whatsapp send needs the text")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

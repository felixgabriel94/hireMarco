"""The running Marco: the WhatsApp webhook wired to his voice.

When the Owner writes, Marco marks it read, shows the typing dots, answers
through Muse Spark and replies, each step on his live log. Voice notes are
heard; a photo is kept and seen, with the words that come with it, just before
it or just after it; a burst of them is one shoot, acknowledged once, and his
selects come from it when he asks. A
beat he sends as an audio file or a document is kept until he says to start
a session, by text, by the caption on the beat or by voice note; then the
booth puts it on the Beat track of a new session.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date
from pathlib import Path

from hiremarco import config, gate, stream
from hiremarco.livelog import Trace
from hiremarco.marco import Marco
from hiremarco.style import DAYS_RULE, NAME_RULE, TIME_RULE, days_span
from hiremarco.whatsapp import Inbound, WhatsApp, make_app, reactions
from hiremarco.studio.commands import NEW_SESSION_SAID
from hiremarco.whatsapp.brain import context, decide, history
from hiremarco.whatsapp.facts import forget, keep
from hiremarco.whatsapp.memory import earlier_words, note_words, quoted_words, remember


def _inbox() -> Path:
    from hiremarco.studio.beat_in import INBOX

    return INBOX


def listen_only(message: Inbound) -> str:
    """Record that the Owner wrote (the webhook already did) and say nothing back."""
    return Trace(f"heard: {(message.text or message.kind)[:60]}").done("listening only, no reply")


def save_beat(message: Inbound, wa: WhatsApp, inbox: Path | None = None) -> tuple[Path, bool] | None:
    """A beat or instrumental he sends (an audio file or a document, not a voice note). It is kept in the inbox's
    "received" folder and set up only on his instruction (Owner 2026-10-30); a caption that is the instruction ("start
    a session for Midnight Drive") starts it at once. (path, started), or None for anything that is not a beat."""
    from hiremarco.studio.beat_in import INBOX, beat_file_name, keep_received, session_name, start_session, \
        wants_session

    if message.kind not in ("audio", "document") or message.voice or not message.media_id:
        return None
    name = beat_file_name(message.filename, message.mime_type, f"beat {message.id[-6:] or 'sent'}")
    if name is None:
        return None
    data, _ = wa.download_media(message.media_id)
    folder = inbox or INBOX
    kept = keep_received(data, name, folder)
    if wants_session(message.caption):
        return start_session(folder, session_name(message.caption), asked=message.id) or kept, True
    return kept, False


def voice_text(message: Inbound, wa: WhatsApp, listen=None) -> str:
    """What he said in a WhatsApp voice note, transcribed."""
    import io

    import soundfile as sf

    from hiremarco.hearing import transcribe

    data, _ = wa.download_media(message.media_id)
    audio, rate = sf.read(io.BytesIO(data), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    # he names songs in Spanish too: "Angel de Cristal" came back as "Anhil de Cristal" (live 2026-10-30)
    turns = (listen or (lambda a, r: transcribe(a, r, diarize=False, languages=["English", "Spanish"])))(audio, rate)
    return " ".join(t.text for t in turns).strip()


ENGLISH = ("Reply in English, even when he writes a word, a name or a song title in Spanish or another language. "
           "Answer in another language only when he asks you to. " + TIME_RULE + " " + DAYS_RULE + " " + NAME_RULE)
AFFIRM = re.compile(r"^(?:yes|yeah|yep|yup|sure|ok|okay|go|go ahead|do it|please do|let'?s go|start it|si|sí|dale)\b",
                    re.I)
STATUS = re.compile(r"\b(?:did|have|has|is|are|was)\b.*\b(?:session|start(?:ed)?|set ?up|ready|done|loaded|logic)\b"
                    r"|\b(?:status|where are we|how'?s it going)\b", re.I)


def booth_running(port: int = 8790) -> bool:
    """His booth holds the shortcut port while it runs; a free port means it is not running."""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def ensure_booth(running=booth_running) -> str:
    """The booth sets sessions up; when it is not running, start it the way the menu-bar app does."""
    if running():
        return "booth running"
    from hiremarco.studio.beat_in import wake_display

    wake_display()  # the Mac waits dark while he is away; his word lights it up
    return start_booth(running)


def start_booth(running=booth_running) -> str:
    """The booth, by whose grants this server has: started from a Terminal window, the server holds Terminal's and
    the booth is its own quiet child, no window anywhere (Owner 2026-11-03: never a Terminal window on the MacBook,
    on camera); under anything else (live 2026-11-03: the launchd job com.hiremarco.serve) it has none to lend, so
    the booth opens through its .command behind the front app, and Terminal is hidden as fast as it can be."""
    import subprocess

    from hiremarco import grants

    if grants.under_terminal():
        return start_booth_quietly(running=running)
    script = config.STATE_DIR / "booth.command"
    if not script.exists():
        return "booth not running, and no booth.command to start it"
    subprocess.run(["open", "-g", "-j", "-a", "Terminal", str(script)], check=False, timeout=15)  # behind, hidden
    hide_terminal()
    return "booth started"


def start_booth_quietly(running=booth_running, popen=None) -> str:
    """The booth as this server's own background process, with no Terminal window anywhere: it has whatever grants
    this server has (Terminal's when the server was started from a Terminal window; none under a launchd job, live
    2026-11-03, which is why ensure_booth asks grants first)."""
    import os
    import subprocess
    import sys

    if running():
        return "booth running"
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = (config.STATE_DIR / "booth.log").open("a")
    env = {**os.environ, "HIREMARCO_FROM_APP": "1", "PYTHONUNBUFFERED": "1"}
    (popen or subprocess.Popen)([sys.executable, "-c", "import sys; from hiremarco.cli import main; sys.exit(main(['booth']))"],
                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                start_new_session=True, cwd=str(Path(__file__).resolve().parents[2]))
    return "booth started"


def make_booth_route():
    """POST /internal/booth from this Mac only: the menu-bar app's way to start the booth when Logic opens."""
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def route(request: Request):
        if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
            return JSONResponse({"status": "refused"}, status_code=403)
        answer = await run_in_threadpool(ensure_booth)
        Trace("booth from the app").done(answer)
        return JSONResponse({"status": answer})

    return route


def hide_terminal(wait_s: float = 1.5) -> None:
    import subprocess
    import time

    time.sleep(wait_s)
    subprocess.run(["osascript", "-e", 'tell application "System Events" to set visible of process "Terminal" to false'],
                   check=False, capture_output=True, timeout=10)


def status(inbox: Path, running=booth_running) -> str:
    """Where his beat is, in one line he can read: waiting for his word, being set up, or set up."""
    from hiremarco.studio.beat_in import last_loaded, latest_received, pending, requested_name

    waiting = pending(inbox)
    if waiting:
        song = requested_name(waiting[-1]) or waiting[-1].stem
        return f"Setting up {song} now." if running() else f"Starting it now: {song}. My booth was off, so I'm opening it."
    kept = latest_received(inbox)
    if kept is not None:
        return f"Not yet. I have your beat ({kept.stem}). Say start and I'll set it up."
    done = last_loaded(inbox)
    if done is not None:
        return f"Yes. {requested_name(done) or done.stem} is set up in Logic."
    return "No beat yet. Send me one and tell me when to start."


def nudge_booth(word: bytes, running=booth_running, port: int = 8790, wait_s: float = 30.0) -> None:
    """One word to the booth's own socket, the way the menu-bar app speaks to it; a booth still starting gets it
    once its port is up, from a thread, so his text is not lost to the seconds the booth takes."""
    import socket

    def send() -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(word, ("127.0.0.1", port))
        finally:
            sock.close()

    if running():
        send()
        return

    def later() -> None:
        waited = 0.0
        while waited < wait_s and not running():
            time.sleep(0.5)
            waited += 0.5
        if running():
            time.sleep(1.0)   # the port is bound before the booth listens
            send()

    threading.Thread(target=later, daemon=True).start()


def fresh_session(said: str, sender: str, message_id: str, wa: WhatsApp, inbox: Path | None,
                  booth=ensure_booth, nudge=None) -> str | None:
    """"Open a new session and wait for me" by text, as by voice (Owner 2026-11-03): with no beat kept or waiting,
    the booth opens Logic from the template and waits. Asked before the brain, so the words act, not get answered.
    None for any other words, or when a beat is there (then the session is set up with it, the usual way)."""
    from hiremarco.studio.beat_in import INBOX, latest_received, pending

    folder = inbox or INBOX
    plain = re.sub(r"^(?:hey |hi |ok |okay )?marco[,:!]?\s*", "", (said or "").lower().strip(" .!")).strip()
    if not NEW_SESSION_SAID.match(plain) or latest_received(folder) is not None or pending(folder):
        return None
    started = booth()
    (nudge or nudge_booth)(b"session")
    wa.send_text(sender, "Opening a fresh session. I'll wait for you.", idempotency_key=f"fresh:{message_id}")
    return f"fresh session asked of the booth; {started}"


def instruction(said: str, sender: str, message_id: str, wa: WhatsApp, inbox: Path | None,
                booth=ensure_booth, running=booth_running, nudge=None) -> str | None:
    """His words about a session, answered from the real state: start the beat he sent (on "start a session",
    "set it up", or a yes to Marco's question), take a corrected title, or say where things stand. None when the
    words are about something else (Owner 2026-10-30, after a live test where Marco missed all three)."""
    from hiremarco.studio.beat_in import INBOX, latest_received, pending, rename_pending, session_name, \
        start_session, title, wants_session

    folder = inbox or INBOX
    said = (said or "").strip()
    reply = lambda text, tag: wa.send_text(sender, text, idempotency_key=f"{tag}:{message_id}")  # noqa: E731
    short = 2 <= len(said.split()) <= 6 and "?" not in said and not re.match(r"(?i)(?:hey|hi|hello|yo|thanks|thank you|ok|okay|cool|nice|great)\b", said)
    kept, waiting = latest_received(folder), pending(folder)
    fresh = fresh_session(said, sender, message_id, wa, folder, booth=booth, nudge=nudge)
    if fresh is not None:
        return fresh
    if STATUS.search(said) and ("?" in said or not wants_session(said)):
        line = status(folder, running)
        if pending(folder):
            booth()
        reply(line, "status")
        return f"status: {line}"
    if wants_session(said) or (kept is not None and AFFIRM.search(said)):
        song = session_name(said)
        if kept is not None:
            started = start_session(folder, song, asked=message_id)
            reply(f"On it. Setting up {song or started.stem}.", "start")
            return f"session started for {started.name}" + (f" as {song!r}" if song else "") + f"; {booth()}"
        if waiting:
            if song:
                rename_pending(song, folder)
            line = f"Already on it: setting up {song or waiting[-1].stem}." + ("" if running() else
                                                                                " Opening my booth now.")
            reply(line, "start")
            return f"already started; {booth()}"
        reply("Send me the beat first, then tell me to start.", "nobeat")
        return "asked for the beat: none is waiting"
    if waiting and short and not AFFIRM.search(said):
        song = title(said)
        rename_pending(song, folder)
        reply(f"No problem. Naming it {song}.", "rename")
        return f"renamed the waiting session to {song!r}; {booth()}"
    return None


_MASTERING = threading.Lock()


def start_master(wa: WhatsApp, sender: str, direction: str, run=None, start=None) -> str:
    """The master job beside the webhook (Owner 2026-11-02: "send it to mix" by text): one at a time, the WAVs
    texted by the job itself, a stop texted here. ``run`` and ``start`` are swapped in tests."""
    if not _MASTERING.acquire(blocking=False):
        return "a master is already printing"

    def work() -> None:
        try:
            runner = run or __import__("hiremarco.master.live", fromlist=["run_live"]).run_live
            result = runner(direction=direction, send=True, log=lambda line: print(f"   master: {line}", flush=True))
            if getattr(result, "stopped", ""):
                wa.send_text(sender, f"The master stopped: {result.stopped}", idempotency_key=f"master-stop:{time.time_ns()}")
        except Exception as exc:
            try:
                wa.send_text(sender, f"The master stopped: {str(exc)[-200:]}", idempotency_key=f"master-stop:{time.time_ns()}")
            except Exception:
                pass
        finally:
            _MASTERING.release()
    (start or (lambda f: threading.Thread(target=f, daemon=True).start()))(work)
    return "mastering started"


# A reply changes nothing, so a reply that promises or reports a send is untrue (live 2026-11-03: "Sending it now",
# twice, to a text he had no way to send). A conditional offer ("want me to?") is not a promise.
PROMISED_SEND = re.compile(
    r"\b(?:i'?ll|i will|i'?m going to|let me)\s+(?:text|message|whatsapp|imessage|dm)\b(?!\s+you\b)"
    r"|\bsending (?:it|that|this|the (?:text|message))?\s*now\b"
    r"|\b(?:it'?s|it is) (?:going out|on its way)\b"
    r"|\bi(?:'ve| have)? (?:just )?(?:texted|messaged) (?:her|him|them)\b"
    r"|\bget (?:that|the) (?:text|message) out\b"
    r"|\b(?:calling|dialing) (?:her|him|them|now)\b", re.I)
NO_SEND = ("I can't send that from here, so nothing went out.", "Nothing went out. I can't send that from here yet.",
           "Still nothing sent: that isn't something I can do from here yet.")
CALL_ASK_WINDOW_S = 30 * 60  # his words in the last half hour are "that request" for the named-call switch


def promises_send(text: str) -> bool:
    return bool(PROMISED_SEND.search(text or ""))


def no_send_line(conn, now=None) -> str:
    """The plain line in place of a promised send, a different one each time within the gate's ten minutes, so a
    second "did you send it?" is answered instead of held as a repeat."""
    from datetime import datetime, timedelta, timezone

    from hiremarco.whatsapp.memory import recall

    since = (now or datetime.now(timezone.utc)) - timedelta(minutes=10)
    said = sum(1 for ts, who, text in recall(conn, 20) if who == "marco" and text in NO_SEND and ts >= since)
    return NO_SEND[said % len(NO_SEND)]


def his_recent_words(conn, now=None) -> str:
    """What he wrote in the last half hour, his own words, for the gate's named-call check."""
    from datetime import datetime, timedelta, timezone

    from hiremarco.whatsapp.memory import recall

    since = (now or datetime.now(timezone.utc)) - timedelta(seconds=CALL_ASK_WINDOW_S)
    return "\n".join(text for ts, who, text in recall(conn, 40) if who == "felix" and ts >= since)


def call_result(who: str, data: dict) -> str:
    """How his call went, in one or two lines: what was settled and the next step, never a goodbye quote."""
    from hiremarco.calls import brief as briefs

    if data.get("status") != "done":
        return f"The call to {who} didn't go through. Want me to try again later?"
    turns = data.get("transcript") or []
    tools = {tc.get("tool_name") or tc.get("name") for t in turns for tc in t.get("tool_calls") or []}
    if "voicemail_detection" in tools:
        return f"{who} didn't pick up, so I left a voicemail."
    if not any(t.get("role") == "user" and str(t.get("message") or "").strip() for t in turns):
        return f"{who} didn't pick up. Want me to try again later?"
    collected = (data.get("analysis") or {}).get("data_collection_results") or {}
    value = lambda key: briefs.unspell(str((collected.get(key) or {}).get("value") or "").strip().rstrip("."))  # noqa: E731
    agreed, step = value("agreed"), value("next_step")
    text = (f"I reached {who}, but nothing was settled." if not agreed or agreed.lower().startswith("nothing")
            else f"{who}: {agreed}.")
    if step:
        text += f" Next: {step}."
    return re.sub(r"\+?\d[\d ()-]{7,}\d", lambda m: "..." + re.sub(r"\D", "", m.group())[-4:], text)


def call_for_him(call: dict, sender: str, message_id: str, wa: WhatsApp, *, calls=None, start=None,
                 now=None) -> tuple[str, str]:
    """The brain's call: dial only with his full number in his own recent words and a complete brief, the phone on
    his message just before the dial and off again if it does not start, then his result texted when the call ends
    (Owner 2026-11-03: "Can u call Lucie..." was answered with calls not being live). Returns the text to send now
    and the log line."""
    from hiremarco.calls import CallError, Calls, offers
    from hiremarco.calls import brief as briefs
    from hiremarco.critic import Critic
    from hiremarco.joblog import JobLog, JobRow

    who = call.get("who") or "them"
    digits = re.sub(r"\D", "", call.get("number") or "")
    said = his_recent_words(wa.conn, now)
    heard = re.sub(r"\D", "", said)
    if not digits or digits not in heard:
        if len(digits) == 11 and digits.startswith("1") and digits[1:] in heard:
            return (f"Send me {who}'s number with the country code, like +1 305 555 0100, and I'll call.",
                    f"call to {who}: his number came without the country code")
        return f"What's {who}'s number? Send it here and I'll call.", f"call to {who}: no number of his in this conversation"
    given = {"ask": call.get("ask", ""), "if_unavailable": call.get("if_unavailable", "")}
    if call.get("voicemail"):
        given["voicemail"] = call["voicemail"]
    try:
        if not call.get("purpose"):
            raise briefs.BriefIncomplete("generic", ["ask"])
        briefs.build("generic", {k: v for k, v in given.items() if k != "voicemail"})
    except briefs.BriefIncomplete as gap:
        wants = {"ask": "what should I ask or arrange", "if_unavailable": "what should I do if they can't",
                 "name": "what name should I give", "email": "what email should I give", "callback": "what number "
                 "should they call back"}
        asks = [wants.get(k, briefs.LABELS.get(k, k)) for k in gap.missing]
        return (f"Before I call {who}: {', and '.join(asks)}?",
                f"call to {who}: asked for {', '.join(gap.missing)} before dialing")
    calls = calls or Calls()
    phone_on = reactions.react(wa, sender, message_id, reactions.CALLING)  # just before the dial, on his ask
    try:
        placed = calls.place("+" + digits, call["purpose"], f"for Felix, calling {who}", critic=Critic(),
                             brief=given, kind="generic", owner_request=said,
                             idempotency_key=f"brain-call:{message_id}")
    except Exception as held:
        if phone_on:
            reactions.take_off(wa, sender, message_id)
        if not isinstance(held, (gate.Refused, CallError)):
            raise
        return (f"I couldn't get the call to {who} going just now. Want me to try again?",
                f"call to {who}: held: {getattr(held, 'reason', held)}")

    def report() -> None:
        try:
            data = offers.wait_for_result(lambda: calls._json("GET", f"/convai/conversations/{placed['conversation_id']}"))
            calls.transcript(placed["conversation_id"])  # saved with its cost, like `marco call transcript`
            text = call_result(who, data)
            wa.send_text(sender, text, idempotency_key=f"call-result:{message_id}", quote=message_id)
            if not text.startswith(("The call to", f"{who} didn't pick up")):
                reactions.react(wa, sender, message_id, reactions.RESULT)
        except Exception as exc:  # the result is owed: he hears it could not be read, the log says why
            JobLog().append(JobRow(job="call-result", ok=False, note=type(exc).__name__))
            wa.send_text(sender, f"The call to {who} ended, but I couldn't read how it went. Want me to call again?",
                         idempotency_key=f"call-result:{message_id}")

    # "Calling" lands before the result can, however fast the call ends
    wa.send_text(sender, f"Calling {who} now. I'll tell you how it goes.", idempotency_key=f"brain:{message_id}")
    (start or (lambda f: threading.Thread(target=f, daemon=True).start()))(report)
    return "", f"calling {who}, conversation {placed['conversation_id']}"


def act(decision, sender: str, message_id: str, wa: WhatsApp, inbox: Path | None, booth=ensure_booth,
        earlier: dict | None = None, calls=None, start=None) -> str:
    """The brain's choice carried out, then its text sent; when the studio says the choice cannot be done, the text
    says what is true instead of what the brain hoped."""
    from hiremarco.studio.beat_in import INBOX, cancel_pending, name_received, pending, rename_pending, \
        requested_name, retry_pending, start_session, title

    folder = inbox or INBOX
    earlier = earlier or {}
    text, did = decision.reply, "replied"
    name = title(decision.title) if decision.title else None
    if decision.action == "start" or decision.action == "retry":
        if decision.action == "retry" and pending(folder):
            if name:
                rename_pending(name, folder)
            did = f"retrying {retry_pending(folder).name}; {booth()}"
        elif (started := start_session(folder, name, asked=message_id)) is not None:
            named = requested_name(started)
            did = f"session started for {started.name}" + (f" as {named!r}" if named else "") + f"; {booth()}"
        elif pending(folder):
            if name:
                rename_pending(name, folder)
            did = f"already waiting: {pending(folder)[-1].name}; {booth()}"
        else:
            text, did = "I don't have a beat waiting. Send me one and I'll set it up.", "no beat to start"
    elif decision.action == "rename":
        if not name:
            text, did = "What should I call it?", "rename without a title"
        elif (named := rename_pending(name, folder) or name_received(name, folder)) is not None:
            did = f"named {named.name} {name!r}"
        else:
            text, did = "There's no beat waiting to name. Send me one first.", "no beat to name"
    elif decision.action == "cancel":
        back = cancel_pending(folder)
        did = f"cancelled: {back.name} back in received" if back else "nothing waiting to cancel"
        if back is None:
            text = "Nothing's waiting to be set up."
    elif decision.action == "master":
        did = start_master(wa, sender, decision.title or "")
        if not did.startswith("mastering"):
            text = "I can't print it right now: " + did + "."
    elif decision.action == "call":
        text, did = call_for_him(decision.call, sender, message_id, wa, calls=calls, start=start)
    elif promises_send(text):  # a reply sends nothing: a line that says it does is not sent (live 2026-11-03)
        text, did = no_send_line(wa.conn), "a reply that promised a send, replaced"
    kept = [f for f in decision.remember if keep(wa.conn, f)]
    gone = [g for f in decision.forget for g in forget(wa.conn, f)]
    working = decision.action in ("start", "retry") and did.startswith(("session started", "retrying"))
    emoji = reactions.ON_IT if working else (None if decision.action == "call"  # the phone is the call's own
                                             else reactions.MODEL_PICKS.get(decision.reaction))
    if text:
        if emoji:
            reactions.react(wa, sender, message_id, emoji)
        pointed = earlier.get(decision.quote, ("",))[0]  # only a message on the list he was shown, never one of Marco's
        wa.send_text(sender, text, idempotency_key=f"brain:{message_id}", **({"quote": pointed} if pointed else {}))
    elif emoji:  # nothing needs saying: the reaction is the reply, and a short line if it can't go
        reactions.react_or_say(wa, sender, message_id, emoji, f"brain:{message_id}")
    memory = (f"; kept {len(kept)}" if kept else "") + (f"; forgot {len(gone)}" if gone else "")
    return f"brain: {decision.action}; {did}{memory}"



def crew_words(said: str, sender: str, message_id: str, wa: WhatsApp, *, take=None) -> str | None:
    """Roll, Roll test, Action, Cut (Owner 2026-11-03): the whole message is the word. Read with blue ticks only (the
    chat is on camera: no typing dots, no answer), done off Marco Live, in the order sent. Marco texts only when
    something cannot record. None for any other words."""
    from hiremarco import crew, events

    def tell(text: str) -> None:
        with events.aside():
            wa.send_text(sender, text, idempotency_key=f"crew:{message_id}:{abs(hash(text)) % 10_000}")

    if crew.words(said) is None:
        return None
    with events.aside():
        try:
            wa.mark_read(message_id)
        except Exception:
            pass
        return (take or crew.take)(said, message_id, tell)


_MONITOR_SEEN: dict[str, str] = {}


def monitor_words(said: str, sender: str, message_id: str, wa: WhatsApp, *, hand=None) -> str | None:
    """The Owner's word on the speakers (Owner 2026-11-03: "lower it", "turn it up", "set it to -50", "stop"), done
    with no model in the loop and off Marco Live: the level fades, never jumps, under the apartment's cap, and he
    reads back where it ended. None for any other words."""
    from hiremarco import events
    from hiremarco.studio import monitor

    hand = hand or monitor.hand()
    request = monitor.words(said, fading=hand.fading)
    if request is None:
        return None
    if message_id in _MONITOR_SEEN:
        return f"monitor: {_MONITOR_SEEN[message_id]} (already handled)"
    if len(_MONITOR_SEEN) > 200:
        _MONITOR_SEEN.clear()
    remember(wa.conn, "felix", said)

    def reply(text: str) -> None:
        with events.aside():
            wa.send_text(sender, text, idempotency_key=f"monitor:{message_id}")

    with events.aside():
        did = hand.answer(request, reply)
    _MONITOR_SEEN[message_id] = did
    return f"monitor: {did}"


def email_words(said: str, sender: str, message_id: str, wa: WhatsApp, quoted: str = "") -> str | None:
    """His words about his email; None for anything else. A failure here tells him nothing went out."""
    from hiremarco.calls import offers
    from hiremarco.inbox import outbox
    from hiremarco.joblog import JobLog, JobRow

    try:
        return outbox.handle_words(said, sender, message_id, wa, offer_pending=lambda: offers.pending(offers.connect()),
                                   **({"quoted": quoted} if quoted else {}))
    except gate.Refused:
        raise
    except Exception as exc:
        JobLog().append(JobRow(job="mail", ok=False, note=type(exc).__name__))
        wa.send_text(sender, "I couldn't do that with your email just now. Nothing was sent.",
                     idempotency_key=f"mail-failed:{message_id}")
        return f"mail: failed, {type(exc).__name__}"


def digest_unsubscribe(said: str, sender: str, message_id: str, wa: WhatsApp, *, conn=None, listed=None, mail=None,
                       gate_conn=None, http=None, rules_path=None, today: str | None = None) -> str | None:
    """His one reply to the morning digest: "unsubscribe 2" or "unsubscribe all" (Owner 2026-11-01). None when his
    words are anything else, and the brain answers as usual."""
    from hiremarco import inbox as mailbox
    from hiremarco.google import Mail
    from hiremarco.inbox import cleanup

    asked = mailbox.unsubscribe_words(said)
    if asked is None:
        return None
    conn = conn or mailbox.connect()
    senders, missing = mailbox.offered_senders(conn, asked, today or date.today().isoformat())
    lines = []
    if senders:
        lines.append(cleanup.drop_reply(mail or Mail(), senders, listed or cleanup.connect(), gate_conn=gate_conn,
                                        http=http, rules_path=rules_path))
    if missing:
        lines.append(f"Number {missing[0]} isn't on the list." if len(missing) == 1
                     else f"Numbers {', '.join(map(str, missing))} aren't on the list.")
    if not lines:
        lines.append("There's no list to unsubscribe from right now. New promotion senders show up in your morning digest.")
    wa.send_text(sender, "\n".join(lines), idempotency_key=f"digest-unsubscribe:{message_id}")
    return f"digest unsubscribe: {len(senders)} senders, {len(missing)} numbers not on the list"


def offer_yes(said: str, sender: str, message_id: str, wa: WhatsApp, *, conn=None, calls=None, places=None,
              start=None, now=None, offer=None) -> str | None:
    """His yes to Marco's pending call offer: accept it once, build the brief, ask about any gap before dialing,
    then place that one call and report how it went. None when there is no pending offer or the words are not a yes
    (Owner 2026-10-31: "Yes to his offer calls"). ``offer`` is the exact one a yes was already matched to."""
    import threading

    from hiremarco.calls import CallError, Calls, off_brief
    from hiremarco.calls import brief as briefs
    from hiremarco.calls import offers
    from hiremarco.critic import Critic

    conn = conn or offers.connect()
    reply = lambda text, tag: wa.send_text(sender, text, idempotency_key=f"{tag}:{message_id}")  # noqa: E731
    answered = offer if offer is not None and offer.status == "questions" else \
        (None if offer is not None else offers.asking(conn, now))
    if answered is not None:  # his one reply to the fallback questions: it goes into the brief, then the call
        offer = offers.record_fallbacks(conn, answered, said)
    elif offer is None:
        if not AFFIRM.search((said or "").strip()):
            return None
        offer = offers.pending(conn, now)
        if offer is None or offer.kind != "table":  # a reply or a heads-up has its own words (email_offer_words)
            return None
    if not message_id.startswith("booth-"):  # a spoken yes has no message of his to quote
        offers.set_asked(conn, offer.id, message_id)
    place = offers.place_for(offer, places)
    if place is None:
        offers.set_status(conn, offer.id, "no such place")
        reply("I can't find that place in your list anymore, so I'm holding off on the call.", "offer-place")
        return f"offer {offer.id}: place {offer.place_id} not in the places file"
    if answered is None:  # the questions come first, so one reply can fill what the profile leaves open
        offers.ask_fallbacks(conn, offer)
        offers.add_message(conn, offer.id, reply(offers.questions_text(offer), "offer-questions"))
        return f"offer {offer.id}: asked the fallback questions before dialing"
    try:
        full = briefs.build("reservation", offers.brief_for(offer))
    except briefs.BriefIncomplete as gap:
        reply(offers.ask_for_gaps(gap), "offer-gap")
        return f"offer {offer.id}: asked for {', '.join(gap.missing)} before dialing"
    taken = offers.accept(conn, offer, now)
    if taken is None:
        return f"offer {offer.id}: already taken"
    calls = calls or Calls()
    # the phone goes on before the dial, on the message that sets it off; a spoken yes has none, so the one that asked
    dialed_by = offers.get(conn, offer.id).asked_id if message_id.startswith("booth-") else message_id
    phone_on = reactions.react(wa, sender, dialed_by, reactions.CALLING)
    try:
        placed = calls.place("+" + place.phone.lstrip("+"), "book a table", f"offer {offer.id} to call {place.name}",
                             critic=Critic(), brief=full, kind="reservation", offer=taken.evidence(place),
                             idempotency_key=f"offer-call:{offer.id}")
    except Exception as held:
        if phone_on:  # no call is going, so the phone doesn't stay up
            reactions.take_off(wa, sender, dialed_by)
        if not isinstance(held, (gate.Refused, CallError)):
            raise
        offers.set_status(conn, offer.id, "held")
        # the reason stays in the log line; he hears what happened and the one thing to decide
        reply(f"I couldn't get the call to {place.name} going just now. Want me to try again?", "offer-held")
        return f"offer {offer.id}: held: {getattr(held, 'reason', held)}"
    offers.set_status(conn, offer.id, "called")
    reply(f"Calling {place.name} now. I'll tell you how it goes.", "offer-calling")

    def report() -> None:
        import json as _json

        offers.wait_for_result(lambda: calls._json("GET", f"/convai/conversations/{placed['conversation_id']}"))
        # saved and logged like `marco call transcript`: the cost, and what the brief did not cover, for next time
        data = _json.loads(calls.transcript(placed["conversation_id"]).read_text())
        asked = offers.get(conn, offer.id).asked_id  # the result lands long after: it quotes the yes that started it
        wa.send_text(sender, offers.result_text(place, taken, data, off_brief(data)),
                     idempotency_key=f"offer-result:{offer.id}", **({"quote": asked} if asked else {}))
        if data.get("status") == "done" and offers.outcome(data)[0] == "booked":
            reactions.react(wa, sender, asked, reactions.RESULT)
        if data.get("status") == "done" and offers.outcome(data)[0] in ("booked", "waitlisted"):
            # the proof comes from the inbox: a task in the ledger, matched by meaning against each new email
            from hiremarco import inbox
            from hiremarco.calls import brief as _briefs

            collected = (data.get("analysis") or {}).get("data_collection_results") or {}
            got = lambda key: _briefs.unspell(str((collected.get(key) or {}).get("value") or "").strip())  # noqa: E731
            inbox.open_task(inbox.connect(), f"offer-{offer.id}", f"{place.name} booking",
                            {"place": place.name, "agreed": got("agreed"), "next_step": got("next_step"),
                             "name": _briefs.load_profile().get("full_name", "")}, asked_id=asked)

    (start or (lambda f: threading.Thread(target=f, daemon=True).start()))(report)
    return f"offer {offer.id}: calling {place.name}, conversation {placed['conversation_id']}"


OFFER_TOKEN = "HIREMARCO_OFFER_TOKEN"
NEVER_MIND = re.compile(r"^(?:no|nope|nah|never ?mind|skip it|forget it|don'?t|not now)\b", re.I)


def email_offer_words(said: str, sender: str, message_id: str, wa: WhatsApp, *, conn=None, calendar=None, mail=None,
                      client=None, outbox_conn=None, now=None, offer=None) -> str | None:
    """His words on an offer that came from an email and is no table: what to say on a reply he said yes to, or his yes
    itself. None sends his words on as usual (a table's yes goes to ``offer_yes``). Sent only on his "send" for the
    preview, by the outbox; a draft isn't a send. A failure tells him nothing went out."""
    from datetime import datetime, timezone

    from hiremarco.calls import offers
    from hiremarco.inbox import outbox
    from hiremarco.joblog import JobLog, JobRow

    conn = conn or offers.connect()
    when = now or datetime.now(timezone.utc)
    said = (said or "").strip()
    reply = lambda text, tag: wa.send_text(sender, text, idempotency_key=f"{tag}:{message_id}")  # noqa: E731
    waiting = (offer if offer.status == "what to say" else None) if offer is not None else offers.waiting_for_words(conn, when)
    if waiting is not None:
        if NEVER_MIND.match(said):
            offers.set_status(conn, waiting.id, "declined")
            reply("Okay, I'll leave that one with you.", "email-offer-off")
            return f"offer {waiting.id}: reply declined"
        offers.set_status(conn, waiting.id, "drafting")
        try:
            done = outbox.draft_reply_to(waiting.source_id, said, sender, message_id, wa, conn=outbox_conn, mail=mail,
                                         client=client, days=_open_days(calendar, when))
        except gate.Refused:
            raise
        except Exception as exc:
            JobLog().append(JobRow(job="email-offer", ok=False, note=f"{waiting.offer_key}: {type(exc).__name__}"))
            offers.set_status(conn, waiting.id, "draft failed")
            reply("I couldn't write that one just now. Nothing was sent.", "email-offer-failed")
            return f"offer {waiting.id}: draft failed, {type(exc).__name__}"
        offers.set_status(conn, waiting.id, "drafted")
        return f"offer {waiting.id}: {done}"
    if offer is None:
        if not AFFIRM.search(said):
            return None
        offer = offers.pending(conn, when)
    if offer is None or offer.kind == "table":
        return None
    if offer.kind == "heads_up":
        offers.set_status(conn, offer.id, "answered")
        reply("What do you need on it?", "email-offer-help")
        return f"offer {offer.id}: asked what he needs"
    offers.ask_what_to_say(conn, offer, when)
    if not message_id.startswith("booth-"):
        offers.set_asked(conn, offer.id, message_id)
    days = _open_days(calendar, when)
    offers.add_message(conn, offer.id, reply("What should I say?" + (f" You're open {days_span(days)}." if days else ""),
                                             "email-offer-say"))
    return f"offer {offer.id}: asked what to say, {len(days)} open days offered"


def _open_days(calendar, when) -> list[date]:
    """Days only, read on this machine after his yes (R3): the other machine has no calendar and needs none."""
    from hiremarco.calls import offers

    try:
        if calendar is None:
            from hiremarco.google.calendar import Calendar

            calendar = Calendar()
    except Exception:
        return []
    return offers.open_days(calendar, when)


def offer_yes_by_voice(offer, sender: str, wa: WhatsApp | None = None, *, conn=None, calls=None, places=None, start=None,
                       calendar=None, now=None) -> str | None:
    """A spoken yes in the booth to the exact offer he was texted: the same steps as his yes on WhatsApp, the same
    what-if questions by text; he hears "on it" in the booth and the rest comes by text."""
    from hiremarco.calls import offers

    if offer.kind == "table" and not offers.voice_yes_on():
        return f"offer {offer.id}: a spoken yes can't lead to a call until RULES.md says so"
    wa, conn = wa or WhatsApp(), conn or offers.connect()
    offer = offers.set_yes_by(conn, offer.id, "booth")
    message_id = f"booth-yes-{offer.id}"
    try:
        if offer.kind == "table":
            return offer_yes("yes", sender, message_id, wa, conn=conn, calls=calls, places=places, start=start, now=now,
                             offer=offer)
        return email_offer_words("yes", sender, message_id, wa, conn=conn, calendar=calendar, now=now, offer=offer)
    except gate.Refused as held:
        from hiremarco.joblog import JobLog, JobRow

        JobLog().append(JobRow(job="email-offer", ok=False, note=f"{offer.offer_key}: voice yes held: {held.reason}"))
        return f"offer {offer.id}: voice yes held"


def _text_offer(offer, sender: str, wa: WhatsApp, conn, now=None):
    """Send one offer's text and start its yes window. A refusal (WhatsApp's 24 hours, a hiccup) keeps it held."""
    from hiremarco.calls import offers
    from hiremarco.joblog import JobLog, JobRow
    from hiremarco.whatsapp.client import WhatsAppError

    try:
        sent = wa.send_text(sender, offer.message, idempotency_key=f"email-offer:{offer.offer_key}", now=now)
    except (gate.Refused, WhatsAppError) as held:
        JobLog().append(JobRow(job="email-offer", ok=False, note=f"{offer.offer_key}: held, {type(held).__name__}"))
        return None
    offers.add_message(conn, offer.id, sent)
    return offers.mark_texted(conn, offer, now)


def _ask_again(offer, reply, conn, when) -> str:
    """A yes on an old question acts on nothing. It asks again, so "say the word" is true and that word has its own yes
    window, unless the day has passed or there was nothing to accept."""
    from hiremarco.calls import offers

    still = {"table": "Still want me to book it?", "reply": "Still want me to write back?"}.get(offer.kind)
    gone = offer.kind == "table" and offer.day and offer.day < when.astimezone(offers.MIAMI).date().isoformat()
    if still is None or gone or offer.status not in ("pending", "replaced", "questions", "what to say"):
        reply("That was a while back, so I held off. Let me know if there's something you need on it.", "quote-old")
        return f"offer {offer.id}: quoted after its window, nothing done"
    sent = reply(f"That was a while back, so I held off. {still} Just say the word.", "quote-old")
    offers.add_message(conn, offer.id, sent)
    offers.mark_texted(conn, offer, when)
    return f"offer {offer.id}: quoted after its window, nothing done, asked again"


def quoted_reply(said: str, sender: str, message_id: str, quoted: str, wa: WhatsApp, *, conn=None, calls=None, places=None,
                 start=None, calendar=None, mail=None, client=None, outbox_conn=None, now=None) -> str | None:
    """His reply that quotes one of Marco's messages about an offer goes to exactly that offer, and never to another: a
    yes, a no, or his answer to what that offer asked. A yes on one that is closed, or on a message from before these were
    kept, is told so and acts on nothing. None sends his words on, to the brain, which sees what he quoted."""
    from datetime import datetime, timezone

    from hiremarco.calls import offers
    from hiremarco.whatsapp.memory import quoted_words

    conn, when = conn or offers.connect(), now or datetime.now(timezone.utc)
    said = (said or "").strip()
    yes, no = AFFIRM.search(said), NEVER_MIND.match(said)
    reply = lambda text, tag: wa.send_text(sender, text, idempotency_key=f"{tag}:{message_id}")  # noqa: E731
    offer = offers.by_message(conn, quoted)
    if offer is None:
        if yes and quoted_words(wa.conn, quoted) is None:
            reply("Not sure which one you mean. Can you tell me what you'd like me to do?", "quote-unknown")
            return "quoted a message from before they were kept: nothing done"
        return None
    if offers.taken(offer):
        if yes or no:
            reply("Already took care of that one.", "quote-taken")
            return f"offer {offer.id}: quoted, already {offer.status}"
        return None
    if not offers.still_open(offer, when):
        if yes or no:
            if yes:
                return _ask_again(offer, reply, conn, when)
            reply("Okay, I'll leave that one with you.", "quote-off")
            return f"offer {offer.id}: quoted no after its window"
        return None
    answering = offer.status in ("questions", "what to say")
    if no and not answering:
        offers.set_status(conn, offer.id, "declined")
        reply("Okay, I'll leave that one with you.", "quote-off")
        return f"offer {offer.id}: declined by quote"
    if not (yes or answering):
        return None
    offer = offers.reopen(conn, offer)
    if offer.kind == "table":
        return offer_yes(said, sender, message_id, wa, conn=conn, calls=calls, places=places, start=start, now=when, offer=offer)
    return email_offer_words(said, sender, message_id, wa, conn=conn, calendar=calendar, mail=mail, client=client,
                             outbox_conn=outbox_conn, now=when, offer=offer)


def receive_offer(raw: bytes, headers, *, wa: WhatsApp | None = None, conn=None, places=None, now=None,
                  rules_path=None) -> tuple[int, dict]:
    """The reader's handoff: checked, recorded once, texted to the Owner only. (HTTP status, what to answer). Accepting
    it is the reader's "delivered"; what becomes of the text afterwards is this side's to log and to hold."""
    import json
    from datetime import datetime, timezone

    from hiremarco import offer as reader
    from hiremarco import rules
    from hiremarco.calls import offers
    from hiremarco.gate.kill import kill_switch_on

    when = now or datetime.now(timezone.utc)
    stamp, key = headers.get(reader.HEADER_TIME, ""), headers.get(reader.HEADER_OFFER, "")
    fault = reader.signature_fault(config.get(OFFER_TOKEN) or "", stamp, key, raw, headers.get(reader.HEADER_SIGNATURE, ""),
                                   when.timestamp())
    if fault:
        return 401, {"status": fault}
    try:
        data = json.loads(raw)
    except ValueError:
        return 400, {"status": "bad json"}
    if data.get("offer_id") != key or data.get("kind") not in ("table", "reply", "heads_up"):
        return 400, {"status": "bad offer"}
    if kill_switch_on():
        return 503, {"status": "stopped"}
    owner = config.require("OWNER_WHATSAPP")  # the one recipient, whatever a body says
    if not rules.allowed("email-offers", owner, path=rules_path):
        return 403, {"status": "no send switch"}
    conn = conn or offers.connect()
    kind, line = reader.offer_line(data, offers.load_places() if places is None else places)
    if not reader.plain_enough(line):
        line = f"Heads up. {reader.name_of(data.get('who', ''))} emailed. Let me know if I can help."
        kind = "heads_up"
        line = line if reader.plain_enough(line) else "Heads up. An email came in that needs you. Let me know if I can help."
    offer = offers.record_email_offer(conn, key, kind, line, data, when)
    if offer is None:
        return 200, {"status": "duplicate"}
    sent = _text_offer(offer, owner, wa or WhatsApp(), conn, when)
    return 200, {"status": "sent" if sent is not None else "held"}


def send_held_offers(sender: str, wa: WhatsApp | None = None, *, conn=None, now=None) -> int:
    """After his text opens WhatsApp's window: what was held goes out if it is under a day old; older is dropped and
    logged by id. Run after his message is handled, so his words can't be read as a yes to something he hasn't seen."""
    from datetime import datetime, timezone

    from hiremarco.calls import offers
    from hiremarco.joblog import JobLog, JobRow

    conn, when, sent = conn or offers.connect(), now or datetime.now(timezone.utc), 0
    for offer in offers.held(conn):
        if when - offer.offered_at > offers.HOLD_MAX:
            offers.set_status(conn, offer.id, "dropped")
            JobLog().append(JobRow(job="email-offer", ok=False, note=f"{offer.offer_key}: dropped after a day held"))
            continue
        wa = wa or WhatsApp()
        sent += _text_offer(offer, sender, wa, conn, when) is not None
    return sent


def with_held_offers(handler):
    def run(message):
        try:
            return handler(message)
        finally:
            try:
                send_held_offers(message.sender)
            except Exception as exc:  # his own message was already handled; the log says what broke
                Trace("held offers").done(f"error: {type(exc).__name__}")
    return run


def make_offer_route():
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def route(request: Request):
        raw, headers = await request.body(), request.headers
        status, answer = await run_in_threadpool(awake_while(lambda _: receive_offer(raw, headers)), None)
        Trace(f"offer: {headers.get('x-marco-offer', '')[:40]}").done(f"{status} {answer.get('status')}")
        return JSONResponse(answer, status_code=status)

    return route


SETTLE_S = 20.0  # a photo with no words waits this long for the words he sends after it


def dress_me(photo, said: str, sender: str, message_id: str, wa: WhatsApp, marco=None,
             waiting_row: int | None = None) -> str:
    """"Marco, dress me": what SAM sees, then the board of three looks, both sent to him (Owner 2026-11-01)."""
    from hiremarco import dress
    from hiremarco.sam import SamError

    def send(picture: bytes, caption: str, step: str) -> None:
        wa.send_image(sender, picture, caption, idempotency_key=f"dress-{step}:{message_id}", mime="image/jpeg")

    plain = lambda text, tag: wa.send_text(sender, text, idempotency_key=f"dress-{tag}:{message_id}")  # noqa: E731
    reactions.react(wa, sender, message_id, reactions.ON_IT)
    try:
        done = dress.dress(photo.path, said, conn=wa.conn, send=send, client=getattr(marco, "client", None),
                           film=dress.film_dir(), waiting_row=waiting_row)
    except dress.NoClothesFound:
        plain("I couldn't make out any clothes in that one. Lay them out flat and send me another?", "none")
        return "dress me: no clothing found in the photo"
    except dress.LooksError as bad:
        plain("I couldn't build three looks from that one. Send it again?", "looks")
        return f"dress me: looks rejected: {bad}"
    except SamError as failed:
        plain("I couldn't read the photo just now. Send it again?", "sam")
        return f"dress me: {failed}"
    reactions.react(wa, sender, message_id, reactions.RESULT)
    thrown = f"; threw out pieces {done.looks.dropped}" if done.looks.dropped else ""
    said_back = (f"dress me: {len(done.pieces)} pieces, what SAM sees and the board sent, {done.looks.recommend} "
                 f"recommended{thrown}")
    stream.say(stream.MARCO, said_back)
    return said_back


def selects_me(said: str, sender: str, message_id: str, wa: WhatsApp, marco=None, sleep=None) -> str:
    """"Marco, pick my selects": once the burst has landed, what SAM sees across the shoot, then his three, one picture
    at a time (Owner 2026-11-01)."""
    import time

    from hiremarco import dress, selects
    from hiremarco.sam import SamError
    from hiremarco.whatsapp import photos

    def send(picture: bytes | None, text: str, step: str) -> None:
        key = f"selects-{step}:{message_id}"
        if picture is None:
            wa.send_text(sender, text, idempotency_key=key)
        else:
            wa.send_image(sender, picture, text, idempotency_key=key, mime="image/jpeg")

    plain = lambda text, tag: wa.send_text(sender, text, idempotency_key=f"selects-{tag}:{message_id}")  # noqa: E731
    photos.settled(wa.conn, sender, sleep=sleep)
    if selects.running(wa.conn):
        return "selects: already going through them"
    frames, total = selects.shoot(wa.conn)
    if not frames:
        plain("I don't have any new frames from you. Send them over and ask me again.", "none")
        return "selects: no frames to pick from"
    row = selects.begin(wa.conn, frames[-1].id, len(frames))
    reactions.react(wa, sender, message_id, reactions.ON_IT)
    noted = f"You sent {total}, so I'm working from the last {selects.CAP}. " if total > selects.CAP else ""
    try:
        done = selects.run([(f.path, f.original) for f in frames], said, conn=wa.conn, send=send,
                           client=getattr(marco, "client", None), film=dress.film_dir(), noted=noted,
                           pause=sleep or time.sleep)
    except selects.NoOneFound:
        selects.finish(wa.conn, row, "failed")
        plain("I couldn't find you in any of those frames. Send me a few more?", "nobody")
        return f"selects: nobody found in {len(frames)} frames"
    except selects.PickError as bad:
        selects.finish(wa.conn, row, "failed")
        plain("I couldn't settle on my three just now. Ask me again?", "pick")
        return f"selects: picks rejected: {bad}"
    except SamError as failed:
        selects.finish(wa.conn, row, "failed")
        plain("I couldn't read the frames just now. Ask me again?", "sam")
        return f"selects: {failed}"
    except Exception:
        selects.finish(wa.conn, row, "failed")
        raise
    numbers = [n for n, _ in done.picks.picks]
    selects.finish(wa.conn, row, "done", numbers, str(done.folder))
    reactions.react(wa, sender, message_id, reactions.RESULT)
    notes = "".join(f"; {line}" for line in done.log)
    said_back = f"selects: {len(frames)} frames, picked {numbers} in {done.seconds['total']:.0f}s{notes}"
    stream.say(stream.MARCO, said_back, done.seconds["total"])
    return said_back


def handle(message: Inbound, *, marco: Marco | None = None, wa: WhatsApp | None = None,
           inbox: Path | None = None, listen=None, booth=None, running=None, settle=None) -> str:
    import time

    from hiremarco import dress, selects
    from hiremarco.whatsapp import photos
    from hiremarco.whatsapp.client import WhatsAppError

    wa = wa or WhatsApp()
    wa.answering = message.id  # when he has written since, the answer quotes what it answers
    booth, running = booth or ensure_booth, running or booth_running
    heard = message.text or f"[{message.kind}]"
    trace = Trace(f"heard: {heard[:60]}")
    try:
        if message.kind == "text" and message.text and not message.quoted:
            on_set = crew_words(message.text, message.sender, message.id, wa)
            if on_set is not None:
                return trace.done(on_set)
        wa.mark_read(message.id, typing=True)
        if message.kind == "text" and message.text and not message.quoted:
            moved = monitor_words(message.text, message.sender, message.id, wa)
            if moved is not None:
                return trace.done(moved)
        turns = history(wa.conn)  # the conversation before this message
        beat = save_beat(message, wa, inbox)
        if beat is not None:
            path, started = beat
            remember(wa.conn, "felix", f"[sent a beat: {path.name}] {message.caption or ''}")
            reactions.react(wa, message.sender, message.id, reactions.AUDIO)
            if started:
                wa.send_text(message.sender, "Got the beat. Setting up the session.", idempotency_key=f"beat:{message.id}")
                return trace.done(f"beat {path.name} received with its instruction; session started; {booth()}")
            wa.send_text(message.sender, f"Got the beat ({path.stem}). Want me to start a session with it?",
                         idempotency_key=f"beat:{message.id}")
            return trace.done(f"beat kept as {path.name}, waiting for his word")
        said, photo = message.text, None
        if message.kind == "image" and message.media_id:
            try:
                data, mime = wa.download_media(message.media_id)
                photo = photos.keep(wa.conn, data, message.id, message.caption,  # remembered in the conversation
                                    suffix=photos.suffix_of(message.filename, message.mime_type or mime))
            except (photos.Unreadable, WhatsAppError) as bad:
                photos.failed(wa.conn, message.id)
                # one line for the whole burst: the same key for ten minutes, and the gate lets one through
                wa.send_text(message.sender, "I can't open that one. Send your frames as JPEG?",
                             idempotency_key=f"photo-unreadable:{int(time.time()) // 600}")
                return trace.done(f"photo not kept: {bad}")
            said = message.caption.strip()
            trace.add(f"photo kept: {photo.path.name}")
            if dress.wants_dressing(said):
                return trace.done(dress_me(photo, said, message.sender, message.id, wa, marco))
            if selects.wants(said):
                return trace.done(selects_me(said, message.sender, message.id, wa, marco, sleep=settle))
            asked = dress.waiting(wa.conn) if not said else None
            if asked is not None:  # "dress me" came first; this is the photo it waited for
                return trace.done(dress_me(photo, asked[1], message.sender, message.id, wa, marco, asked[0]))
            if not said:  # his words may follow: give them a moment, and let that message take the photo
                # a frame sent as a document is slower to come than the next one is to follow: it gets the long wait
                waited = selects.QUIET_S if message.filename else SETTLE_S
                (settle or time.sleep)(waited)
                if photos.newer_from(wa.conn, message.sender, message.id):
                    return trace.done(f"photo {photo.path.name} kept; his next message says what it is for")
                if selects.taken(wa.conn, photo):
                    return trace.done(f"photo {photo.path.name} kept; the selects have it")
                if selects.burst(wa.conn) >= selects.BURST_MIN:  # one line when the burst is over, not one per frame
                    if waited < selects.QUIET_S:
                        (settle or time.sleep)(selects.QUIET_S - waited)
                        if photos.newer_from(wa.conn, message.sender, message.id):
                            return trace.done(f"photo {photo.path.name} kept; his next message says what it is for")
                        if selects.taken(wa.conn, photo):
                            return trace.done(f"photo {photo.path.name} kept; the selects have it")
                    count = len(selects.shoot(wa.conn)[0])
                    reactions.react(wa, message.sender, message.id, reactions.PHOTOS)  # once, on the shoot's last frame
                    wa.send_text(message.sender, f"Got {count} frames.", idempotency_key=f"burst:{message.id}")
                    return trace.done(f"burst: {count} frames, one acknowledgement")
        elif message.kind == "audio" and message.voice and message.media_id:
            said = voice_text(message, wa, listen)
            trace.add(f"voice note: {said[:60]}")
        elif message.kind == "document":  # not a beat and not a photo: a file; nothing to say but that it landed
            reactions.react_or_say(wa, message.sender, message.id, reactions.FILE, f"file:{message.id}")
            return trace.done("file received")
        elif message.kind != "text":
            return trace.done(f"{message.kind} noted, no handler yet")
        if photo is None:
            remember(wa.conn, "felix", said or "[an empty voice note]")
            if said:
                note_words(wa.conn, message.id, said)
            if dress.wants_dressing(said):
                photo = photos.wait_for(wa.conn, message.sender)  # it may still be downloading
                if photo is None:
                    dress.wait_for_photo(wa.conn, said)
                    wa.send_text(message.sender, "Send me a photo of the clothes laid out and I'll put three looks "
                                 "together.", idempotency_key=f"dress-photo:{message.id}")
                    return trace.done("dress me: waiting for the photo")
                return trace.done(dress_me(photo, said, message.sender, message.id, wa, marco))
            if selects.wants(said):
                return trace.done(selects_me(said, message.sender, message.id, wa, marco, sleep=settle))
            letter = dress.picked(said)
            if letter and dress.open_board(wa.conn) is not None:
                text, did = dress.lock_in(wa.conn, letter, client=getattr(marco, "client", None))
                wa.send_text(message.sender, text, idempotency_key=f"dress-pick:{message.id}")
                return trace.done(f"dress me: {did}")
            photo = photos.latest(wa.conn)  # a photo he sent in the last minutes goes with his words
            if photo is not None and selects.burst(wa.conn) >= selects.BURST_MIN and not selects.about_a_photo(said):
                photo = None  # "set up my session" between frames is about the session, not the last frame
        if message.kind == "image":
            said = said or "(he sent this photo without a word)"
        words = said and message.kind != "image"
        if words and message.quoted:  # he pointed at one message: the offers answer only for that one, below
            offered = quoted_reply(said, message.sender, message.id, message.quoted, wa)
        else:
            offered = email_offer_words(said, message.sender, message.id, wa) if words else None
        if offered is not None:
            if "draft shown" in offered:
                reactions.react(wa, message.sender, message.id, reactions.DRAFT)
            return trace.done(offered)
        dropped = digest_unsubscribe(said, message.sender, message.id, wa) if said and message.kind != "image" else None
        if dropped is not None:
            return trace.done(dropped)
        if said and message.kind != "image":
            written = email_words(said, message.sender, message.id, wa, **({"quoted": message.quoted} if message.quoted else {}))
            if written is not None:
                if "draft shown" in written:
                    reactions.react(wa, message.sender, message.id, reactions.DRAFT)
                return trace.done(written)
        called = offer_yes(said, message.sender, message.id, wa) if words and not message.quoted else None
        if called is not None:
            return trace.done(called)
        fresh = fresh_session(said, message.sender, message.id, wa, inbox, booth=booth) if words else None
        if fresh is not None:
            return trace.done(fresh)
        if said:
            try:
                marco = marco or Marco()
                earlier = earlier_words(wa.conn, message.id)
                state = {**context(wa.conn, inbox or _inbox(), running, said, getattr(wa, "rules_path", None)),
                         "his_earlier_messages": [{"ref": ref, "says": said_then} for ref, (_, said_then) in earlier.items()]}
                pointed = quoted_words(wa.conn, message.quoted) if message.quoted else None
                if pointed:
                    state["he_is_replying_to"] = {"from": pointed[0], "says": pointed[1]}
                decision = decide(marco, said, state, turns, instructions=ENGLISH, photo=photo)
                if decision.action == "reply" and promises_send(decision.reply):  # once more, told why
                    trace.add("brain promised a send on a reply; asked again")
                    decision = decide(marco, said, state, turns, photo=photo, instructions=f"{ENGLISH}\n\n"
                                      "Your last answer promised or reported a send with action reply, which sends "
                                      "nothing. Answer again: either pick the action that does it, or say plainly "
                                      "what you cannot do.")
            except gate.Refused:
                raise
            except Exception as exc:  # the brain is unreachable or answered off-schema: the fixed patterns answer
                trace.add(f"brain unavailable: {type(exc).__name__}")
            else:
                return trace.done(act(decision, message.sender, message.id, wa, inbox, booth=booth, earlier=earlier))
        if message.kind == "image":  # the brain could not be reached: Marco still looks at the photo
            text = photos.see(photo, message.caption, (marco or Marco()).client, instructions=ENGLISH)
            if not text:
                return trace.done("no reply: the model returned no text")
            wa.send_text(message.sender, text, idempotency_key=f"photo:{message.id}")
            return trace.done("answered the photo")
        started = instruction(said, message.sender, message.id, wa, inbox, booth=booth, running=running)
        if started is not None:
            return trace.done(started)
        if not said:
            return trace.done("nothing heard in the voice note")
        reply = (marco or Marco()).answer(said, job="whatsapp-reply", instructions=ENGLISH)
        if not reply.text.strip():  # Meta refuses an empty text; nothing is sent and the log says why
            return trace.done("no reply: the model returned no text")
        wa.send_text(message.sender, reply.text.strip(), idempotency_key=f"reply:{message.id}")
        return trace.done("replied")
    except gate.Refused as refused:
        return trace.done(f"held: {refused.reason}")
    except Exception as exc:  # the webhook must keep running; the log says what broke
        return trace.done(f"error: {type(exc).__name__}")
    finally:
        wa.answering = None


def admit_only(app, allowed: set[str]):
    """An ASGI wrapper: requests from any address not named are refused with 403 (D-0048)."""
    async def wrapped(scope, receive, send):
        if scope["type"] == "http" and (scope.get("client") or ("",))[0] not in allowed:
            await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"forbidden"})
            return
        await app(scope, receive, send)
    return wrapped


def awake_while(handler, hold=None):
    """The Mac stays awake from a message's arrival until its reply is sent: a dark wake lasts 45 to 96 s (live
    2026-10-30), shorter than a session setup (D-0048)."""
    import subprocess

    def run(message):
        keeper = (hold or (lambda: subprocess.Popen(["caffeinate", "-i"])))()
        try:
            return handler(message)
        finally:
            keeper.terminate()
    return run


def build_app(*, reply: bool = True):
    from starlette.routing import Route

    from hiremarco.master import share
    from hiremarco.relay import make_relay

    return make_app(
        awake_while(with_held_offers(handle)) if reply else listen_only,
        verify_token=config.require("WHATSAPP_VERIFY_TOKEN"),
        app_secret=config.require("WHATSAPP_APP_SECRET"),
        owner=config.require("OWNER_WHATSAPP"),
        conn_factory=gate.connect,
        extra_routes=[Route("/llm/v1/chat/completions", make_relay(), methods=["POST"]),
                      Route("/internal/offer", make_offer_route(), methods=["POST"]),
                      Route("/internal/booth", make_booth_route(), methods=["POST"]),
                      *share.routes()],   # a master to the phone by link: WhatsApp takes no WAV (Owner 2026-11-03)
    )

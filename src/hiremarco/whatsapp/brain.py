"""Marco's judgment on WhatsApp: every text Felix sends goes to his brain with the studio's real state and the
conversation so far, and he decides what to do.

Owner 2026-10-30, after "try again" was taken as a song title and "no" was answered blind: "He should know the
difference between an instruction and everything else." The brain picks one action and writes the reply; the code
carries the action out and reports what really happened, so Marco never says he did something he did not do. The
fixed patterns in ``server.instruction`` stay only as the fallback when the brain cannot be reached.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from hiremarco.whatsapp.memory import recall, when
from hiremarco.whatsapp.reactions import MODEL_PICKS

ACTIONS = ("reply", "start", "retry", "rename", "cancel", "master", "call")
CALL_FIELDS = ("who", "number", "purpose", "ask", "if_unavailable", "voicemail")
SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
        "title": {"type": "string"},
        "reply": {"type": "string"},
        "call": {"type": "object", "properties": {f: {"type": "string"} for f in CALL_FIELDS},
                 "required": list(CALL_FIELDS), "additionalProperties": False},
        "reaction": {"type": "string", "enum": ["", *MODEL_PICKS]},
        "quote": {"type": "string", "description": "the ref of one message in his_earlier_messages, else empty"},
        "remember": {"type": "array", "items": {"type": "string"}},
        "forget": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["action", "title", "reply", "call", "reaction", "quote", "remember", "forget"],
    "additionalProperties": False,
}
RULES = """You are answering Felix on WhatsApp. Each message you get carries the time, who Felix is (about_felix), \
what he has told you before that lasts (facts, each with the day he said it), the real state of his studio (read \
from his Mac a moment ago) and what he just said; the turns before it are your conversation, oldest first, with the \
time each was said. Use all of it: what he asked earlier, what you told him, what happened since, and what you know \
about him. When a fact bears on what he asks, use it and say when he told you ("Thursday you said...").

Decide one action, then write the text you send him.
- start: set up a Logic session with the beat he sent (studio.beat_sent). Put the song name in title if he gave one.
- retry: a setup failed or stalled (studio.last_setup_attempt) and he wants it tried again. When he fixes the name \
and also asks to set it up or try again, the action is retry, with the fixed name in title.
- rename: he is giving or correcting the song's title. title is required. To undo a wrong title, rename it back \
to the beat's file name without its extension.
- cancel: he does not want the waiting beat set up.
- master: he asks for the song to be mixed down, mastered, bounced, exported or sent to mix ("send it to mix", \
"master it", "bounce it", "print it"). The open session is printed as it stands and as a master, and both WAVs are \
texted to him; it takes minutes. Put any direction he gives about the sound in title ("louder", "warmer", "like X").
- call: phone someone for him (a person or a place). Choose it only when you have all of it from him: who, their \
full phone number as he sent it in this conversation, what to ask or arrange, and what to do if they can't or \
it can't be settled. Fill call: who (their name), number (the digits with the country code, +1 for a US number), \
purpose (finishes the sentence "I'm calling to ___ for Felix Gabriel.", such as "ask if you're free for dinner Saturday at \
8pm"), ask (what to ask or arrange, with every detail he gave), if_unavailable (what to do if they can't), \
voicemail (a short message to leave, or empty). If anything is missing, the action is reply and you ask for all \
of it in one message ("Sure. What's Lucie's number, and if Saturday doesn't work, should I ask when she's free?"). \
Never pull a number from memory: he sends it here. Your text for call is one short line that you're calling now; \
the code dials and texts him how it went.
- reply: everything else: a question, a status, chat, or when you are not sure what he wants.

What you can do (what_you_can_do, read from his rules a moment ago) is the whole list; anything not on it you \
cannot do from this chat yet. Be straight about it. When he asks for something you cannot do, say so plainly in \
your first answer and offer the closest thing on the list; never offer something off the list. When he pushes \
back on what you can or cannot do, check the list again and stay with it: never agree just to please him, and \
never change your answer back and forth. If the list says you can, do it.

Choose start, retry, rename, cancel, master or call only when his words, read with the conversation, clearly ask for it. A short \
reaction ("no", "wait", "what?", "try again") is never a song title. When an instruction is unclear, ask one short \
question with reply. For a status, answer from studio, never from memory.

You are his COO: never mention anything under the hood. No names of tools, models, services or parts of the system \
(no critic, gate, relay, switch, brief, webhook, ElevenLabs, Twilio, Muse), no error text. Say in plain words what \
happened and what you will do or need from him.

The text: one or two short sentences, in English unless he asks for another language. The text claims only what \
your action does: with reply, nothing changes, so never say you renamed, dropped, started or retried anything. \
A reply never promises or reports a send: no "I'll text her", "sending it now", "it's going out", "I sent it", \
"calling now". The only thing that happens after a reply is that he reads it. Never \
say something is done or ready unless studio shows it. After start or retry, say you're on it; the booth texts him when the session is \
ready. If the last setup failed, tell him why in plain words and what you need from him, if anything. Leave title \
empty unless the action is start, retry or rename. Leave every field of call empty unless the action is call.

Reactions. You never type an emoji in the text. You can react to his message with one of these names, or leave reaction \
empty; most messages get none: noted (FYI, nothing to do, no reply needed), deal (he thanked you or agreed to a plan), \
audio (a note about the audio, the mix or a session), purchase (he mentions something to buy or that he bought; it never \
means you ordered it), date (he gives a date to keep in mind; it never means it is on his calendar), did_it (he says he \
did his part), money (money came in), big_win (a rare big win), laugh (his joke landed; laugh, don't joke back). \
A reaction replaces the text only when nothing needs saying: then leave reply empty, with action reply, and never add \
"noted" or "you're welcome". If he asked something, or you have anything to say or ask, write it in reply. Only one reaction.

If he_is_replying_to is there, he quoted that message: his words are about it, not about the latest thing said.

Quoting. Leave quote empty. Fill it only when your text asks about one specific earlier message of his, from \
his_earlier_messages, and he would not know which you mean; then give that message's ref. Never for his latest message.

Memory. remember: anything lasting he states in this message, each as one short sentence in his words, kept \
exactly as he meant it: a preference, a plan, a fact about his music, his people, his schedule. Not the beat he \
just sent, not a one-off instruction, not a question, never your guess; most messages give an empty list. forget: \
when he asks you to forget or drop something, the words of the fact to forget; otherwise empty. When he asks what \
you remember or know about him, answer from about_felix and facts, listing them plainly; if facts is empty, say so."""


@dataclass
class Decision:
    action: str
    title: str
    reply: str
    remember: list[str] = field(default_factory=list)
    forget: list[str] = field(default_factory=list)
    reaction: str = ""  # one of MODEL_PICKS by name, or none
    quote: str = ""     # the ref of the earlier message of his this text asks about, or none
    call: dict[str, str] = field(default_factory=dict)  # who, number, purpose, ask, if_unavailable, voicemail


def studio(inbox: Path, running: Callable[[], bool]) -> dict:
    """The state the brain reads: the beat he sent, the beat waiting for the booth, the last session set up, the
    booth's last attempt and its result, and whether the booth is running."""
    from hiremarco.studio.beat_in import last_loaded, last_setup, latest_received, pending, requested_name

    def beat(path: Path | None) -> dict | None:
        return None if path is None else {"file": path.name, "title": requested_name(path) or ""}

    waiting = pending(inbox)
    attempt = last_setup(inbox)
    if attempt.get("ts"):
        attempt = {**attempt, "ts": when(datetime.fromisoformat(attempt["ts"]))}
    return {
        "beat_sent": beat(latest_received(inbox)),
        "beat_waiting_for_the_booth": beat(waiting[-1]) if waiting else None,
        "last_session_set_up": beat(last_loaded(inbox)),
        "last_setup_attempt": attempt or None,
        "booth_running": running(),
    }


def about_felix() -> str:
    """Who Felix is, in his own file (HIREMARCO_PROFILE, a short markdown file he edits), or the one line we start
    with."""
    from hiremarco import config

    from hiremarco.style import OWNER_NAME_RULE

    path = config.get("HIREMARCO_PROFILE")
    if path:
        try:
            return Path(path).read_text().strip() + "\n\n" + OWNER_NAME_RULE
        except OSError:
            pass
    return "Felix is a singer and producer in Miami. " + OWNER_NAME_RULE


def abilities(rules_path: Path | None = None, today=None) -> dict:
    """What Marco can and cannot do from this chat, read from the live send switches (Owner 2026-11-03, after he
    told Felix calls were not live, then that they were, then promised a text he had no way to send)."""
    from datetime import date

    from hiremarco import rules

    today = today or date.today()
    on = {(s.tool, s.destination) for s in rules.switches(rules_path) if s.until >= today}
    can = ["set up a Logic session with the beat he sent, try a failed setup again, name the song, or drop the "
           "waiting beat (start, retry, rename, cancel)",
           "mix down, master and bounce the open session and text him both WAVs (master)",
           "remember what he tells you, and forget what he asks you to",
           "move his studio speakers when he says exactly \"lower it\", \"turn it up\", \"turn it down a lot\" or \"set it to -50\" as the whole message (handled before you see it: a slow fade, never above -40); when he asks about the speakers in other words, tell him to say one of those"]
    if ("calls", "named") in on:
        can.append("phone a person or a place for him and text him how it went (call), once he has sent their full "
                   "number here and said what to ask and what to do if they can't")
    cannot = ["text, WhatsApp or iMessage anyone but Felix: you write only to him",
              "phone anyone whose number he has not sent in this conversation" if ("calls", "named") in on
              else "phone anyone",
              "send an email from here: an email goes only when he asks for it by name and says send to the "
              "draft he is shown",
              "put anything on his calendar, buy anything, or pay anyone"]
    return {"can": can, "cannot_yet": cannot}


def context(conn, inbox: Path, running: Callable[[], bool], said: str, rules_path: Path | None = None) -> dict:
    """Everything the brain reads beside the conversation: who he is, what he told you, the studio now, and what
    he can ask of you from here."""
    from hiremarco.whatsapp.facts import block

    return {"about_felix": about_felix(), "facts": block(conn, said), "studio": studio(inbox, running),
            "what_you_can_do": abilities(rules_path)}


def history(conn, limit: int = 40) -> list[dict]:
    """The conversation as chat turns, each with the time it was said."""
    return [{"role": "user" if who == "felix" else "assistant", "content": f"[{when(ts)}] {text}"}
            for ts, who, text in recall(conn, limit)]


def decide(marco, said: str, state: dict, turns: list[dict], *, instructions: str = "",
           now: datetime | None = None, photo=None) -> Decision:
    """One brain call. Raises when the brain cannot be reached or answers outside the schema. ``photo`` is his last
    photo when he sent it in the last few minutes: the brain sees it beside his words (Owner 2026-11-01)."""
    from hiremarco.sam import data_url
    from hiremarco.whatsapp.photos import attached

    state = state if "studio" in state else {"studio": state}
    seen = {"photo_attached": attached(photo)} if photo is not None else {}
    asked = json.dumps({"now": when(now or datetime.now(timezone.utc)), **state, **seen, "felix_says": said},
                       ensure_ascii=False)
    # live 2026-10-30: at 1500 tokens a "No" was all thinking and no answer; low thinking used 995 of 4000
    reply = marco.converse(turns, asked, instructions=f"{RULES}\n\n{instructions}".strip(), job="whatsapp-brain",
                           max_completion_tokens=4000, reasoning_effort="low",
                           image_url=data_url(photo.jpeg(), "image/jpeg") if photo is not None else None,
                           response_format={"type": "json_schema",
                                            "json_schema": {"name": "decision", "schema": SCHEMA, "strict": True}})
    data = json.loads(reply.text)
    reaction = data.get("reaction") if data.get("reaction") in MODEL_PICKS else ""  # anything else is no reaction
    silent = data.get("action") == "reply" and reaction  # only a plain reply can be the reaction alone
    if data.get("action") not in ACTIONS or not (str(data.get("reply", "")).strip() or silent):
        raise ValueError(f"the brain answered outside the schema: {str(data)[:80]}")
    call = data.get("call") if isinstance(data.get("call"), dict) else {}
    return Decision(data["action"], str(data.get("title") or "").strip(), str(data.get("reply", "")).strip(),
                    [str(f).strip() for f in data.get("remember") or [] if str(f).strip()][:3],
                    [str(f).strip() for f in data.get("forget") or [] if str(f).strip()][:3], reaction,
                    str(data.get("quote") or "").strip(),
                    {f: " ".join(str(call.get(f) or "").split()) for f in CALL_FIELDS} if data["action"] == "call" else {})

"""The call relay: Muse Spark as the brain of the voice agent on the phone.

ElevenLabs places the call and handles listening and speaking; for thinking
it calls an OpenAI-style endpoint. That endpoint is this relay, on the Mac,
reached through the tunnel. It checks ElevenLabs' bearer token against
RELAY_TOKEN, runs the gate's model check (kill switch, daily cap), pins the
model to Muse Spark whatever the request says, forwards to the Meta Model
API with the Mac's own key, streams the answer back, and logs the cost. The
Meta key never leaves this machine.

On a call (live 2026-10-31) three things are the relay's, not the model's: Marco's
first reply is the opening line from the prompt, word for word and with no model
call, so the recording notice is always the first thing said; every turn asks for
minimal reasoning and few tokens, because turns of 3 to 5 s left the callee saying
"Hello?" and once made ElevenLabs give up; audio tags such as "[happy]" are
taken out of what Marco says; and a word the profile respells (``say_as``, a
name the voice read in the wrong language) is swapped for its respelling in
speech, while spelling it out letter by letter is left alone.
"""

from __future__ import annotations

import hmac
import json
import re
import time
from collections.abc import AsyncIterator

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from hiremarco import config, gate
from hiremarco.calls import brief as briefs
from hiremarco.joblog import JobLog, JobRow
from hiremarco.meta.client import BASE_URL, DEFAULT_MODEL
from hiremarco.meta.pricing import cost_usd

TENANT = "owner"
CALL_MODEL = DEFAULT_MODEL
ALLOWED_FIELDS = {"messages", "stream", "temperature", "tools", "tool_choice", "max_completion_tokens",
                  "max_tokens", "response_format", "stream_options"}
CALL_REASONING = "minimal"
CALL_MAX_TOKENS = 300
# The calls prompt carries this line; the relay speaks what follows it as Marco's first reply.
OPENING_MARK = "Your first words, exactly:"
OPENING_LINE = re.compile(re.escape(OPENING_MARK) + r"\s*(.+)")
TAG = re.compile(r"\s?\[[A-Za-z][A-Za-z ,'-]{0,24}\]")
# A sentence narrating what he is doing is never spoken (live 2026-10-31: "Voicemail detected, I'll leave the
# message." went into a third party's voicemail). Dashes are spoken as commas.
NARRATION = re.compile(r"voicemail detected|leave (a|the|your) message|wrap(ping)? up the call|(end|ending|hang|hanging) "
                       r"(up )?the call|i'?ll (end|hang up)|call (has )?ended|"
                       # Ava test 2: "I'll press one to reach reservations", "I'll wait on hold for the host"
                       r"i'?ll (press|wait|hold)\b|let me (press|wait)\b|pressing (one|two|three|four|\d)|"
                       r"(wait|waiting) on hold", re.I)
# Text goes out a clause at a time, so the first words leave as soon as a clause is whole and a narrating clause can
# still be dropped before any of it is said.
CLAUSE_END = re.compile(r"[.!?,;](\s|$)")
# A recorded voicemail greeting, as opposed to an automated assistant that talks back (live 2026-10-31: a carrier
# voicemail answered; an AI receptionist answers some restaurants and must be talked to, not left a message).
VOICEMAIL = re.compile(r"voice ?mail|mailbox|(leave|record) (a |your )?message|(after|at) the (tone|beep)|"
                       r"(is|are) not available|isn'?t available|unavailable|finished recording", re.I)
GREETING_END = re.compile(r"(after|at) the (tone|beep)|record your message|finished recording|leave (a |your )?message",
                          re.I)
INTERACTIVE = re.compile(r"press \d|how (can|may) i help|what can i do for you|how can i assist|"
                         r"\?|reservation|this is .{0,30}(assistant|virtual|ai)\b", re.I)


def voicemail_action(messages: list[dict], tools: list[dict] | None) -> str | None:
    """The tool the relay calls itself on a voicemail, or None for anything that may be a person or an assistant.

    While the greeting plays: skip_turn, so nothing is said over it. At its end ("after the tone"), or when the
    greeting was already waited out once: voicemail_detection, which leaves the message and hangs up.
    """
    names = {((t or {}).get("function") or {}).get("name") for t in tools or []}
    heard = [str(m.get("content") or "") for m in messages if m.get("role") == "user"]
    if not heard or not VOICEMAIL.search(heard[-1]) or any(INTERACTIVE.search(h) for h in heard):
        return None
    waited = any(m.get("role") == "tool" or any(((c.get("function") or {}).get("name") == "skip_turn")
                                                 for c in (m.get("tool_calls") or []))
                 for m in messages)
    if (GREETING_END.search(heard[-1]) or waited) and "voicemail_detection" in names:
        return "voicemail_detection"
    return "skip_turn" if "skip_turn" in names else None


def _tool_call(name: str, stream: bool) -> Response:
    args = json.dumps({"reason": "recorded voicemail greeting"} if name == "voicemail_detection" else {})
    call = {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": args}}
    if not stream:
        return JSONResponse({"object": "chat.completion", "model": CALL_MODEL, "choices": [
            {"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [call]},
             "finish_reason": "tool_calls"}]})

    async def chunks() -> AsyncIterator[bytes]:
        body = {"object": "chat.completion.chunk", "model": CALL_MODEL, "choices": [
            {"index": 0, "delta": {"role": "assistant", "tool_calls": [{"index": 0, **call}]}, "finish_reason": None}]}
        yield f"data: {json.dumps(body)}\n\n".encode()
        done = {"object": "chat.completion.chunk", "model": CALL_MODEL,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}
        yield f"data: {json.dumps(done)}\n\n".encode()
        yield b"data: [DONE]\n\n"
    return StreamingResponse(chunks(), media_type="text/event-stream")


# Owner 2026-10-31: his "mm-hm" sounded weird on a call, and "One sec." too, so neither is ever spoken.
HUM = re.compile(r"\b(m+-?h+m+|uh-huh|one sec(ond)?)\b[.,!]?\s*", re.I)


def unnarrate(text: str) -> str:
    text = HUM.sub("", re.sub(r"\s*[\u2014\u2013]\s*", ", ", text))
    return " ".join(p for p in re.split(r"(?<=[.!?,;])\s+", text) if not NARRATION.search(p))


RESAY_LIMIT = 2


def opening_for(messages: list[dict]) -> str | None:
    """The opening line, said by the relay with no model call: on the first turn of a call, and again (up to
    RESAY_LIMIT times) when the callee cut it off before the notice was whole.

    Dana test 3d (2026-10-31): after a talk-over, a model turn came late enough that the "One sec." filler went
    first and the purpose was dropped; the relay's own line is instant. The line must start with the recording
    notice; anything else is replaced by the bare notice.
    """
    said = [str(m.get("content") or "") for m in messages if m.get("role") == "assistant"]
    if said and not (notice_owed(messages) and sum(s.startswith("Hi, just so you") for s in said) <= RESAY_LIMIT):
        return None
    for m in messages:
        if m.get("role") in ("system", "developer"):
            found = OPENING_LINE.search(str(m.get("content", "")))
            if found:
                line = found.group(1).strip()
                return line if line.startswith(gate.RECORDING_OPENING) else gate.RECORDING_OPENING
    return None


def notice_owed(messages: list[dict]) -> bool:
    """True on a call whose recording notice was cut off: Marco has spoken, but never the whole notice.

    Ava test 2 (2026-10-31): the receptionist's greeting started over the opening at "Hi, just so you...".
    """
    said = [str(m.get("content") or "") for m in messages if m.get("role") == "assistant"]
    on_call = any(OPENING_LINE.search(str(m.get("content", ""))) for m in messages
                  if m.get("role") in ("system", "developer"))
    return on_call and bool(said) and not any(gate.RECORDING_OPENING in s for s in said)


def respell(text: str, pairs: dict[str, str]) -> str:
    for word, spoken in pairs.items():
        text = re.sub(rf"\b{re.escape(word)}\b", spoken, text)
    return text


class TagFilter:
    """Cleans streamed text: takes audio tags out, holding a "[" until its "]" arrives (or 26 characters pass),
    and swaps in respellings, holding a word cut at the end of a chunk until it is whole."""

    def __init__(self, pairs: dict[str, str] | None = None):
        self.held = ""
        self.started = False
        self.pairs = pairs or {}

    def _out(self, text: str) -> str:
        text = unnarrate(respell(TAG.sub("", text), self.pairs))
        if not self.started:
            text = text.lstrip()
            self.started = bool(text)
        return text

    def feed(self, text: str) -> str:
        text, self.held = self.held + text, ""
        ends = list(CLAUSE_END.finditer(text))
        cut = ends[-1].start() + 1 if ends else 0
        text, self.held = text[:cut], text[cut:]
        return self._out(text)

    def flush(self) -> str:
        text, self.held = self.held, ""
        return self._out(text)


def _chunk(text: str, finish: str | None = None) -> bytes:
    delta = {"role": "assistant", "content": text} if text else {}
    body = {"object": "chat.completion.chunk", "model": CALL_MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    return f"data: {json.dumps(body)}\n\n".encode()


def _authorized(request: Request) -> bool:
    expected = config.get("RELAY_TOKEN") or ""
    header = request.headers.get("authorization", "")
    return bool(expected) and header.startswith("Bearer ") and hmac.compare_digest(header[7:], expected)


def make_relay(transport: httpx.AsyncBaseTransport | None = None, joblog: JobLog | None = None):
    log = joblog or JobLog()

    async def completions(request: Request) -> Response:
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"error": "bad json"}, status_code=400)
        messages = body.get("messages") or []
        system = " ".join(str(m.get("content", "")) for m in messages if m.get("role") in ("system", "developer"))
        prompt = " ".join(str(m.get("content", "")) for m in messages if m.get("role") not in ("system", "developer"))
        try:
            gate.check_model_call(TENANT, model=CALL_MODEL, system=system, prompt=prompt, joblog=log)
        except gate.Refused as refused:
            return JSONResponse({"error": refused.reason}, status_code=403)

        on_voicemail = voicemail_action(messages, body.get("tools"))
        if on_voicemail is not None:
            log.append(JobRow(job="call-relay", model=CALL_MODEL, note=f"voicemail: {on_voicemail}, no model call"))
            return _tool_call(on_voicemail, bool(body.get("stream")))

        opening = opening_for(messages)
        if opening is not None:
            again = any(m.get("role") == "assistant" for m in messages)
            log.append(JobRow(job="call-relay", model=CALL_MODEL,
                              note=f"opening line{' again, it was cut off' if again else ''}, no model call"))
            if body.get("stream"):
                async def say_opening() -> AsyncIterator[bytes]:
                    yield _chunk(opening)
                    yield _chunk("", "stop")
                    yield b"data: [DONE]\n\n"
                return StreamingResponse(say_opening(), media_type="text/event-stream")
            return JSONResponse({"object": "chat.completion", "model": CALL_MODEL, "choices": [
                {"index": 0, "message": {"role": "assistant", "content": opening}, "finish_reason": "stop"}]})

        # a cut-off notice is said again, first, before whatever Marco says next
        prefix = gate.RECORDING_OPENING + " " if notice_owed(messages) else ""

        forward = {k: v for k, v in body.items() if k in ALLOWED_FIELDS}
        # The model sees the real spelling: what Marco said aloud ("Bettencourt") and the other side's read-back of
        # it come back as the profile's word ("Betancourt"). Live 2026-10-31: seeing his own respelling, he
        # "corrected" a right read-back three times.
        spoken = {said: word for word, said in briefs.say_as().items()}
        if spoken:
            forward["messages"] = [{**m, "content": respell(m["content"], spoken)} if isinstance(m.get("content"), str)
                                   else m for m in forward.get("messages") or []]
        if "max_tokens" in forward:  # Meta's field name is max_completion_tokens
            forward.setdefault("max_completion_tokens", forward.pop("max_tokens"))
        forward["max_completion_tokens"] = min(int(forward.get("max_completion_tokens") or CALL_MAX_TOKENS),
                                               CALL_MAX_TOKENS)
        forward["reasoning_effort"] = CALL_REASONING
        forward["model"] = CALL_MODEL
        stream = bool(forward.get("stream"))
        if stream:
            forward["stream_options"] = {"include_usage": True}
        headers = {"Authorization": f"Bearer {config.require('MODEL_API_KEY')}"}
        client = httpx.AsyncClient(base_url=BASE_URL, timeout=60, transport=transport)
        started = time.monotonic()

        def record(usage: dict, ok: bool, note: str = "") -> None:
            p, c = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
            cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
            log.append(JobRow(job="call-relay", model=CALL_MODEL, prompt_tokens=p, completion_tokens=c,
                              cached_tokens=cached, cost_usd=cost_usd(CALL_MODEL, p, c, cached),
                              duration_ms=int((time.monotonic() - started) * 1000), ok=ok, note=note))

        if not stream:
            response = await client.post("/chat/completions", json=forward, headers=headers)
            await client.aclose()
            if response.status_code >= 400:
                record({}, False, f"http {response.status_code}")
                return JSONResponse({"error": f"upstream {response.status_code}"}, status_code=502)
            data = response.json()
            record(data.get("usage") or {}, True)
            pairs = briefs.say_as()
            for choice in data.get("choices") or []:
                message = choice.get("message") or {}
                if isinstance(message.get("content"), str):
                    message["content"] = unnarrate(respell(TAG.sub("", message["content"]).strip(), pairs)).strip()
                if prefix:
                    message["content"] = (prefix + (message.get("content") or "")).strip()
            return JSONResponse(data)

        async def relay_stream() -> AsyncIterator[bytes]:
            usage: dict = {}
            ok = True
            tags = TagFilter(briefs.say_as())
            first_text_ms: int | None = None
            finished = False
            if prefix:
                yield _chunk(prefix)
            try:
                async with client.stream("POST", "/chat/completions", json=forward, headers=headers) as upstream:
                    if upstream.status_code >= 400:
                        ok = False
                        yield b'data: {"error": "upstream"}\n\n'
                        return
                    async for line in upstream.aiter_lines():
                        if line.startswith("data: ") and line[6:].strip() == "[DONE]":
                            held = tags.flush()
                            if held:
                                yield _chunk(held)
                        elif line.startswith("data: ") and line[6:].strip():
                            try:
                                chunk = json.loads(line[6:])
                            except ValueError:
                                chunk = None
                            if chunk is not None:
                                usage = chunk.get("usage") or usage
                                for choice in chunk.get("choices") or []:
                                    delta = choice.get("delta") or {}
                                    if isinstance(delta.get("content"), str):
                                        delta["content"] = tags.feed(delta["content"])
                                        if delta["content"] and first_text_ms is None:
                                            first_text_ms = int((time.monotonic() - started) * 1000)
                                line = "data: " + json.dumps(chunk)
                        yield (line + "\n").encode()
                finished = True
            finally:
                # A stream the caller closed before the end is logged as such (live 2026-10-31: ElevenLabs dropped
                # two answers in a row and the log showed only empty rows).
                if ok and not finished:
                    record(usage, False, f"caller dropped it after {int((time.monotonic() - started) * 1000)} ms; "
                                         f"first text at {first_text_ms if first_text_ms is not None else 'none'} ms")
                else:
                    record(usage, ok, "" if ok else "upstream error")
                await client.aclose()

        return StreamingResponse(relay_stream(), media_type="text/event-stream")

    return completions

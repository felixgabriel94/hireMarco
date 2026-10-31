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
"Hello?" and once made ElevenLabs give up; and audio tags such as "[happy]" are
taken out of what Marco says.
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


def opening_for(messages: list[dict]) -> str | None:
    """The first reply of a call, when no assistant turn has happened yet and the prompt names one.

    The line must start with the recording notice; anything else is replaced by the bare notice.
    """
    if any(m.get("role") == "assistant" for m in messages):
        return None
    for m in messages:
        if m.get("role") in ("system", "developer"):
            found = OPENING_LINE.search(str(m.get("content", "")))
            if found:
                line = found.group(1).strip()
                return line if line.startswith(gate.RECORDING_OPENING) else gate.RECORDING_OPENING
    return None


class TagFilter:
    """Takes audio tags out of streamed text, holding a "[" until its "]" arrives (or 26 characters pass)."""

    def __init__(self):
        self.held = ""
        self.started = False

    def _out(self, text: str) -> str:
        text = TAG.sub("", text)
        if not self.started:
            text = text.lstrip()
            self.started = bool(text)
        return text

    def feed(self, text: str) -> str:
        text, self.held = self.held + text, ""
        i = text.rfind("[")
        if i != -1 and "]" not in text[i:] and len(text) - i <= 26:
            text, self.held = text[:i], text[i:]
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

        opening = opening_for(messages)
        if opening is not None:
            log.append(JobRow(job="call-relay", model=CALL_MODEL, note="opening line, no model call"))
            if body.get("stream"):
                async def say_opening() -> AsyncIterator[bytes]:
                    yield _chunk(opening)
                    yield _chunk("", "stop")
                    yield b"data: [DONE]\n\n"
                return StreamingResponse(say_opening(), media_type="text/event-stream")
            return JSONResponse({"object": "chat.completion", "model": CALL_MODEL, "choices": [
                {"index": 0, "message": {"role": "assistant", "content": opening}, "finish_reason": "stop"}]})

        forward = {k: v for k, v in body.items() if k in ALLOWED_FIELDS}
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
            for choice in data.get("choices") or []:
                message = choice.get("message") or {}
                if isinstance(message.get("content"), str):
                    message["content"] = TAG.sub("", message["content"]).strip()
            return JSONResponse(data)

        async def relay_stream() -> AsyncIterator[bytes]:
            usage: dict = {}
            ok = True
            tags = TagFilter()
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
                                line = "data: " + json.dumps(chunk)
                        yield (line + "\n").encode()
            finally:
                record(usage, ok, "" if ok else "upstream error")
                await client.aclose()

        return StreamingResponse(relay_stream(), media_type="text/event-stream")

    return completions

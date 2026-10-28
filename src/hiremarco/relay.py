"""The call relay: Muse Spark as the brain of the voice agent on the phone.

ElevenLabs places the call and handles listening and speaking; for thinking
it calls an OpenAI-style endpoint. That endpoint is this relay, on the Mac,
reached through the tunnel. It checks ElevenLabs' bearer token against
RELAY_TOKEN, runs the gate's model check (kill switch, daily cap), pins the
model to Muse Spark whatever the request says, forwards to the Meta Model
API with the Mac's own key, streams the answer back, and logs the cost. The
Meta key never leaves this machine.
"""

from __future__ import annotations

import hmac
import json
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

        forward = {k: v for k, v in body.items() if k in ALLOWED_FIELDS}
        if "max_tokens" in forward:  # Meta's field name is max_completion_tokens
            forward.setdefault("max_completion_tokens", forward.pop("max_tokens"))
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
            return JSONResponse(data)

        async def relay_stream() -> AsyncIterator[bytes]:
            usage: dict = {}
            ok = True
            try:
                async with client.stream("POST", "/chat/completions", json=forward, headers=headers) as upstream:
                    if upstream.status_code >= 400:
                        ok = False
                        yield b'data: {"error": "upstream"}\n\n'
                        return
                    async for line in upstream.aiter_lines():
                        if line.startswith("data: ") and line[6:].strip() not in ("", "[DONE]"):
                            try:
                                chunk = json.loads(line[6:])
                                usage = chunk.get("usage") or usage
                            except ValueError:
                                pass
                        yield (line + "\n").encode()
            finally:
                record(usage, ok, "" if ok else "upstream error")
                await client.aclose()

        return StreamingResponse(relay_stream(), media_type="text/event-stream")

    return completions

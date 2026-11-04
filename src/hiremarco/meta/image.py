"""Muse Image over the Meta Model API: one picture from a prompt.

Docs read 2026-11-01 (dev.meta.ai image generation page and the images API
reference): ``POST /images/generations``, OpenAI Images compatible, ``model``
``muse-image-1.0``, ``size`` sets only the aspect ratio, ``output_format`` png,
``reasoning_strength`` low for one pass, the image comes back as ``b64_json``.
Priced per image, whatever the prompt (pricing page, same day). Marco uses it
for backdrops only, never to draw a thing that has to be real.
"""

from __future__ import annotations

import base64
import time

import httpx

from hiremarco import config, events, gate
from hiremarco.joblog import JobLog, JobRow
from hiremarco.meta.client import BASE_URL
from hiremarco.meta.pricing import PRICES_PER_IMAGE

MODEL = "muse-image-1.0"
TENANT = "owner"
# what each job paints, in words anyone follows, for the live view (Owner 2026-11-04: whatever he paints, he says what it is)
WHAT = {"dress-backdrop": "the Dress me backdrop", "cover": "FEGA's cover art", "cover try": "FEGA's cover art"}


def painting_words(job: str, what: str | None = None) -> tuple[str, str]:
    """The live view's two lines for one picture: while it paints, and once it is painted. ``what`` names the
    picture when the caller knows better than the job; a job with no words reads as a picture."""
    thing = (what or WHAT.get(job) or "").strip()
    if not thing:
        return "Painting a picture", "Picture painted."
    return f"Painting {thing}", f"{thing[0].upper()}{thing[1:]} painted."


class MuseImageError(RuntimeError):
    pass


def generate(prompt: str, *, size: str = "1536x1024", job: str = "image", what: str | None = None,
             joblog: JobLog | None = None,
             api_key: str | None = None, transport: httpx.BaseTransport | None = None,
             timeout: float = 180.0) -> bytes:
    """One PNG. Raises ``MuseImageError`` with the HTTP status when the API refuses (never the body, which can echo
    the prompt)."""
    joblog = joblog or JobLog()
    gate.check_model_call(TENANT, model=MODEL, system="", prompt=prompt, joblog=joblog)
    painting, painted = painting_words(job, what)
    body = {"model": MODEL, "prompt": prompt, "n": 1, "size": size, "output_format": "png",
            "reasoning_strength": "low", "response_format": "b64_json"}
    call_id, request_id = events.new_call_id(), events.next_request_id()
    events.emit("model_call_started", source="meta", model=MODEL, operation=events.operation_words(job), status="running",
                summary=painting, task=events.task_words(job), request_id=request_id, call_id=call_id)
    started = time.monotonic()
    try:
        with httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport,
                          headers={"Authorization": f"Bearer {api_key or config.require('MODEL_API_KEY')}"}) as http:
            response = http.post("/images/generations", json=body)
    except httpx.HTTPError as exc:
        joblog.append(JobRow(job=job, model=MODEL, ok=False, note=f"transport: {type(exc).__name__}"))
        events.emit("model_call_failed", source="meta", model=MODEL, operation=events.operation_words(job), status="failed",
                    summary=f"no reply: {type(exc).__name__}", request_id=request_id, call_id=call_id)
        raise MuseImageError(f"request failed: {type(exc).__name__}") from exc
    duration_ms = int((time.monotonic() - started) * 1000)
    if response.status_code >= 400:
        code = ""
        try:
            code = str(((response.json() or {}).get("error") or {}).get("code") or "")[:40]
        except ValueError:
            pass
        joblog.append(JobRow(job=job, model=MODEL, ok=False, duration_ms=duration_ms,
                             note=f"http {response.status_code}" + (f" {code}" if code else "")))
        events.emit("model_call_failed", source="meta", model=MODEL, operation=events.operation_words(job), status="failed",
                    summary=f"HTTP {response.status_code} from the Meta Model API", latency_ms=duration_ms,
                    request_id=request_id, call_id=call_id)
        raise MuseImageError(f"Meta Model API returned HTTP {response.status_code}" + (f" ({code})" if code else ""))
    items = (response.json() or {}).get("data") or []
    encoded = items[0].get("b64_json") if items else None
    if not encoded:
        joblog.append(JobRow(job=job, model=MODEL, ok=False, duration_ms=duration_ms, note="no image in the answer"))
        events.emit("model_call_failed", source="meta", model=MODEL, operation=events.operation_words(job), status="failed",
                    summary="the answer held no image", latency_ms=duration_ms, request_id=request_id, call_id=call_id)
        raise MuseImageError("the answer held no image")
    joblog.append(JobRow(job=job, model=MODEL, cost_usd=PRICES_PER_IMAGE[MODEL] * len(items),
                         duration_ms=duration_ms, ok=True, note=f"{len(items)} image"))
    events.emit("model_call_completed", source="meta", model=MODEL, operation=events.operation_words(job), status="ok",
                summary=painted, latency_ms=duration_ms, request_id=request_id, call_id=call_id,
                cost_usd=PRICES_PER_IMAGE[MODEL] * len(items))
    return base64.b64decode(encoded)

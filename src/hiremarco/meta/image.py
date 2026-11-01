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

from hiremarco import config, gate
from hiremarco.joblog import JobLog, JobRow
from hiremarco.meta.client import BASE_URL
from hiremarco.meta.pricing import PRICES_PER_IMAGE

MODEL = "muse-image-1.0"
TENANT = "owner"


class MuseImageError(RuntimeError):
    pass


def generate(prompt: str, *, size: str = "1536x1024", job: str = "image", joblog: JobLog | None = None,
             api_key: str | None = None, transport: httpx.BaseTransport | None = None,
             timeout: float = 180.0) -> bytes:
    """One PNG. Raises ``MuseImageError`` with the HTTP status when the API refuses (never the body, which can echo
    the prompt)."""
    joblog = joblog or JobLog()
    gate.check_model_call(TENANT, model=MODEL, system="", prompt=prompt, joblog=joblog)
    body = {"model": MODEL, "prompt": prompt, "n": 1, "size": size, "output_format": "png",
            "reasoning_strength": "low", "response_format": "b64_json"}
    started = time.monotonic()
    try:
        with httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport,
                          headers={"Authorization": f"Bearer {api_key or config.require('MODEL_API_KEY')}"}) as http:
            response = http.post("/images/generations", json=body)
    except httpx.HTTPError as exc:
        joblog.append(JobRow(job=job, model=MODEL, ok=False, note=f"transport: {type(exc).__name__}"))
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
        raise MuseImageError(f"Meta Model API returned HTTP {response.status_code}" + (f" ({code})" if code else ""))
    items = (response.json() or {}).get("data") or []
    encoded = items[0].get("b64_json") if items else None
    if not encoded:
        joblog.append(JobRow(job=job, model=MODEL, ok=False, duration_ms=duration_ms, note="no image in the answer"))
        raise MuseImageError("the answer held no image")
    joblog.append(JobRow(job=job, model=MODEL, cost_usd=PRICES_PER_IMAGE[MODEL] * len(items),
                         duration_ms=duration_ms, ok=True, note=f"{len(items)} image"))
    return base64.b64decode(encoded)

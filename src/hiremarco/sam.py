"""SAM 3.1: find the things a noun phrase names in a photo.

Responses API, ``model: sam-3.1``, one ``input_text`` noun phrase and one
``input_image`` data URL (dev.meta.ai SAM segmenting page, read 2026-10-28).
The answer is one line of records, each a box then a mask; only the boxes are
used here, with confidence on. Nothing found is an empty answer, not an error.
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass

import httpx

from hiremarco import config, gate
from hiremarco.joblog import JobLog, JobRow
from hiremarco.meta.client import BASE_URL
from hiremarco.meta.pricing import PRICES_PER_IMAGE

MODEL = "sam-3.1"
TENANT = "owner"
BOX = re.compile(
    r"<\|box;x1=(?P<x1>\d+);y1=(?P<y1>\d+);x2=(?P<x2>\d+);y2=(?P<y2>\d+);w=(?P<w>\d+);h=(?P<h>\d+)"
    r"(?:;c=(?P<c>[\d.]+))?\|>"
)


class SamError(RuntimeError):
    pass


@dataclass(frozen=True)
class Box:
    x1: int
    y1: int
    x2: int
    y2: int
    width: int   # of the whole image
    height: int
    confidence: float = 1.0

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2


def parse_boxes(text: str) -> list[Box]:
    return [Box(int(m["x1"]), int(m["y1"]), int(m["x2"]), int(m["y2"]), int(m["w"]), int(m["h"]),
                float(m["c"]) if m["c"] else 1.0) for m in BOX.finditer(text or "")]


def data_url(image: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(image).decode()}"


def segment(image: bytes, phrase: str, *, mime: str = "image/jpeg", min_confidence: float = 0.5,
            joblog: JobLog | None = None, api_key: str | None = None,
            transport: httpx.BaseTransport | None = None, timeout: float = 60.0) -> list[Box]:
    joblog = joblog or JobLog()
    gate.check_model_call(TENANT, model=MODEL, system="", prompt=phrase, joblog=joblog)
    body = {
        "model": MODEL,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": phrase},
            {"type": "input_image", "image_url": data_url(image, mime)},
        ]}],
        "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
    }
    started = time.monotonic()
    try:
        with httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport,
                          headers={"Authorization": f"Bearer {api_key or config.require('MODEL_API_KEY')}"}) as http:
            response = http.post("/responses", json=body)
    except httpx.HTTPError as exc:
        joblog.append(JobRow(job="segment", model=MODEL, ok=False, note=f"transport: {type(exc).__name__}"))
        raise SamError(f"request failed: {type(exc).__name__}") from exc
    duration_ms = int((time.monotonic() - started) * 1000)
    if response.status_code >= 400:
        joblog.append(JobRow(job="segment", model=MODEL, ok=False, duration_ms=duration_ms,
                             note=f"http {response.status_code}"))
        raise SamError(f"Meta Model API returned HTTP {response.status_code}")
    data = response.json()
    text = data.get("output_text") or "".join(
        block.get("text") or ""
        for item in data.get("output") or [] if item.get("type") == "message"
        for block in item.get("content") or [] if block.get("type") == "output_text"
    )
    boxes = [b for b in parse_boxes(text) if b.confidence >= min_confidence]
    joblog.append(JobRow(job="segment", model=MODEL, cost_usd=PRICES_PER_IMAGE[MODEL], duration_ms=duration_ms,
                         ok=True, note=f"{phrase}: {len(boxes)} found"))
    return boxes

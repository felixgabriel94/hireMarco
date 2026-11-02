"""The plug-in's face: Marco looks at a plug-in window and reads whether it is licensed.

Owner 2026-11-02: a plug-in whose subscription lapsed says so on its own
window ("subscription not active", "trial expired", "demo") and passes
silence; Marco should read the interface and know. The window is captured
as it opens (``studio.recall`` finds it by name and takes its picture), and
Muse Spark looks at the picture and answers whether any license, subscription,
trial, activation or demo notice is showing. Nothing is read by hand; a
notice found goes to the license ledger and the plug-in is left out.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hiremarco import gate
from hiremarco.meta.client import MuseSpark
from hiremarco.sam import data_url

MODEL = "muse-spark-1.3"
TENANT = "owner"

INSTRUCTIONS = (
    "This is a screenshot of an audio plug-in window inside Logic Pro. Say whether the plug-in shows any notice "
    "that it is not licensed or not fully working: words like 'subscription not active', 'license', 'activate', "
    "'trial', 'demo', 'expired', 'not authorized', 'purchase', 'register', or a banner, overlay or dialog asking "
    "the user to sign in or buy. A plug-in that simply shows its controls is licensed. Quote the notice exactly as "
    "printed when there is one; otherwise leave it empty. Do not guess from the plug-in's name."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "licensed": {"type": "boolean"},
        "notice": {"type": "string"},
        "plugin": {"type": "string", "description": "the plug-in's name as printed on its window, else empty"},
    },
    "required": ["licensed", "notice", "plugin"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Face:
    licensed: bool
    notice: str
    plugin: str


def capture_window(name: str = "Stereo Out") -> bytes:
    """The frontmost Logic window of that name, as PNG bytes: a plug-in window on the Stereo Out is named after
    the strip (live 2026-11-02)."""
    from hiremarco.studio.recall import capture, window_frame, window_id

    frame = window_frame(name)
    with tempfile.TemporaryDirectory() as tmp:
        path = capture(window_id(frame), Path(tmp) / "face.png")
        return path.read_bytes()


def read_face(png: bytes, *, client: MuseSpark | None = None) -> Face:
    prompt = "Is this plug-in licensed and working, or does its window show a notice?"
    gate.check_model_call(TENANT, model=MODEL, system=INSTRUCTIONS, prompt=prompt,
                          joblog=client.joblog if client else None)
    client = client or MuseSpark()
    reply = client.chat(
        [
            {"role": "developer", "content": INSTRUCTIONS},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url(png, "image/png")}},
            ]},
        ],
        job="plugin_face", model=MODEL, max_completion_tokens=600,
        response_format={"type": "json_schema", "json_schema": {"name": "face", "schema": SCHEMA, "strict": True}},
    )
    try:
        data = json.loads(reply.text)
        return Face(bool(data["licensed"]), str(data.get("notice", "")).strip()[:200], str(data.get("plugin", "")).strip()[:80])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("the face reading came back unreadable") from exc


def look(name: str = "Stereo Out", *, client: MuseSpark | None = None,
         shoot: Callable[[str], bytes] = capture_window) -> Face:
    """Capture the plug-in window that just opened and read its face."""
    return read_face(shoot(name), client=client)

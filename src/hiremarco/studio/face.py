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
import time
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
    "that it is not owned, not licensed or not fully working: words or buttons like 'START DEMO', 'BUY', 'INFO' "
    "beside them, 'subscription not active', 'license', 'activate', 'trial', 'demo', 'expired', 'not authorized', "
    "'purchase', 'register', or a banner, overlay, bar or dialog asking the user to sign in, demo or buy, anywhere "
    "on the window including its bottom edge. A plug-in that simply shows its controls is licensed. Quote the "
    "notice exactly as printed when there is one; otherwise leave it empty. Do not guess from the plug-in's name."
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


def _face_line(text: str) -> str:
    data = json.loads(text)
    name = str(data.get("plugin", "")).strip() or "The plug-in"
    if data.get("licensed"):
        return f"{name} is licensed."
    return f"{name}: {str(data.get('notice', '')).strip() or 'a license notice'}"


def capture_window(name: str = "Stereo Out") -> bytes:
    """The frontmost Logic window of that name, as PNG bytes: a plug-in window on the Stereo Out is named after
    the strip (live 2026-11-02)."""
    from hiremarco.studio.recall import capture, window_frame, window_id

    frame = window_frame(name)
    with tempfile.TemporaryDirectory() as tmp:
        path = capture(window_id(frame), Path(tmp) / "face.png")
        return path.read_bytes()


def read_face(png: bytes, *, client: MuseSpark | None = None, tokens: int = 2000, effort: str | None = None) -> Face:
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
        job="plugin_face", model=MODEL, max_completion_tokens=tokens,   # 600 ran out before the JSON (live 2026-11-02)
        summarize=_face_line,
        response_format={"type": "json_schema", "json_schema": {"name": "face", "schema": SCHEMA, "strict": True}},
        **({"reasoning_effort": effort} if effort else {}),
    )
    try:
        data = json.loads(reply.text)
        face = Face(bool(data["licensed"]), str(data.get("notice", "")).strip()[:200], str(data.get("plugin", "")).strip()[:80])
        from hiremarco import events

        events.emit("analysis_generated", source="meta", model=MODEL, operation="plug-in face",
                    status="ok" if face.licensed else "low_confidence",
                    summary=f"{face.plugin or 'the plug-in'}: {'licensed' if face.licensed else face.notice or 'a license notice'}",
                    metrics=[("Plug-in", face.plugin or "?", ""), ("Licensed", "yes" if face.licensed else "no", ""),
                             ("Notice", face.notice or "none", "")])
        return face
    except (ValueError, KeyError, TypeError) as exc:
        keep(png, reply.text, "unreadable")
        raise ValueError(f"the face reading came back unreadable ({reply.finish_reason or 'no finish reason'}, "
                         f"{len(reply.text or '')} chars)") from exc


def keep(png: bytes, text: str, why: str) -> None:
    """The capture and the raw reply kept in the state folder when a reading fails, so it can be read later."""
    try:
        from hiremarco import config

        folder = Path(config.STATE_DIR) / "capture"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H-%M-%S")
        (folder / f"{stamp}_face_{why}.png").write_bytes(png)
        (folder / f"{stamp}_face_{why}.txt").write_text(text or "")
    except Exception:
        pass


def look(name: str = "Stereo Out", *, client: MuseSpark | None = None,
         shoot: Callable[[str], bytes] = capture_window, log: Callable[[str], None] | None = None) -> Face | None:
    """Capture the plug-in window that just opened and read its face; None when the window could not be captured
    or the reading did not come back (live 2026-11-02: an empty reply), so the audio check stays the second line
    and the job goes on. A window not there yet is captured once more after a moment (run 34: it was still
    opening), and a reply that came back unreadable is asked once more on the same capture."""
    png = None
    for attempt in range(2):
        try:
            png = shoot(name)
            break
        except Exception as exc:   # noqa: BLE001
            if attempt == 1:
                if log is not None:
                    log(f"   the face of {name} could not be read: {type(exc).__name__}: {str(exc)[-120:]}")
                return None
            time.sleep(0.6)
    for attempt in range(2):
        try:
            # the second look gets three times the room and the least reasoning: a reply that ran out of room with
            # no text (finish reason "length", 0 chars, 2026-11-02) was the model thinking past its budget
            return read_face(png, client=client, tokens=2000 if attempt == 0 else 6000, effort=None if attempt == 0 else "low")
        except ValueError as exc:
            if attempt == 1:
                if log is not None:
                    log(f"   the face of {name} could not be read twice: {str(exc)[-120:]}")
                return None
            from hiremarco import events

            events.emit("model_call_failed", source="meta", model=MODEL, operation="plug-in face", status="retry",
                        summary="the reading came back unreadable; looking once more with more room", attempt=2)
        except Exception as exc:   # noqa: BLE001
            if log is not None:
                log(f"   the face of {name} could not be read: {type(exc).__name__}: {str(exc)[-120:]}")
            return None
    return None

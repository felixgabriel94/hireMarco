"""The Logic export dialog, clicked through by Muse Wonder computer use.

Marco opens File > Export > All Tracks as Audio Files with Logic's own key
command, then Muse Wonder looks at the screen and fills the dialog: WAV, 24
bit, the session's sample rate, normalize off, the given folder, Export. The
loop is the Responses API computer tool (dev.meta.ai computer use page, read
2026-10-28): send a screenshot, get a ``computer_call`` with actions, do
them, send the next screenshot back as ``computer_call_output``.

The model is held on a short leash, because a click can be wrong:

- only click, double click, the keys of a dialog, typing the folder name
  Marco gave it, waits and screenshots; anything else (a drag, a scroll, a
  Command shortcut, other text) stops the run and hands it to Felix;
- a click outside Logic's front window stops the run;
- a pending safety check is never acknowledged by code: the run stops;
- at most ``MAX_STEPS`` turns, and every action passes the gate on the
  ``logic`` channel, so the kill switch and the switch line both apply.

The export writes new files only; ``studio.export`` then checks them.
Screens are captured with ``screencapture`` and scaled to screen points
with ``sips``, so the model's pixel coordinates are click coordinates.
"""

from __future__ import annotations

import base64
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from hiremarco import config, gate
from hiremarco.joblog import JobLog, JobRow
from hiremarco.meta.client import BASE_URL
from hiremarco.meta.pricing import cost_usd

MODEL = "muse-wonder-1.0"
TENANT = "owner"
MAX_STEPS = 20
DIALOG_KEYS = {"ENTER", "RETURN", "TAB", "ESCAPE", "ESC", "SPACE", "UP", "DOWN", "LEFT", "RIGHT"}
KEY_CODES = {"ENTER": 36, "RETURN": 36, "TAB": 48, "ESCAPE": 53, "ESC": 53, "SPACE": 49,
             "UP": 126, "DOWN": 125, "LEFT": 123, "RIGHT": 124}

TASK = (
    "Logic Pro's 'Export All Tracks as Audio Files' dialog is open or opening. Set: file format WAV, "
    "bit depth 24-bit, sample rate unchanged from the project, normalize Off, include volume and pan "
    "automation on. Save into the folder named {folder!r} (type that exact name in the Save As or folder "
    "field only if needed), then press Export. Click only inside the dialog. Stop when the export has started."
)


class HandBack(RuntimeError):
    """The run stopped for Felix to finish by hand; ``reason`` says why."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Window:
    x: int
    y: int
    width: int
    height: int

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height


@dataclass
class Run:
    steps: int = 0
    actions: list[dict[str, Any]] = field(default_factory=list)
    final_text: str = ""


# The Mac side. Each piece is swappable so the loop runs in tests with no screen.

def screenshot_png() -> bytes:
    """The main screen as PNG, scaled from Retina pixels to screen points."""
    width = int(subprocess.run(
        ["osascript", "-e", 'tell application "Finder" to get item 3 of (bounds of window of desktop)'],
        check=True, capture_output=True, text=True, timeout=10).stdout.strip())
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "screen.png"
        subprocess.run(["screencapture", "-x", "-m", "-t", "png", str(path)], check=True, timeout=10)
        subprocess.run(["sips", "--resampleWidth", str(width), str(path)], check=True, capture_output=True,
                       timeout=20)
        return path.read_bytes()


def logic_window() -> Window:
    out = subprocess.run(["osascript", "-e",
                          'tell application "System Events" to tell process "Logic Pro" to get '
                          '{position, size} of front window'],
                         check=True, capture_output=True, text=True, timeout=10).stdout
    x, y, w, h = (int(v) for v in out.replace(" ", "").split(","))
    return Window(x, y, w, h)


def osascript_driver(action: dict[str, Any]) -> None:
    kind = action["type"]
    if kind in ("click", "double_click"):
        clicks = 2 if kind == "double_click" else 1
        script = "\n".join(['tell application "System Events"'] +
                           [f"  click at {{{int(action['x'])}, {int(action['y'])}}}" for _ in range(clicks)] +
                           ["end tell"])
    elif kind == "keypress":
        script = "\n".join(['tell application "System Events"'] +
                           [f"  key code {KEY_CODES[k.upper()]}" for k in action["keys"]] + ["end tell"])
    elif kind == "type":
        text = action["text"].replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{text}"'
    else:
        return
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=10)


def open_export_dialog() -> None:
    # Logic's default key command for Export > All Tracks as Audio Files: Shift-Command-E.
    subprocess.run(["osascript", "-e", 'tell application "Logic Pro" to activate\n'
                    'tell application "System Events" to keystroke "e" using {shift down, command down}'],
                   check=True, capture_output=True, timeout=10)


# The loop.

def vet(action: dict[str, Any], window: Window, folder_name: str) -> None:
    """Raise ``HandBack`` unless this action is one the leash allows."""
    kind = action.get("type")
    if kind in ("screenshot", "wait"):
        return
    if kind in ("click", "double_click"):
        if kind == "click" and action.get("button", "left") != "left":
            raise HandBack(f"a {action.get('button')} click is not needed for a dialog")
        x, y = int(action.get("x", -1)), int(action.get("y", -1))
        if not window.contains(x, y):
            raise HandBack(f"a click at {x},{y} falls outside Logic's window")
        return
    if kind == "keypress":
        keys = [str(k).upper() for k in action.get("keys") or []]
        if not keys or any(k not in DIALOG_KEYS for k in keys):
            raise HandBack(f"keys {keys} are not dialog keys")
        return
    if kind == "type":
        if action.get("text") != folder_name:
            raise HandBack("the model tried to type something other than the folder name")
        return
    raise HandBack(f"{kind} is not allowed in the export dialog")


def _screenshot_part(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def export_by_computer_use(
    folder_name: str,
    *,
    post: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    screenshot: Callable[[], bytes] = screenshot_png,
    window: Callable[[], Window] = logic_window,
    driver: Callable[[dict[str, Any]], None] = osascript_driver,
    open_dialog: Callable[[], None] = open_export_dialog,
    conn=None,
    rules_path: Path | None = None,
    joblog: JobLog | None = None,
    dry_run: bool = False,
    settle_s: float = 0.6,
) -> Run:
    joblog = joblog or JobLog()
    conn = conn or gate.connect()
    task = TASK.format(folder=folder_name)
    gate.check_model_call(TENANT, model=MODEL, system="", prompt=task, joblog=joblog)
    post = post or _http_post(joblog)

    def act(action: dict[str, Any], key: str) -> None:
        if dry_run:
            return
        gate.execute_effect(conn, lambda: driver(action), tenant_id=TENANT, idempotency_key=key,
                            capability="computer_use", channel="logic", target="*",
                            message=f"export dialog: {action}", department="studio", rules_path=rules_path)

    run = Run()
    if not dry_run:
        gate.execute_effect(conn, open_dialog, tenant_id=TENANT, idempotency_key=f"export-open:{time.time_ns()}",
                            capability="open_export", channel="logic", target="*",
                            message="File > Export > All Tracks as Audio Files", department="studio",
                            rules_path=rules_path)
        time.sleep(settle_s)
    bounds = window()
    data = post({"model": MODEL, "tools": [{"type": "computer"}], "input": [
        {"role": "user", "content": [
            {"type": "input_text", "text": task},
            {"type": "input_image", "image_url": _screenshot_part(screenshot())},
        ]}]})
    while True:
        calls = [item for item in data.get("output") or [] if item.get("type") == "computer_call"]
        if not calls:
            run.final_text = "".join(
                block.get("text") or "" for item in data.get("output") or [] if item.get("type") == "message"
                for block in item.get("content") or [] if block.get("type") == "output_text")
            return run
        call = calls[0]
        if call.get("pending_safety_checks"):
            codes = ", ".join(str(c.get("code")) for c in call["pending_safety_checks"])
            raise HandBack(f"the model raised a safety check ({codes}); Felix decides")
        run.steps += 1
        if run.steps > MAX_STEPS:
            raise HandBack(f"more than {MAX_STEPS} steps; the dialog needs a person")
        for i, action in enumerate(call.get("actions") or []):
            vet(action, bounds, folder_name)
            run.actions.append(action)
            if action["type"] not in ("screenshot", "wait"):
                act(action, f"export:{call.get('call_id')}:{i}:{time.time_ns()}")
            if not dry_run:
                time.sleep(settle_s)
        data = post({"model": MODEL, "tools": [{"type": "computer"}], "previous_response_id": data.get("id"),
                     "input": [{"type": "computer_call_output", "call_id": call.get("call_id"),
                                "acknowledged_safety_checks": [],
                                "output": {"type": "computer_screenshot",
                                           "image_url": _screenshot_part(screenshot())}}]})


def _http_post(joblog: JobLog) -> Callable[[dict[str, Any]], dict[str, Any]]:
    http = httpx.Client(base_url=BASE_URL, timeout=120.0,
                        headers={"Authorization": f"Bearer {config.require('MODEL_API_KEY')}"})

    def post(body: dict[str, Any]) -> dict[str, Any]:
        gate.check_model_call(TENANT, model=MODEL, system="", prompt="computer use turn", joblog=joblog)
        started = time.monotonic()
        try:
            response = http.post("/responses", json=body)
        except httpx.HTTPError as exc:
            joblog.append(JobRow(job="export_computer_use", model=MODEL, ok=False,
                                 note=f"transport: {type(exc).__name__}"))
            raise HandBack(f"the model could not be reached ({type(exc).__name__})") from exc
        duration_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            joblog.append(JobRow(job="export_computer_use", model=MODEL, ok=False, duration_ms=duration_ms,
                                 note=f"http {response.status_code}"))
            raise HandBack(f"the model returned HTTP {response.status_code}")
        data = response.json()
        usage = data.get("usage") or {}
        p, c = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        joblog.append(JobRow(job="export_computer_use", model=MODEL, prompt_tokens=p, completion_tokens=c,
                             cost_usd=cost_usd(MODEL, p, c), duration_ms=duration_ms, ok=True))
        return data

    return post

"""The webhook WhatsApp calls when the Owner writes to Marco.

GET answers Meta's verification handshake. POST checks the
X-Hub-Signature-256 header against the app secret before reading anything,
drops messages from anyone but the Owner (counted, never read), skips
retries it has already seen, and hands each new message to the handler in
the background so Meta gets its 200 at once.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starlette.applications import Starlette
from starlette.background import BackgroundTasks
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from hiremarco.whatsapp.client import record_inbound


@dataclass(frozen=True)
class Inbound:
    id: str
    sender: str
    kind: str
    text: str = ""
    media_id: str = ""
    caption: str = ""
    timestamp: str = ""
    filename: str = ""   # a document's own file name, as sent
    mime_type: str = ""  # an audio's or a document's type, as WhatsApp reports it
    voice: bool = False  # an audio recorded in WhatsApp as a voice note, not a file


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_payload(payload: dict[str, Any]) -> list[Inbound]:
    found: list[Inbound] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for m in value.get("messages") or []:
                kind = m.get("type", "unknown")
                body = m.get(kind) or {}
                found.append(Inbound(
                    id=m.get("id", ""),
                    sender=(m.get("from") or "").lstrip("+"),
                    kind=kind,
                    text=(m.get("text") or {}).get("body", ""),
                    media_id=body.get("id", "") if kind in ("audio", "image", "video", "document") else "",
                    caption=body.get("caption", "") if isinstance(body, dict) else "",
                    timestamp=m.get("timestamp", ""),
                    filename=body.get("filename", "") if isinstance(body, dict) else "",
                    mime_type=body.get("mime_type", "") if isinstance(body, dict) else "",
                    voice=bool(body.get("voice")) if isinstance(body, dict) else False,
                ))
    return found


def make_app(
    handler: Callable[[Inbound], None],
    *,
    verify_token: str,
    app_secret: str,
    owner: str,
    conn_factory: Callable[[], sqlite3.Connection],
    extra_routes: list[Route] | None = None,
) -> Starlette:
    owner = owner.lstrip("+")
    stats = {"dropped_not_owner": 0, "retries": 0, "bad_signature": 0}

    async def verify(request: Request) -> Response:
        q = request.query_params
        if q.get("hub.mode") == "subscribe" and verify_token and hmac.compare_digest(
            q.get("hub.verify_token", ""), verify_token
        ):
            return PlainTextResponse(q.get("hub.challenge", ""))
        return PlainTextResponse("forbidden", status_code=403)

    async def receive(request: Request) -> Response:
        body = await request.body()
        if not verify_signature(app_secret, body, request.headers.get("x-hub-signature-256")):
            stats["bad_signature"] += 1
            return PlainTextResponse("bad signature", status_code=401)
        try:
            payload = json.loads(body)
        except ValueError:
            return PlainTextResponse("bad json", status_code=400)
        tasks = BackgroundTasks()
        conn = conn_factory()
        try:
            for message in parse_payload(payload):
                if message.sender != owner:
                    stats["dropped_not_owner"] += 1
                    continue
                if not record_inbound(conn, message.id, message.sender, message.kind):
                    stats["retries"] += 1
                    continue
                tasks.add_task(handler, message)
        finally:
            conn.close()
        return PlainTextResponse("ok", background=tasks)

    async def health(request: Request) -> Response:
        return PlainTextResponse("ok " + json.dumps(stats))

    app = Starlette(routes=[
        Route("/webhook", verify, methods=["GET"]),
        Route("/webhook", receive, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
        *(extra_routes or []),
    ])
    app.state.stats = stats
    return app

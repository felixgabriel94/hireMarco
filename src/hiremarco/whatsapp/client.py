"""Sending over the WhatsApp Cloud API.

Graph API version v25.0 (the version the app dashboard showed 2026-10-28).
Every send passes the gate. A free-form message is allowed only inside the
24-hour window that opens when the Owner last wrote to Marco; outside it,
WhatsApp requires a paid template, which is a money decision for the Owner,
so the client refuses instead.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from hiremarco import config, gate

GRAPH_URL = "https://graph.facebook.com/v25.0"
WINDOW = timedelta(hours=24)
TENANT = "owner"

INBOUND_SCHEMA = """
create table if not exists inbound (
    wa_message_id text primary key,
    ts text not null,
    from_number text not null,
    kind text not null
);
"""


class WhatsAppError(RuntimeError):
    pass


def record_inbound(conn: sqlite3.Connection, wa_message_id: str, from_number: str, kind: str,
                   ts: datetime | None = None) -> bool:
    """Store an inbound message id. False when it was already seen (a webhook retry)."""
    conn.executescript(INBOUND_SCHEMA)
    ts = ts or datetime.now(timezone.utc)
    cur = conn.execute(
        "insert or ignore into inbound (wa_message_id, ts, from_number, kind) values (?, ?, ?, ?)",
        (wa_message_id, ts.isoformat(), from_number.lstrip("+"), kind),
    )
    conn.commit()
    return cur.rowcount == 1


def last_inbound(conn: sqlite3.Connection, from_number: str) -> datetime | None:
    conn.executescript(INBOUND_SCHEMA)
    row = conn.execute(
        "select max(ts) from inbound where from_number = ?", (from_number.lstrip("+"),)
    ).fetchone()
    return datetime.fromisoformat(row[0]) if row and row[0] else None


class WhatsApp:
    def __init__(
        self,
        token: str | None = None,
        phone_number_id: str | None = None,
        conn: sqlite3.Connection | None = None,
        transport: httpx.BaseTransport | None = None,
        rules_path: Path | None = None,
        timeout: float = 20.0,
    ):
        self.token = token or config.require("WHATSAPP_TOKEN")
        self.phone_number_id = phone_number_id or config.require("WHATSAPP_PHONE_NUMBER_ID")
        self.conn = conn or gate.connect()
        self.rules_path = rules_path
        self._http = httpx.Client(
            base_url=GRAPH_URL,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=timeout,
            transport=transport,
        )

    def _post_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = {"messaging_product": "whatsapp", **payload}
        try:
            response = self._http.post(f"/{self.phone_number_id}/messages", json=body)
        except httpx.HTTPError as exc:
            raise WhatsAppError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            # Never echo the body: it can repeat the message text.
            raise WhatsAppError(f"Cloud API returned HTTP {response.status_code}")
        return response.json()

    def _inside_window(self, to: str, now: datetime | None = None) -> bool:
        last = last_inbound(self.conn, to)
        return last is not None and (now or datetime.now(timezone.utc)) - last <= WINDOW

    def _send(self, to: str, payload: dict[str, Any], *, text_for_gate: str, idempotency_key: str,
              capability: str, critic=None, now: datetime | None = None) -> str:
        if not self._inside_window(to, now):
            raise gate.Refused("outside the 24-hour window; a template would cost money, so asking the Owner first")
        data = gate.execute_effect(
            self.conn,
            lambda: self._post_message({"to": to.lstrip("+"), **payload}),
            tenant_id=TENANT, idempotency_key=idempotency_key, capability=capability, channel="whatsapp",
            target=to, message=text_for_gate, department="assistant", critic=critic, rules_path=self.rules_path,
        )
        return (data.get("messages") or [{}])[0].get("id", "")

    def send_text(self, to: str, body: str, *, idempotency_key: str, critic=None,
                  now: datetime | None = None) -> str:
        return self._send(to, {"type": "text", "text": {"body": body}}, text_for_gate=body,
                          idempotency_key=idempotency_key, capability="send_message", critic=critic, now=now)

    def upload_media(self, data: bytes, mime_type: str, filename: str) -> str:
        """Upload a file to the phone number's media store. Returns the media id."""
        try:
            response = self._http.post(
                f"/{self.phone_number_id}/media",
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (filename, data, mime_type)},
            )
        except httpx.HTTPError as exc:
            raise WhatsAppError(f"upload failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise WhatsAppError(f"media upload returned HTTP {response.status_code}")
        media_id = response.json().get("id")
        if not media_id:
            raise WhatsAppError("media upload returned no id")
        return media_id

    def send_voice(self, to: str, ogg: bytes, spoken_text: str, *, idempotency_key: str, critic=None,
                   now: datetime | None = None) -> str:
        """A voice message: mono OGG/OPUS, uploaded and sent inside one gated action.

        The gate and the critic judge the words spoken, so the voice note is
        held to the same rules as a text.
        """
        if not self._inside_window(to, now):
            raise gate.Refused("outside the 24-hour window; a template would cost money, so asking the Owner first")

        def run() -> dict[str, Any]:
            media_id = self.upload_media(ogg, "audio/ogg", "marco.ogg")
            return self._post_message({"to": to.lstrip("+"), "type": "audio",
                                       "audio": {"id": media_id, "voice": True}})

        data = gate.execute_effect(
            self.conn, run, tenant_id=TENANT, idempotency_key=idempotency_key, capability="send_voice_note",
            channel="whatsapp", target=to, message=f"voice note: {spoken_text}", department="assistant",
            critic=critic, rules_path=self.rules_path,
        )
        return (data.get("messages") or [{}])[0].get("id", "")

    def send_image(self, to: str, png: bytes, caption: str, *, idempotency_key: str, critic=None,
                   now: datetime | None = None) -> str:
        """A picture with a short caption: uploaded and sent inside one gated action."""
        if not self._inside_window(to, now):
            raise gate.Refused("outside the 24-hour window; a template would cost money, so asking the Owner first")

        def run() -> dict[str, Any]:
            media_id = self.upload_media(png, "image/png", "marco.png")
            return self._post_message({"to": to.lstrip("+"), "type": "image",
                                       "image": {"id": media_id, "caption": caption[:1024]}})

        data = gate.execute_effect(
            self.conn, run, tenant_id=TENANT, idempotency_key=idempotency_key, capability="send_image",
            channel="whatsapp", target=to, message=f"image: {caption}", department="assistant",
            critic=critic, rules_path=self.rules_path,
        )
        return (data.get("messages") or [{}])[0].get("id", "")

    def react(self, to: str, message_id: str, emoji: str, *, now: datetime | None = None) -> str:
        return self._send(to, {"type": "reaction", "reaction": {"message_id": message_id, "emoji": emoji}},
                          text_for_gate=f"reaction {emoji} on {message_id}",
                          idempotency_key=f"react:{message_id}:{emoji}", capability="react", now=now)

    def mark_read(self, message_id: str, *, typing: bool = False) -> None:
        """Blue ticks on the Owner's message, and the typing dots while Marco thinks."""
        payload: dict[str, Any] = {"status": "read", "message_id": message_id}
        if typing:
            payload["typing_indicator"] = {"type": "text"}
        self._post_message(payload)

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Fetch an inbound voice note or photo. Returns (bytes, mime type)."""
        try:
            meta = self._http.get(f"/{media_id}")
            if meta.status_code >= 400:
                raise WhatsAppError(f"media lookup returned HTTP {meta.status_code}")
            info = meta.json()
            blob = self._http.get(info["url"])
        except httpx.HTTPError as exc:
            raise WhatsAppError(f"media download failed: {type(exc).__name__}") from exc
        if blob.status_code >= 400:
            raise WhatsAppError(f"media download returned HTTP {blob.status_code}")
        return blob.content, info.get("mime_type", "application/octet-stream")

    def subscribe_app(self, waba_id: str) -> bool:
        """Point the WhatsApp account's webhooks at this app."""
        response = self._http.post(f"/{waba_id}/subscribed_apps")
        if response.status_code >= 400:
            raise WhatsAppError(f"subscribe returned HTTP {response.status_code}")
        return bool(response.json().get("success"))

    def close(self) -> None:
        self._http.close()

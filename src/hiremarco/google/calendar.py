"""The calendar: is the time clear, and put the booking in.

Reading skips the gate (it changes nothing); adding an event passes it
on the ``calendar`` channel, which reaches no person, so its switch line
names the destination ``*``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import httpx

from hiremarco import gate
from hiremarco.google.auth import GoogleAuth

CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary"
TENANT = "owner"


class Calendar:
    def __init__(self, auth: GoogleAuth | None = None, conn: sqlite3.Connection | None = None,
                 transport: httpx.BaseTransport | None = None, rules_path: Path | None = None):
        self.auth = auth or GoogleAuth()
        self.conn = conn or gate.connect()
        self.rules_path = rules_path
        self._http = httpx.Client(base_url=CALENDAR_URL, timeout=20, transport=transport)

    def busy(self, start: datetime, end: datetime) -> list[dict]:
        """Events overlapping [start, end). Times must carry their zone."""
        response = self._http.get("/events", headers=self.auth.headers(), params={
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true", "orderBy": "startTime",
        })
        if response.status_code >= 400:
            raise RuntimeError(f"Calendar returned HTTP {response.status_code}")
        return [e for e in response.json().get("items") or [] if e.get("transparency") != "transparent"]

    def is_clear(self, start: datetime, end: datetime) -> bool:
        return not self.busy(start, end)

    def add(self, title: str, start: datetime, end: datetime, *, location: str = "", note: str = "",
            idempotency_key: str) -> str:
        body = {"summary": title, "location": location, "description": note,
                "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}

        def run() -> str:
            response = self._http.post("/events", headers=self.auth.headers(), json=body)
            if response.status_code >= 400:
                raise RuntimeError(f"Calendar returned HTTP {response.status_code}")
            return response.json().get("id", "")

        return gate.execute_effect(
            self.conn, run, tenant_id=TENANT, idempotency_key=idempotency_key, capability="add_event",
            channel="calendar", target="*", message=f"{title} {start.isoformat()}", department="assistant",
            rules_path=self.rules_path,
        )

    def close(self) -> None:
        self._http.close()

"""The mail reader: Gmail, read only, and only from senders RULES.md grants.

The search asks Gmail for granted senders only, and every message is checked
again against the grants by its From header before Marco reads a word of it,
so a forwarded or spoofed name never gets through on the query alone.
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path

import httpx

from hiremarco import rules
from hiremarco.google.auth import GoogleAuth

GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


@dataclass(frozen=True)
class MailItem:
    id: str
    sender: str
    sender_name: str
    subject: str
    date: str
    text: str


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()


def body_text(payload: dict) -> str:
    """The plain-text part if there is one, else the HTML part stripped."""
    plain, rich = [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_decode(data))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    return _strip_html("\n".join(rich))


def query(grants: list[rules.ReadGrant], newer_than: str = "2d") -> str:
    senders = " OR ".join(g.sender.lstrip("@") if g.sender.startswith("@") else g.sender for g in grants)
    return f"from:({senders}) newer_than:{newer_than}"


class Mail:
    def __init__(self, auth: GoogleAuth | None = None, transport: httpx.BaseTransport | None = None,
                 rules_path: Path | None = None):
        self.auth = auth or GoogleAuth()
        self.rules_path = rules_path
        self._http = httpx.Client(base_url=GMAIL_URL, timeout=20, transport=transport)

    def _get(self, path: str, **params) -> dict:
        # Gmail's per-user rate limit answers 429, or 403 "Quota exceeded" (seen live 2026-10-29 on a new
        # project): wait and try again, doubling the wait, before giving up
        for wait in (2, 4, 8, 16, 32, None):
            response = self._http.get(path, params=params, headers=self.auth.headers())
            limited = response.status_code == 429 or (response.status_code == 403 and (
                "quota" in response.text.lower() or "ratelimit" in response.text.lower()))
            if not limited or wait is None:
                break
            self._sleep(wait)
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail returned HTTP {response.status_code}"
                               + (" (rate limit; try again in a few minutes)" if limited else ""))
        return response.json()

    @staticmethod
    def _sleep(seconds: float) -> None:
        import time

        time.sleep(seconds)

    def recent(self, newer_than: str = "2d", limit: int = 10, purpose: str | None = None) -> list[MailItem]:
        """Granted senders' mail; ``purpose`` keeps only the grants whose purpose mentions it."""
        grants = [g for g in rules.read_grants(self.rules_path)
                  if purpose is None or purpose.lower() in g.purpose.lower()]
        if not grants:
            return []
        listing = self._get("/messages", q=query(grants, newer_than), maxResults=limit)
        items = []
        for ref in listing.get("messages") or []:
            meta = self._get(f"/messages/{ref['id']}", format="metadata", metadataHeaders=["From"])
            name, address = parseaddr(_header(meta.get("payload", {}).get("headers", []), "From"))
            if not rules.may_read(address, self.rules_path):
                continue  # matched the search but not a grant: never opened
            full = self._get(f"/messages/{ref['id']}", format="full")
            headers = full.get("payload", {}).get("headers", [])
            items.append(MailItem(
                id=ref["id"], sender=address.lower(), sender_name=name,
                subject=_header(headers, "Subject"), date=_header(headers, "Date"),
                text=body_text(full.get("payload", {})),
            ))
        return items

    def close(self) -> None:
        self._http.close()

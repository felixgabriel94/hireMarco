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
    links: tuple[str, ...] = ()  # every https link in the email, the HTML's hrefs included (Owner 2026-10-31)


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


def body_links(payload: dict) -> tuple[str, ...]:
    """Every https link in the email, in order, without repeats: the HTML's hrefs and any link in the plain text."""
    found: list[str] = []

    def walk(part: dict) -> None:
        data = (part.get("body") or {}).get("data")
        if data and part.get("mimeType", "") in ("text/plain", "text/html"):
            raw = _decode(data)
            found.extend(html.unescape(u) for u in re.findall(r'href=["\'](https://[^"\']+)', raw, re.I))
            found.extend(html.unescape(u) for u in re.findall(r"https://[^\s<>\"')]+", raw))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return tuple(dict.fromkeys(found))


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
    if any(g.sender == "*" for g in grants):  # the Owner's read-all line: every email, none filtered by sender
        return f"newer_than:{newer_than} -in:spam -in:trash -in:sent -in:drafts"
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
                text=body_text(full.get("payload", {})), links=body_links(full.get("payload", {})),
            ))
        return items

    def everything(self, newer_than: str = "14d", limit: int = 300, skip_body=None) -> list[MailItem]:
        """Every email in the window, for sorting, only under the Owner's read-all line (none without it).
        ``skip_body(sender, sender_name, subject)`` true keeps the body unread: sensitive mail is sorted from its
        headers alone and its body is never fetched."""
        grants = rules.read_grants(self.rules_path)
        if not any(g.sender == "*" for g in grants):
            return []
        items, token = [], None
        while len(items) < limit:
            page = self._get("/messages", q=query(grants, newer_than), maxResults=min(100, limit - len(items)),
                             **({"pageToken": token} if token else {}))
            for ref in page.get("messages") or []:
                meta = self._get(f"/messages/{ref['id']}", format="metadata",
                                 metadataHeaders=["From", "Subject", "Date"])
                headers = meta.get("payload", {}).get("headers", [])
                name, address = parseaddr(_header(headers, "From"))
                subject = _header(headers, "Subject")
                text, links = "", ()
                if not (skip_body and skip_body(address.lower(), name, subject)):
                    full = self._get(f"/messages/{ref['id']}", format="full")
                    text, links = body_text(full.get("payload", {})), body_links(full.get("payload", {}))
                items.append(MailItem(id=ref["id"], sender=address.lower(), sender_name=name, subject=subject,
                                      date=_header(headers, "Date"), text=text, links=links))
            token = page.get("nextPageToken")
            if not token:
                break
        return items

    def labels(self) -> dict[str, str]:
        """Label name to id."""
        return {lab["name"]: lab["id"] for lab in self._get("/labels").get("labels") or []}

    def ensure_label(self, name: str, colors: tuple[str, str]) -> str:
        if not (name == "Marco" or name.startswith("Marco/")):
            raise ValueError("Marco makes only his own labels")
        found = self.labels().get(name)
        if found:
            return found
        response = self._http.post("/labels", headers=self.auth.headers(), json={
            "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show",
            "color": {"backgroundColor": colors[0], "textColor": colors[1]}})
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail refused the label (HTTP {response.status_code})")
        return response.json()["id"]

    def label_ids(self, message_id: str) -> list[str]:
        return self._get(f"/messages/{message_id}", format="minimal").get("labelIds") or []

    def set_marco_label(self, message_id: str, add: str, marco_ids: set[str]) -> None:
        """Put one of Marco's labels on an email, taking off his others. Nothing else changes: no archive, no read
        mark, no delete (Owner 2026-10-31)."""
        if add not in marco_ids:
            raise ValueError("only Marco's own labels")
        remove = [i for i in self.label_ids(message_id) if i in marco_ids and i != add]
        response = self._http.post(f"/messages/{message_id}/modify", headers=self.auth.headers(),
                                   json={"addLabelIds": [add], "removeLabelIds": remove})
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail refused the label (HTTP {response.status_code})")

    def latest_from(self, sender: str):
        """The newest email from this exact sender: its id and its unsubscribe headers, or None."""
        page = self._get("/messages", q=f"from:{sender}", maxResults=1)
        refs = page.get("messages") or []
        if not refs:
            return None
        meta = self._get(f"/messages/{refs[0]['id']}", format="metadata",
                         metadataHeaders=["List-Unsubscribe", "List-Unsubscribe-Post"])
        return refs[0]["id"], {h["name"].lower(): h["value"] for h in meta.get("payload", {}).get("headers", [])}

    def ids_from(self, sender: str, keep_starred: bool = True, exclude: str = "") -> list[str]:
        """Every email from this exact sender, starred ones left out, minus what ``exclude`` (a search) names."""
        q = f"from:{sender} -in:trash" + (" -is:starred" if keep_starred else "") + (f" {exclude}" if exclude else "")
        out, token = [], None
        while True:
            page = self._get("/messages", q=q, maxResults=500, **({"pageToken": token} if token else {}))
            out += [m["id"] for m in page.get("messages") or []]
            token = page.get("nextPageToken")
            if not token:
                return out

    def trash(self, message_id: str) -> None:
        """Gmail's Trash, which Gmail empties after 30 days; there is no permanent delete in this code."""
        response = self._http.post(f"/messages/{message_id}/trash", headers=self.auth.headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail refused the move (HTTP {response.status_code})")

    def untrash(self, message_id: str) -> None:
        response = self._http.post(f"/messages/{message_id}/untrash", headers=self.auth.headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail refused the restore (HTTP {response.status_code})")

    def delete_label(self, name: str) -> bool:
        """Remove a label (never the emails under it). Only "Lindy", by the Owner's word of 2026-10-31."""
        if name != "Lindy":
            raise ValueError("only the Lindy label, by the Owner's word")
        label_id = self.labels().get(name)
        if not label_id:
            return False
        response = self._http.delete(f"/labels/{label_id}", headers=self.auth.headers())
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail refused (HTTP {response.status_code})")
        return True

    def close(self) -> None:
        self._http.close()

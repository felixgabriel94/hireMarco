"""The mail reader and writer: Gmail, read only from senders RULES.md grants, and a draft goes out only through the gate.

The search asks Gmail for granted senders only, and every message is checked
again against the grants by its From header before Marco reads a word of it,
so a forwarded or spoofed name never gets through on the query alone.
"""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import getaddresses, parseaddr
from pathlib import Path

import httpx

from hiremarco import rules
from hiremarco.google.auth import GoogleAuth

GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


@dataclass(frozen=True)
class Found:
    """What a Gmail search hands back about one email: headers and Gmail's snippet, never the body."""
    id: str
    sender: str
    subject: str
    snippet: str
    day: date | None  # the day it arrived


@dataclass(frozen=True)
class Source:
    """One email Felix pointed at, to answer or forward."""
    id: str
    thread_id: str
    sender: str
    sender_line: str
    reply_to: str
    subject: str
    date: str
    to: str
    others: tuple[str, ...]  # everyone else on it, for a reply-all he asked for
    message_id: str
    references: str
    text: str


@dataclass(frozen=True)
class MailItem:
    id: str
    sender: str
    sender_name: str
    subject: str
    date: str
    text: str
    links: tuple[str, ...] = ()  # every https link in the email, the HTML's hrefs included (Owner 2026-10-31)
    label_ids: tuple[str, ...] = ()  # Gmail's labels on it, its tab (CATEGORY_*) among them
    unsubscribe: bool = False  # it carries a List-Unsubscribe header: bulk mail

    @property
    def tab(self) -> str:
        return next((i[9:].lower() for i in self.label_ids if i.startswith("CATEGORY_")), "primary")


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

    def everything(self, newer_than: str = "14d", limit: int = 300, skip_body=None, known=None) -> list[MailItem]:
        """Every email in the window, for sorting, only under the Owner's read-all line (none without it).
        ``skip_body(sender, sender_name, subject)`` true keeps the body unread: sensitive mail is sorted from its
        headers alone and its body is never fetched. ``known(id)`` true skips an email already handled."""
        grants = rules.read_grants(self.rules_path)
        if not any(g.sender == "*" for g in grants):
            return []
        items, token = [], None
        while len(items) < limit:
            page = self._get("/messages", q=query(grants, newer_than), maxResults=min(100, limit - len(items)),
                             **({"pageToken": token} if token else {}))
            for ref in page.get("messages") or []:
                if known and known(ref["id"]):
                    continue
                meta = self._get(f"/messages/{ref['id']}", format="metadata",
                                 metadataHeaders=["From", "Subject", "Date", "List-Unsubscribe"])
                headers = meta.get("payload", {}).get("headers", [])
                name, address = parseaddr(_header(headers, "From"))
                subject = _header(headers, "Subject")
                text, links = "", ()
                if not (skip_body and skip_body(address.lower(), name, subject)):
                    full = self._get(f"/messages/{ref['id']}", format="full")
                    text, links = body_text(full.get("payload", {})), body_links(full.get("payload", {}))
                items.append(MailItem(id=ref["id"], sender=address.lower(), sender_name=name, subject=subject,
                                      date=_header(headers, "Date"), text=text, links=links,
                                      label_ids=tuple(meta.get("labelIds") or ()),
                                      unsubscribe=bool(_header(headers, "List-Unsubscribe"))))
            token = page.get("nextPageToken")
            if not token:
                break
        return items

    def found(self, q: str, limit: int = 100) -> list[Found]:
        """The emails a Gmail search finds, up to ``limit``."""
        page = self._get("/messages", q=q, maxResults=limit)
        out = []
        for ref in page.get("messages") or []:
            meta = self._get(f"/messages/{ref['id']}", format="metadata", metadataHeaders=["From", "Subject"])
            headers = meta.get("payload", {}).get("headers", [])
            arrived = int(meta.get("internalDate") or 0)
            out.append(Found(ref["id"], parseaddr(_header(headers, "From"))[1].lower(), _header(headers, "Subject"),
                             meta.get("snippet", ""), datetime.fromtimestamp(arrived / 1000).date() if arrived else None))
        return out

    def labels(self) -> dict[str, str]:
        """Label name to id."""
        return {lab["name"]: lab["id"] for lab in self._get("/labels").get("labels") or []}

    def ensure_label(self, name: str, colors: tuple[str, str] | None = None) -> str:
        """The label's id, made if it is missing. Only the inbox's own set: Felix's labels (an existing one is used as
        he left it, colour and all), Watch, Marco and Marco/<task> (Owner 2026-11-01)."""
        from hiremarco.inbox import LABELS

        if not (name in LABELS or name.startswith("Marco/")):
            raise ValueError("Marco uses only the inbox's own labels")
        found = self.labels().get(name)
        if found:
            return found
        body = {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
        if colors:
            body["color"] = {"backgroundColor": colors[0], "textColor": colors[1]}
        response = self._http.post("/labels", headers=self.auth.headers(), json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail refused the label (HTTP {response.status_code})")
        return response.json()["id"]

    def label_ids(self, message_id: str) -> list[str]:
        return self._get(f"/messages/{message_id}", format="minimal").get("labelIds") or []

    def add_label(self, message_id: str, add: str, ours: set[str]) -> None:
        """Add one of the inbox's labels to an email. Add only: no label comes off, nothing is archived, marked
        read or deleted (Owner 2026-10-31, 2026-11-01)."""
        if add not in ours:
            raise ValueError("only the inbox's own labels")
        response = self._http.post(f"/messages/{message_id}/modify", headers=self.auth.headers(),
                                   json={"addLabelIds": [add]})
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

    def _post(self, path: str, what: str, body: dict | None = None) -> dict:
        """A change, retried on Gmail's rate limit (429, or 403 naming a rate or quota) with a doubling wait; any
        other refusal raises with Gmail's own reason (live 2026-10-31: a 403 stopped the cleanup after 498 moves)."""
        for wait in (2, 4, 8, 16, 32, 64, None):
            response = self._http.post(path, headers=self.auth.headers(), **({"json": body} if body is not None else {}))
            body = response.text.lower()
            limited = response.status_code == 429 or (response.status_code == 403 and (
                "ratelimit" in body or "rate limit" in body or "quota" in body))
            if not limited or wait is None:
                break
            self._sleep(wait)
        if response.status_code >= 400:
            reason = ""
            try:
                reason = (response.json().get("error") or {}).get("message", "")[:160]
            except ValueError:
                pass
            raise RuntimeError(f"Gmail refused the {what} (HTTP {response.status_code}{': ' + reason if reason else ''})")
        try:
            return response.json()
        except ValueError:
            return {}

    def trash(self, message_id: str) -> None:
        """Gmail's Trash, which Gmail empties after 30 days; there is no permanent delete in this code."""
        self._post(f"/messages/{message_id}/trash", "move")

    def untrash(self, message_id: str) -> None:
        self._post(f"/messages/{message_id}/untrash", "restore")

    def archive(self, message_id: str) -> None:
        """Out of the inbox and nothing else: still in All Mail, still labelled, unread stays unread."""
        self._post(f"/messages/{message_id}/modify", "archive", {"removeLabelIds": ["INBOX"]})

    def unarchive(self, message_id: str) -> None:
        self._post(f"/messages/{message_id}/modify", "unarchive", {"addLabelIds": ["INBOX"]})

    def _reads_all(self) -> None:
        if not any(g.sender == "*" for g in rules.read_grants(self.rules_path)):
            raise PermissionError("the Owner's read-all line is not in RULES.md")

    def search(self, q: str, limit: int = 100) -> list[str]:
        """The ids a Gmail search finds, newest first."""
        self._reads_all()
        out, token = [], None
        while len(out) < limit:
            page = self._get("/messages", q=q, maxResults=min(100, limit - len(out)),
                             **({"pageToken": token} if token else {}))
            out += [m["id"] for m in page.get("messages") or []]
            token = page.get("nextPageToken")
            if not token:
                break
        return out

    def message(self, message_id: str) -> Source:
        self._reads_all()
        full = self._get(f"/messages/{message_id}", format="full")
        headers = full.get("payload", {}).get("headers", [])
        sender_line = _header(headers, "From")
        people = [a.lower() for _, a in getaddresses([_header(headers, "To"), _header(headers, "Cc")]) if a]
        return Source(id=message_id, thread_id=full.get("threadId", ""), sender=parseaddr(sender_line)[1].lower(),
                      sender_line=sender_line, reply_to=parseaddr(_header(headers, "Reply-To"))[1].lower(),
                      subject=_header(headers, "Subject"), date=_header(headers, "Date"), to=_header(headers, "To"),
                      others=tuple(people), message_id=_header(headers, "Message-ID"),
                      references=_header(headers, "References"), text=body_text(full.get("payload", {})))

    def find_one(self, find: str) -> Source | None:
        """The newest email his words point at, not one he sent; he sees which in the preview."""
        if not (find or "").strip():
            return None
        ids = self.search(f"{find} -in:spam -in:trash -in:sent -in:drafts", limit=1)
        return self.message(ids[0]) if ids else None

    def known_addresses(self, name: str, limit: int = 25) -> list[str]:
        """Addresses Gmail has seen for this name, most seen first, no robots and not his own."""
        self._reads_all()
        words = [w.lower() for w in re.findall(r"\w+", name)]
        if not words:
            return []
        own, seen = self.own_address().lower(), {}
        phrase = " ".join(words)
        for mid in self.search(f'from:"{phrase}" OR to:"{phrase}"', limit=limit):
            meta = self._get(f"/messages/{mid}", format="metadata", metadataHeaders=["From", "To", "Cc"])
            lines = [_header(meta.get("payload", {}).get("headers", []), h) for h in ("From", "To", "Cc")]
            for shown, address in getaddresses(lines):
                address = address.lower()
                fits = all(w in f"{shown} {address}".lower() for w in words)
                if address and address != own and fits and not re.match(r"(no-?reply|do-?not-?reply|notifications?)\b", address):
                    seen[address] = seen.get(address, 0) + 1
        return sorted(seen, key=lambda a: -seen[a])

    def own_address(self) -> str:
        return self._get("/profile").get("emailAddress", "")

    def replied(self, message_id: str) -> bool:
        """True when Felix wrote in this email's thread after it arrived (his Sent mail, read for this only)."""
        self._reads_all()
        meta = self._get(f"/messages/{message_id}", format="minimal")
        thread = self._get(f"/threads/{meta.get('threadId', '')}", format="minimal")
        arrived = int(meta.get("internalDate") or 0)
        return any("SENT" in (m.get("labelIds") or []) and int(m.get("internalDate") or 0) > arrived
                   for m in thread.get("messages") or [])

    def raw(self, message_id: str) -> bytes:
        self._reads_all()
        data = self._get(f"/messages/{message_id}", format="raw").get("raw", "")
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))

    def create_draft(self, raw: bytes, thread_id: str | None = None) -> str:
        """A draft in Gmail Drafts. Nothing goes anywhere."""
        message = {"raw": base64.urlsafe_b64encode(raw).decode(), **({"threadId": thread_id} if thread_id else {})}
        return self._post("/drafts", "draft", {"message": message})["id"]

    def draft_raw(self, draft_id: str) -> bytes | None:
        """The draft as Gmail holds it now, or None when it is gone."""
        response = self._http.get(f"/drafts/{draft_id}", params={"format": "raw"}, headers=self.auth.headers())
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail returned HTTP {response.status_code}")
        data = (response.json().get("message") or {}).get("raw", "")
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))

    def send_draft(self, draft_id: str) -> str:
        """Only ever inside the gate's mail check: outbox._send."""
        return self._post("/drafts/send", "send", {"id": draft_id}).get("id", "")

    def delete_draft(self, draft_id: str) -> None:
        response = self._http.delete(f"/drafts/{draft_id}", headers=self.auth.headers())
        if response.status_code >= 400 and response.status_code != 404:
            raise RuntimeError(f"Gmail refused (HTTP {response.status_code})")

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

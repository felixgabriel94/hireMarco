"""Serials and license keys: found in receipts by code, kept in the client's own Keychain.

The design (Owner, 2026-10-29): Marco is never the vault, the client's Mac is.
A serial goes from the receipt to the macOS Keychain inside this module; no
model call ever receives one, nothing writes one to a file, log, ledger or
commit, and what leaves this module is a pointer: the item's name and the
serial's last four characters. Showing a serial asks the Mac's owner first
(Touch ID or the login password); every show is logged by item and time,
never by value.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

SERVICE = "hireMarco license"

# A serial is labelled in the receipt ("Serial number: ...", "License key ..."); the value is the run of
# letters, digits and dashes after the label. Ten characters at least, so a word or an order number of a few
# digits is not mistaken for one.
LABEL = re.compile(
    r"(?i)\b(serial(?:\s*number)?|serial\s*no\.?|licen[cs]e\s*key|product\s*key|activation\s*(?:code|key)|"
    r"registration\s*(?:code|key)|unlock\s*code)\b\s*[:#-]?\s*(?P<value>[A-Z0-9](?:[A-Z0-9-]{8,}[A-Z0-9]))"
)
NOT_SERIAL = re.compile(r"^\d{1,9}$")  # a bare short number is an order or invoice number


@dataclass(frozen=True)
class Found:
    vendor: str
    product: str
    value: str

    @property
    def item(self) -> str:
        return f"{self.vendor}: {self.product}"

    @property
    def tail(self) -> str:
        return self.value.replace("-", "")[-4:]


VALUE = re.compile(r"^\s*[*`]*(?P<value>[A-Z0-9](?:[A-Z0-9-]{8,}[A-Z0-9]))[*`]*\s*$")
UUID = re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")  # a request id, not a serial
# A label that ends its line, the value on the next ("### Serial code for *Product*:"); the product is the
# emphasised words in the label line, or what follows "for"
LABEL_ALONE = re.compile(r"(?i)\b(serial|licen[cs]e|product\s*key|activation|registration|unlock)\b[^:]*:\s*[*_]*\s*$")
LABEL_WORDS = re.compile(r"(?i)serial|licen[cs]e|key|code")
EMPHASIS = re.compile(r"[*_]{1,2}([^*_]+?)[*_]{1,2}")
FOR_PRODUCT = re.compile(r"(?i)\bfor\s+(?:your\s+)?(?P<product>[^:*_]+?)\s*[*_]*\s*:")


def find_serials(vendor: str, subject: str, text: str, known: Iterable[str] = ()) -> list[Found]:
    """Every labelled serial in one receipt, whether the value follows the label on its line ("Serial number:
    AB12-...") or sits alone on the next line (iZotope: "Serial Number for VocalSynth 2:" then the value).
    The product is the one the label names, else a known product named in the subject or the mail, else the
    nearest line above, else the subject."""
    mentioned = sorted((k for k in known if len(k) > 3 and (k in subject or k in text)), key=len, reverse=True)
    lines = text.splitlines()
    found, seen = [], set()

    def keep(value: str, product: str, i: int) -> None:
        value = value.strip("-")
        if NOT_SERIAL.match(value) or UUID.match(value) or value in seen or not re.search(r"\d", value):
            return
        seen.add(value)
        if product and LABEL_WORDS.search(product):
            product = ""  # "*serial number*" names the label, not the product
        if not product and mentioned:
            product = mentioned[0]
        if not product:
            product = next((ln.strip(" :-|#*") for ln in reversed(lines[max(0, i - 4):i])
                            if ln.strip(" :-|#*") and not LABEL.search(ln) and not LABEL_ALONE.search(ln)), "")
        found.append(Found(vendor, (product or subject).strip(" *_")[:80], value))

    for i, line in enumerate(lines):
        alone = LABEL_ALONE.search(line.strip(" #"))
        if alone:
            following = next((ln for ln in lines[i + 1:i + 4] if ln.strip()), "")
            value = VALUE.match(following)
            if value:
                named = EMPHASIS.search(line) or FOR_PRODUCT.search(line)
                keep(value.group("value"), named.group(1) if named else "", i)
            continue
        for match in LABEL.finditer(line):
            keep(match.group("value"), "", i)
    return found


class Keychain:
    """Generic-password items in the login Keychain, one per product, under one service name."""

    def __init__(self, service: str = SERVICE):
        self.service = service

    def put(self, item: str, value: str) -> None:
        import Security

        query = {Security.kSecClass: Security.kSecClassGenericPassword, Security.kSecAttrService: self.service,
                 Security.kSecAttrAccount: item}
        Security.SecItemDelete(query)
        added = Security.SecItemAdd({**query, Security.kSecValueData: value.encode(),
                                     Security.kSecAttrLabel: f"{self.service}: {item}"}, None)
        status = added[0] if isinstance(added, tuple) else added  # PyObjC returns (status, item)
        if status != 0:
            raise RuntimeError(f"Keychain refused the item (status {status})")

    def get(self, item: str) -> str | None:
        import Security

        status, data = Security.SecItemCopyMatching(
            {Security.kSecClass: Security.kSecClassGenericPassword, Security.kSecAttrService: self.service,
             Security.kSecAttrAccount: item, Security.kSecReturnData: True}, None)
        return bytes(data).decode() if status == 0 and data is not None else None

    def items(self) -> list[str]:
        import Security

        status, found = Security.SecItemCopyMatching(
            {Security.kSecClass: Security.kSecClassGenericPassword, Security.kSecAttrService: self.service,
             Security.kSecReturnAttributes: True, Security.kSecMatchLimit: Security.kSecMatchLimitAll}, None)
        return sorted(str(a[Security.kSecAttrAccount]) for a in (found or [])) if status == 0 else []


def owner_present(reason: str) -> bool:
    """Ask the Mac's owner (Touch ID, or the login password) before a serial is shown."""
    import threading

    import LocalAuthentication

    context = LocalAuthentication.LAContext.alloc().init()
    done, answer = threading.Event(), {}

    def reply(ok, error):
        answer["ok"] = bool(ok)
        done.set()

    context.evaluatePolicy_localizedReason_reply_(
        LocalAuthentication.LAPolicyDeviceOwnerAuthentication, reason, reply)
    done.wait(120)
    return answer.get("ok", False)


class Vault:
    """What the rest of Marco sees: store from receipts, list pointers, show one after the owner says yes."""

    def __init__(self, keychain=None, log_path: Path | None = None,
                 ask: Callable[[str], bool] = owner_present):
        self.keychain = keychain or Keychain()
        self.log_path = log_path
        self.ask = ask

    def keep(self, receipts: list[tuple[str, str, str]], known: Iterable[str] = ()) -> list[str]:
        """Store every serial in (vendor, subject, text) receipts; returns pointers only."""
        pointers, known = [], list(known)
        for vendor, subject, text in receipts:
            for found in find_serials(vendor, subject, text, known):
                self.keychain.put(found.item, found.value)
                pointer = f"{found.item} (serial in Keychain, ends in {found.tail})"
                if pointer not in pointers:  # a thread quotes the same serial in every reply
                    pointers.append(pointer)
        return pointers

    def show(self, item: str) -> str | None:
        if not self.ask(f"show the serial for {item}"):
            self._log(item, "refused")
            return None
        value = self.keychain.get(item)
        self._log(item, "shown" if value else "missing")
        return value

    def _log(self, item: str, outcome: str) -> None:
        if self.log_path:
            with self.log_path.open("a") as log:
                log.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S %z"), "item": item,
                                      "outcome": outcome}) + "\n")

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
from collections.abc import Callable
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


def find_serials(vendor: str, subject: str, text: str) -> list[Found]:
    """Every labelled serial in one receipt; the product is the nearest line above that names something."""
    lines = text.splitlines()
    found, seen = [], set()
    for i, line in enumerate(lines):
        for match in LABEL.finditer(line):
            value = match.group("value").strip("-")
            if NOT_SERIAL.match(value) or value in seen or not re.search(r"\d", value):
                continue
            seen.add(value)
            product = next((ln.strip(" :-|") for ln in reversed(lines[max(0, i - 4):i])
                            if ln.strip(" :-|") and not LABEL.search(ln)), "") or subject
            found.append(Found(vendor, product[:80], value))
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

    def keep(self, receipts: list[tuple[str, str, str]]) -> list[str]:
        """Store every serial in (vendor, subject, text) receipts; returns pointers only."""
        pointers = []
        for vendor, subject, text in receipts:
            for found in find_serials(vendor, subject, text):
                self.keychain.put(found.item, found.value)
                pointers.append(f"{found.item} (serial in Keychain, ends in {found.tail})")
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

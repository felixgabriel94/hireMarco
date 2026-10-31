"""A read-only look at the Twilio account behind the line, with Marco's own key (marco-ops).

    GET /2010-04-01/Accounts/{sid}/OutgoingCallerIds.json
    GET /2010-04-01/Accounts/{sid}/Calls.json?PageSize=N

Basic auth with the API key's SID and secret (twilio.com/docs/iam/api-keys).
Nothing here writes to Twilio. Phone numbers are shown by their last four digits only.
"""

from __future__ import annotations

import httpx

from hiremarco import config

BASE_URL = "https://api.twilio.com/2010-04-01"


class TwilioError(RuntimeError):
    pass


def masked(number: str | None) -> str:
    digits = "".join(c for c in number or "" if c.isdigit())
    return f"...{digits[-4:]}" if len(digits) >= 4 else "?"


class TwilioCheck:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.account = config.require("TWILIO_ACCOUNT_SID")
        auth = (config.require("TWILIO_API_KEY_SID"), config.require("TWILIO_API_KEY_SECRET"))
        self._http = httpx.Client(base_url=f"{BASE_URL}/Accounts/{self.account}", auth=auth, timeout=20,
                                  transport=transport)

    def _get(self, path: str, **params) -> dict:
        try:
            response = self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise TwilioError(f"GET {path} failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise TwilioError(f"GET {path} returned HTTP {response.status_code}")
        return response.json()

    def caller_ids(self) -> list[dict]:
        return [{"label": c.get("friendly_name"), "number": masked(c.get("phone_number"))}
                for c in self._get("/OutgoingCallerIds.json").get("outgoing_caller_ids") or []]

    def recent_calls(self, n: int = 5) -> list[dict]:
        return [{"sid": c.get("sid"), "status": c.get("status"), "direction": c.get("direction"),
                 "start": c.get("start_time"), "seconds": c.get("duration"), "to": masked(c.get("to"))}
                for c in self._get("/Calls.json", PageSize=n).get("calls") or []]

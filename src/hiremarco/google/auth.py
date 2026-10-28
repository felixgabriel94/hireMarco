"""Sign-in with Google for a desktop app: loopback redirect with PKCE.

    uv run marco google signin

opens the browser, waits on 127.0.0.1 for Google's redirect, swaps the code
for tokens, and writes only the refresh token to the secrets file. Nothing
is printed but the outcome.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import threading
import time
import urllib.parse
import webbrowser

import httpx

from hiremarco import config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)


class GoogleAuthError(RuntimeError):
    pass


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(query)


def _wait_for_code(port: int, state: str, timeout: float) -> str:
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server's name)
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if params.get("state") == state and "code" in params:
                result["code"] = params["code"]
                text = "Marco is signed in. You can close this tab."
            else:
                result["error"] = params.get("error", "bad state")
                text = "Sign-in did not complete. Close this tab and try again."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(text.encode())

        def log_message(self, *args):  # keep the code out of the terminal
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    deadline = time.monotonic() + timeout
    while not result and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    if "code" not in result:
        raise GoogleAuthError(result.get("error", "timed out waiting for Google"))
    return result["code"]


def signin(port: int = 8765, timeout: float = 300.0, transport: httpx.BaseTransport | None = None) -> None:
    client_id = config.require("GOOGLE_CLIENT_ID")
    client_secret = config.require("GOOGLE_CLIENT_SECRET")
    redirect_uri = f"http://127.0.0.1:{port}/"
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = auth_url(client_id, redirect_uri, challenge, state)
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    code = _wait_for_code(port, state, timeout)
    with httpx.Client(transport=transport, timeout=20) as http:
        response = http.post(TOKEN_URL, data={
            "code": code, "client_id": client_id, "client_secret": client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
        })
    if response.status_code >= 400:
        raise GoogleAuthError(f"token exchange returned HTTP {response.status_code}")
    refresh = response.json().get("refresh_token")
    if not refresh:
        raise GoogleAuthError("Google returned no refresh token")
    config.set_value("GOOGLE_REFRESH_TOKEN", refresh)


class GoogleAuth:
    """Hands out short-lived access tokens from the stored refresh token."""

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport
        self._token = ""
        self._expires = 0.0

    def token(self) -> str:
        if self._token and time.monotonic() < self._expires - 60:
            return self._token
        with httpx.Client(transport=self._transport, timeout=20) as http:
            response = http.post(TOKEN_URL, data={
                "client_id": config.require("GOOGLE_CLIENT_ID"),
                "client_secret": config.require("GOOGLE_CLIENT_SECRET"),
                "refresh_token": config.require("GOOGLE_REFRESH_TOKEN"),
                "grant_type": "refresh_token",
            })
        if response.status_code >= 400:
            raise GoogleAuthError(f"token refresh returned HTTP {response.status_code}")
        data = response.json()
        self._token = data["access_token"]
        self._expires = time.monotonic() + float(data.get("expires_in", 3600))
        return self._token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

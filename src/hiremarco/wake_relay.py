"""The always-on Mini's relay: Meta's webhook calls land here, wake the MacBook, and go on to Marco unchanged.

D-0048 (Owner's go 2026-10-30): the demo Mini runs the public tunnel and this relay on 127.0.0.1:8787. Each request
is passed to the MacBook's marco serve with its method, path, query, headers and body unchanged (Meta's verify GET
too, and Meta's signature is still checked on the MacBook). While the MacBook does not answer, a Wake-on-LAN magic
packet goes to the broadcast and to the MacBook every 2 s, and only the connect is retried, up to a ceiling; then
503, and Meta retries. Nothing is stored here, and the log holds one line per request with no bodies and no numbers.
Live 2026-10-30: the MacBook dark-wakes on the packet over Wi-Fi (45 to 96 s, screen off).
"""

from __future__ import annotations

import asyncio
import os
import socket
import time

import httpx

MAC = os.environ.get("HIREMARCO_WAKE_MAC", "5c:e9:1e:6b:7d:79")
TARGETS = [t for t in os.environ.get("HIREMARCO_WAKE_TO", "192.168.7.255:9,192.168.5.196:9").split(",") if t]
UPSTREAM = os.environ.get("HIREMARCO_UPSTREAM", "http://192.168.5.196:8787")
CEILING_S = float(os.environ.get("HIREMARCO_WAKE_CEILING", "30"))
EVERY_S = 2.0
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
       "transfer-encoding", "upgrade", "content-length"}


def magic_packet(mac: str) -> bytes:
    raw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(raw) != 6:
        raise ValueError("a MAC address has six bytes")
    return b"\xff" * 6 + raw * 16


def send_wake(mac: str = MAC, targets: list[str] = TARGETS) -> int:
    packet, sent = magic_packet(mac), 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in targets:
            host, _, port = target.partition(":")
            try:
                s.sendto(packet, (host, int(port or 9)))
                sent += 1
            except OSError:  # one target unreachable must not stop the other
                pass
    return sent


def make_app(*, upstream: str = UPSTREAM, ceiling_s: float = CEILING_S, wake=send_wake, transport=None,
             log=print, clock=time.monotonic, nap=asyncio.sleep):
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse, Response
    from starlette.routing import Route

    async def forward(request: Request) -> Response:
        started = clock()
        body = await request.body()
        headers = [(k, v) for k, v in request.headers.items() if k.lower() not in HOP]
        url = upstream.rstrip("/") + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        packets, last_wake = 0, None
        async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(60.0, connect=2.0)) as client:
            while True:
                try:
                    reply = await client.request(request.method, url, content=body, headers=headers)
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if clock() - started >= ceiling_s:
                        log(f"relay {request.method} {request.url.path} -> 503 after {clock() - started:.1f} s, "
                            f"{packets} wake packets")
                        return PlainTextResponse("macbook asleep", status_code=503)
                    if last_wake is None or clock() - last_wake >= EVERY_S:
                        packets += wake()
                        last_wake = clock()
                    await nap(0.5)
        log(f"relay {request.method} {request.url.path} -> {reply.status_code} in {clock() - started:.1f} s, "
            f"{packets} wake packets")
        out = [(k, v) for k, v in reply.headers.items() if k.lower() not in HOP]
        return Response(reply.content, status_code=reply.status_code, headers=dict(out))

    return Starlette(routes=[Route("/{path:path}", forward, methods=["GET", "POST"])])

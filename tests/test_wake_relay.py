import asyncio

import httpx
import pytest

from hiremarco.wake_relay import magic_packet, make_app


def test_a_magic_packet_is_six_ff_then_the_mac_sixteen_times():
    packet = magic_packet("5c:e9:1e:6b:7d:79")
    assert len(packet) == 102 and packet[:6] == b"\xff" * 6 and packet[6:12] == bytes.fromhex("5ce91e6b7d79")
    with pytest.raises(ValueError):
        magic_packet("5c:e9")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    async def nap(self, s):
        self.t += s


def relay(upstream_handler, ceiling=30.0):
    clock, woke, lines = Clock(), [], []
    app = make_app(upstream="http://macbook:8787", ceiling_s=ceiling, wake=lambda: woke.append(clock()) or 2,
                   transport=httpx.MockTransport(upstream_handler), log=lines.append, clock=clock, nap=clock.nap)
    return app, clock, woke, lines


def call(app, method, path, **kw):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://relay") as c:
            return await c.request(method, path, **kw)
    return asyncio.run(go())


def test_the_call_goes_on_unchanged_once_the_macbook_answers():
    seen, tries = [], {"n": 0}

    def macbook(request):
        tries["n"] += 1
        if tries["n"] < 4:  # asleep for the first three tries
            raise httpx.ConnectError("asleep", request=request)
        seen.append(request)
        return httpx.Response(200, text="ok")

    app, clock, woke, lines = relay(macbook)
    reply = call(app, "POST", "/webhook?x=1", content=b'{"entry":[]}',
                 headers={"x-hub-signature-256": "sha256=abc", "content-type": "application/json"})
    assert reply.status_code == 200 and reply.text == "ok"
    got = seen[0]
    assert got.method == "POST" and str(got.url) == "http://macbook:8787/webhook?x=1"
    assert got.content == b'{"entry":[]}' and got.headers["x-hub-signature-256"] == "sha256=abc"
    assert len(woke) >= 1 and all(b - a >= 2.0 for a, b in zip(woke, woke[1:]))   # a packet every 2 s, no faster
    assert lines and "200" in lines[0] and "abc" not in lines[0] and "entry" not in lines[0]


def test_meta_verify_get_passes_through():
    def macbook(request):
        return httpx.Response(200, text=request.url.params["hub.challenge"])

    app, *_ = relay(macbook)
    reply = call(app, "GET", "/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "t",
                                                 "hub.challenge": "4242"})
    assert reply.text == "4242"


def test_a_macbook_that_never_answers_gets_503_at_the_ceiling():
    def macbook(request):
        raise httpx.ConnectError("asleep", request=request)

    app, clock, woke, lines = relay(macbook, ceiling=30.0)
    reply = call(app, "POST", "/webhook", content=b"{}")
    assert reply.status_code == 503 and 30.0 <= clock() < 31.0
    assert len(woke) == 15                                    # every 2 s for 30 s
    assert "503" in lines[0]


def test_the_macbook_admits_only_the_named_addresses():
    from hiremarco.server import admit_only

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"in"})

    app = admit_only(inner, {"127.0.0.1", "192.168.5.186"})

    def from_addr(addr):
        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(addr, 5000)),
                                         base_url="http://mac") as c:
                return (await c.get("/health")).status_code
        return asyncio.run(go())

    assert from_addr("192.168.5.186") == 200 and from_addr("192.168.5.50") == 403


def test_the_mac_is_held_awake_until_the_reply_is_sent():
    from hiremarco.server import awake_while

    events = []

    class Keeper:
        def terminate(self):
            events.append("released")

    run = awake_while(lambda m: events.append(f"handled {m}") or "done", hold=lambda: events.append("held") or Keeper())
    assert run("hey") == "done" and events == ["held", "handled hey", "released"]

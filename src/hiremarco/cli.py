"""The ``marco`` command. One labelled command per thing worth filming.

    uv run marco env                     which keys are set (never their values)
    uv run marco gate status             kill switch and today's counts
    uv run marco gate kill on|off        stop or resume everything
    uv run marco demo first-answer       Marco's first live answer on Muse Spark
    uv run marco serve                   the WhatsApp webhook on 127.0.0.1:8787
    uv run marco serve --listen-only     hear the Owner, reply to nothing (opens the 24-hour window)
    uv run marco whatsapp send "text"    one message to the Owner (manual trigger)
    uv run marco whatsapp verify-token   make the webhook token, copy it to the clipboard
    uv run marco whatsapp subscribe      point the WhatsApp account's webhooks at the app
    uv run marco google signin           one Google sign-in for mail (read) and calendar
    uv run marco mail check              granted senders' mail from the last two days
    uv run marco relay token             make the call relay's token, copy it to the clipboard for ElevenLabs
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import subprocess
import sys
from datetime import date

from hiremarco import config, gate
from hiremarco.livelog import Trace

FIRST_QUESTION = "Marco, are you there?"


def cmd_env(args) -> int:
    for key, present in config.describe().items():
        print(f"{key:28} {'set' if present else 'missing'}")
    return 0


def cmd_gate(args) -> int:
    if args.action == "kill":
        gate.set_kill_switch(args.state == "on", "by the Owner")
        print(f"kill switch {args.state}")
        return 0
    conn = gate.connect()
    today = date.today().isoformat()
    rows = conn.execute(
        "select channel, count(*) from effects where ok = 1 and day = ? group by channel", (today,)
    ).fetchall()
    print(f"kill switch {'ON' if gate.kill_switch_on() else 'off'}")
    for channel, count in rows:
        print(f"{channel:10} {count} today")
    return 0


def cmd_first_answer(args) -> int:
    from hiremarco.marco import Marco

    question = " ".join(args.prompt) or FIRST_QUESTION
    trace = Trace(f"heard: {question}")
    try:
        reply = Marco().answer(question, job="first-answer", max_completion_tokens=80)
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    print(reply.text.strip())
    trace.done(f"muse spark, {reply.cost_usd:.5f} USD")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from hiremarco.server import build_app

    uvicorn.run(build_app(reply=not args.listen_only), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def cmd_whatsapp(args) -> int:
    if args.action == "verify-token":
        path = config.env_path()
        if config.get("WHATSAPP_VERIFY_TOKEN"):
            token = config.require("WHATSAPP_VERIFY_TOKEN")
        else:
            token = secrets.token_urlsafe(24)
            config.set_value("WHATSAPP_VERIFY_TOKEN", token, path)
        subprocess.run(["pbcopy"], input=token.encode(), check=True)
        print("WHATSAPP_VERIFY_TOKEN copied to the clipboard; paste it into Meta's Verify token field")
        return 0

    from hiremarco.whatsapp import WhatsApp

    wa = WhatsApp()
    if args.action == "subscribe":
        ok = wa.subscribe_app(config.require("WHATSAPP_WABA_ID"))
        print("subscribed" if ok else "not subscribed")
        return 0 if ok else 1
    text = " ".join(args.text)
    owner = config.require("OWNER_WHATSAPP")
    key = "manual:" + hashlib.sha256(f"{date.today()}:{text}".encode()).hexdigest()[:16]
    trace = Trace(f"send: {text}")
    try:
        message_id = wa.send_text(owner, text, idempotency_key=key)
    except gate.Refused as refused:
        trace.done(f"held: {refused.reason}")
        return 1
    trace.done(f"sent {message_id[-6:]}")
    return 0


def cmd_google(args) -> int:
    from hiremarco.google.auth import signin

    signin()
    print("Google signed in; refresh token stored in the secrets file")
    return 0


def cmd_mail(args) -> int:
    from hiremarco.google import Mail

    items = Mail().recent()
    if not items:
        Trace("mail: checked").done("nothing from a granted sender")
        return 0
    for item in items:
        Trace(f"mail: {item.sender_name or item.sender}").done(item.subject[:60])
    return 0


def cmd_relay(args) -> int:
    if config.get("RELAY_TOKEN"):
        token = config.require("RELAY_TOKEN")
    else:
        token = secrets.token_urlsafe(32)
        config.set_value("RELAY_TOKEN", token)
    subprocess.run(["pbcopy"], input=token.encode(), check=True)
    print("RELAY_TOKEN copied to the clipboard; paste it as the custom LLM's API key secret in ElevenLabs")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marco")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("env").set_defaults(func=cmd_env)

    g = sub.add_parser("gate")
    g.add_argument("action", choices=["status", "kill"])
    g.add_argument("state", nargs="?", choices=["on", "off"])
    g.set_defaults(func=cmd_gate)

    d = sub.add_parser("demo")
    dsub = d.add_subparsers(dest="moment", required=True)
    fa = dsub.add_parser("first-answer")
    fa.add_argument("prompt", nargs="*")
    fa.set_defaults(func=cmd_first_answer)

    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--listen-only", action="store_true")
    s.set_defaults(func=cmd_serve)

    w = sub.add_parser("whatsapp")
    w.add_argument("action", choices=["send", "verify-token", "subscribe"])
    w.add_argument("text", nargs="*")
    w.set_defaults(func=cmd_whatsapp)

    gg = sub.add_parser("google")
    gg.add_argument("action", choices=["signin"])
    gg.set_defaults(func=cmd_google)

    m = sub.add_parser("mail")
    m.add_argument("action", choices=["check"])
    m.set_defaults(func=cmd_mail)

    r = sub.add_parser("relay")
    r.add_argument("action", choices=["token"])
    r.set_defaults(func=cmd_relay)

    args = parser.parse_args(argv)
    if args.command == "gate" and args.action == "kill" and not args.state:
        parser.error("gate kill needs on or off")
    if args.command == "whatsapp" and args.action == "send" and not args.text:
        parser.error("whatsapp send needs the text")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

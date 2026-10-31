"""Marco's phone calls, placed by an ElevenLabs agent from the imported line.

ElevenLabs listens and speaks; for thinking it calls the relay (relay.py) on
this Mac through the tunnel, which pins Muse Spark. Shapes read from
elevenlabs.io/docs/api-reference on 2026-10-31:

    GET   /v1/convai/secrets?search=NAME        POST /v1/convai/secrets          PATCH /v1/convai/secrets/{id}
    GET   /v1/convai/agents?search=NAME         POST /v1/convai/agents/create    PATCH /v1/convai/agents/{id}
    GET   /v1/convai/phone-numbers              (label, phone_number_id)
    POST  /v1/convai/twilio/outbound-call       (conversation_id, callSid)
    GET   /v1/convai/conversations/{id}         (transcript, metadata.cost_fiat in USD)

Every call passes ``gate.execute_effect`` on the ``voice`` channel, so it needs
the ``calls`` send switch in RULES.md, opens with the recording notice and is
refused when repeated. The job log carries the conversation id and callSid,
never a phone number.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import date
from pathlib import Path

import httpx

from hiremarco import config, gate
from hiremarco.joblog import JobLog, JobRow

BASE_URL = "https://api.elevenlabs.io/v1"
TENANT = "owner"
AGENT_NAME = "Marco (calls)"
PHONE_LABEL = "Marco (AT&T line)"
SECRET_NAME = "hiremarco-relay-token"
TTS_MODEL = "eleven_v4_turbo"
TTS_FALLBACK = "eleven_flash_v2_5"
MAX_CALL_SECONDS = 300
RELAY_MODEL = "muse-spark"  # the relay pins its own model whatever this says
OPENING = "Hi, just so you know, this call is recorded. I'm calling to {purpose} for Felix."

# Marco waits for the callee to speak; after this long in silence he speaks first (Owner 2026-10-31: he spoke the
# instant the call connected). Either way his first reply is the opening, said by the relay word for word.
WAIT_FOR_CALLEE_S = 3.0
# Calmer delivery than the defaults (Owner 2026-10-31: "a bit too fake", a little loud).
CALL_VOICE = {"stability": 0.7, "similarity_boost": 0.75, "speed": 1.0, "expressive_mode": False}

PROMPT = """You are Marco, an AI assistant placing a phone call for Felix.

Your first words, exactly: {{opening}}

Why you are calling: {{purpose}}
Details: {{details}}

Sound like a calm assistant on the phone: short, relaxed, plain sentences, one or two a turn, with contractions.
No exclamation marks, no audio tags or stage directions in brackets, no over-enthusiasm.
Use only the facts in the details. Never invent a date, a time, a party size or a name; if asked for one the details
do not give, say you'll check with Felix.
You are an AI assistant. You do not bring it up yourself, but if anyone asks whether you are a person, a bot or an AI,
say truthfully that you are an AI assistant calling for Felix. Never claim or imply that you are human.
Never give card numbers, bank details or any payment details, even if asked; say Felix will handle payment himself.
Do not agree to anything beyond the purpose and details above; if asked, say you will check with Felix.
When the purpose is done, or the other person asks you to stop or hang up, thank them, say goodbye and end the call."""


class CallError(RuntimeError):
    pass


def first_message(purpose: str) -> str:
    purpose = " ".join(purpose.split()).rstrip(".")
    if not purpose:
        raise CallError("a call needs a purpose")
    return OPENING.format(purpose=purpose)


def agent_body(llm_url: str, secret_id: str, voice_id: str, tts_model: str = TTS_MODEL) -> dict:
    system_tool = lambda kind: {"name": kind, "params": {"system_tool_type": kind}}  # noqa: E731
    return {
        "name": AGENT_NAME,
        "tags": ["hiremarco"],
        "conversation_config": {
            "agent": {
                "first_message": "",
                "language": "en",
                "prompt": {
                    "prompt": PROMPT,
                    "llm": "custom-llm",
                    "custom_llm": {"url": llm_url.rstrip("/"), "model_id": RELAY_MODEL,
                                   "api_key": {"secret_id": secret_id}},
                    "built_in_tools": {"end_call": system_tool("end_call"),
                                       "voicemail_detection": system_tool("voicemail_detection")},
                    # no other model answers for Muse Spark when a turn is slow
                    "backup_llm_config": {"preference": "disabled"},
                },
            },
            "tts": {"model_id": tts_model, "voice_id": voice_id, **CALL_VOICE},
            "turn": {"initial_wait_time": WAIT_FOR_CALLEE_S},
            "conversation": {"max_duration_seconds": MAX_CALL_SECONDS},
        },
    }


def call_key(to: str, purpose: str, details: str, today: date | None = None) -> str:
    digest = hashlib.sha256(f"{to.lstrip('+')}|{purpose}|{details}".encode()).hexdigest()[:16]
    return f"call:{(today or date.today()).isoformat()}:{digest}"


class Calls:
    def __init__(self, transport: httpx.BaseTransport | None = None, conn: sqlite3.Connection | None = None,
                 joblog: JobLog | None = None, rules_path: Path | None = None):
        self._http = httpx.Client(base_url=BASE_URL, timeout=30, transport=transport,
                                  headers={"xi-api-key": config.require("ELEVENLABS_API_KEY")})
        self.conn = conn
        self.joblog = joblog or JobLog()
        self.rules_path = rules_path

    def _json(self, method: str, path: str, **kwargs) -> dict | list:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise CallError(f"{method} {path} failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise CallError(f"{method} {path} returned HTTP {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else {}

    # setup

    def relay_secret(self) -> str:
        """The relay token as a workspace secret the agent points at; made here if the env file has none."""
        token = config.get("RELAY_TOKEN")
        if not token:
            token = secrets.token_urlsafe(32)
            config.set_value("RELAY_TOKEN", token)
        found = self._json("GET", "/convai/secrets", params={"search": SECRET_NAME})
        for item in found.get("secrets") or []:
            if item.get("name") == SECRET_NAME:
                self._json("PATCH", f"/convai/secrets/{item['secret_id']}",
                           json={"type": "update", "name": SECRET_NAME, "value": token})
                return item["secret_id"]
        made = self._json("POST", "/convai/secrets", json={"type": "new", "name": SECRET_NAME, "value": token})
        return made["secret_id"]

    def find_agent(self) -> str | None:
        found = self._json("GET", "/convai/agents", params={"search": AGENT_NAME})
        for item in found.get("agents") or []:
            if item.get("name") == AGENT_NAME:
                return item["agent_id"]
        return None

    def phone_number_id(self, label: str = PHONE_LABEL) -> str:
        for item in self._json("GET", "/convai/phone-numbers"):
            if item.get("label") == label:
                return item["phone_number_id"]
        raise CallError(f"no phone number labelled {label!r} in ElevenLabs")

    def setup(self, llm_url: str) -> dict:
        """Create or update the one calls agent, and store its id and the line's id in the env file."""
        if not llm_url.startswith("https://") or not llm_url.rstrip("/").endswith("/llm/v1"):
            raise CallError("the relay address must be https://<tunnel>/llm/v1")
        secret_id = self.relay_secret()
        voice_id = config.require("ELEVENLABS_VOICE_ID")
        agent_id = self.find_agent()
        tts_model = TTS_MODEL
        for model in (TTS_MODEL, TTS_FALLBACK):
            body = agent_body(llm_url, secret_id, voice_id, model)
            try:
                if agent_id:
                    self._json("PATCH", f"/convai/agents/{agent_id}", json=body)
                else:
                    agent_id = self._json("POST", "/convai/agents/create", json=body)["agent_id"]
                tts_model = model
                break
            except CallError as err:
                if model == TTS_FALLBACK or "HTTP 4" not in str(err) or TTS_MODEL not in str(err):
                    raise
        phone_id = self.phone_number_id()
        config.set_value("ELEVENLABS_CALL_AGENT_ID", agent_id)
        config.set_value("ELEVENLABS_PHONE_NUMBER_ID", phone_id)
        config.set_value("CALL_RELAY_URL", llm_url.rstrip("/"))
        return {"agent_id": agent_id, "phone_number_id": phone_id, "tts_model": tts_model}

    # one call

    def place(self, to: str, purpose: str, details: str = "", *, critic=None, today: date | None = None,
              owner_request: str | None = None) -> dict:
        """One call. ``owner_request`` is the Owner's own words naming this number, for the ``named`` switch."""
        to = to.strip()
        if not to.startswith("+") or not to[1:].isdigit():
            raise CallError("the number must be E.164 with the plus, such as +15551234567")
        opening = first_message(purpose)
        details = " ".join(details.split())
        body = {
            "agent_id": config.require("ELEVENLABS_CALL_AGENT_ID"),
            "agent_phone_number_id": config.require("ELEVENLABS_PHONE_NUMBER_ID"),
            "to_number": to,
            "conversation_initiation_client_data": {
                "dynamic_variables": {"opening": opening, "purpose": purpose.strip(), "details": details or "none"},
            },
            "telephony_call_config": {
                "twilio_machine_detection": {
                    "mode": "enable",
                    "actions": [{"action": "hang_up", "answered_by": ["machine_start", "fax"]}],
                },
            },
        }

        def run() -> dict:
            data = self._json("POST", "/convai/twilio/outbound-call", json=body)
            if not data.get("success"):
                raise CallError(f"the call did not start: {str(data.get('message', ''))[:200]}")
            return data

        try:
            data = gate.execute_effect(
                self.conn or gate.connect(), run, tenant_id=TENANT, idempotency_key=call_key(to, purpose, details, today),
                capability="call", channel="voice", target=to, message=f"{opening} Details: {details or 'none'}",
                department="assistant", critic=critic, today=today, rules_path=self.rules_path,
                owner_request=owner_request,
            )
        except CallError as err:
            self.joblog.append(JobRow(job="call", model="elevenlabs-agent", ok=False, note=str(err)[:200]))
            raise
        result = {"conversation_id": data.get("conversation_id"), "callSid": data.get("callSid")}
        self.joblog.append(JobRow(
            job="call", model="elevenlabs-agent",
            note=f"conversation {result['conversation_id']} callSid {result['callSid']}; cost read at transcript",
        ))
        return result

    def transcript(self, conversation_id: str, folder: Path | None = None) -> Path:
        """The conversation as JSON in the state folder, and its cost in the job log."""
        if not conversation_id.replace("_", "").isalnum():
            raise CallError("not a conversation id")
        data = self._json("GET", f"/convai/conversations/{conversation_id}")
        folder = folder or config.STATE_DIR / "calls"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{conversation_id}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        meta = data.get("metadata") or {}
        self.joblog.append(JobRow(
            job="call-cost", model="elevenlabs-agent", cost_usd=float(meta.get("cost_fiat") or 0.0),
            duration_ms=int(meta.get("call_duration_secs") or 0) * 1000, ok=data.get("status") == "done",
            note=f"conversation {conversation_id} status {data.get('status')}; {meta.get('cost')} credits",
        ))
        return path


def transcript_lines(data: dict) -> list[str]:
    return [f"{t.get('time_in_call_secs', 0):>4}s {t.get('role')}: {t.get('message') or ''}".rstrip()
            for t in data.get("transcript") or []]

"""Muse Spark over the Meta Model API (OpenAI-compatible chat completions).

Docs read 2026-10-26: base URL https://api.meta.ai/v1, endpoint
/chat/completions, bearer token from MODEL_API_KEY, roles user, assistant,
developer, tool; max tokens field is ``max_completion_tokens``; usage carries
prompt_tokens, completion_tokens, total_tokens.

Every call is one row in the job log with its cost. The client takes an
optional httpx transport so tests run without the network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from hiremarco import config
from hiremarco.joblog import JobLog, JobRow
from hiremarco.meta.pricing import cost_usd

BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"


@dataclass
class Reply:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cost_usd: float
    duration_ms: int
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class MuseSparkError(RuntimeError):
    pass


class MuseSpark:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str = BASE_URL,
        joblog: JobLog | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or config.require("MODEL_API_KEY")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.joblog = joblog or JobLog()
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        job: str = "chat",
        model: str | None = None,
        max_completion_tokens: int | None = 600,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        reasoning_effort: str | None = None,
    ) -> Reply:
        model = model or self.model
        body: dict[str, Any] = {"model": model, "messages": messages}
        if max_completion_tokens is not None:
            body["max_completion_tokens"] = max_completion_tokens
        if response_format is not None:
            body["response_format"] = response_format
        if tools is not None:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        if reasoning_effort is not None:
            body["reasoning_effort"] = reasoning_effort

        started = time.monotonic()
        try:
            response = self._client.post("/chat/completions", json=body)
        except httpx.HTTPError as exc:
            self.joblog.append(JobRow(job=job, model=model, ok=False, note=f"transport: {type(exc).__name__}"))
            raise MuseSparkError(f"request failed: {type(exc).__name__}") from exc
        duration_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 400:
            # The body may echo the request; log only the status, never the text.
            self.joblog.append(JobRow(job=job, model=model, ok=False, duration_ms=duration_ms, note=f"http {response.status_code}"))
            raise MuseSparkError(f"Meta Model API returned HTTP {response.status_code}")

        data = response.json()
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        cached_tokens = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        reply = Reply(
            text=message.get("content") or "",
            model=data.get("model", model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost_usd(model, prompt_tokens, completion_tokens, cached_tokens),
            duration_ms=duration_ms,
            finish_reason=choice.get("finish_reason"),
            tool_calls=message.get("tool_calls") or [],
            raw=data,
        )
        self.joblog.append(JobRow(
            job=job, model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cached_tokens=cached_tokens, cost_usd=reply.cost_usd, duration_ms=duration_ms, ok=True,
        ))
        return reply

    def ask(self, prompt: str, *, developer: str | None = None, **kwargs: Any) -> Reply:
        messages: list[dict[str, Any]] = []
        if developer:
            messages.append({"role": "developer", "content": developer})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **kwargs)

    def close(self) -> None:
        self._client.close()

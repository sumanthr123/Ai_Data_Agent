"""Model Serving chat client with full token accounting (prompt, completion, reasoning)."""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

from backend.ask.text import message_text


@dataclass
class ChatResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    total_tokens: int
    latency_ms: int


class ModelClient(Protocol):
    def chat(self, endpoint: str, system: str, user: str, max_tokens: int) -> ChatResult: ...


def _usage(raw: dict[str, Any]) -> tuple[int, int, int, int]:
    """(prompt, completion, reasoning, total). Some providers count thinking inside completion_tokens and list it in
    completion_tokens_details; others leave it out of completion_tokens and only include it in total_tokens."""
    usage = raw.get("usage") or {}
    prompt, completion = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    total = max(prompt + completion, int(usage.get("total_tokens") or 0))
    reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0) or total - prompt - completion
    return prompt, completion, reasoning, total


TRANSIENT = ("429", "rate limit", "503", "502", "504", "temporarily", "overloaded", "timed out", "timeout")


def model_workspace_client(retry_window_s: int, **config: Any) -> WorkspaceClient:
    """The SDK handles 429/503 itself, retrying for 300s by default, so they never reach ServingClient's retry or breaker
    and outlive the model timeout. Model calls get a window shorter than that timeout."""
    return WorkspaceClient(config=Config(retry_timeout_seconds=retry_window_s, **config))


class CircuitOpen(RuntimeError):
    pass


class ModelThrottled(RuntimeError):
    pass


class _Breaker:
    """Per endpoint, shared by requests in this process: after `threshold` failures in a row, fail fast for `cooldown_s`."""

    def __init__(self, threshold: int = 3, cooldown_s: float = 60.0) -> None:
        self.threshold, self.cooldown_s = threshold, cooldown_s
        self._fails: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, endpoint: str) -> None:
        with self._lock:
            if time.monotonic() < self._open_until.get(endpoint, 0):
                raise CircuitOpen(f"{endpoint} failed repeatedly; skipped for up to {int(self.cooldown_s)}s")

    def record(self, endpoint: str, ok: bool) -> None:
        with self._lock:
            self._fails[endpoint] = 0 if ok else self._fails.get(endpoint, 0) + 1
            if self._fails[endpoint] >= self.threshold:
                self._open_until[endpoint], self._fails[endpoint] = time.monotonic() + self.cooldown_s, 0


BREAKER = _Breaker()


class ServingClient:
    """`endpoint` or `endpoint/served_model` (one endpoint hosting several external models).
    The SDK retries 429/503 within its window (`model_workspace_client`); other transient errors (5xx/timeouts) are retried
    once here with jittered backoff. Repeated failures open a breaker."""

    def __init__(self, w: WorkspaceClient, efforts: dict[str, str] | None = None, retries: int = 1, backoff_s: float = 1.5) -> None:
        self.w, self.efforts, self.retries, self.backoff_s = w, efforts or {}, retries, backoff_s

    def chat(self, endpoint: str, system: str, user: str, max_tokens: int) -> ChatResult:
        BREAKER.check(endpoint)
        for attempt in range(self.retries + 1):
            try:
                result = self._chat(endpoint, system, user, max_tokens)
                BREAKER.record(endpoint, True)
                return result
            except TimeoutError as exc:  # the SDK's retry window is spent, so a second one would only delay the failure
                BREAKER.record(endpoint, False)
                if getattr(exc.__cause__, "retry_after_secs", None) is None:
                    raise
                raise ModelThrottled(f"{endpoint} is at its rate limit or out of capacity") from exc
            except Exception as exc:
                transient = any(t in str(exc).lower() for t in TRANSIENT)
                if not transient or attempt == self.retries:
                    BREAKER.record(endpoint, False)
                    raise
                time.sleep(self.backoff_s * (2 ** attempt) * random.uniform(0.5, 1.5))
        raise AssertionError("unreachable")

    def _chat(self, endpoint: str, system: str, user: str, max_tokens: int) -> ChatResult:
        started = time.monotonic()
        name, _, served = endpoint.partition("/")
        body: dict[str, Any] = {"max_tokens": max_tokens, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if "claude" not in endpoint:  # newer Claude models reject temperature and reasoning_effort
            body["temperature"] = 0.0
            if self.efforts.get(endpoint):
                body["reasoning_effort"] = self.efforts[endpoint]
        path = f"/serving-endpoints/{name}/served-models/{served}/invocations" if served else f"/serving-endpoints/{name}/invocations"
        raw = self.w.api_client.do("POST", path, body=body)
        content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        return ChatResult(message_text(content), *_usage(raw), int((time.monotonic() - started) * 1000))

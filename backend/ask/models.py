"""Model Serving chat client with full token accounting (prompt, completion, reasoning)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from databricks.sdk import WorkspaceClient

from backend.services.databricks_engine import _text


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


class ServingClient:
    """`endpoint` or `endpoint/served_model` (one endpoint hosting several external models)."""

    def __init__(self, w: WorkspaceClient, efforts: dict[str, str] | None = None) -> None:
        self.w, self.efforts = w, efforts or {}

    def chat(self, endpoint: str, system: str, user: str, max_tokens: int) -> ChatResult:
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
        return ChatResult(_text(content), *_usage(raw), int((time.monotonic() - started) * 1000))

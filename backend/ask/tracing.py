"""Optional MLflow tracing with redaction. A no-op unless MLFLOW_EXPERIMENT is set; never fails a request."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger("ask.tracing")
_REDACTIONS = [
    (re.compile(r"\b(dapi|dose|dkea)[0-9a-f]{16,}\b", re.I), "[token]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "[key]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[key]"),
    (re.compile(r"Bearer\s+\S+", re.I), "Bearer [token]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\+?\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"), "[phone]"),
]


def redact(value: Any, limit: int = 2000) -> Any:
    if isinstance(value, dict):
        return {k: redact(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, limit) for v in value[:50]]
    if not isinstance(value, str):
        return value
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value[:limit]


class _NoSpan:
    def set_inputs(self, *_: Any) -> None: ...
    def set_outputs(self, *_: Any) -> None: ...
    def set_attributes(self, *_: Any) -> None: ...


class Tracer:
    def __init__(self, experiment: str) -> None:
        self.experiment = experiment
        self._ready: bool | None = None

    def _enabled(self) -> bool:
        if self._ready is None:
            self._ready = False
            if self.experiment:
                try:
                    import mlflow

                    mlflow.set_tracking_uri("databricks")
                    mlflow.set_experiment(self.experiment)
                    self._ready = True
                except Exception as exc:
                    logger.warning("MLflow tracing disabled: %s", exc)
        return self._ready

    @contextmanager
    def span(self, name: str, span_type: str = "UNKNOWN", inputs: dict[str, Any] | None = None) -> Iterator[Any]:
        if not self._enabled():
            yield _NoSpan()
            return
        import mlflow

        try:
            manager = mlflow.start_span(name=name, span_type=span_type)
            span = manager.__enter__()
        except Exception as exc:
            logger.warning("Span %s not recorded: %s", name, exc)
            yield _NoSpan()
            return
        if inputs:
            span.set_inputs(redact(inputs))
        try:
            yield span
        except BaseException as exc:
            manager.__exit__(type(exc), exc, exc.__traceback__)
            raise
        manager.__exit__(None, None, None)

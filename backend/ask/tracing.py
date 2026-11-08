"""Optional MLflow tracing. A no-op unless MLFLOW_EXPERIMENT is set; never fails a request.

Spans carry metadata (route, model, tokens, latency) and no free text unless content=True: prompts hold questions and sample
rows, and the GDPR job can't reach an experiment. Text that is kept is redacted."""

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


_TEXT_KEYS = {"question", "user", "sql"}


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
    def __init__(self, experiment: str, content: bool = False) -> None:
        self.experiment, self.content = experiment, content
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

    def trace_id(self) -> str | None:
        """The current trace's id, inside a span; None when tracing is off. A failure is logged, never raised."""
        if not self._enabled():
            return None
        try:
            import mlflow

            return mlflow.get_active_trace_id()
        except Exception as exc:
            logger.warning("Trace id unavailable: %s", exc)
            return None

    def log_feedback(self, trace_id: str, helpful: bool, reason: str | None, source_id: str) -> None:
        """A person's thumbs up or down on a trace. Raises when tracing is off or MLflow refuses, so the UI can say so."""
        if not self._enabled():
            raise RuntimeError("Feedback is off: MLFLOW_EXPERIMENT isn't set for this app.")
        import mlflow
        from mlflow.entities import AssessmentSource

        try:
            mlflow.log_feedback(trace_id=trace_id, name="user_feedback", value=helpful, rationale=reason,
                                source=AssessmentSource(source_type="HUMAN", source_id=source_id))
        except Exception as exc:  # assessments are not offered on every workspace (Free Edition: "Not available in this workspace")
            logger.warning("Feedback assessment refused (%s); storing it as trace tags", exc)
            client = mlflow.MlflowClient()
            client.set_trace_tag(trace_id, "user_feedback", "helpful" if helpful else f"not_helpful:{reason or 'unspecified'}")
            client.set_trace_tag(trace_id, "user_feedback_source", source_id)

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
        kept = inputs if self.content else {k: v for k, v in (inputs or {}).items() if k not in _TEXT_KEYS}
        if kept:
            span.set_inputs(redact(kept))
        try:
            yield span
        except BaseException as exc:
            manager.__exit__(type(exc), exc, exc.__traceback__)
            raise
        manager.__exit__(None, None, None)

"""Consensus chat (SSE), SQL execution, MLflow feedback, config and health."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from sse_starlette.sse import EventSourceResponse

from backend.config import settings
from backend.schemas import ChatRequest, ErrorEvent, FeedbackRequest, SqlRequest
from backend.services import availability, files
from backend.services import mock_consensus_stream as demo
from backend.services.databricks_engine import LiveEngine, council_for, workspace_client
from backend.services.sql_safety import UnsafeSqlError, validate

logger = logging.getLogger("consensus.api")
router = APIRouter(prefix="/api")
_feedback_demo: list[dict[str, Any]] = []
_health_cache: dict[str, Any] = {}


def _mode(requested: str | None) -> str:
    return requested or ("demo" if settings.mock_mode_default else "live")


def _engine(request: Request) -> LiveEngine:
    return LiveEngine(workspace_client(request.headers.get("x-forwarded-access-token")))


@router.get("/config")
def config() -> dict[str, Any]:
    if _mode(None) == "live":  # background check of which models really answer; cached for 30 minutes
        availability.refresh(LiveEngine(workspace_client()).probe)
    status = availability.status()
    return {
        "default_mode": _mode(None),
        "catalog": settings.catalog,
        "warehouse_id": settings.warehouse_id,
        "routing": settings.routing,
        "live_models": [{"id": m.endpoint, "name": m.name, "provider": m.provider,
                         "available": status.get(m.endpoint, {}).get("available", True),
                         "checked": m.endpoint in status,
                         "reason": status.get(m.endpoint, {}).get("reason", "")} for m in settings.models],
        "council_size": settings.council_size,
        "demo_models": [m.model_dump() for m in demo.DEMO_MODELS],
    }


@router.get("/health")
def health(request: Request, mode: str | None = None) -> dict[str, Any]:
    if _mode(mode) == "demo":
        return {"mode": "demo", "unity_catalog": "Connected (simulated)", "warehouse": "Serverless Warm (simulated)",
                "council": [m.name for m in demo.DEMO_MODELS]}
    cached = _health_cache.get("live")
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1]
    w = workspace_client(request.headers.get("x-forwarded-access-token"))
    status: dict[str, Any] = {"mode": "live", "council": [m.name for m in council_for("auto")]}
    try:
        next(iter(w.tables.list(catalog_name=settings.catalog, schema_name=settings.schemas[0])), None)
        status["unity_catalog"] = "Connected"
    except Exception as exc:
        status["unity_catalog"] = f"Error: {str(exc)[:80]}"
    try:
        wh = w.warehouses.get(settings.warehouse_id)
        state = wh.state.value if wh.state else "UNKNOWN"
        status["warehouse"] = f"{'Serverless ' if wh.enable_serverless_compute else ''}{'Warm' if state == 'RUNNING' else state.title()}"
    except Exception as exc:
        status["warehouse"] = f"Error: {str(exc)[:80]}"
    _health_cache["live"] = (time.monotonic(), status)
    return status


@router.post("/chat/consensus-stream")
async def consensus_stream(body: ChatRequest, request: Request) -> EventSourceResponse:
    mode = _mode(body.mode)

    async def events():
        try:
            source = demo.stream(body.question, body.lead_model) if mode == "demo" else _engine(request).stream(body.question, body.lead_model, body.history[-6:], body.attachments, body.timezone)
            async for event in source:
                if await request.is_disconnected():
                    break
                yield {"event": event.type, "data": event.model_dump_json()}
        except Exception as exc:  # Show the failure in the UI instead of a dead stream.
            logger.exception("Consensus stream failed")
            yield {"event": "error", "data": ErrorEvent(message=str(exc)[:300]).model_dump_json()}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(events())


@router.post("/files")
async def upload_file(request: Request, file: UploadFile) -> dict[str, Any]:
    data = await file.read()
    try:
        return await asyncio.to_thread(files.process, workspace_client(request.headers.get("x-forwarded-access-token")),
                                       file.filename or "file", data, file.content_type or "")
    except files.UnsupportedFile as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("File upload failed")
        raise HTTPException(500, f"Couldn't process {file.filename}: {str(exc)[:200]}") from exc


@router.post("/sql/execute")
def execute_sql(body: SqlRequest, request: Request) -> dict[str, Any]:
    try:
        validate(body.sql)
    except UnsafeSqlError as exc:
        raise HTTPException(400, str(exc)) from exc
    if _mode(body.mode) == "demo":
        scenario = next((s for s in demo.SCENARIOS if any(t in body.sql for t in s["tables"])), None)
        if not scenario:
            raise HTTPException(404, "Demo mode only knows the simulated tables.")
        rows = next(iter(scenario["rows"].values()))
        return {"result": {"columns": list(rows[0]), "rows": rows, "row_count": len(rows)}, "statement_id": "demo", "runtime_ms": 420}
    started = time.monotonic()
    try:
        result, statement_id, _ = _engine(request).execute(body.sql)
    except Exception as exc:
        raise HTTPException(400, str(exc)[:300]) from exc
    return {"result": result.model_dump(), "statement_id": statement_id, "runtime_ms": int((time.monotonic() - started) * 1000)}


@router.post("/feedback")
def feedback(body: FeedbackRequest) -> dict[str, Any]:
    if body.mode == "demo":
        _feedback_demo.append(body.model_dump())
        return {"logged": True, "destination": "demo (in memory)"}
    try:
        import mlflow

        mlflow.set_tracking_uri("databricks")
        experiment = settings.mlflow_experiment or f"/Users/{workspace_client().current_user.me().user_name}/consensus-agent-feedback"
        mlflow.set_experiment(experiment)
        with mlflow.start_run(run_name=f"feedback-{body.rating}"):
            mlflow.log_params({"winner_model": body.winner_model, "rating": body.rating, "question": body.question[:250]})
            mlflow.log_metrics({"reliability": body.reliability, "thumbs_up": 1.0 if body.rating == "up" else 0.0})
            if body.sql:
                mlflow.log_text(body.sql, "winning_query.sql")
        return {"logged": True, "destination": f"MLflow · {experiment}"}
    except Exception as exc:
        logger.warning("MLflow feedback failed: %s", exc)
        return {"logged": False, "destination": "MLflow", "error": str(exc)[:200]}

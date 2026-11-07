"""/api/ask: governed, reviewed answers; /api/ask/uploads and /api/ask/datasets: the user's data."""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import io
import json
import logging
import re
import threading
import time
from functools import lru_cache

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Form, HTTPException, Request, Response, UploadFile
from sse_starlette.sse import EventSourceResponse

from backend.ask.cache import ResultCache, auth_key
from backend.ask import profiling, sql_guard
from backend.ask.contracts import AskRequest, AskResponse, AuthContext, DatasetRecord, ExportRequest, ModelOption, UploadResult
from backend.ask.ingest import IngestionService, UploadRejected, user_key
from backend.ask.models import ServingClient, model_workspace_client
from backend.ask.orchestrator import DatabricksData, Orchestrator
from backend.ask.registry import Registry
from backend.ask.review_queue import ReviewQueue
from backend.ask.settings import ConfigError, ask_settings, model_family
from backend.ask.tracing import Tracer
from backend.ask.warehouse import Execution, QueryError, execute
from backend.schemas import ColumnNode
from backend.ask.text import plain_error
from backend.services.sql_safety import UnsafeSqlError

logger = logging.getLogger("ask.api")
_NUMBER = re.compile(r"^-?\d[\d,]*(\.\d+)?([eE][+-]?\d+)?$")
router = APIRouter(prefix="/api")
_cache = ResultCache(ask_settings.cache_ttl_s)
_tracer = Tracer(ask_settings.mlflow_experiment)
SP_DISCLOSURE = ("Queries run as the app's service principal, not as you, so Unity Catalog applies the app's permissions. "
                 "Enable user authorization for the app and set USE_USER_TOKEN=true to enforce your own access.")


def _principal(request: Request) -> str | None:
    """The signed-in user, as Databricks Apps forwards it; None locally."""
    return request.headers.get("x-forwarded-email") or request.headers.get("x-forwarded-preferred-username") or request.headers.get("x-forwarded-user")


def _app_run(sql: str, parameters: dict[str, str | None] | None = None) -> Execution:
    """Backend-owned SQL (registry, ingestion, profiling) as the app; never model-written SQL."""
    return execute(_app_client(), sql, warehouse_id=ask_settings.warehouse_id, timeout_s=120, row_limit=10_000,
                   byte_limit=ask_settings.statement_byte_limit, parameters=parameters)


@lru_cache(maxsize=1)
def _app_client() -> WorkspaceClient:
    return WorkspaceClient()


@lru_cache(maxsize=1)
def _model_client() -> WorkspaceClient:
    return model_workspace_client(ask_settings.model_retry_window_s)


@lru_cache(maxsize=1)
def registry() -> Registry:
    return Registry(ask_settings, _app_run)


@lru_cache(maxsize=1)
def review_queue() -> ReviewQueue:
    return ReviewQueue(ask_settings.review_queue_table, _app_run)


def ingestion() -> IngestionService:
    return IngestionService(_app_client(), ask_settings, registry(), _app_run)


_swept_at = float("-inf")
_sweep_lock = threading.Lock()


def sweep_expired(every_s: int = 3600) -> None:
    """Drop expired uploads (tables, files, registry rows) at most hourly, and only while the app is in use: a timer
    would wake the SQL warehouse when nobody is. Expired uploads are hidden from listings and queries meanwhile."""
    global _swept_at
    with _sweep_lock:
        if time.monotonic() - _swept_at < every_s:
            return
        _swept_at = time.monotonic()
    threading.Thread(target=_sweep, daemon=True, name="upload-cleanup").start()


def _sweep() -> None:
    try:
        removed = ingestion().cleanup_expired()
        if removed:
            logger.info("Removed %d expired upload(s)", removed)
    except Exception as exc:
        logger.warning("Upload cleanup failed: %s", exc)


def _clients(request: Request) -> tuple[WorkspaceClient, AuthContext, str | None]:
    token = request.headers.get("x-forwarded-access-token")
    if ask_settings.use_user_token:
        if not token:
            raise HTTPException(401, "User authorization is required but no user token was forwarded.")
        return WorkspaceClient(host=_app_client().config.host, token=token, auth_type="pat"), AuthContext(mode="user"), token
    return _app_client(), AuthContext(mode="service_principal", disclosure=SP_DISCLOSURE), None


async def _watch_disconnect(request: Request, cancelled: threading.Event, done: asyncio.Event) -> None:
    while not done.is_set():
        if await request.is_disconnected():
            cancelled.set()  # stops further model calls and cancels the running warehouse statement
            return
        await asyncio.sleep(0.5)


def _orchestrator(request: Request, cancelled: threading.Event, on_event=None) -> Orchestrator:
    try:
        ask_settings.check()
    except ConfigError as exc:
        raise HTTPException(503, f"Misconfigured: {exc}") from exc
    data_w, auth, token = _clients(request)
    # Models are called as the app (users don't need endpoint access); data is read with the caller's credentials.
    return Orchestrator(ask_settings, DatabricksData(data_w, ask_settings, cancelled), ServingClient(_model_client(), ask_settings.efforts()),
                        auth, auth_key(token), _cache, _tracer, cancelled, registry=registry(), user_key=user_key(_principal(request)),
                        on_event=on_event, review=review_queue().put if ask_settings.review_queue_table else None)


def _check_model(body: AskRequest) -> None:
    if body.model and body.model not in ask_settings.model_choices:
        raise HTTPException(422, f"Model {body.model} isn't one of the models you can choose.")


_probes: dict[str, tuple[float, ModelOption]] = {}


def _probe(endpoint: str) -> ModelOption:
    """A tiny call, cached 15 minutes, so the picker can grey out models that can't answer (e.g. a provider out of credits)."""
    cached = _probes.get(endpoint)
    if cached and time.monotonic() - cached[0] < 900:
        return cached[1]
    try:
        ServingClient(_model_client(), retries=0).chat(endpoint, "Reply OK.", "OK", 16)
        option = ModelOption(id=endpoint, family=model_family(endpoint), available=True)
    except Exception as exc:
        option = ModelOption(id=endpoint, family=model_family(endpoint), available=False, note=plain_error(exc))
    _probes[endpoint] = (time.monotonic(), option)
    return option


@router.get("/ask/models", response_model=list[ModelOption])
async def models() -> list[ModelOption]:
    """Models the user can pick to answer; "Auto" (no pick) uses the configured Analyst."""
    return list(await asyncio.gather(*(asyncio.to_thread(_probe, e) for e in ask_settings.model_choices)))


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request) -> AskResponse:
    _check_model(body)
    cancelled, done = threading.Event(), asyncio.Event()
    orchestrator = _orchestrator(request, cancelled)
    watcher = asyncio.create_task(_watch_disconnect(request, cancelled, done))
    try:
        return await asyncio.wait_for(orchestrator.run(body), ask_settings.request_timeout_s)
    except asyncio.TimeoutError:
        cancelled.set()
        raise HTTPException(504, f"The question took longer than {ask_settings.request_timeout_s}s and was stopped.") from None
    except asyncio.CancelledError:
        logger.info("ask cancelled by the client")
        raise HTTPException(499, "Request cancelled.") from None
    finally:
        done.set()
        watcher.cancel()


@router.post("/ask/stream")
async def ask_stream(body: AskRequest, request: Request) -> EventSourceResponse:
    """Server-sent events: `stage` (running/succeeded/failed per step) as they happen, then one `result` or `error`.
    Closing the connection cancels the run, including the warehouse statement."""
    _check_model(body)
    cancelled, queue = threading.Event(), asyncio.Queue()
    orchestrator = _orchestrator(request, cancelled, on_event=queue.put_nowait)

    async def events():
        task = asyncio.create_task(asyncio.wait_for(orchestrator.run(body), ask_settings.request_timeout_s))
        try:
            while not task.done():
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    yield {"event": "stage", "data": getter.result().model_dump_json()}
                else:
                    getter.cancel()
            while not queue.empty():
                yield {"event": "stage", "data": queue.get_nowait().model_dump_json()}
            try:
                yield {"event": "result", "data": task.result().model_dump_json()}
            except asyncio.TimeoutError:
                yield {"event": "error", "data": json.dumps({"message": f"The question took longer than {ask_settings.request_timeout_s}s and was stopped."})}
            except Exception as exc:
                logger.exception("ask stream failed")
                yield {"event": "error", "data": json.dumps({"message": f"Something went wrong: {plain_error(exc)}"})}
        finally:
            cancelled.set()  # client went away or we finished: stop model calls and the warehouse statement
            task.cancel()

    return EventSourceResponse(events())


@router.post("/ask/export")
async def export_csv(body: ExportRequest, request: Request) -> Response:
    """Full result as CSV, re-run with the caller's credentials after the same access and SQL checks as /api/ask."""
    data_w, _, _ = _clients(request)
    owner = user_key(_principal(request))
    datasets = [d.lower() for d in body.datasets] or [ask_settings.default_dataset.lower()]
    if not all(registry().can_read(d, owner) for d in datasets):
        raise HTTPException(404, "Dataset not found or not available to you.")
    try:
        guarded = sql_guard.guard(body.sql, set(datasets))
        run = await asyncio.to_thread(execute, data_w, guarded.sql, warehouse_id=ask_settings.warehouse_id, timeout_s=ask_settings.statement_timeout_s,
                                      row_limit=ask_settings.export_max_rows, byte_limit=ask_settings.statement_byte_limit)
    except UnsafeSqlError as exc:
        raise HTTPException(422, str(exc)) from exc
    except QueryError as exc:
        raise HTTPException(502, str(exc)) from exc
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(run.result.columns)
    for row in run.result.rows:
        writer.writerow([_cell(row.get(c)) for c in run.result.columns])
    headers = {"Content-Disposition": 'attachment; filename="query-result.csv"', "X-Row-Count": str(run.result.row_count),
               "X-Truncated": str(run.result.truncated).lower()}
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


def _cell(value) -> str:
    """Spreadsheet-safe: a value starting with = + - @ would run as a formula in Excel, so it gets a leading quote."""
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "+", "@", "\t", "\r") or (text[:1] == "-" and not _NUMBER.match(text)):
        return "'" + text
    return text


@router.get("/ask/datasets", response_model=list[DatasetRecord])
async def datasets(request: Request) -> list[DatasetRecord]:
    """Shared datasets plus the caller's own uploads (never anyone else's), each with its profile and columns."""
    records = registry().visible(user_key(_principal(request)))
    sweep_expired()  # the listing just woke the warehouse anyway
    return [await asyncio.to_thread(_with_profile, r) if r.kind == "shared" else r for r in records]


def _with_profile(record: DatasetRecord) -> DatasetRecord:
    """Shared datasets are profiled once per table version (SQL, as the app) and cached."""
    try:
        table = _app_client().tables.get(record.dataset)
        version = str(table.updated_at or "")
        profile = registry().shared_profile(record.dataset, version)
        if profile is None:
            columns = [ColumnNode(name=c.name or "", type=c.type_text or "") for c in (table.columns or [])]
            profile = profiling.profile(_app_run, record.dataset, columns, [k for k in (record.key_columns, record.grain_columns) if k], record.date_column)
            registry().set_shared_profile(record.dataset, version, profile)
        refreshed = dt.datetime.fromtimestamp(table.updated_at / 1000, dt.timezone.utc).isoformat(timespec="seconds") if table.updated_at else None
        return record.model_copy(update={"profile": profile, "refreshed_at": refreshed})
    except Exception as exc:
        logger.warning("Profile of %s unavailable: %s", record.dataset, exc)
        return record


@router.post("/ask/uploads", response_model=UploadResult)
async def upload(request: Request, file: UploadFile, conversation_id: str = Form(""), sheet: str = Form("")) -> UploadResult:
    data = await file.read(ask_settings.upload_max_mb * 1024 * 1024 + 1)
    try:
        return await asyncio.to_thread(ingestion().upload, _principal(request), conversation_id or None, file.filename or "upload",
                                       file.content_type or "", data, sheet or None)
    except UploadRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception("Upload failed")
        raise HTTPException(502, f"The upload couldn't be stored: {plain_error(exc)}") from exc


@router.delete("/ask/uploads/{dataset}")
async def delete_upload(dataset: str, request: Request) -> dict[str, bool]:
    if not await asyncio.to_thread(ingestion().delete, _principal(request), dataset):
        raise HTTPException(404, "No such upload.")
    return {"deleted": True}

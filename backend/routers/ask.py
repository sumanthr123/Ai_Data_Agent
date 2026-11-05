"""/api/ask: governed, reviewed answers; /api/ask/uploads and /api/ask/datasets: the user's data."""

from __future__ import annotations

import asyncio
import logging
import threading
from functools import lru_cache

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from backend.ask.cache import ResultCache, auth_key
from backend.ask.contracts import AskRequest, AskResponse, AuthContext, DatasetRecord, UploadResult
from backend.ask.ingest import IngestionService, UploadRejected, user_key
from backend.ask.models import ServingClient
from backend.ask.orchestrator import DatabricksData, Orchestrator
from backend.ask.registry import Registry
from backend.ask.settings import ConfigError, ask_settings
from backend.ask.tracing import Tracer
from backend.ask.warehouse import Execution, execute
from backend.services.databricks_engine import _plain_error

logger = logging.getLogger("ask.api")
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
def registry() -> Registry:
    return Registry(ask_settings, _app_run)


def ingestion() -> IngestionService:
    return IngestionService(_app_client(), ask_settings, registry(), _app_run)


def cleanup_loop(stop: threading.Event, every_s: int = 3600) -> None:
    """Drop expired uploads (tables, files, registry rows) at startup and then hourly."""
    while not stop.is_set():
        try:
            removed = ingestion().cleanup_expired()
            if removed:
                logger.info("Removed %d expired upload(s)", removed)
        except Exception as exc:
            logger.warning("Upload cleanup failed: %s", exc)
        stop.wait(every_s)


def _clients(request: Request) -> tuple[WorkspaceClient, AuthContext, str | None]:
    token = request.headers.get("x-forwarded-access-token")
    if ask_settings.use_user_token:
        if not token:
            raise HTTPException(401, "User authorization is required but no user token was forwarded.")
        return WorkspaceClient(host=WorkspaceClient().config.host, token=token, auth_type="pat"), AuthContext(mode="user"), token
    return WorkspaceClient(), AuthContext(mode="service_principal", disclosure=SP_DISCLOSURE), None


async def _watch_disconnect(request: Request, cancelled: threading.Event, done: asyncio.Event) -> None:
    while not done.is_set():
        if await request.is_disconnected():
            cancelled.set()  # stops further model calls and cancels the running warehouse statement
            return
        await asyncio.sleep(0.5)


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request) -> AskResponse:
    try:
        ask_settings.check()
    except ConfigError as exc:
        raise HTTPException(503, f"Misconfigured: {exc}") from exc
    data_w, auth, token = _clients(request)
    cancelled, done = threading.Event(), asyncio.Event()
    # Models are called as the app (users don't need endpoint access); data is read with the caller's credentials.
    orchestrator = Orchestrator(ask_settings, DatabricksData(data_w, ask_settings, cancelled), ServingClient(WorkspaceClient(), ask_settings.efforts()),
                                auth, auth_key(token), _cache, _tracer, cancelled, registry=registry(), user_key=user_key(_principal(request)))
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


@router.get("/ask/datasets", response_model=list[DatasetRecord])
def datasets(request: Request) -> list[DatasetRecord]:
    """Shared datasets plus the caller's own uploads (never anyone else's)."""
    return registry().visible(user_key(_principal(request)))


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
        raise HTTPException(502, f"The upload couldn't be stored: {_plain_error(exc)}") from exc


@router.delete("/ask/uploads/{dataset}")
async def delete_upload(dataset: str, request: Request) -> dict[str, bool]:
    if not await asyncio.to_thread(ingestion().delete, _principal(request), dataset):
        raise HTTPException(404, "No such upload.")
    return {"deleted": True}

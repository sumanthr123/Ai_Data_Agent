"""POST /api/ask: one governed, reviewed answer per question (JSON)."""

from __future__ import annotations

import asyncio
import logging
import threading

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, HTTPException, Request

from backend.ask.cache import ResultCache, auth_key
from backend.ask.contracts import AskRequest, AskResponse, AuthContext
from backend.ask.models import ServingClient
from backend.ask.orchestrator import DatabricksData, Orchestrator
from backend.ask.settings import ConfigError, ask_settings
from backend.ask.tracing import Tracer

logger = logging.getLogger("ask.api")
router = APIRouter(prefix="/api")
_cache = ResultCache(ask_settings.cache_ttl_s)
_tracer = Tracer(ask_settings.mlflow_experiment)
SP_DISCLOSURE = ("Queries run as the app's service principal, not as you, so Unity Catalog applies the app's permissions. "
                 "Enable user authorization for the app and set USE_USER_TOKEN=true to enforce your own access.")


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
                                auth, auth_key(token), _cache, _tracer, cancelled)
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

"""Databricks-native Multi-Model Consensus AI Data Agent: FastAPI API + compiled React UI."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.routers import ask, catalog, consensus
from backend.services import availability

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Check which models really answer as soon as the app starts, so an unavailable one is never put on the council.
    stop = threading.Event()
    if not settings.mock_mode_default:
        from backend.services.databricks_engine import LiveEngine, workspace_client

        try:
            availability.refresh(LiveEngine(workspace_client()).probe)
        except Exception as exc:  # never block startup on the check
            logging.getLogger("consensus").warning("Availability check didn't start: %s", exc)
        threading.Thread(target=ask.cleanup_loop, args=(stop,), daemon=True, name="upload-cleanup").start()
    yield
    stop.set()


app = FastAPI(title="Consensus AI Data Agent", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
app.include_router(consensus.router)
app.include_router(ask.router)
app.include_router(catalog.router)

DIST = Path(__file__).parent / "frontend" / "dist"
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str) -> FileResponse:
    """Serve the React app; unknown paths fall back to index.html for client-side routing."""
    candidate = DIST / path
    if path and candidate.is_file():
        return FileResponse(candidate)
    index = DIST / "index.html"
    if not index.exists():
        from fastapi import HTTPException

        raise HTTPException(503, "Frontend not built. Run: cd frontend && npm install && npm run build")
    return FileResponse(index)

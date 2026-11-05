"""Databricks-native Multi-Model Consensus AI Data Agent: FastAPI API + compiled React UI."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.routers import ask, catalog, consensus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


app = FastAPI(title="Consensus AI Data Agent", docs_url="/api/docs", openapi_url="/api/openapi.json")
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

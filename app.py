"""AI Data Assistant: the governed /api/ask API (FastAPI) plus the compiled React UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.ask import logs
from backend.routers import ask

logs.setup()


app = FastAPI(title="AI Data Assistant", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(ask.router)


@app.get("/api/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}

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
    # Revalidate the page on every load so a deploy reaches users at once; the hashed /assets files never change.
    return FileResponse(index, headers={"Cache-Control": "no-cache"})

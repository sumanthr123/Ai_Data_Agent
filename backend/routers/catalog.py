"""Unity Catalog tree for the explorer rail."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

from backend.config import settings
from backend.schemas import CatalogTree
from backend.services import mock_consensus_stream as demo
from backend.services.databricks_engine import LiveEngine, workspace_client

router = APIRouter(prefix="/api")
_cache: dict[str, tuple[float, CatalogTree]] = {}


@router.get("/catalog/tree", response_model=CatalogTree)
def tree(request: Request, mode: str | None = None) -> CatalogTree:
    if (mode or ("demo" if settings.mock_mode_default else "live")) == "demo":
        return demo.catalog_tree()
    if "live" in _cache and time.monotonic() - _cache["live"][0] < 900:
        return _cache["live"][1]
    try:
        result = LiveEngine(workspace_client(request.headers.get("x-forwarded-access-token"))).catalog_tree()
    except Exception as exc:
        raise HTTPException(502, f"Unity Catalog: {str(exc)[:200]}") from exc
    _cache["live"] = (time.monotonic(), result)
    return result

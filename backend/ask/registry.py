"""Dataset registry: shared datasets (datasets.json) plus per-user uploads (a Delta table, shared by all workers).

Only backend code writes the registry, through the ingestion runner; model-written SQL never reaches it.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from backend.ask.contracts import DatasetRecord, Profile
from backend.ask.profiling import table_ref
from backend.ask.freshness import Policy
from backend.ask.settings import AskSettings
from backend.ask.warehouse import Execution

logger = logging.getLogger("ask.registry")
Runner = Callable[..., Execution]  # run(sql, parameters=None)
_STATIC = Path(__file__).with_name("datasets.json")


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Registry:
    def __init__(self, cfg: AskSettings, runner: Runner | None, refresh_s: int = 5) -> None:
        self.cfg, self.runner, self.refresh_s = cfg, runner, refresh_s
        self._lock = threading.Lock()
        self._uploads: dict[str, DatasetRecord] = {}
        self._loaded_at = 0.0
        self._profiles: dict[str, tuple[str, Profile]] = {}  # shared dataset -> (table version, profile)
        static = json.loads(_STATIC.read_text().replace("{prefix}", cfg.schema_prefix)) if _STATIC.exists() else {}
        static = {n: m for n, m in static.items() if not m.get("legacy") or n.lower() == cfg.default_dataset.lower()}  # the source being replaced is listed only for a rollback
        self.freshness = {name.lower(): Policy(**m["freshness"]) for name, m in static.items() if m.get("freshness")}
        self.shared = {name.lower(): DatasetRecord(dataset=name.lower(), kind="shared", source=name, description=m.get("description", ""),
                                                   grain=m.get("grain", ""), key_columns=m.get("key_columns", []),
                                                   grain_columns=m.get("grain_columns", []), date_column=m.get("date_column"),
                                                   join_keys=m.get("join_keys", {}), column_descriptions=m.get("columns", {}))
                       for name, m in static.items()}
        if cfg.default_dataset.lower() not in self.shared and not cfg.default_dataset.startswith("/Volumes/"):
            self.shared[cfg.default_dataset.lower()] = DatasetRecord(dataset=cfg.default_dataset.lower(), kind="shared", source=cfg.default_dataset)

    # ---- storage -----------------------------------------------------------------------------------------------

    def ensure_table(self) -> None:
        self._run(f"CREATE TABLE IF NOT EXISTS {table_ref(self.cfg.registry_table)} (dataset STRING NOT NULL, owner STRING, kind STRING, "
                  "record STRING, expires_at TIMESTAMP, updated_at TIMESTAMP) COMMENT 'AI Data Assistant dataset registry (app-managed)'")

    def _run(self, sql: str, parameters: dict[str, str | None] | None = None) -> Execution:
        if not self.runner:
            raise RuntimeError("The dataset registry has no writer configured.")
        return self.runner(sql, parameters=parameters)

    def _reload(self, force: bool = False) -> None:
        if not self.runner or (not force and time.monotonic() - self._loaded_at < self.refresh_s):
            return
        try:
            rows = self._run(f"SELECT record FROM {table_ref(self.cfg.registry_table)} WHERE kind = 'upload'").result.rows
        except Exception as exc:  # no registry table yet: no uploads
            logger.info("Registry not readable yet: %s", str(exc)[:200])
            rows = []
        uploads = {}
        for row in rows:
            record = DatasetRecord.model_validate_json(row["record"])
            uploads[record.dataset] = record
        with self._lock:
            self._uploads, self._loaded_at = uploads, time.monotonic()

    def save(self, record: DatasetRecord) -> None:
        self._run(f"""MERGE INTO {table_ref(self.cfg.registry_table)} t
USING (SELECT :dataset AS dataset, :owner AS owner, :kind AS kind, :record AS record,
              CAST(:expires_at AS TIMESTAMP) AS expires_at, current_timestamp() AS updated_at) s
ON t.dataset = s.dataset
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *""", {"dataset": record.dataset, "owner": record.owner, "kind": record.kind,
                                     "record": record.model_dump_json(), "expires_at": record.expires_at})
        with self._lock:
            self._uploads[record.dataset] = record

    def delete(self, dataset: str) -> None:
        self._run(f"DELETE FROM {table_ref(self.cfg.registry_table)} WHERE dataset = :dataset", {"dataset": dataset})
        with self._lock:
            self._uploads.pop(dataset, None)

    # ---- lookups -----------------------------------------------------------------------------------------------

    def get(self, dataset: str) -> DatasetRecord | None:
        name = dataset.lower()
        if name in self.shared:
            return self.shared[name]
        self._reload()
        if name not in self._uploads and time.monotonic() - self._loaded_at > 2:
            self._reload(force=True)  # registered by another worker a moment ago; throttled so unknown names can't each cost a query
        record = self._uploads.get(name)
        return None if record is None or self._expired(record) else record

    def can_read(self, dataset: str, user_key: str) -> bool:
        record = self.get(dataset)
        return bool(record and (record.kind == "shared" or record.owner == user_key))

    def visible(self, user_key: str) -> list[DatasetRecord]:
        self._reload(force=True)  # a listing must include an upload another worker registered a moment ago
        mine = [r for r in self._uploads.values() if r.owner == user_key and not self._expired(r)]
        return list(self.shared.values()) + sorted(mine, key=lambda r: r.created_at or "", reverse=True)

    def expired(self) -> list[DatasetRecord]:
        self._reload(force=True)
        return [r for r in self._uploads.values() if self._expired(r)]

    @staticmethod
    def _expired(record: DatasetRecord) -> bool:
        return bool(record.expires_at and dt.datetime.fromisoformat(record.expires_at) <= now())

    # ---- shared dataset profiles (computed in SQL, cached per table version) ------------------------------------

    def shared_profile(self, dataset: str, version: str) -> Profile | None:
        cached = self._profiles.get(dataset)
        return cached[1] if cached and cached[0] == version else None

    def set_shared_profile(self, dataset: str, version: str, profile: Profile) -> None:
        self._profiles[dataset] = (version, profile)

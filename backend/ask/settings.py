"""Settings for /api/ask, from environment variables (app.yaml on Databricks Apps, .env locally)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _json(name: str, default: dict) -> dict:
    raw = os.getenv(name, "")
    return json.loads(raw) if raw.strip() else default


# Endpoint name fragment -> model family. Analyst and Reviewer must come from different families.
_FAMILIES = {"gemini": "google", "gemma": "google", "claude": "anthropic", "gpt": "openai", "llama": "meta",
             "qwen": "alibaba", "mistral": "mistral", "mixtral": "mistral", "dbrx": "databricks"}

DEFAULT_DEFINITIONS = {
    "profit margin": "SUM(profit) / SUM(sales) over the filtered rows, never an average of row-level margins",
    "average order value": "SUM(sales) / COUNT(DISTINCT order_id)",
    "orders": "COUNT(DISTINCT order_id), not row counts",
    "sales": "SUM(sales) in the dataset's currency (USD assumed)",
}


def model_family(endpoint: str) -> str:
    name = endpoint.lower().rsplit("/", 1)[-1]
    return next((family for key, family in _FAMILIES.items() if key in name), name)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AskSettings:
    warehouse_id: str = os.getenv("DATABRICKS_SQL_WAREHOUSE_ID") or os.getenv("DATABRICKS_WAREHOUSE_ID", "")
    default_dataset: str = os.getenv("DEFAULT_DATASET_SOURCE", "ai_data_agent.orders.superstore")
    catalog: str = os.getenv("UC_CATALOG", "ai_data_agent")
    schema: str = os.getenv("UC_SCHEMA", "orders")
    upload_volume: str = os.getenv("UC_UPLOAD_VOLUME", "uploads")
    # Uploaded files become tables here; the dataset registry lives here too. Only the ingestion service writes to it.
    upload_schema: str = os.getenv("UC_UPLOAD_SCHEMA", "user_uploads")
    upload_max_mb: int = _int("UPLOAD_MAX_MB", 25)
    upload_max_columns: int = _int("UPLOAD_MAX_COLUMNS", 200)
    upload_max_sheets: int = _int("UPLOAD_MAX_SHEETS", 20)
    upload_max_rows: int = _int("UPLOAD_MAX_ROWS", 500_000)
    upload_ttl_hours: int = _int("UPLOAD_TTL_HOURS", 24)
    analyst: str = os.getenv("ANALYST_MODEL_ENDPOINT", "gemini-3-5-flash")
    reviewer: str = os.getenv("REVIEWER_MODEL_ENDPOINT", "databricks-gpt-oss-120b")
    adjudicator: str = os.getenv("ADJUDICATOR_MODEL_ENDPOINT", "gemini-3-5-flash/gemini-pro-latest")
    use_user_token: bool = os.getenv("USE_USER_TOKEN", "false").lower() in ("1", "true", "yes")
    # Hard budgets per question, enforced in code.
    max_model_calls: int = _int("MAX_MODEL_CALLS_PER_QUESTION", 6)
    max_sql_attempts: int = _int("MAX_SQL_ATTEMPTS", 3)
    max_total_tokens: int = _int("MAX_TOTAL_MODEL_TOKENS", 12000)
    max_rows_to_model: int = _int("MAX_RESULT_ROWS_TO_MODEL", 50)
    max_answer_words: int = _int("MAX_FINAL_ANSWER_WORDS", 250)
    max_rows_to_ui: int = _int("MAX_RESULT_ROWS_TO_UI", 500)
    statement_timeout_s: int = _int("STATEMENT_TIMEOUT_S", 45)
    statement_byte_limit: int = _int("STATEMENT_BYTE_LIMIT", 16 * 1024 * 1024)
    model_timeout_s: int = _int("ASK_MODEL_TIMEOUT_S", 60)
    cache_ttl_s: int = _int("RESULT_CACHE_TTL_S", 300)
    # Output tokens each role may use (reasoning models spend part of this thinking).
    analyst_max_out: int = _int("ANALYST_MAX_OUTPUT_TOKENS", 3000)
    reviewer_max_out: int = _int("REVIEWER_MAX_OUTPUT_TOKENS", 2500)
    adjudicator_max_out: int = _int("ADJUDICATOR_MAX_OUTPUT_TOKENS", 2500)
    # reasoning_effort sent to each role's endpoint (low keeps thinking tokens inside the budget); "" sends none.
    analyst_effort: str = os.getenv("ANALYST_REASONING_EFFORT", "low")
    reviewer_effort: str = os.getenv("REVIEWER_REASONING_EFFORT", "low")
    adjudicator_effort: str = os.getenv("ADJUDICATOR_REASONING_EFFORT", "")
    request_timeout_s: int = _int("ASK_REQUEST_TIMEOUT_S", 150)
    definitions: dict = field(default_factory=lambda: _json("BUSINESS_DEFINITIONS", DEFAULT_DEFINITIONS))
    # {"endpoint": [usd_per_1M_input, usd_per_1M_output]}; costs are reported only for endpoints listed here.
    prices: dict = field(default_factory=lambda: _json("MODEL_PRICES_JSON", {}))
    mlflow_experiment: str = os.getenv("MLFLOW_EXPERIMENT", "")

    @property
    def registry_table(self) -> str:
        return f"{self.catalog}.{self.upload_schema}.dataset_registry"

    def efforts(self) -> dict[str, str]:
        return {e: v for e, v in ((self.analyst, self.analyst_effort), (self.reviewer, self.reviewer_effort),
                                  (self.adjudicator, self.adjudicator_effort)) if v}

    def check(self) -> None:
        """Refuse to run a 'debate' between aliases of one model."""
        if not self.warehouse_id:
            raise ConfigError("DATABRICKS_SQL_WAREHOUSE_ID is not set.")
        if model_family(self.analyst) == model_family(self.reviewer):
            raise ConfigError(f"Analyst ({self.analyst}) and Reviewer ({self.reviewer}) must be different model families.")
        if self.adjudicator and self.adjudicator in (self.analyst, self.reviewer):
            raise ConfigError("Adjudicator must be a different endpoint from the Analyst and Reviewer.")


ask_settings = AskSettings()

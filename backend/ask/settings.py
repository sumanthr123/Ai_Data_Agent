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
    analyst: str = os.getenv("ANALYST_MODEL_ENDPOINT", "databricks-gpt-oss-120b")
    reviewer: str = os.getenv("REVIEWER_MODEL_ENDPOINT", "databricks-llama-4-maverick")
    adjudicator: str = os.getenv("ADJUDICATOR_MODEL_ENDPOINT", "databricks-qwen35-122b-a10b")
    # Tier 2 council: members draft SQL independently; the judge rotates to a family that didn't author the leading result.
    council_endpoints: tuple[str, ...] = tuple(e.strip() for e in os.getenv("COUNCIL_ENDPOINTS", "databricks-gpt-oss-120b,databricks-llama-4-maverick").split(",") if e.strip())
    # Tried once when the Analyst or Reviewer endpoint fails; never the same family as the other role.
    # Models the user may pick to answer (the Analyst); "Auto" uses ANALYST_MODEL_ENDPOINT.
    model_choices: tuple[str, ...] = tuple(e.strip() for e in os.getenv("MODEL_CHOICES", "databricks-gpt-oss-120b,databricks-llama-4-maverick,"
        "databricks-qwen35-122b-a10b,gemini-3-5-flash/gemini-3-5-flash,claude-sonnet-5-5/claude-sonnet-5-5").split(",") if e.strip())
    fallback_endpoints: tuple[str, ...] =tuple(e.strip() for e in os.getenv("FALLBACK_ENDPOINTS", "databricks-qwen35-122b-a10b").split(",") if e.strip())
    council_extra_tokens: int = _int("COUNCIL_EXTRA_TOKENS", 10000)
    council_extra_calls: int = _int("COUNCIL_EXTRA_CALLS", 4)
    use_user_token: bool = os.getenv("USE_USER_TOKEN", "false").lower() in ("1", "true", "yes")
    # "debate": Analyst + independent Reviewer (+ Adjudicator). "single": the Analyst alone, the evaluation baseline.
    review_mode: str = os.getenv("REVIEW_MODE", "debate")
    # Hard budgets per question, enforced in code.
    max_model_calls: int = _int("MAX_MODEL_CALLS_PER_QUESTION", 6)
    max_sql_attempts: int = _int("MAX_SQL_ATTEMPTS", 3)
    max_total_tokens: int = _int("MAX_TOTAL_MODEL_TOKENS", 12000)
    max_rows_to_model: int = _int("MAX_RESULT_ROWS_TO_MODEL", 50)
    max_answer_words: int = _int("MAX_FINAL_ANSWER_WORDS", 250)
    max_rows_to_ui: int = _int("MAX_RESULT_ROWS_TO_UI", 500)
    export_max_rows: int = _int("EXPORT_MAX_ROWS", 100_000)
    statement_timeout_s: int = _int("STATEMENT_TIMEOUT_S", 45)
    warehouse_start_grace_s: int = _int("WAREHOUSE_START_GRACE_S", 90)  # extra time while the warehouse starts or queues
    statement_byte_limit: int = _int("STATEMENT_BYTE_LIMIT", 16 * 1024 * 1024)
    model_timeout_s: int = _int("ASK_MODEL_TIMEOUT_S", 60)
    cache_ttl_s: int = _int("RESULT_CACHE_TTL_S", 300)
    # Output tokens each role may use (reasoning models spend part of this thinking).
    analyst_max_out: int = _int("ANALYST_MAX_OUTPUT_TOKENS", 3000)
    reviewer_max_out: int = _int("REVIEWER_MAX_OUTPUT_TOKENS", 2500)
    adjudicator_max_out: int = _int("ADJUDICATOR_MAX_OUTPUT_TOKENS", 2500)
    # reasoning_effort sent to each role's endpoint (low keeps thinking tokens inside the budget); "" sends none.
    analyst_effort: str = os.getenv("ANALYST_REASONING_EFFORT", "low")
    reviewer_effort: str = os.getenv("REVIEWER_REASONING_EFFORT", "")
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
                                  (self.adjudicator, self.adjudicator_effort)) if v} | \
            {e: "low" for e in self.council_endpoints if e not in (self.analyst, self.reviewer, self.adjudicator)}

    def check(self) -> None:
        """Refuse to run a 'debate' between aliases of one model."""
        if not self.warehouse_id:
            raise ConfigError("DATABRICKS_SQL_WAREHOUSE_ID is not set.")
        if model_family(self.analyst) == model_family(self.reviewer):
            raise ConfigError(f"Analyst ({self.analyst}) and Reviewer ({self.reviewer}) must be different model families.")
        if self.adjudicator and self.adjudicator in (self.analyst, self.reviewer):
            raise ConfigError("Adjudicator must be a different endpoint from the Analyst and Reviewer.")


ask_settings = AskSettings()

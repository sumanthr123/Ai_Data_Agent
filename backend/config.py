"""Settings, from environment variables (set in app.yaml on Databricks Apps)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class CouncilModel:
    endpoint: str
    name: str
    provider: str


# Databricks-hosted Foundation Model endpoints available in this workspace. To add Claude or
# Gemini, create an External Model endpoint and add "endpoint|Name|Provider" to COUNCIL_MODELS.
DEFAULT_COUNCIL = (
    "gemini-3-5-flash|Gemini 3.5 Flash|Google,"
    "databricks-gpt-oss-120b|GPT-OSS 120B|OpenAI open-weight,"
    "gemini-3-5-flash/gemini-flash-latest|Gemini Flash Latest|Google"
)


def _models() -> list[CouncilModel]:
    models = []
    for spec in _list("COUNCIL_MODELS", DEFAULT_COUNCIL):
        endpoint, name, provider = (spec.split("|") + ["", ""])[:3]
        models.append(CouncilModel(endpoint, name or endpoint, provider or "Databricks"))
    return models


@dataclass(frozen=True)
class Settings:
    warehouse_id: str = os.getenv("DATABRICKS_WAREHOUSE_ID", "3d46aa484790192c")
    catalog: str = os.getenv("UC_CATALOG", "ai_data_agent")
    schemas: list[str] = field(default_factory=lambda: _list("UC_SCHEMAS", "orders"))
    models: list[CouncilModel] = field(default_factory=_models)
    council_size: int = int(os.getenv("COUNCIL_SIZE", "3"))
    mock_mode_default: bool = os.getenv("MOCK_MODE", "true").lower() in ("1", "true", "yes")
    mlflow_experiment: str = os.getenv("MLFLOW_EXPERIMENT", "")
    use_user_token: bool = os.getenv("USE_USER_TOKEN", "false").lower() in ("1", "true", "yes")
    max_rows: int = int(os.getenv("MAX_RESULT_ROWS", "500"))
    model_timeout_s: float = float(os.getenv("MODEL_TIMEOUT_S", "90"))
    # Once all but one model have finished, wait at most this long for the last one before reporting it timed out.
    straggler_grace_s: float = float(os.getenv("STRAGGLER_GRACE_S", "20"))
    # "council": every question goes to the full council. "selective": one fast model first; the council is added
    # for data and web questions, and for general answers the first model isn't confident about.
    routing: str = os.getenv("ROUTING", "council")


settings = Settings()

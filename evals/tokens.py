"""Per-call token breakdown on a fixed question set (live models and warehouse). Web search is stubbed: it isn't a
Model Serving call and its cost doesn't depend on our prompts.

    DATABRICKS_CONFIG_PROFILE=<p> DATABRICKS_WAREHOUSE_ID=<id> .venv/bin/python -m evals.tokens [--repeat 2] [--label name]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import threading
from collections import defaultdict
from pathlib import Path

from databricks.sdk import WorkspaceClient

from backend.ask.cache import ResultCache
from backend.ask.contracts import AskRequest, AuthContext
from backend.ask.models import ServingClient
from backend.ask.orchestrator import DatabricksData, Orchestrator
from backend.ask.settings import AskSettings
from backend.ask.tracing import Tracer

QUESTIONS = [
    ("data", "What were total sales by region in 2017?", False),
    ("data", "What is the profit margin by segment?", False),
    ("data", "Which 5 customers had the highest sales?", False),
    ("why", "Why is Furniture margin so low in the Central region?", False),
    ("docs", "How long are uploaded files kept and how are they cleaned up?", False),
    ("code", "Write PySpark code to compute monthly sales from the superstore table", False),
    ("chat", "hi, what can you do?", False),
    ("council", "What is the profit margin by segment?", True),
]
STUB = lambda q: {"query": q, "retrieved_at": "-", "summary": "(stub)", "sources": []}  # noqa: E731


async def main(repeat: int, label: str) -> None:
    w, cfg = WorkspaceClient(), AskSettings()
    rows = []
    for _ in range(repeat):
        for kind, question, council in QUESTIONS:
            orch = Orchestrator(cfg, DatabricksData(w, cfg, threading.Event()), ServingClient(w, cfg.efforts()), AuthContext(mode="service_principal"),
                                "tokens", ResultCache(1), Tracer(""), search=STUB)
            r = await orch.run(AskRequest(question=question, datasets=[cfg.default_dataset], council=council))
            calls = [{"purpose": c.purpose, "prompt": c.prompt_tokens, "completion": c.completion_tokens, "reasoning": c.reasoning_tokens}
                     for c in r.verification.calls if c.status == "ok"]
            rows.append({"kind": kind, "question": question, "status": r.status, "reviewed": r.verification.reviewed,
                         "tokens": r.verification.total_tokens, "ms": r.total_ms, "calls": calls})
            print(f"{kind:8} {r.status:16} {r.verification.total_tokens:6} tok  {r.total_ms / 1000:5.1f}s  "
                  + " ".join(f"{c['purpose']}={c['prompt']}/{c['completion']}/{c['reasoning']}" for c in calls), flush=True)
    by_kind, by_part = defaultdict(list), defaultdict(int)
    for row in rows:
        by_kind[row["kind"]].append(row["tokens"])
        for c in row["calls"]:
            by_part["prompt"] += c["prompt"]
            by_part["completion"] += c["completion"]
            by_part["reasoning"] += c["reasoning"]
    total = sum(by_part.values())
    print("\nmean tokens by kind:", {k: round(statistics.mean(v)) for k, v in by_kind.items()})
    print("share:", {k: f"{v / total:.0%}" for k, v in by_part.items()}, "total", total)
    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    (out / f"tokens-{label}.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--label", default="run")
    args = parser.parse_args()
    asyncio.run(main(args.repeat, args.label))

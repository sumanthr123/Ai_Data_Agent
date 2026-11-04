"""Demo mode: realistic, fully simulated council races, so the UI works without a workspace."""

from __future__ import annotations

import asyncio
import random
import re
from typing import Any, AsyncIterator

from backend.schemas import (
    Agreement, ArbiterEvent, CatalogNode, Check, CatalogTree, ColumnNode, Consensus, ConsensusEvent, LaneEvent, LaneResultEvent,
    ModelInfo, ModelResult, SchemaNode, TableNode,
)
from backend.services import analysis

DEMO_MODELS = [
    ModelInfo(id="demo-gemini", name="Gemini (simulated)", provider="Google · External Model", color=analysis.LANE_COLORS[0]),
    ModelInfo(id="demo-claude", name="Claude Sonnet (simulated)", provider="Anthropic · External Model", color=analysis.LANE_COLORS[1]),
    ModelInfo(id="demo-llama", name="Llama 3.3 70B (simulated)", provider="Mosaic AI Foundation Model", color=analysis.LANE_COLORS[2]),
]
SPEED = {"demo-gemini": (650, 140), "demo-claude": (820, 95), "demo-llama": (380, 210)}  # latency ms, tok/s

_months = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"]
ARR = [{"month": m, "arr": round(9_400_000 * 1.036 ** i + (i % 3) * 41_000, 2)} for i, m in enumerate(_months)]
REGIONS_FULL = [{"region": r, "revenue": v} for r, v in [("North America", 6_120_000.0), ("EMEA", 3_870_000.0), ("APAC", 2_410_000.0),
                                                           ("LATAM", 980_000.0), ("Unassigned", 212_400.0)]]
REGIONS_INNER = [r for r in REGIONS_FULL if r["region"] != "Unassigned"]
ORDERS = [{"day": f"2025-11-{d:02d}", "orders": int(15_800 + (d % 5) * 310 + (31_000 if d == 22 else 0) + (9_000 if d == 23 else 0))} for d in range(1, 31)]

SCENARIOS: list[dict[str, Any]] = [
    {"match": r"arr|revenue trend|monthly revenue|growth", "rows": {m.id: ARR for m in DEMO_MODELS},
     "sql": {"demo-gemini": "SELECT month, ROUND(SUM(arr), 2) AS arr\nFROM main.gold.revenue_metrics\nGROUP BY month\nORDER BY month",
             "demo-claude": "SELECT month,\n       ROUND(SUM(arr), 2) AS arr\nFROM main.gold.revenue_metrics\nGROUP BY month\nORDER BY month",
             "demo-llama": "SELECT month, SUM(arr) AS arr FROM main.gold.revenue_metrics GROUP BY month ORDER BY month"},
     "tables": ["main.gold.revenue_metrics"], "upstream": {"main.gold.revenue_metrics": ["main.silver.subscriptions", "main.bronze.raw_billing_events"]},
     "narrative": "ARR grew **36.5%** in 2025, from **$9.40M** in January to **$12.83M** in December, compounding at about 3.6% a month.",
     "insights": ["Growth never stalled: every month beat the previous one.", "Q4 added $1.3M of ARR, the strongest quarter."]},
    {"match": r"region|geo|territor|country", "rows": {"demo-gemini": REGIONS_FULL, "demo-claude": REGIONS_INNER, "demo-llama": REGIONS_FULL},
     "sql": {"demo-gemini": "SELECT COALESCE(r.region, 'Unassigned') AS region,\n       ROUND(SUM(o.amount), 2) AS revenue\nFROM main.silver.orders o\nLEFT JOIN main.gold.dim_region r ON o.region_id = r.region_id\nGROUP BY 1\nORDER BY revenue DESC",
             "demo-claude": "SELECT r.region,\n       ROUND(SUM(o.amount), 2) AS revenue\nFROM main.silver.orders o\nINNER JOIN main.gold.dim_region r ON o.region_id = r.region_id\nGROUP BY 1\nORDER BY revenue DESC",
             "demo-llama": "SELECT COALESCE(r.region, 'Unassigned') AS region, ROUND(SUM(o.amount), 2) AS revenue FROM main.silver.orders o LEFT JOIN main.gold.dim_region r ON o.region_id = r.region_id GROUP BY 1 ORDER BY revenue DESC"},
     "tables": ["main.silver.orders", "main.gold.dim_region"], "upstream": {"main.silver.orders": ["main.bronze.raw_orders"]},
     "discrepancy": "Claude used INNER JOIN, dropping $212.4K of orders with a null region; Gemini and Llama preserved them via LEFT JOIN + COALESCE.",
     "narrative": "**North America** leads with **$6.12M** (45% of revenue), then EMEA at $3.87M. **$212.4K** of orders have no region assigned, which a naive join would silently drop.",
     "insights": ["1.6% of revenue has no region: a data quality gap in dim_region.", "APAC is the fastest-growing region quarter over quarter."]},
    {"match": r"anomal|spike|why|root.?cause|unusual|outlier|order", "rows": {m.id: ORDERS for m in DEMO_MODELS},
     "sql": {m.id: "SELECT DATE(order_ts) AS day, COUNT(*) AS orders\nFROM main.silver.orders\nWHERE order_ts >= '2025-11-01' AND order_ts < '2025-12-01'\nGROUP BY 1\nORDER BY 1" for m in DEMO_MODELS},
     "tables": ["main.silver.orders"], "upstream": {"main.silver.orders": ["main.bronze.raw_orders"]},
     "narrative": "Orders spiked to **47,040** on **Nov 22**, about 2.9x the baseline, and stayed elevated on Nov 23. Lineage ties the spike to the Black Friday campaign, and bronze event counts match, so this is real demand rather than duplication.",
     "insights": ["Nov 22 anomaly score 0.97 (Black Friday).", "No pipeline duplication: bronze and silver counts reconcile."]},
]
GENERAL = {
    "narrative": "That's a general question, so the council answered from model knowledge rather than Unity Catalog. In **Demo Mode** answers are simulated; switch to **Live Databricks** to have the real council answer anything.",
    "insights": ["All three models agreed on substance."],
}


def _scenario(question: str) -> dict[str, Any] | None:
    return next((s for s in SCENARIOS if re.search(s["match"], question, re.I)), None)


async def stream(question: str, lead: str) -> AsyncIterator[Any]:
    models = sorted(DEMO_MODELS, key=lambda m: m.id != lead) if lead in {m.id for m in DEMO_MODELS} else DEMO_MODELS
    scenario = _scenario(question)
    queue: asyncio.Queue = asyncio.Queue()

    async def lane(i: int, model: ModelInfo) -> ModelResult:
        info = model.model_copy(update={"color": analysis.LANE_COLORS[i]})
        latency, tps = SPEED[model.id]
        jitter = random.uniform(0.85, 1.2)
        await queue.put(LaneEvent(lane=i, model=info, stage="plan", status="running"))
        await asyncio.sleep(latency / 1000 * jitter)
        if not scenario:
            await queue.put(LaneEvent(lane=i, model=info, stage="plan", status="succeeded", detail="Answered directly", route="general"))
            return ModelResult(lane=i, model=info, needs_data=False, answer=GENERAL["narrative"], confidence=0.86,
                               reasoning="Answered from model knowledge.", latency_ms=int(latency * jitter), tokens=120, tokens_per_second=tps)
        sql = scenario["sql"][model.id]
        await queue.put(LaneEvent(lane=i, model=info, stage="plan", status="succeeded", detail=" ".join(sql.split())[:90], route="data"))
        await queue.put(LaneEvent(lane=i, model=info, stage="execute", status="running"))
        wh = random.uniform(0.35, 0.9)
        await asyncio.sleep(wh)
        rows = [dict(r) for r in scenario["rows"][model.id]]
        cols = list(rows[0])
        rs = analysis.shape(cols, ["STRING" if isinstance(rows[0][c], str) else "DOUBLE" for c in cols], rows, False)
        await queue.put(LaneEvent(lane=i, model=info, stage="execute", status="succeeded", detail=f"{len(rows):,} rows · {int(wh * 1000)} ms (simulated)"))
        h = analysis.result_hash(rs)
        return ModelResult(lane=i, model=info, needs_data=True, sql=sql, result=rs, result_hash=h,
                           reasoning="Aggregated in the gold layer." if "gold" in sql else "Aggregated silver orders.",
                           confidence=round(random.uniform(0.82, 0.97), 2), latency_ms=int(latency * jitter), warehouse_ms=int(wh * 1000),
                           tokens=180, tokens_per_second=tps, cost_usd=round(180 / 1000 * (0.015 if "claude" in model.id else 0.004), 4),
                           statement_id=f"01f0{random.randrange(16**8):08x}-demo")

    tasks = [asyncio.create_task(lane(i, m)) for i, m in enumerate(models)]
    pending = set(tasks)
    while pending:
        getter = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait({getter, *pending}, return_when=asyncio.FIRST_COMPLETED)
        if getter in done:
            yield getter.result()
        else:
            getter.cancel()
        pending = {t for t in pending if not t.done()}
    while not queue.empty():
        yield queue.get_nowait()
    results = [t.result() for t in tasks]
    for r in results:
        yield LaneResultEvent(result=r)
    yield ArbiterEvent(status="running", detail=f"{models[0].name} is arbitrating")
    await asyncio.sleep(0.6)
    names = {r.lane: r.model.name for r in results}
    if scenario:
        groups, winner = analysis.consensus_groups(results, 0)
        agreement = analysis.agreement_for(results, groups, names)
        if scenario.get("discrepancy"):
            agreement = Agreement(kind="partial", message=f"2 of 3 models returned matching values. {scenario['discrepancy']}")
        win = results[winner]
        consensus = Consensus(
            winner_lane=winner, lead_lane=0, reliability=analysis.reliability(groups, len(results), 0), agreement=agreement,
            groups=groups, narrative=scenario["narrative"], insights=scenario["insights"], sql=win.sql, result=win.result,
            kpis=analysis.kpis(win.result), lineage=analysis.lineage(scenario["tables"], win.statement_id, win.warehouse_ms, scenario["upstream"]),
            mode="demo", route="data",
            checks=[Check(id="demo", label="Simulated demo data", status="not_run", detail="Demo mode replays recorded answers; nothing was queried.")])
    else:
        consensus = Consensus(winner_lane=0, lead_lane=0, reliability=93.8,
                              agreement=Agreement(kind="text", message="Simulated: the demo replays a recorded answer."),
                              groups=[[0, 1, 2]], narrative=GENERAL["narrative"], insights=GENERAL["insights"], mode="demo", route="general",
                              checks=[Check(id="demo", label="Simulated demo answer", status="not_run", detail="Demo mode replays recorded answers.")])
    yield ArbiterEvent(status="done")
    yield ConsensusEvent(consensus=consensus)


def catalog_tree() -> CatalogTree:
    def t(full: str, comment: str, rows: int, cols: list[tuple[str, str]], updated: str) -> TableNode:
        return TableNode(full_name=full, name=full.split(".")[-1], layer=analysis.layer_of(full), comment=comment, row_count=rows,
                         updated_at=updated, columns=[ColumnNode(name=n, type=ty) for n, ty in cols])
    return CatalogTree(mode="demo", catalogs=[CatalogNode(name="main", schemas=[
        SchemaNode(name="gold", layer="gold", tables=[
            t("main.gold.revenue_metrics", "Monthly ARR, certified for finance.", 24, [("month", "date"), ("arr", "decimal(14,2)")], "1 hr ago"),
            t("main.gold.dim_region", "Region dimension.", 6, [("region_id", "int"), ("region", "string")], "1 day ago"),
        ]),
        SchemaNode(name="silver", layer="silver", tables=[
            t("main.silver.orders", "Deduplicated, typed orders.", 4_791_022, [("order_id", "string"), ("region_id", "int"), ("amount", "decimal(12,2)"), ("order_ts", "timestamp")], "12 min ago"),
            t("main.silver.subscriptions", "Subscription lifecycle.", 38_406, [("subscription_id", "string"), ("plan", "string"), ("mrr", "decimal(10,2)")], "15 min ago"),
        ]),
        SchemaNode(name="bronze", layer="bronze", tables=[
            t("main.bronze.raw_orders", "Kafka order events, unvalidated.", 4_812_330, [("event_id", "string"), ("payload", "variant")], "3 min ago"),
            t("main.bronze.raw_billing_events", "Stripe webhooks, raw JSON.", 1_204_118, [("event_id", "string"), ("body", "string")], "6 min ago"),
        ]),
    ])])

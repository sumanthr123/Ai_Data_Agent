"""The council graph's failure modes, and per-table freshness."""
import asyncio
import dataclasses
import datetime as dt
import unittest
import unittest.mock

from backend.ask import council_graph, freshness, sql_guard
from backend.ask.freshness import Policy
from backend.ask.registry import Registry
from backend.services import analysis
from backend.services.sql_safety import UnsafeSqlError
from backend.ask.warehouse import Execution, QueryError
from backend.tests.test_ask import CFG, GOOD, PLAN, TABLE, FakeData, run


def invoke(endpoints: list[str]) -> list[str]:
    seen: list[str] = []

    async def draft(e):
        return e

    async def verify(drafts):
        seen.extend(sorted(drafts))
        return "tally", "done"

    async def judge(tally):
        raise AssertionError("no quorum path must not reach the judge")

    asyncio.run(council_graph.build(draft, verify, judge).ainvoke({"endpoints": endpoints, "drafts": []}))
    return seen


class CouncilGraphTests(unittest.TestCase):
    def test_verify_waits_for_every_branch(self):
        self.assertEqual(invoke(["a", "b", "c"]), ["a", "b", "c"])

    def test_verify_runs_with_no_drafters(self):
        self.assertEqual(invoke([]), [])

    def test_a_slow_member_is_a_failed_vote_not_a_failed_run(self):
        cfg = dataclasses.replace(CFG, council_member_timeout_s=0)
        r, _, _ = run({cfg.analyst: [PLAN], cfg.reviewer: [PLAN]}, cfg=cfg, council=True)
        self.assertEqual(r.status, "UNRESOLVED")
        self.assertIn("timed out", [c.note for c in r.council.candidates])


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        freshness._cache.clear()

    def test_table_uses_history_and_is_cached_for_a_minute(self):
        details = analysis.shape(["col_name", "data_type"], ["STRING", "STRING"], [{"col_name": "Type", "data_type": "MANAGED"}], False)
        history = analysis.shape(["timestamp"], ["TIMESTAMP"], [{"timestamp": "2026-11-06 06:00:00"}], False)
        execute = unittest.mock.Mock(side_effect=[Execution(details, "s", 1), Execution(history, "s", 1)])
        self.assertEqual(freshness.last_commit("g.t", execute), "2026-11-06T06:00:00")
        freshness.last_commit("g.t", execute)
        self.assertEqual(execute.call_count, 2)

    def test_materialized_view_uses_last_refreshed(self):
        rows = [{"col_name": "Type", "data_type": "MATERIALIZED_VIEW"}, {"col_name": "Last Refreshed", "data_type": "2026-11-07T13:21:32Z"}]
        execute = unittest.mock.Mock(return_value=Execution(analysis.shape(["col_name", "data_type"], ["STRING", "STRING"], rows, False), "s", 1))
        self.assertEqual(freshness.last_commit("g.mv", execute), "2026-11-07T13:21:32Z")
        execute.assert_called_once()
        self.assertGreater(freshness.age_s("2026-11-07T13:21:32Z", dt.datetime(2026, 11, 7, 14, tzinfo=dt.timezone.utc)), 0)

    def test_unreadable_history_never_raises(self):
        self.assertIsNone(freshness.last_commit("g.mv", unittest.mock.Mock(side_effect=QueryError("nope"))))

    def test_required_freshness(self):
        self.assertEqual(freshness.required_s("What are sales today?"), 3600)
        self.assertEqual(freshness.required_s("Live order count"), 1)
        self.assertIsNone(freshness.required_s("Sales by region in 2017?"))

    def test_table_sla_overrides_the_default(self):
        data = FakeData()
        data.updated_at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat()
        fine, _, _ = run({CFG.analyst: [PLAN, GOOD], CFG.reviewer: [{"status": "APPROVED", "issues": [], "required_sql_fix": None}]}, data=data)
        self.assertNotIn("freshness", [c.name for c in fine.verification.checks])
        with unittest.mock.patch("backend.ask.registry.Registry.__init__", _with_sla):
            late, _, _ = run({CFG.analyst: [PLAN, GOOD], CFG.reviewer: [{"status": "APPROVED", "issues": [], "required_sql_fix": None}]}, data=data)
        self.assertIn("freshness", [c.name for c in late.verification.checks])

    def test_today_against_old_data_is_disclosed(self):
        approved = {"status": "APPROVED", "issues": [], "required_sql_fix": None}
        r, _, _ = run({CFG.analyst: [PLAN, GOOD], CFG.reviewer: [approved]}, question="What are sales by region today?")
        self.assertTrue(r.freshness_unmet)
        self.assertIn("ends 2017-12-30", r.answer)
        self.assertEqual(r.data_as_of[TABLE], "2017-12-30")


_real_init = __import__("backend.ask.registry", fromlist=["Registry"]).Registry.__init__


def _with_sla(self, *a, **k):
    _real_init(self, *a, **k)
    self.freshness = {TABLE: Policy(sla_s=60)}


class AgentGoldDatasetTests(unittest.TestCase):
    def test_schema_prefix_selects_dev_or_production_names(self):
        for prefix, name in (("", "ai_data_agent.agent_gold.orders"), ("dev_x_", "ai_data_agent.dev_x_agent_gold.orders")):
            registry = Registry(dataclasses.replace(CFG, schema_prefix=prefix), None)
            self.assertIn(name, registry.shared)
            self.assertEqual(registry.freshness[name].table, name.replace("agent_gold", "gold"))


class AgentGoldGuardTests(unittest.TestCase):
    ALLOWED = {"ai_data_agent.agent_gold.orders", "ai_data_agent.agent_gold.sales_metrics"}

    def test_metric_view_query_passes(self):
        sql = "SELECT region, MEASURE(total_sales) AS s FROM ai_data_agent.agent_gold.sales_metrics GROUP BY region"
        self.assertIn("MEASURE(total_sales)", sql_guard.guard(sql, self.ALLOWED).sql)

    def test_other_layers_are_rejected(self):
        for table in ("bronze.orders_raw", "silver.orders", "gold.orders", "agent_ops.deletion_requests"):
            for sql in (f"SELECT * FROM ai_data_agent.{table}", f"WITH x AS (SELECT * FROM ai_data_agent.{table}) SELECT * FROM x"):
                with self.subTest(sql=sql), self.assertRaises(UnsafeSqlError):
                    sql_guard.guard(sql, self.ALLOWED)

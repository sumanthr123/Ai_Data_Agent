"""The live pipeline with fake models, warehouse and web search: route-specific stages, failures, validation, formatting."""

import asyncio
import json
import time
import unittest
from unittest import mock

from backend.config import CouncilModel, settings
from backend.schemas import ColumnNode, TableNode
from backend.services import analysis, databricks_engine as engine_mod, web_search

MODELS = [CouncilModel("a", "Model A", "P"), CouncilModel("b", "Model B", "P"), CouncilModel("c", "Model C", "P")]
TABLE = TableNode(full_name="cat.orders.superstore", name="superstore", layer="gold", columns=[
    ColumnNode(name="order_date", type="date"), ColumnNode(name="region", type="string"),
    ColumnNode(name="sales", type="double"), ColumnNode(name="profit", type="double"),
    ColumnNode(name="country", type="string", comment="Always United States.")], updated_at="1793000000000")
GOOD = "SELECT region, SUM(sales) AS total_sales FROM cat.orders.superstore WHERE YEAR(order_date) = 2016 GROUP BY region"
WRONG_YEAR = "SELECT region, SUM(sales) AS total_sales FROM cat.orders.superstore WHERE YEAR(order_date) = 2017 GROUP BY region"
ROWS = {GOOD: [("West", 187480.18), ("East", 180685.82)], WRONG_YEAR: [("West", 250128.37), ("East", 213082.90)]}


def plan_data(sql):
    return json.dumps({"needs_data": True, "sql": sql, "reasoning": "r", "confidence": 0.9})


def plan_text(answer, confidence=0.9):
    return json.dumps({"needs_data": False, "reasoning": "r", "confidence": confidence}) + "\n---ANSWER---\n" + answer


class FakeEngine(engine_mod.LiveEngine):
    def __init__(self, plans, review=None, write=None, slow=()):
        super().__init__(w=None)  # type: ignore[arg-type]
        self.plans, self.review, self.write, self.slow = plans, review or {"candidates": []}, write, slow
        self.executed: list[str] = []

    def _chat(self, endpoint, system, user, max_tokens=4000, purpose="answer"):
        if endpoint in self.slow and purpose == "plan":
            time.sleep(1.5)
        if purpose == "plan":
            reply = self.plans[endpoint]
            if isinstance(reply, Exception):
                raise reply
            return reply, 10
        if purpose == "validate":
            return json.dumps(self.review), 10
        if purpose == "write":
            if self.write:
                return self.write, 10
            if "---ANSWER---" in system or "---ANSWER---" in user:
                return json.dumps({"insights": [], "agreement": "consistent"}) + "\n---ANSWER---\nWritten answer [1].", 10
            return json.dumps({"narrative": "West had the highest sales.", "insights": []}), 10
        if purpose == "answer":
            return "Verstappen won [1].", 10
        return "", 0

    def execute(self, sql):
        self.executed.append(sql)
        if "boom" in sql:
            raise RuntimeError("Warehouse: TABLE_OR_VIEW_NOT_FOUND")
        rows = [{"region": r, "total_sales": v} for r, v in ROWS.get(sql, ROWS[GOOD])]
        return analysis.shape(["region", "total_sales"], ["STRING", "DOUBLE"], rows, False), "stmt", 5

    def _coverage(self, table):
        return ("order_date", "2014-01-03", "2017-12-30", 9994)


def run(engine, question, lead="auto"):
    async def go():
        return [e async for e in engine.stream(question, lead)]
    with mock.patch.object(engine_mod, "council_for", return_value=MODELS), \
         mock.patch.object(engine_mod.schema_cache, "get", return_value=("- cat.orders.superstore", [TABLE])):
        return asyncio.run(go())


def lane_stages(events):
    return {(e.lane, e.stage, e.status) for e in events if e.type == "lane"}


def consensus(events):
    return next(e.consensus for e in events if e.type == "consensus")


class RouteStageTests(unittest.TestCase):
    def test_data_route_shows_only_database_stages(self):
        events = run(FakeEngine({m.endpoint: plan_data(GOOD) for m in MODELS}), "Total sales by region in 2016")
        stages = {s for _, s, _ in lane_stages(events)}
        self.assertEqual(stages, {"plan", "execute"})
        pipeline = [e.stage for e in events if e.type == "pipeline"]
        self.assertIn("compare", pipeline)
        self.assertIn("validate", pipeline)
        self.assertNotIn("search", pipeline)
        c = consensus(events)
        self.assertEqual(c.route, "data")
        self.assertEqual(c.agreement.kind, "match")
        self.assertEqual({k.id: k.status for k in c.checks}["agreement"], "passed")
        self.assertNotIn("verified", c.agreement.message.lower())
        self.assertEqual(c.data_context.filters, "YEAR(order_date) = 2016")
        self.assertIn("2014-01-03", c.data_context.coverage)
        self.assertIn("assumed to be USD", c.data_context.currency)

    def test_identical_queries_run_once(self):
        engine = FakeEngine({m.endpoint: plan_data(GOOD) for m in MODELS})
        c = consensus(run(engine, "Total sales by region in 2016"))
        self.assertEqual(len(engine.executed), 1)
        self.assertEqual((c.metrics.queries_executed, c.metrics.queries_reused), (1, 2))

    def test_general_route_has_no_warehouse_stage(self):
        events = run(FakeEngine({m.endpoint: plan_text("Spark is a distributed engine.") for m in MODELS}), "What is Spark?")
        self.assertEqual({s for _, s, _ in lane_stages(events)}, {"plan"})
        self.assertEqual(consensus(events).route, "general")

    def test_web_route_shows_search_and_answer_stages_with_resolved_sources(self):
        plans = {m.endpoint: json.dumps({"needs_web": True, "search_query": "latest F1 winner", "confidence": 0.9}) for m in MODELS}
        found = {"query": "q", "searched_at": "now", "retrieved_at": "2026-11-04 18:00 UTC", "summary": "Verstappen won.[1]",
                 "sources": [{"n": 1, "title": "Race report", "publisher": "Formula 1", "url": "https://formula1.com/a",
                              "published": "2026-11-01", "retrieved_at": "2026-11-04 18:00 UTC"}]}
        with mock.patch.object(web_search, "available", return_value=True), mock.patch.object(web_search, "search", return_value=found):
            events = run(FakeEngine(plans), "Who won the latest F1 race?")
        self.assertEqual({s for _, s, _ in lane_stages(events)}, {"plan", "answer"})
        self.assertIn("search", [e.stage for e in events if e.type == "pipeline"])
        c = consensus(events)
        self.assertEqual(c.sources[0].title, "Race report")
        self.assertEqual({k.id: k.status for k in c.checks}["citations"], "passed")


class LeadModelTests(unittest.TestCase):
    def test_chosen_model_writes_the_answer_when_its_result_matches(self):
        # Lane 0 is the model the user picked; lane 2 returned the same values plus an extra column.
        extra = "SELECT region, SUM(sales) AS total_sales, COUNT(*) AS n FROM cat.orders.superstore WHERE YEAR(order_date) = 2016 GROUP BY region"
        engine = FakeEngine({"a": plan_data(GOOD), "b": plan_data(GOOD), "c": plan_data(extra)})
        engine.execute = lambda sql: (analysis.shape(["region", "total_sales"] + (["n"] if "COUNT" in sql else []), ["STRING", "DOUBLE", "LONG"],
                                                     [{"region": r, "total_sales": v, **({"n": 5} if "COUNT" in sql else {})} for r, v in ROWS[GOOD]], False), "s", 1)
        c = consensus(run(engine, "Total sales by region in 2016", lead="a"))
        self.assertEqual(c.winner_lane, 0)


class FailureTests(unittest.TestCase):
    def test_one_model_fails_and_partial_results_are_kept(self):
        plans = {"a": plan_data(GOOD), "b": plan_data(GOOD), "c": RuntimeError("Your credit balance is too low")}
        events = run(FakeEngine(plans), "Total sales by region in 2016")
        self.assertIn((2, "plan", "failed"), lane_stages(events))
        self.assertNotIn((2, "execute", "succeeded"), lane_stages(events))
        c = consensus(events)
        checks = {k.id: k for k in c.checks}
        self.assertEqual(checks["execution"].status, "warning")
        self.assertIn("no credits", checks["execution"].detail)
        self.assertIsNotNone(c.result)

    def test_failed_query_is_reported_as_failed(self):
        plans = {"a": plan_data(GOOD), "b": plan_data(GOOD), "c": plan_data("SELECT boom FROM x")}
        events = run(FakeEngine(plans), "Total sales by region in 2016")
        self.assertIn((2, "execute", "failed"), lane_stages(events))
        self.assertNotIn((2, "execute", "succeeded"), lane_stages(events))

    def test_web_search_failure_does_not_invent_facts(self):
        plans = {m.endpoint: json.dumps({"needs_web": True, "search_query": "election results", "confidence": 0.9}) for m in MODELS}
        with mock.patch.object(web_search, "available", return_value=True), \
             mock.patch.object(web_search, "search", side_effect=RuntimeError("Web search failed (503)")):
            events = run(FakeEngine(plans), "Who is winning the election today?")
        c = consensus(events)
        self.assertIn("couldn't retrieve live information", c.narrative)
        self.assertEqual(c.sources, [])
        self.assertEqual({k.id: k.status for k in c.checks}["search"], "failed")
        self.assertNotIn("answer", {s for _, s, _ in lane_stages(events)})

    def test_slow_model_times_out_without_blocking_the_rest(self):
        plans = {m.endpoint: plan_data(GOOD) for m in MODELS}
        with mock.patch.object(type(settings), "straggler_grace_s", 0.3, create=True):
            object.__setattr__(settings, "straggler_grace_s", 0.3)
            try:
                events = run(FakeEngine(plans, slow=("c",)), "Total sales by region in 2016")
            finally:
                object.__setattr__(settings, "straggler_grace_s", 20.0)
        failed = [e for e in events if e.type == "lane" and e.lane == 2 and e.status == "failed"]
        self.assertTrue(failed and "Timed out" in failed[0].detail)
        self.assertEqual(consensus(events).agreement.kind, "match")


class ValidationTests(unittest.TestCase):
    def test_matching_models_with_wrong_date_filter_are_not_treated_as_correct(self):
        plans = {"a": plan_data(WRONG_YEAR), "b": plan_data(WRONG_YEAR), "c": plan_data(GOOD)}
        c = consensus(run(FakeEngine(plans), "Total sales by region in 2016"))
        self.assertEqual(c.winner_lane, 2)  # the minority query that matches the question wins
        self.assertIn("2016", c.sql)
        self.assertEqual({k.id: k.status for k in c.checks}["agreement"], "warning")
        self.assertIn("was not used", c.agreement.message)
        self.assertIn("Model C's result", c.agreement.message)

    def test_period_outside_coverage_reports_no_data(self):
        sql = "SELECT SUM(sales) AS total_sales FROM cat.orders.superstore WHERE YEAR(order_date) = 2021"
        c = consensus(run(FakeEngine({m.endpoint: plan_data(sql) for m in MODELS}), "What were total sales in 2021?"))
        self.assertIn("No data is available for 2021", c.narrative)
        self.assertNotIn("$", c.narrative)
        self.assertEqual(c.kpis, [])

    def test_strict_arithmetic_returns_only_the_number_without_models(self):
        engine = FakeEngine({})
        c = consensus(run(engine, "What is 17 × 23? Reply with just the number."))
        self.assertEqual(c.narrative, "391")
        self.assertEqual((c.route, c.insights, engine.usage), ("arithmetic", [], []))

    def test_strict_format_strips_commentary(self):
        plans = {m.endpoint: plan_text("The capital is Paris.") for m in MODELS}
        engine = FakeEngine(plans, write=json.dumps({"insights": ["extra"], "agreement": "consistent"}) + "\n---ANSWER---\nParis")
        c = consensus(run(engine, "What is the capital of France? Reply with just the name."))
        self.assertEqual((c.narrative, c.insights, c.strict_format), ("Paris", [], True))


class SelectiveRoutingTests(unittest.TestCase):
    def setUp(self):
        object.__setattr__(settings, "routing", "selective")

    def tearDown(self):
        object.__setattr__(settings, "routing", "council")

    def test_simple_general_question_uses_one_model(self):
        engine = FakeEngine({m.endpoint: plan_text("Python is a programming language.") for m in MODELS})
        events = run(engine, "Write a Python function that reverses a string")
        self.assertEqual({lane for lane, _, _ in lane_stages(events)}, {0})
        c = consensus(events)
        self.assertEqual((c.route, c.agreement.kind), ("general", "single"))
        self.assertIn("not cross-checked", next(k.label for k in c.checks if k.id == "agreement"))

    def test_data_question_starts_the_whole_council_at_once(self):
        events = run(FakeEngine({m.endpoint: plan_data(GOOD) for m in MODELS}), "Total sales by region in 2016")
        starts = [e.lane for e in events if e.type == "lane" and e.stage == "plan" and e.status == "running"]
        self.assertEqual(sorted(starts[:3]), [0, 1, 2])  # all three began before any finished

    def test_low_confidence_general_answer_escalates(self):
        plans = {m.endpoint: plan_text("Maybe.", confidence=0.4) for m in MODELS}
        events = run(FakeEngine(plans), "Explain monads simply")
        self.assertEqual({lane for lane, _, _ in lane_stages(events)}, {0, 1, 2})

    def test_web_question_plans_once_and_every_model_answers(self):
        plans = {m.endpoint: json.dumps({"needs_web": True, "search_query": "f1 winner", "confidence": 0.9}) for m in MODELS}
        found = {"query": "q", "searched_at": "now", "retrieved_at": "t", "summary": "Verstappen won.[1]",
                 "sources": [{"n": 1, "title": "Race", "publisher": "F1", "url": "https://formula1.com/a", "published": "", "retrieved_at": "t"}]}
        with mock.patch.object(web_search, "available", return_value=True), mock.patch.object(web_search, "search", return_value=found):
            events = run(FakeEngine(plans), "Who won the latest F1 race?")
        stages = lane_stages(events)
        self.assertEqual({lane for lane, s, _ in stages if s == "plan"}, {0})
        self.assertEqual({lane for lane, s, st in stages if s == "answer" and st == "succeeded"}, {0, 1, 2})


if __name__ == "__main__":
    unittest.main()

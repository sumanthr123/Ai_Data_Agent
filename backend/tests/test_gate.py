"""evals/gate.py thresholds on hand-made result rows."""

from __future__ import annotations

import unittest

from evals import gate


def row(cat: int, ok: bool, status: str = "ANSWERED", reviewed: bool = True, ms: int = 10_000, mode: str = "debate") -> dict:
    return {"category": cat, "mode": mode, "pass": ok, "status": [status], "reviewed": [reviewed], "ms": ms, "tokens": 1000}


GOOD = [row(c, True) for c in (1, 2, 7, 10, 11) for _ in range(10)] + [row(c, True, "NEEDS_CLARIFICATION", False) for c in (3, 8, 9)] + [row(5, True)]


class GateTests(unittest.TestCase):
    def test_passes_when_thresholds_hold(self):
        self.assertEqual(gate.failures(gate.metrics(GOOD, [{"category": 6, "pass": True}]), None), [])

    def test_confident_wrong_answers_fail(self):
        m = gate.metrics(GOOD + [row(1, False), row(1, False)], [])
        self.assertTrue(any(f.startswith("confident_wrong") for f in gate.failures(m, None)))

    def test_unreviewed_wrong_answer_is_not_confident_wrong(self):
        self.assertEqual(gate.metrics(GOOD + [row(1, False, reviewed=False)], [])["confident_wrong"], 0)

    def test_one_safety_failure_fails(self):
        m = gate.metrics(GOOD, [{"category": 6, "pass": False}])
        self.assertTrue(any(f.startswith("safety") for f in gate.failures(m, None)))

    def test_slow_p95_and_regression_fail(self):
        m = gate.metrics(GOOD + [row(1, True, ms=90_000) for _ in range(5)], [])
        bad = gate.failures(m, {"correctness": 1.0, "pass_rate": 1.0, **{k: None for k in ("sql_result_match", "safety", "abstention_appropriate", "route_correct")}})
        self.assertTrue(any(f.startswith("p95") for f in bad))
        m2 = gate.metrics(GOOD + [row(2, False, reviewed=False)] * 3, [])
        self.assertTrue(any("dropped" in f for f in gate.failures(m2, {"correctness": 1.0})))

    def test_missing_category_fails(self):
        self.assertTrue(any("missing" in f for f in gate.failures(gate.metrics([row(1, True)], []), None)))

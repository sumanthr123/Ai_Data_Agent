"""Pure logic: semantic comparison, requirement checks, strict formatting, arithmetic, citations, KPI labels."""

import unittest
from unittest import mock

from backend.schemas import ModelInfo, ModelResult
from backend.services import analysis, compare, validation, web_search
from backend.services.databricks_engine import _facts, clean_citations


def rs(columns, rows):
    return analysis.shape(columns, ["STRING" if isinstance(rows[0][c], str) else "DOUBLE" for c in columns] if rows else [], rows, False)


def lane(i, result=None, error=None, sql=""):
    return ModelResult(lane=i, model=ModelInfo(id=f"m{i}", name=f"M{i}", provider="p", color="#000"), needs_data=True,
                       result=result, error=error, sql=sql)


REGIONS = [("West", 725457.8245, 108418.4489), ("East", 678781.24, 91522.78), ("Central", 501239.89, 39706.36)]


class CompareTests(unittest.TestCase):
    def test_names_order_and_precision_are_ignored(self):
        a = rs(["region", "total_sales"], [{"region": r, "total_sales": round(s, 2)} for r, s, _ in REGIONS])
        b = rs(["Region", "sales"], [{"Region": r, "sales": s} for r, s, _ in reversed(REGIONS)])
        self.assertEqual(compare.compare_pair(a, b).relation, "match")

    def test_real_differences_beyond_rounding_conflict(self):
        a = rs(["region", "margin"], [{"region": "West", "margin": 27.05}, {"region": "East", "margin": 9.97}])
        b = rs(["region", "margin"], [{"region": "West", "margin": 27.0532}, {"region": "East", "margin": 9.9701}])
        c = rs(["region", "margin"], [{"region": "West", "margin": 27.15}, {"region": "East", "margin": 9.97}])
        self.assertEqual(compare.compare_pair(a, b).relation, "match")
        p = compare.compare_pair(a, c)
        self.assertEqual(p.relation, "conflict")
        self.assertIn("west", p.detail)

    def test_missing_field_is_not_a_conflict(self):
        full = rs(["region", "sales", "profit"], [{"region": r, "sales": s, "profit": p} for r, s, p in REGIONS])
        partial = rs(["region", "sales"], [{"region": r, "sales": s} for r, s, _ in REGIONS])
        lanes = [lane(0, full), lane(1, full), lane(2, partial)]
        result = compare.compare_results(lanes, {0: "A", 1: "B", 2: "C"}, validation.requested_fragments("sales and profit by region"))
        self.assertEqual(result.kind, "incomplete")
        self.assertEqual(result.missing, {2: ["profit"]})
        self.assertIn("omitted profit", result.notes[2])
        # When profit wasn't asked for, the extra column isn't something the others "omitted".
        self.assertEqual(compare.compare_results(lanes, {0: "A", 1: "B", 2: "C"}, validation.requested_fragments("sales by region")).kind, "match")

    def test_value_conflict_and_partial_majority(self):
        good = rs(["region", "sales"], [{"region": r, "sales": s} for r, s, _ in REGIONS])
        bad = rs(["region", "sales"], [{"region": r, "sales": s * (0.9 if r == "West" else 1)} for r, s, _ in REGIONS])
        result = compare.compare_results([lane(0, good), lane(1, good), lane(2, bad)], {0: "A", 1: "B", 2: "C"})
        self.assertEqual(result.kind, "partial")
        self.assertEqual(result.groups[0], [0, 1])
        self.assertIn("west", result.notes[2].lower())

    def test_different_row_sets_are_reported_separately_from_conflicts(self):
        top3 = rs(["region", "sales"], [{"region": r, "sales": s} for r, s, _ in REGIONS])
        top2 = rs(["region", "sales"], [{"region": r, "sales": s} for r, s, _ in REGIONS[:2]])
        result = compare.compare_results([lane(0, top3), lane(1, top2)], {0: "A", 1: "B"})
        self.assertEqual(result.kind, "different")

    def test_extra_identifier_column_still_aligns_rows(self):
        a = rs(["customer_id", "customer_name", "sales"], [{"customer_id": "SM-20320", "customer_name": "Sean Miller", "sales": 25043.05},
                                                          {"customer_id": "TC-20980", "customer_name": "Tamara Chand", "sales": 19052.22}])
        b = rs(["customer_name", "total_sales"], [{"customer_name": "Tamara Chand", "total_sales": 19052.22},
                                                 {"customer_name": "Sean Miller", "total_sales": 25043.05}])
        self.assertEqual(compare.compare_pair(a, b).relation, "match")

    def test_fraction_vs_percent_is_a_formatting_difference(self):
        a = rs(["region", "margin"], [{"region": "West", "margin": 0.1495}, {"region": "East", "margin": 0.1348}])
        b = rs(["region", "margin_pct"], [{"region": "West", "margin_pct": 14.95}, {"region": "East", "margin_pct": 13.48}])
        self.assertEqual(compare.compare_pair(a, b).relation, "scale")

    def test_failed_lane_is_not_disagreement(self):
        good = rs(["region", "sales"], [{"region": r, "sales": s} for r, s, _ in REGIONS])
        result = compare.compare_results([lane(0, good), lane(1, good), lane(2, error="boom")], {0: "A", 1: "B", 2: "C"})
        self.assertEqual(result.kind, "match")


class ValidationTests(unittest.TestCase):
    def test_wrong_year_filter_is_flagged(self):
        issues = validation.check_requirements("Total sales by region in 2016",
                                               "SELECT region, SUM(sales) FROM t WHERE YEAR(order_date) = 2017 GROUP BY region", None, (2014, 2017))
        self.assertTrue(any("2016" in i for i in issues))

    def test_period_outside_coverage(self):
        self.assertEqual(validation.out_of_coverage("What were sales in 2021?", (2014, 2017)), [2021])
        self.assertEqual(validation.out_of_coverage("Sales in 2016 vs 2021", (2014, 2017)), [])

    def test_margin_definition(self):
        avg = "SELECT region, AVG(profit / sales) AS margin FROM t GROUP BY region"
        right = "SELECT region, SUM(profit) / NULLIF(SUM(sales), 0) AS margin FROM t GROUP BY region"
        self.assertTrue(validation.check_requirements("profit margin by region", avg, None, None))
        self.assertFalse(validation.check_requirements("profit margin by region", right, None, None))

    def test_missing_requested_metric_and_empty_results(self):
        result = rs(["region", "sales"], [{"region": "West", "sales": 1.0}])
        self.assertTrue(any("profit" in i for i in validation.check_requirements("sales and profit by region", "SELECT 1", result, None)))
        empty = analysis.shape(["sales"], ["DOUBLE"], [], False)
        self.assertTrue(any("no rows" in i for i in validation.check_requirements("sales", "SELECT 1", empty, None)))

    def test_strict_format_and_arithmetic(self):
        q = "What is 17 × 23? Reply with just the number."
        self.assertTrue(validation.strict_format(q))
        self.assertEqual(validation.arithmetic(q), ("17 × 23", "391"))
        self.assertEqual(validation.apply_strict(q, "17 × 23 = 391"), "391")
        self.assertIsNone(validation.arithmetic("What is Spark?"))
        self.assertIsNone(validation.arithmetic("sales in 2016 by region"))
        self.assertFalse(validation.strict_format("What are total sales by region?"))

    def test_filters_are_extracted(self):
        sql = "SELECT region, SUM(sales) FROM t WHERE YEAR(order_date) = 2016 GROUP BY region HAVING SUM(sales) > 0"
        self.assertEqual(validation.filters(sql), "YEAR(order_date) = 2016 AND SUM(sales) > 0")


class FactsAndKpiTests(unittest.TestCase):
    def test_empty_and_null_are_not_zero(self):
        self.assertIn("NOT the same as zero", _facts(analysis.shape(["sales"], ["DOUBLE"], [], False)))
        nulls = analysis.shape(["region", "sales"], ["STRING", "DOUBLE"], [{"region": "West", "sales": None}], False)
        self.assertIn("NULL", _facts(nulls))

    def test_kpi_labels_state_the_grain_and_rates_are_not_summed(self):
        totals = rs(["region", "total_sales"], [{"region": r, "total_sales": s} for r, s, _ in REGIONS])
        labels = [k.label for k in analysis.kpis(totals)]
        self.assertIn("AVG SALES PER REGION", labels)
        margins = rs(["region", "profit_margin"], [{"region": "West", "profit_margin": 0.149}, {"region": "East", "profit_margin": 0.135}])
        labels = [k.label for k in analysis.kpis(margins)]
        self.assertFalse(any(label.startswith(("TOTAL", "AVG")) for label in labels))


class CitationTests(unittest.TestCase):
    def test_markers_follow_supported_claims_and_search_pages_are_dropped(self):
        text = "Max Verstappen won the race. Antonelli clinched the title."
        chunks = [{"web": {"uri": "https://redirect/1", "title": "formula1.com"}}, {"web": {"uri": "https://redirect/2", "title": "google.com"}}]
        supports = [{"segment": {"text": "Max Verstappen won the race."}, "groundingChunkIndices": [0, 1]},
                    {"segment": {"text": "Antonelli clinched the title."}, "groundingChunkIndices": [1]}]
        pages = [{"title": "Race report", "publisher": "Formula 1", "url": "https://formula1.com/a", "published": "2026-11-01"}, None]
        with mock.patch.object(web_search, "_resolve_all", return_value=pages):
            marked, sources = web_search.cite(text, chunks, supports, "2026-11-04 18:00 UTC")
        self.assertEqual(marked, "Max Verstappen won the race.[1] Antonelli clinched the title.")
        self.assertEqual([s["n"] for s in sources], [1])
        self.assertEqual(sources[0]["published"], "2026-11-01")

    def test_same_page_cited_twice_gets_one_number(self):
        chunks = [{"web": {"uri": "r1"}}, {"web": {"uri": "r2"}}]
        supports = [{"segment": {"text": "A."}, "groundingChunkIndices": [0]}, {"segment": {"text": "B."}, "groundingChunkIndices": [1]}]
        page = {"title": "Ballotpedia", "publisher": "Ballotpedia", "url": "https://ballotpedia.org/x", "published": ""}
        with mock.patch.object(web_search, "_resolve_all", return_value=[page, dict(page)]):
            marked, sources = web_search.cite("A. B.", chunks, supports, "t")
        self.assertEqual((marked, len(sources)), ("A.[1] B.[1]", 1))

    def test_search_result_urls_are_not_sources(self):
        self.assertTrue(web_search._is_search_page("https://www.google.com/search?q=election+results"))
        self.assertFalse(web_search._is_search_page("https://www.sos.state.tx.us/elections/results"))

    def test_invalid_citations_removed_and_uncited_figures_counted(self):
        text, uncited = clean_citations("Turnout was 61% [1]. Candidate A has 52.1% of votes counted [7]. The count continues.", 2)
        self.assertNotIn("[7]", text)
        self.assertEqual(uncited, 1)


if __name__ == "__main__":
    unittest.main()

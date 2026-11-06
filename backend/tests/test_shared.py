"""Tests for code shared with the old council engine: value comparison (the council) and web citations."""

import unittest
from unittest import mock

from backend.ask.text import clean_citations
from backend.services import analysis, compare, web_search


def rs(columns, rows):
    return analysis.shape(columns, ["STRING" if isinstance(rows[0][c], str) else "DOUBLE" for c in columns] if rows else [], rows, False)


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

    def test_extra_measure_and_different_rows(self):
        full = rs(["region", "sales", "profit"], [{"region": r, "sales": s, "profit": p} for r, s, p in REGIONS])
        partial = rs(["region", "sales"], [{"region": r, "sales": s} for r, s, _ in REGIONS])
        self.assertEqual(compare.compare_pair(full, partial).relation, "missing_fields")
        top2 = rs(["region", "sales"], [{"region": r, "sales": s} for r, s, _ in REGIONS[:2]])
        self.assertNotIn(compare.compare_pair(partial, top2).relation, ("match", "missing_fields", "scale"))


class NumberCheckTests(unittest.TestCase):
    def test_group_totals_are_supported_but_invented_figures_are_not(self):
        from backend.ask.text import unsupported_numbers
        rows = [{"month": m, "category": c, "sales": s} for m, c, s in
                [("2017-01", "Furniture", 5964.03), ("2017-01", "Technology", 16733.05), ("2017-02", "Furniture", 6866.34), ("2017-02", "Technology", 6027.02)]]
        result = rs(["month", "category", "sales"], rows)
        self.assertEqual(unsupported_numbers("February sales were $12,893.36 across categories.", result), [])  # 6866.34 + 6027.02
        self.assertEqual(unsupported_numbers("February sales were $13,500.00.", result), ["$13,500.00"])


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

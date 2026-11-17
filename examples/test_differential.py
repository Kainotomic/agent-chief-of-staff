"""Tests for differential.py. Run from this directory: python3 -m unittest -v test_differential"""
import unittest

import differential as df

OLD = {f"q{n}": [f"doc-{n}-{r}" for r in range(10)] for n in range(20)}


def table(changes):
    return {**OLD, **changes}.__getitem__


def ranked(new, bar=df.RankedBar(), counts=(lambda: 5, lambda: 5)):
    return df.compare_ranked(OLD, OLD.__getitem__, new, bar, *counts)


class Ranked(unittest.TestCase):
    def test_the_same_results_pass(self):
        report = ranked(OLD.__getitem__)
        self.assertTrue(report.passed, str(report))
        self.assertEqual(report.compared, 20)

    def test_one_different_top_result_fails_a_bar_of_all(self):
        report = ranked(table({"q3": ["doc-3-1", "doc-3-0"] + OLD["q3"][2:]}))
        self.assertFalse(report.passed)
        self.assertIn("top result the same on 19 of 20", str(report))

    def test_a_lower_top_bar_allows_it(self):
        report = ranked(table({"q3": ["doc-3-1", "doc-3-0"] + OLD["q3"][2:]}), df.RankedBar(same_top=0.95))
        self.assertTrue(report.passed, str(report))

    def test_overlap_at_the_bar_passes_and_below_it_fails(self):
        self.assertTrue(ranked(table({"q0": OLD["q0"][:8] + ["x", "y"]})).passed)
        report = ranked(table({"q0": OLD["q0"][:7] + ["x", "y", "z"]}))
        self.assertFalse(report.passed)
        self.assertIn("input 0: top 10 share 7, the bar needs 8", str(report))

    def test_a_short_old_list_needs_all_of_it(self):
        old = {"q": ["a", "b", "c"]}
        bar = df.RankedBar(equal_counts=False)
        self.assertTrue(df.compare_ranked(old, old.__getitem__, lambda q: ["a", "b", "c", "d"], bar).passed)
        self.assertFalse(df.compare_ranked(old, old.__getitem__, lambda q: ["a", "b"], bar).passed)

    def test_a_call_that_raises_is_a_failure_not_a_skip(self):
        def new(q):
            if q == "q5":
                raise TimeoutError
            return OLD[q]
        report = ranked(new)
        self.assertFalse(report.passed)
        self.assertIn("input 5: new raised TimeoutError", str(report))

    def test_a_result_that_is_not_a_list_fails(self):
        self.assertFalse(ranked(table({"q1": None})).passed)
        self.assertFalse(ranked(table({"q1": "doc-1-0"})).passed)

    def test_an_entry_that_is_not_an_id_fails_that_input_and_the_run_goes_on(self):
        seen = []

        def new(q):
            seen.append(q)
            return ["doc-1-0", {"id": "doc-1-1"}] if q == "q1" else OLD[q]
        report = ranked(new)
        self.assertFalse(report.passed)
        self.assertIn("input 1: new returned a dict entry, not a result id", str(report))
        self.assertEqual(len(seen), 20)
        self.assertEqual(len(report.failures), 1, str(report))

    def test_an_empty_old_result_fails(self):
        old = {"q": []}
        report = df.compare_ranked(old, old.__getitem__, old.__getitem__, df.RankedBar(equal_counts=False))
        self.assertFalse(report.passed)

    def test_no_inputs_pass_nothing(self):
        report = df.compare_ranked([], OLD.__getitem__, OLD.__getitem__, df.RankedBar(equal_counts=False))
        self.assertFalse(report.passed)

    def test_row_counts_must_match_and_be_given(self):
        self.assertIn("row counts differ: old 5, new 4", str(ranked(OLD.__getitem__, counts=(lambda: 5, lambda: 4))))
        report = df.compare_ranked(OLD, OLD.__getitem__, OLD.__getitem__, df.RankedBar())
        self.assertFalse(report.passed)
        self.assertIn("no count callables", str(report))

    def test_a_count_that_raises_fails(self):
        def boom():
            raise ConnectionError
        self.assertFalse(ranked(OLD.__getitem__, counts=(lambda: 5, boom)).passed)

    def test_the_report_names_its_bar(self):
        self.assertIn("min_overlap=8", str(ranked(OLD.__getitem__)))

    def test_a_bar_out_of_range_is_refused(self):
        for bad in (dict(same_top=0), dict(same_top=1.5), dict(k=0), dict(min_overlap=11), dict(min_overlap=0)):
            with self.assertRaises(ValueError, msg=bad):
                df.RankedBar(**bad)


class Exact(unittest.TestCase):
    CALLS = ["a", "b", "c"]

    def test_the_same_fields_pass(self):
        same = lambda c: {"status": 200, "model": "m-1", "latency_ms": 10}
        other = lambda c: {"status": 200, "model": "m-1", "latency_ms": 99}
        self.assertTrue(df.compare_exact(self.CALLS, same, other, ["status", "model"]).passed)

    def test_a_different_field_fails(self):
        report = df.compare_exact(self.CALLS, lambda c: {"status": 200, "model": "m-1"},
                                  lambda c: {"status": 200 if c != "b" else 502, "model": "m-1"}, ["status", "model"])
        self.assertFalse(report.passed)
        self.assertIn("input 1: status differs: old 200, new 502", str(report))

    def test_a_missing_field_fails_even_when_both_lack_it(self):
        report = df.compare_exact(self.CALLS, lambda c: {"status": 200}, lambda c: {"status": 200}, ["status", "model"])
        self.assertFalse(report.passed)

    def test_a_raise_or_a_non_dict_fails(self):
        def boom(c):
            raise OSError
        self.assertFalse(df.compare_exact(self.CALLS, lambda c: {"status": 200}, boom, ["status"]).passed)
        self.assertFalse(df.compare_exact(self.CALLS, lambda c: {"status": 200}, lambda c: [200], ["status"]).passed)

    def test_no_fields_or_no_inputs(self):
        with self.assertRaises(ValueError):
            df.compare_exact(self.CALLS, dict, dict, [])
        self.assertFalse(df.compare_exact([], dict, dict, ["status"]).passed)


if __name__ == "__main__":
    unittest.main()

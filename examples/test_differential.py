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

    def test_each_adapter_sees_the_original_nested_input(self):
        request = {"query": ["requested"]}

        def old(item):
            item["query"][0] = "fallback"
            return ["fallback"]

        bar = df.RankedBar(k=1, min_overlap=1, equal_counts=False)
        report = df.compare_ranked([request], old, lambda item: item["query"], bar)
        self.assertFalse(report.passed, str(report))
        self.assertIn("top result the same on 0 of 1", str(report))
        self.assertEqual(request, {"query": ["requested"]})

    def test_reused_ranked_buffer_preserves_the_old_result(self):
        buffer = ["old"]

        def new(item):
            buffer[:] = ["new"]
            return buffer

        bar = df.RankedBar(k=1, min_overlap=1, equal_counts=False)
        report = df.compare_ranked(["q"], lambda item: buffer, new, bar)
        self.assertFalse(report.passed, str(report))
        self.assertIn("top result the same on 0 of 1", str(report))

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

    def test_a_none_entry_is_not_a_result_id(self):
        old = {"q": ["a"]}
        bar = df.RankedBar(k=2, min_overlap=1, equal_counts=False)
        report = df.compare_ranked(old, old.__getitem__, lambda q: ["a", None], bar)
        self.assertFalse(report.passed)
        self.assertIn("new returned a NoneType entry", str(report))

    def test_an_invalid_id_after_top_k_fails_on_either_side(self):
        bar = df.RankedBar(k=1, min_overlap=1, equal_counts=False)
        valid, invalid = lambda q: ["a"], lambda q: ["a", None]
        for side, old, new in (("old", invalid, valid), ("new", valid, invalid)):
            with self.subTest(side=side):
                report = df.compare_ranked(["q"], old, new, bar)
                self.assertFalse(report.passed, str(report))
                self.assertIn(f"{side} returned a NoneType entry", str(report))

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

    def test_invalid_row_counts_fail_before_equality(self):
        cases = ((None, None, ("old", "new")), (-1, -1, ("old", "new")),
                 (5.0, 5, ("old",)), (0, False, ("new",)), ("5", "5", ("old", "new")),
                 (5, -1, ("new",)))
        for old, new, invalid_sides in cases:
            with self.subTest(old=old, new=new):
                report = ranked(OLD.__getitem__, counts=(lambda: old, lambda: new))
                self.assertFalse(report.passed, str(report))
                for side in invalid_sides:
                    self.assertIn(f"{side} row count must be a nonnegative integer", str(report))
                self.assertNotIn("row counts differ", str(report))

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

    def test_each_adapter_sees_the_original_nested_input(self):
        request = {"query": ["requested"]}

        def old(item):
            item["query"][0] = "fallback"
            return {"model": "fallback"}

        report = df.compare_exact([request], old, lambda item: {"model": item["query"][0]}, ["model"])
        self.assertFalse(report.passed, str(report))
        self.assertIn("model differs: old 'fallback', new 'requested'", str(report))
        self.assertEqual(request, {"query": ["requested"]})

    def test_reused_exact_response_preserves_the_old_fields(self):
        buffer = {"model": "old"}

        def new(item):
            buffer["model"] = "new"
            return buffer

        report = df.compare_exact(["q"], lambda item: buffer, new, ["model"])
        self.assertFalse(report.passed, str(report))
        self.assertIn("model differs: old 'old', new 'new'", str(report))

    def test_reused_nested_field_preserves_the_old_value(self):
        models = ["old"]

        def new(item):
            models[:] = ["new"]
            return {"models": models}

        report = df.compare_exact(["q"], lambda item: {"models": models}, new, ["models"])
        self.assertFalse(report.passed, str(report))
        self.assertIn("models differs: old ['old'], new ['new']", str(report))

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

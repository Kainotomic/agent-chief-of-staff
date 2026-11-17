#!/usr/bin/env python3
"""Differential check before a cutover: run the same inputs through the old and the new service and judge the result
against a pass bar fixed before the first call (docs/verification.md).

Rules this sketch implements:
  - the bar is an argument of the run, so it is set before any result exists; the report carries it, so a reader
    sees what the result was judged against;
  - every input goes to both services: a call that raises, or returns something of the wrong shape (a ranked list
    with an entry that is not a result id), is a failure on that input, never a skip, and the run goes on;
  - no inputs, or no comparable result, is a failure: a comparison of nothing passes nothing;
  - ranked results (a memory service's recall) pass when the top result matches on the required share of inputs,
    the top k overlap by at least min_overlap on every input (or all of the old top k, when it holds fewer), and
    the row counts are equal when count callables are given;
  - exact results (a model gateway) pass when every listed field is present and equal on both sides, every call.

Standard library only. Inject the two services as callables: input -> result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True)
class RankedBar:
    same_top: float = 1.0   # share of inputs whose first result must be the same (1.0 = all of them)
    k: int = 10             # how many top results to compare
    min_overlap: int = 8    # of the top k, at least this many shared, on every input
    equal_counts: bool = True

    def __post_init__(self):
        if not 0 < self.same_top <= 1 or self.k < 1 or not 0 < self.min_overlap <= self.k:
            raise ValueError(f"bar out of range: {self}")


@dataclass
class Report:
    bar: object
    compared: int = 0
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.compared > 0 and not self.failures

    def __str__(self) -> str:
        head = f"{'PASS' if self.passed else 'FAIL'}: {self.compared} compared against {self.bar}"
        return "\n".join([head, *(f"  fail: {f}" for f in self.failures), *(f"  note: {n}" for n in self.notes)])


def _call(service: Callable, item, side: str, i: int):
    try:
        return service(item), None
    except Exception as error:  # a failed call is a finding, not a skip
        return None, f"input {i}: {side} raised {type(error).__name__}"


def compare_ranked(inputs: Iterable, old: Callable[[object], Sequence], new: Callable[[object], Sequence],
                   bar: RankedBar, count_old: Callable[[], int] | None = None,
                   count_new: Callable[[], int] | None = None) -> Report:
    """old(item) and new(item) return result ids (strings or integers), best first."""
    report, same_top, ranked = Report(bar), 0, 0
    for i, item in enumerate(inputs):
        report.compared += 1
        a, problem_a = _call(old, item, "old", i)
        b, problem_b = _call(new, item, "new", i)
        problems = [p for p in (problem_a, problem_b) if p]
        for side, value in (("old", a), ("new", b)):
            if not problems and not isinstance(value, (list, tuple)):
                problems.append(f"input {i}: {side} returned {type(value).__name__}, not a ranked list")
            elif not problems:
                bad = next((r for r in value[:bar.k] if not isinstance(r, (str, int))), None)
                if bad is not None:
                    problems.append(f"input {i}: {side} returned a {type(bad).__name__} entry, not a result id")
        if problems:
            report.failures += problems
            continue
        a, b = list(a)[:bar.k], list(b)[:bar.k]
        if not a:
            report.failures.append(f"input {i}: old returned nothing, so there is nothing to match")
            continue
        ranked += 1
        if b and a[0] == b[0]:
            same_top += 1
        need = min(bar.min_overlap, len(a))
        shared = len(set(a) & set(b))
        if shared < need:
            report.failures.append(f"input {i}: top {bar.k} share {shared}, the bar needs {need}")
    if ranked and same_top < bar.same_top * ranked - 1e-9:  # float slack: 0.95 of 20 is 19
        report.failures.append(f"top result the same on {same_top} of {ranked}, the bar needs {bar.same_top:.0%}")
    if bar.equal_counts:
        if count_old is None or count_new is None:
            report.failures.append("the bar needs equal row counts, but no count callables were given")
        else:
            try:
                n_old, n_new = count_old(), count_new()
            except Exception as error:
                report.failures.append(f"row count raised {type(error).__name__}")
            else:
                if n_old != n_new:
                    report.failures.append(f"row counts differ: old {n_old}, new {n_new}")
                report.notes.append(f"row counts: old {n_old}, new {n_new}")
    return report


def compare_exact(inputs: Iterable, old: Callable[[object], dict], new: Callable[[object], dict],
                  fields: Sequence[str]) -> Report:
    """old(item) and new(item) return a dict; every name in fields must be present and equal on both sides."""
    if not fields:
        raise ValueError("compare_exact needs at least one field to compare")
    report = Report(f"fields equal: {', '.join(fields)}")
    for i, item in enumerate(inputs):
        report.compared += 1
        a, problem_a = _call(old, item, "old", i)
        b, problem_b = _call(new, item, "new", i)
        problems = [p for p in (problem_a, problem_b) if p]
        if problems:
            report.failures += problems
            continue
        for name in fields:
            if not isinstance(a, dict) or not isinstance(b, dict) or name not in a or name not in b:
                report.failures.append(f"input {i}: {name!r} missing on one side")
            elif a[name] != b[name]:
                report.failures.append(f"input {i}: {name} differs: old {a[name]!r}, new {b[name]!r}")
    return report


if __name__ == "__main__":
    docs = {f"q{n}": [f"doc-{n}-{r}" for r in range(10)] for n in range(20)}
    drifted = {q: r[:8] + ["doc-x", "doc-y"] for q, r in docs.items()}
    print(compare_ranked(docs, docs.__getitem__, drifted.__getitem__, RankedBar(), lambda: 400, lambda: 400))
    swapped = dict(drifted, q3=["doc-3-1", "doc-3-0"] + drifted["q3"][2:])
    print(compare_ranked(docs, docs.__getitem__, swapped.__getitem__, RankedBar(), lambda: 400, lambda: 399))
    calls = ["hello", "summarise this"]
    print(compare_exact(calls, lambda c: {"status": 200, "model": "model-a"},
                        lambda c: {"status": 200, "model": "model-a" if c == "hello" else "model-b"}, ["status", "model"]))

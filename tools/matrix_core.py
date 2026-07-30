"""Pure numeric core of the invocation matrix.

Split from run_matrix.py on purpose: what the limit is, what verdict a runtime
implies, and what counts as a hole are the decisions that must be right, and
they are testable without compiling anything or running a clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_FLOOR_MS = 1000
DEFAULT_STEP_MS = 500


@dataclass(frozen=True)
class Limits:
    t_main_ms: int
    tl_ms: int
    kill_ms: int


def compute_limits(
    t_main_per_test: dict[str, int],
    floor_ms: int = DEFAULT_FLOOR_MS,
    step_ms: int = DEFAULT_STEP_MS,
) -> Limits:
    """TL = max(2 x slowest model run, floor), rounded up to a human number.

    The floor exists because with t_main at 8 ms a 16 ms limit is nonsense:
    process startup alone is ~2 ms and scheduler noise dominates.
    """
    if not t_main_per_test:
        raise ValueError("cannot compute limits without any model-solution timings")
    t_main = max(t_main_per_test.values())
    raw = max(2 * t_main, floor_ms)
    tl = int(math.ceil(raw / step_ms) * step_ms)
    return Limits(t_main_ms=t_main, tl_ms=tl, kill_ms=2 * tl)


@dataclass(frozen=True)
class Outcome:
    verdict: str
    banded: bool


def classify(
    time_ms: int, killed: bool, checker_verdict: str, limits: Limits
) -> Outcome:
    """Turn a runtime plus a checker verdict into a per-test outcome.

    Time is decided before correctness: a judge stops a solution at the limit,
    so the checker never runs on one that exceeded it. `banded` marks the
    (TL, kill] zone — strictly over TL, open on that end, since a run
    exactly at TL is accepted (see the `>` below, not `>=`) — where the
    result is too close to call on other hardware.
    """
    if killed:
        return Outcome("TL", banded=False)
    if time_ms > limits.tl_ms:
        return Outcome("TL", banded=time_ms <= limits.kill_ms)
    if checker_verdict == "FAIL":
        return Outcome("FAIL", banded=False)
    return Outcome(checker_verdict, banded=False)


# Worst-first. FAIL is a package bug and must never be masked by a solution's
# own failure; TL outranks WA because the judge stops before the checker runs.
_SEVERITY = ["FAIL", "TL", "ML", "RE", "PE", "WA", "OK"]

_FAILING = {"WA", "TL", "ML", "PE", "RE"}


def group_verdict(per_test: list[str]) -> str:
    """Collapse a group's per-test verdicts into the one the judge would report."""
    if not per_test:
        raise ValueError("a group must contain at least one test")
    for verdict in _SEVERITY:
        if verdict in per_test:
            return verdict
    raise ValueError(f"unknown verdicts in group: {sorted(set(per_test))}")


def compare(
    expected: dict[str, dict[str, str]],
    actual: dict[str, dict[str, str]],
) -> tuple[list[dict], list[dict]]:
    """Split every disagreement into holes and mismatches.

    A hole is the suite's failure: a solution declared wrong that nothing
    caught. A mismatch is everything else that differed, which is where an
    accepted solution disagreeing with the model shows up.
    """
    holes: list[dict] = []
    mismatches: list[dict] = []

    for solution in sorted(expected):
        for group in expected[solution]:
            want = expected[solution][group]
            got = actual.get(solution, {}).get(group)
            if want == got:
                continue
            record = {
                "solution": solution,
                "group": group,
                "expected": want,
                "actual": got,
            }
            if want in _FAILING and got == "OK":
                holes.append(record)
            else:
                mismatches.append(record)

    return holes, mismatches

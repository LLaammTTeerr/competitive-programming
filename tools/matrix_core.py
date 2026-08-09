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
# own failure; NO_OUTPUT is the same category — the harness could not evaluate
# the run at all (the process exited cleanly and never wrote its output file,
# usually a wrong filename rather than a wrong algorithm), so it must not be
# masked either. TL outranks WA because the judge stops before the checker runs.
_SEVERITY = ["FAIL", "NO_OUTPUT", "TL", "ML", "RE", "PE", "WA", "OK"]

# Verdicts an author can DECLARE for a solution. NO_OUTPUT and FAIL are
# absent by design: both are discovered by the harness, never declared.
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


# How much a CPU-time measurement may be inflated by other sandboxes running
# on the same machine. Measured under isolate on an 8-thread box, median of
# the concurrent cohort against a serial baseline:
#
#   workers   2      3      4      6      8
#   CPU-bound 1.08x  1.10x  1.15x  1.18x  1.27x
#   mem-bound 1.04x  1.04x  1.21x  1.48x  1.65x (1.92x in a second run)
#
# 1.5 covers the 4-worker figures with real headroom. It must stay strictly
# below 2.0 and that is not a style preference: `kill_ms` is always
# `2 * tl_ms`, so a kernel kill implies a genuine over-limit run only while
# `kill_ms / bound > tl_ms`. At bound >= 2 every killed run becomes
# ambiguous, the serial tail swallows the whole speedup, and the argument
# this function rests on stops holding.
CONTENTION_BOUND = 1.5


def needs_serial_retime(
    time_ms: int, killed: bool, limits: Limits, bound: float = CONTENTION_BOUND
) -> bool:
    """Was this measurement taken close enough to TL that contention could
    have decided it?

    Contention is **one-sided**: isolate reports the sandboxed process's own
    CPU time, and a neighbouring box can only add to it — nothing another
    sandbox does makes a process consume less CPU than it would alone. So a
    measurement `T` taken under a contention bound `F` implies a true serial
    time in `[T/F, T]`, and only one interval is undecidable:

        T <= tl_ms      -> true <= T <= tl_ms   -> genuinely not TL
        T > F * tl_ms   -> true >= T/F > tl_ms  -> genuinely TL
        otherwise       -> undecidable, re-time serially

    `killed` short-circuits to False because isolate kills at `kill_ms`,
    which `compute_limits` fixes at `2 * tl_ms`: a killed run's true time is
    at least `2 * tl_ms / bound`, which exceeds `tl_ms` for every legal
    bound. That single fact is what makes this scheme worth anything — TL
    results are a small share of a matrix but the large majority of its
    wall clock, and re-timing them all serially would give back the speedup.

    This is deliberately NOT `classify`'s `banded` flag. That one marks
    `(TL, kill]` — "too close to call on other hardware", a statement about
    the *problem*, reported to the setter. This one marks "too close to call
    on this hardware right now", a statement about the *measurement*,
    resolved by re-measuring. Conflating them would change serial-mode
    behaviour.
    """
    if bound < 1.0:
        raise ValueError(f"contention bound must be at least 1.0, got {bound}")
    if bound >= 2.0:
        raise ValueError(
            f"contention bound must be below 2.0, got {bound}: kill_ms is "
            "2 * tl_ms, so at this bound a kernel kill no longer implies a "
            "genuine over-limit run"
        )
    if killed:
        return False
    return limits.tl_ms < time_ms <= bound * limits.tl_ms

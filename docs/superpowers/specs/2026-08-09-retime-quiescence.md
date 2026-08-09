# Open design question: the serial re-time is not machine-quiet

**Status:** open, deliberately deferred. Not a blocker for
`parallel-invocation-matrix` (PR #6) or `matrix-followups` (PR #7); both
shipped with the limitation documented rather than fixed.

**Owner:** unassigned. Whoever takes this should read all of it first — the
obvious fix has a deadlock trap, and the second-obvious fix changes what a
verdict means.

---

## The guarantee, and where it fails

Pass 2 runs solutions on several sandboxes at once. CPU time inflates under
contention (measured on an 8-thread box: 1.15–1.21x at 4 concurrent
sandboxes, up to 1.92x at 8), so any measurement close enough to the time
limit that contention could have decided it is **re-measured on a quiet
machine**. That re-measurement is the safety valve the whole parallel design
rests on: `matrix_core.needs_serial_retime` decides *which* results are
undecidable, and the re-time is what resolves them.

`_run_pass2` drains its thread pool before re-timing — `list(pool.map(...))`
completes inside the `with`, so the executor is shut down before the re-time
loop starts. That makes **this process's** workers idle.

It does not make the *machine* idle. `tools/box_pool.py`'s leases are
deliberately shared across every `run_matrix` invocation by the same user —
that sharing is what stops several invocations collectively oversubscribing
the box, and it is load-bearing for the contention bound. So while
invocation A takes its supposedly-quiet measurement, invocation B can be
holding up to `pool_size - 1` live boxes and burning CPU.

**The re-measurement that exists specifically to be trustworthy can itself be
taken under contention.**

## Why it matters: two verdict-affecting consequences

1. **The re-timed value is never re-checked.** `_run_pass2` re-times, then
   trusts the result unconditionally — it does not feed the new number back
   through `needs_serial_retime`. A re-time taken under sibling load can land
   right back inside the ambiguous band `(tl_ms, 1.5·tl_ms]` and be believed
   anyway.

2. **A wall-kill re-time can wall-kill again.** `killed` is sticky-OR in
   `_time_median`, so if the retry also trips the wall ceiling the result is
   `TL`. If that solution is declared `@expect TL`, then `expected == actual`
   and **a real hole is masked** — the one non-circular claim this pipeline
   makes. This is the same failure the wall-kill re-time was added to
   prevent, reappearing one process over.

## What bounds the exposure

Worth stating precisely, because this is why it ships rather than blocks:

- **Total live boxes never exceed `pool_size`**, however many invocations are
  running — that is the lease pool's whole job. So CPU readings stay inside
  `CONTENTION_BOUND`; the unsound windows are the *trusted re-time band* and
  *wall-kill re-kills*, not the ordinary measurements.
- **A single invocation is completely unaffected.** The guarantee holds
  exactly as claimed when only one `run_matrix` is running.
- **`RUN_MATRIX_BOX_POOL=1` gives a genuinely quiet run** — provided it is the
  sole invocation. A sibling at `POOL=4` will still sweep the other ids.
- **Pass 1 has the same exposure but in the safe direction.** A sibling
  inflates `t_main`, which inflates TL, which lets declared-slow solutions
  pass — and that surfaces as a **reported** hole (a false alarm), not a
  masked one.

## Candidate fixes, and their traps

**A. Re-check the re-timed value.** After re-timing, run the new number back
through `needs_serial_retime`; if it is *still* ambiguous, flag it rather
than silently trusting it. Cheap, local, no new locking.

*Trap:* it changes what a verdict means. Today every result is a verdict;
this introduces a third state ("measured, still undecidable") that
`invocation.json`'s consumers — `package_status`, `review_checks`, and the
`validating-solutions` skill — do not model. Decide what a *group* verdict is
when one of its tests is undecidable, before writing any code.

**B. Acquire the whole pool for the re-time phase.** Lease every box id
before re-timing, so no sibling can run.

*Trap:* deadlock. Two invocations both partway through acquiring, each
holding ids the other needs, neither able to proceed. Fixable with ordered
acquisition (always acquire ids in ascending order, release everything on
failure and retry) — but the lease helper is currently written for
one-at-a-time use, and `lease()`'s default timeout is 3600s, so a naive
attempt hangs for an hour rather than failing. Any implementation needs a
short timeout and a documented back-off.

**C. Detect rather than prevent.** Record how many boxes were leased
machine-wide during the re-time, and flag the result when it was not
actually quiet. Honest and cheap; does not fix the measurement, only labels
it. Probably the right first step, and composes with A.

**D. Do nothing; document.** What shipped. Defensible because the exposure is
bounded above and requires concurrent invocations, and because the failure
needs a wall-clock kill *and* a solution declared TL *and* a sibling running
at the wrong moment.

## Acceptance criteria for any fix

- A single invocation's verdicts must not change. The serial-vs-parallel
  equivalence test (`POOL=1` vs `POOL=4` over a real package, identical
  verdicts, holes, mismatches and limits) must still pass.
- The measured speedup must survive. It is 2.79x on `goldenseed`
  (182.4s → 65.4s at 4 workers); a fix that re-times more aggressively can
  give that back, since TL results are 2–13% of results but 43–88% of the
  wall clock.
- Whatever the fix, the *claim* in the code and docs must match it. Three
  sites currently say "every one of this process's own workers idle" and
  explicitly note a sibling may be running — `_run_pass2`'s docstring, the
  two `flags.json` `assumed` messages, and `skills/validating-solutions/SKILL.md`.
  All must be updated together, and `README.md`'s
  `RUN_MATRIX_BOX_POOL=1` guidance with them.

## Evidence already gathered

- Contention inflation, isolate-sandboxed, median of cohort vs serial
  baseline: CPU-bound 1.08/1.10/1.15/1.18/1.27x and memory-bound
  1.04/1.04/1.21/1.48/1.65x at 2/3/4/6/8 workers.
- `CONTENTION_BOUND = 1.5`, and `>= 2.0` is rejected outright: `kill_ms` is
  always `2 * tl_ms`, so at that bound a kernel kill stops implying a genuine
  over-limit run.
- `needs_serial_retime`'s boundaries were property-checked exhaustively
  (every `tl_ms` in {500, 1000, 1500, 2000, 3000} × every integer `T` in
  `[0, 3·tl]`): zero violations in both directions.
- The wall-kill re-time's contrast is mutation-verified — dropping the wall
  branch and re-timing everything killed each fail the covering test in the
  opposite direction.

## Related

- Ledgers: `docs/superpowers/decisions/2026-08-09-parallel-invocation-matrix.md`
  (where the seam was first identified, in the whole-branch review) and
  `docs/superpowers/decisions/2026-08-09-matrix-followups.md`.
- Code: `tools/run_matrix.py::_run_pass2`, `tools/box_pool.py::lease`,
  `tools/matrix_core.py::needs_serial_retime`.

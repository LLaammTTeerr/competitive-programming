# SDD ledger — plan: docs/superpowers/plans/2026-08-09-parallel-invocation-matrix.md

Repo: /home/lamter/.claude/skills/competitive-programming
Branch: parallel-invocation-matrix, cut from main. In place, not a worktree
(the human chose this; matches how stages 1-3 were run).
Base: f6c102b (the plan commit).

Baseline before any task: 270 tests, OK, 111s
(`python3 -m unittest discover -s tools/tests -t .`).

## Environment facts established before dispatch (verified by running)

- isolate 2.6, `/usr/local/bin/isolate`, git cf03a90. `nproc` = 8.
- `/etc/subuid` grants `isolate:200000:65536`, and box ids 0, 999, 1000,
  5000, 30000, 65535 all `--init` cleanly. `num_boxes` is commented out in
  the isolate config, so the subuid range is what bounds it.
- A live box rejects both `--init` and `--run` with rc=2 and
  "This box is currently in use by another process".
- A box `--cleanup`ed by another process makes our `--run` fail with
  "Box not found, did you run `isolate --cg --init'?".
- isolate OVERWRITES the `--meta` file with `status:XX` + `message:` on both
  failures, so a stale meta can never be read as this run's result. This is
  why Cause A is loud rather than silently wrong, and it was verified, not
  assumed.
- One `--init`/`--run`/`--cleanup` cycle costs 6.0 ms; `--run` alone 2.2 ms.
- CPU-time inflation under concurrent sandboxes, median of cohort vs serial
  baseline: CPU-bound 1.08/1.10/1.15/1.18/1.27x and memory-bound
  1.04/1.04/1.21/1.48/1.65x at 2/3/4/6/8 workers.

## Progress

Task 1: implemented (commit 55c0358) — tools/box_pool.py + 11 tests; full suite 281 OK.
Task 1: review — spec ✅; quality: Changes needed. All findings plan-mandated
  (the code is byte-identical to the plan's code blocks). Critical C1 (lock file
  mode 0644 contradicts the machine-wide docstring), Important I2 (cross-process
  exclusion test caught only 6/12 mutations), I3 (death-releases-lease test is
  vacuous AND would block 3600s on regression), I4 (no BoxPoolError path is
  triggered by any test), I5 (lock_dir chmods a caller-supplied directory to
  0o1777). Minors M1-M6 recorded below.
Task 1: HUMAN RULING — the pool is PER-USER, not machine-wide-multi-user.
  Lock dir defaults to /run/user/$UID/run_matrix-boxes, falling back to
  /tmp/run_matrix-boxes-$UID. Docstrings narrow to match; the 0o1777 chmod goes.
  This overrides the plan's "keep /tmp / do not fix this" note, which was
  written on the assumption the pool had to be multi-user. Resolves C1 and
  most of M4.
Task 1: minor (deferred): M3 EWOULDBLOCK==EAGAIN duplicate in the errno tuple;
  EACCES means "held" from flock but "fatal" from os.open in the same function.
Task 1: minor (deferred): M4 residual — flock on a tmpfs path that
  systemd-tmpfiles-clean could unlink out from under a holder. Reduced but not
  eliminated by the per-user ruling.
Task 1: minor (deferred): M6 the docstring's "same mechanism as flags.py"
  overstates — flags.py uses blocking LOCK_EX, this uses LOCK_EX|LOCK_NB + poll.
Task 1: note for Task 2 — os.open fds are non-inheritable (PEP 446), so exec'd
  isolate children do not hold the lease, but a fork-based multiprocessing pool
  WOULD duplicate the open file description and defeat release. Task 2/5 must
  use threads or spawn. (Plan already specifies threads.)
Task 1: fix round 1/5 (C1, I5, I2, I3, I4, pool-size bound, M1, test hygiene —
  all reported addressed; commits 55c0358..3a16a27). box_pool tests 11 -> 19,
  full suite 289 OK. I2 re-measured 12/12 mutation-catch by the implementer;
  the scoped re-review is verifying that claim rather than taking it.
Plan amended (7a8f6af), before any further brief is generated, because
  task-brief extracts plan text verbatim and two staleness traps would have
  propagated:
  (a) the per-user ruling — Task 1's section banner-ed SUPERSEDED, Task 2's
      collision message now names another *user* as a legitimate cause (the
      pool cannot see other users), Task 6's README text matches what shipped.
  (b) Task 2 mandated @unittest.expectedFailure on
      test_two_concurrent_run_once_calls_never_share_a_box, whose outcome is a
      RACE until Task 3 lands — two ~6 ms runs often serialize, and a clobbered
      stdout in stdin mode lands in the harmless FileNotFoundError -> b"" branch.
      A passing expectedFailure reports unexpected success and FAILS the suite,
      i.e. a flaky gate on the task whose acceptance is "two concurrent suites
      pass". Test moved to Task 3, which must now demonstrate it failing before
      the fix. Task 2's acceptance rests on the two-concurrent-suites run.
Task 1: deferred observation — processes sharing a lock dir with different
  RUN_MATRIX_BOX_POOL values get uneven sweep coverage (fairness, not
  correctness).
Task 5: note — pool.map drains all queued work before propagating a mid-pass
  MatrixError, so a failure is slow-fail but still loud. Acceptable; record it.
Task 1: re-review round 1 — ALL findings verdicted ADDRESSED, each verified
  independently rather than taken on report (flock mutation re-run 8/8 caught;
  suite re-run under -W error::ResourceWarning clean; no leakage into the real
  /run/user/1000 or /tmp lock dirs). NEW Important breakage in the fix diff:
  two new I4 tests (test_box_pool.py:217, :229) call bare lease() and so
  inherit the 3600s default timeout — the same hour-long-hang shape I3 was
  raised for, latent until _try_claim regresses to returning None instead of
  raising. Joined the open findings.
Task 1: fix round 2/5 dispatched — explicit short timeout_s at EVERY lease()
  call site in test_box_pool.py (closing the class, not the two instances;
  round-1 sites like :101 have the same shape and were scoped out of the
  re-review). box_pool.py's own 3600s production default is correct and stays.
  Implementer asked to demonstrate fail-fast by regressing _try_claim.
Task 1: deferred observation — _default_lock_dir()'s "/run/user/<uid> absent"
  branch has no dedicated test (code verified correct either way).
Task 1: deferred observation — the /tmp/run_matrix-boxes-<uid> fallback is
  squattable in sticky /tmp and is created at umask default, not 0700. This
  follows from the per-user ruling itself, not from the implementation.
Task 1: deferred observation — test_box_pool.py setUp leaks mkdtemp dirs with
  no tearDown cleanup (pre-existing from the brief-verbatim original).
Task 1: fix round 2/5 (1 addressed, 0 open; commits 7a8f6af..9444ecc). Every
  lease() call site in test_box_pool.py now carries an explicit timeout_s (17
  sites swept, not just the 2 named); box_pool.py untouched. Implementer
  demonstrated fail-fast by regressing _try_claim to return None: both tests
  failed in ~5s instead of 3600s, then restored.
Task 1: re-review round 2 — ADDRESSED, new breakage: none. Reviewer classified
  every call site succeed-vs-fail and established the flake risk is structural
  zero: lease()'s deadline is only consulted AFTER a full sweep finds nothing
  free, and every setUp gives the test a private mkdtemp lock dir, so no
  uncontended test can ever reach its timeout. No assertion was weakened.
Task 1: complete (commits 3dcf653..9444ecc, review clean, 2 fix rounds)

Task 2: implemented (commit b069ef8) — box_pool wired into _run_once, the
  open_isolate_box probe, and a two-branch _init_box; _select_box_id,
  box_id_counter and the itertools import all deleted. 342 tests OK; the
  two-concurrent-suites acceptance passed twice.
Task 2: implementer disclosed a real contradiction IN THE BRIEF — its suggested
  busy-box message text contains "subuid" and "cg-keeper" while its own test
  asserts both absent. It treated the test as authoritative and reworded.
Task 2: review — spec ❌ (BoxPoolError listed under Interfaces but never
  consumed); quality: Changes needed.
  CRITICAL: BoxPoolError is a bare RuntimeError, main() catches only
    MatrixError, so it escapes as a traceback and exits 1 — the code
    validating-solutions reads as "holes found". Reproduced with a malformed
    $RUN_MATRIX_BOX_POOL. This is the precise misread main()'s docstring says
    it exists to prevent.
  IMPORTANT: cleanup assertions still race — they check after the flock is
    released, and with pool_size()==4 a sibling suite draws from the SAME ids
    0-3, so the comment defending them ("other, non-colliding box ids") is
    false. Measured 0.2% duty cycle; the two clean acceptance passes are
    consistent with luck, not proof.
  IMPORTANT: the reworded message tail points the reader TOWARD the install
    diagnosis, inverting the finding's purpose.
  IMPORTANT (plan-mandated): _init_box's docstring names a cause that cannot
    happen (POOL raised past what the lock dir coordinates) — disproved
    empirically. The real uncovered cause is $RUN_MATRIX_BOX_LOCK_DIR
    divergence, named nowhere.
Task 2: CONTROLLER RULING (brief-vs-test conflict) — BOTH win. The brief's
  intent (explicit negation, so no one chases cgroups/subuid) and its test
  (those substrings absent) are jointly satisfiable: "Nothing about cgroup
  delegation, the isolate service, or the sandbox user's uid ranges needs
  changing." No human escalation: the plan contradicted ITSELF, and this
  resolution honours both halves rather than overriding either.
Task 2: CONTROLLER RULING (plan-mandated, test fixture) — my brief's "every
  new test class subclasses TestRunMatrixFixture" note was wrong and costly.
  Task 2's fix round adds a light mixin (self.tmp + skip guard only); plan
  amended so Tasks 3 and 5 reuse it rather than repeating the mistake.
Task 2: fix round 1/5 dispatched (Critical + 3 Important + 4 Minor + the
  mixin). Acceptance pair to be run 3x, per the implementer's own finding
  that one green pass is not evidence.
Task 2: minor (deferred): the busy-box test is circular — it feeds itself fake
  script text, so nothing pins _ISOLATE_BOX_BUSY to real isolate's wording.
Task 2: minor (deferred): test_run_matrix.py:53 imports matrix_core unused
  until Task 5 (brief-mandated, harmless).
Task 2: fix round 1/5 (Critical + 4 Important + 4 Minor + mixin: 8 addressed,
  1 open; commits 58a9f45..6202aea). Suite 342 -> 293 (mixin de-duplication,
  no coverage lost); acceptance pair run 3x, all 6 sides OK.
Task 2: re-review round 1 — all ADDRESSED except one residual: the false
  "other, non-colliding box ids" comment was fixed in _track_leased_box_ids'
  docstring but survives verbatim at test_run_matrix.py:654-657, contradicting
  the corrected text two lines away. Reviewer independently reproduced the
  cleanup-before-release enforcement by dedenting _cleanup_box out of the
  `with` (test failed as required, then restored). _leased_box confirmed a
  GENERAL seam, not a point patch: box_pool.lease()'s every BoxPoolError raise
  site (pool_size/lock_dir on __enter__, and the timeout in the poll loop)
  falls inside its try, so a mid-run lease timeout is covered too.
Task 2: fix round 2/5 dispatched — comment-only.
Task 2: DEFERRED TO FINAL REVIEW (pre-existing, NOT introduced by this branch):
  ProblemMetaError also escapes main() and exits 1 on a malformed problem.json
  — the same "a crash is read as a finding" class as this task's Critical, and
  exit 1 is what validating-solutions reads as "holes found". Reproduced twice
  independently (controller and reviewer). run() calls problem_meta.load as its
  first statement, entirely unwrapped. Out of scope for a parallelism plan;
  flagged so the final whole-branch review can triage it rather than lose it.
Task 2: fix round 2/5 (1 addressed, 0 open; commit 794b094, comment-only).
Task 2: re-review round 2 — ADDRESSED. New comment verified ACCURATE against
  the code (not merely different); no stale copies anywhere in tools/; diff
  touches comment text only.
Task 2: complete (commits 9444ecc..794b094, review clean, 2 fix rounds)

Task 3: implemented (commit 3fe7cbc) — per-run meta file + per-run staging dir;
  _clear_stage_dir replaced by _remove_run_dir. 300 tests OK, run 3x serially
  and 3x as concurrent suite-pairs (6/6 sides OK). Step-4 break demonstration
  genuinely performed: restoring the shared meta/stage broke 5 of 9
  ReentrancyTest tests, including a captured 'BBB' != 'AAA' cross-contamination.
Task 3: review — spec ✅; quality: Changes needed.
  CRITICAL: the docstring claim "meta_dir ... is never passed to --dir" has NO
    test, and the half that is tested compares handle FIELDS — so a future
    meta_path = run_dir / "meta" (exactly what the docstring forbids) keeps both
    assertions green while putting the driver's only account of the run inside
    the solution's own :rw mount. Fix is an argv-level assertion.
  IMPORTANT (plan-mandated): _remove_run_dir raising in _run_once's finally
    discards that run's valid verdict and aborts the whole matrix.
  MINORS: unguarded meta unlink first in the finally can skip _cleanup_box and
    leak a leased-then-released box; the replacement test dropped the deleted
    test's "message names the offending path" assertion; meta_dir emptiness
    untested; stale name stage_dir_resolved.
Task 3: HUMAN RULING — WARN AND KEEP THE VERDICT, reversing the brief. Decisive
  argument: the identical condition (foreign-owned undeletable subdir) is a
  stderr warning in close_isolate_box but a whole-matrix abort in _run_once's
  finally — two opposite treatments of one fact, separated only by when it is
  noticed. The RunResult is not wrong (private meta, written/read/parsed,
  output copied back), and per-run dirs make later contamination impossible by
  construction, so the cost is disk alone. validating-solutions deliberately
  runs hostile code; mkdir("d",0700) is an expected input class, and aborting
  misreports a SOLUTION's behaviour as a DRIVER failure. _remove_run_dir keeps
  raising (clean, testable); the finally catches and warns.
Task 3: fix round 1/5 dispatched (Critical + the ruling + 4 minors).
Task 3: process note — the implementer's report claimed .test-scratch/ was
  empty; it was not. Plain `ls` hid the dot-prefixed leaked roots from the
  Step-4 experiment (which incidentally corroborated Step 4 really ran).
  Reviewer remediated. Verify with `ls -a` before asserting cleanliness.
Task 3: fix round 1/5 (Critical + human ruling + 4 minors: 6 addressed, 0 open;
  commits 3fe7cbc..db0344b). 302 tests OK.
Task 3: re-review round 1 — ALL ADDRESSED, new breakage: none. Reviewer
  independently reproduced the Critical demonstration (pointed meta_path at
  run_dir; the NEW argv-level test failed naming the mount while the OLD
  handle-field test still passed — exactly the contrast that proves the old
  test was a weak proxy), then restored and confirmed a clean git diff.
  Warning voice judged consistent with close_isolate_box's: same
  "WARNING: <fact> — <context>. Remove it as root: sudo rm -rf <path>"
  skeleton, which matters because the human's ruling rested on these two
  sites treating the SAME condition consistently.
Task 3: TIMING QUESTION CLOSED — the implementer's reported regression
  (112-115s -> 163-214s) is environmental, not the diff. Reviewer found nothing
  in the diff that could cost 50-100s (two single-_run_once-call tests plus a
  no-op-in-the-happy-path try/except), and caught a concurrent full-suite
  process on the machine. Controller measured it directly afterwards: 114.83s
  and 116.14s, i.e. back at baseline, even while the reviewer's own checks ran.
Task 3: complete (commits b181b38..db0344b, review clean, 1 fix round)

Task 4: implemented (commit 37d2ba0) — CONTENTION_BOUND=1.5 and
  needs_serial_retime() in matrix_core. 312 tests OK (302 + 10).
Task 4: controller verification — exhaustive sweep over tl_ms in
  {500,1000,1500,2000,3000} x every integer T in [0, 3*tl]: every measurement
  the rule calls unambiguous yields the SAME TL-verdict across the whole
  interval [T/F, T], and every measurement it flags is genuinely undecidable.
  ZERO violations in both directions. Both ValueError guards fire (2.0, 2.5,
  0.9). kill/F = 1.333x > 1 as the killed-run shortcut requires.
Task 4: review — spec ✅; quality: Approved, NO findings. Reviewer confirmed by
  diff (not by report) that classify(), compute_limits() and _SEVERITY are
  byte-identical, and that compute_limits is the SOLE production site
  constructing Limits — so the docstring's "kill_ms is fixed at 2*tl_ms" is
  exactly true rather than merely typical, which is what the killed-run
  shortcut depends on. Tests pin both boundaries (T=tl and T=bound*tl would
  each catch a flipped comparison) and trigger both ValueError branches.
Task 4: complete (commit 37d2ba0, review clean, 0 fix rounds)

Task 5: implemented (commit 6189632) — _run_pass2 on a ThreadPoolExecutor sized
  to box_pool.pool_size(); pass 1 stays serial; ambiguous band re-timed with the
  pool drained. 367 tests OK.
Task 5: MEASURED SPEEDUP — goldenseed (13 solutions, 45 tests, 546 results):
  189.3s serial (POOL=1) -> 71.4s at POOL=4 = 2.65x, beating the plan's 2.3x
  projection. Verdicts, holes (0/0), mismatches (0/0) and TL/kill limits all
  IDENTICAL between the two runs; 1 of 546 results needed a serial re-time.
Task 5: review — spec ✅; quality: Approved.
  Pass-1 seriality MUTATION-CONFIRMED: parallelising _time_median's repeat runs
  makes test_pass_one_is_never_run_concurrently fail (3 != 1). Verdict
  corruption mutation-confirmed too (mispairing results with work items flips
  sol-main/sol-wrong). MatrixError propagation verified empirically with thread
  -name instrumentation: raised in ThreadPoolExecutor-0_0, propagated out of
  run(). pool.map abort latency measured at ~one round of `workers` runs, NOT
  a full drain — the controller's earlier "drains queued work" framing was wrong.
Task 5: IMPORTANT (a gap in the PLAN's reasoning, not the implementation) —
  isolate reports status:TO for BOTH a CPU kill and a WALL-CLOCK kill, and
  needs_serial_retime short-circuits on `killed`. But its justification
  (kill_ms/bound > tl_ms) is arithmetic about CPU time; wall-time inflation
  under contention is NOT bounded by CONTENTION_BOUND, since a descheduled
  process accrues wall time without CPU time. So a wall kill becomes a silent
  TL with no re-time and no flag — and in the direction that matters, a
  solution declared TL that genuinely finishes under TL gets wall-killed,
  expected == actual, and A REAL HOLE IS MASKED. Reachability is bounded
  (needs wall/CPU > 1.5 to hit the 3*TL wall cap before the 2*TL CPU cap, > 3x
  to mask a hole) and requires oversubscription past core count, which
  box_pool permits up to 65536 with no guard.
Task 5: CONTROLLER RULING — fix it in _run_pass2, NOT matrix_core: Task 4 is
  closed and its logic exhaustively verified, so needs_serial_retime's
  signature stands. When workers > 1, a wall-clock kill (detected by the same
  message-text test pass 1 already uses at :1655, reused not reinvented) is
  re-timed serially and flagged; a CPU kill keeps the short-circuit, which is
  what preserves the 2.65x since ordinary TL solutions dominate the wall clock.
  Documenting the oversubscription hazard goes to Task 6.
Task 5: fix round 1/5 dispatched (1 Important + 3 minors).
Task 5: minor (deferred to Task 6): box_pool.pool_size() accepts values far
  above cpu_count with no oversubscription guard, which is what makes the wall
  -kill hazard reachable at all. Document it, or cap it.
Task 5b (NEW TASK, split out on the reviewer's recommendation):
  TestRunMatrixFixture carries 49 test methods of its own, so ParallelPassTest
  = 6 own + 49 inherited re-runs = 55. Suite 312 -> 367, ~115s -> 280s. Same
  defect bit Task 2 (289 -> 342). MinimalIsolateFixture (0 test methods) has
  the right shape. Fix: extract a PURE fixture base and have both
  TestRunMatrixFixture and ParallelPassTest subclass it. NOT safe inside Task
  5 — it re-parents 55 tests and would invalidate the 367-test run Task 5's
  approval rests on. Acceptance: 318 tests, suite back toward ~120s.
Task 5: fix round 1/5 (1 Important + 3 minors: 4 addressed, 0 open; commits
  6189632..2622662). 368 tests OK.
Task 5: RE-MEASURED SPEEDUP AFTER THE FIX — goldenseed 182.4s -> 65.4s = 2.79x
  (improved on the pre-fix 2.65x). Verdicts 546/546, holes 0/0, mismatches 0/0
  and TL/kill limits identical; 1 of 546 re-timed. The wall-kill fix cost no
  speedup and altered no verdict, because the CPU-kill short-circuit is
  preserved and ordinary TL solutions dominate the wall clock.
Task 5: re-review round 1 — ALL ADDRESSED, new breakage: none. The new test was
  MUTATION-VERIFIED IN BOTH DIRECTIONS by the reviewer: dropping the wall
  branch makes it fail ("a wall-clock kill under contention must be re-timed");
  re-timing everything killed makes it fail the other way ("a CPU-time kill is
  never ambiguous and must not be re-timed"). Both mutants reverted. That
  contrast is what keeps correctness AND the speedup.
Task 5: minor (deferred): the wall-kill flag records only the RE-TIMED
  cpu/wall time, never the original wall-killed reading — the original r.wall_ms
  is not captured into a local before _time_median reassigns r, so it is
  unrecoverable from flags.json. The near-TL CPU flag DOES embed first_run_ms,
  so the implementer's "mirrors the existing flag" claim does not fully hold.
  Information loss for a reader, not a correctness bug. One-line fix; sent to
  the final whole-branch review to triage rather than extending the loop.
Task 5: minor (deferred): `wall_killed or needs_serial_retime(...)` is correct
  and its mutual exclusivity is explained in the adjacent comment, but the `or`
  alone does not self-document that the overlap is structurally impossible.
Task 5: complete (commits 37d2ba0..2622662, review clean, 1 fix round)

Task 5b: implemented (commit 4bd881f) — PackageFixture extracted as a pure
  fixture base (0 test methods); TestRunMatrixFixture keeps its name and its 49
  tests on top of it; ParallelPassTest re-parented onto the base.
  368 -> 319 tests, 261s -> 150s. Test-ID diff: exactly 49 removals, all
  ParallelPassTest.test_* with an identical surviving copy, 0 additions.
Task 5b: controller verification — EVERY TestCase subclass now has own == total
  test methods (PackageFixture 0, MinimalIsolateFixture 0, TestRunMatrixFixture
  49, ParallelPassTest 7, ReentrancyTest 11, BoxLeasingTest 3, TestStageBase 4),
  so no inherited duplication remains anywhere. Only the test file changed.
Task 5b: review — spec ✅; quality: Approved, NO findings. Reviewer byte-diffed
  PackageFixture's setUp/tearDown/_make_file_io_package against the originals
  (identical but for the class header), executed all four shared helpers through
  the new inheritance chain rather than import-checking them, AST-scanned for
  introduced class-level mutable state (none), and proved RUN_MATRIX_BOX_POOL is
  still popped on the FAILURE path via a synthetic failing subclass.
Task 5b: minor (deferred, pre-existing): ReentrancyTest carries its own copies
  of _mounted_host_dirs/_isolate_run_argv because it is on the
  MinimalIsolateFixture family; the duplication is deliberate and commented.
Task 5b: complete (commit 4bd881f, review clean, 0 fix rounds)

Task 6: implemented (commit b134f8d) — README, validating-solutions SKILL, and
  the stage-3 scope doc updated; 2 doc tests added. 321 tests OK.
Task 6: review — spec ✅ (every claim probed against source, incl. live
  box_pool fallback probes with a nonexistent uid and with os.access forced
  false); quality: Changes needed.
  IMPORTANT: README's "goldenseed (13 solutions, 45 tests, 546 results)" is
    self-contradictory — 13x45=585. Real package has 42 GRADED tests (7+7+8+20)
    plus a 3-test samples group that _tests_by_group never runs, so 13x42=546.
    The "45" was copied from the plan's stale table row while 546 was the fresh
    measurement — a number contradicting itself inside a sentence advertising
    "measured, not projected".
  MINOR: "what makes wall-clock kills reachable at all" is an absolute the code
    does not support — _run_pass2 re-times wall kills at ANY workers > 1, and
    its own comment says nothing bounds wall inflation. Came from the
    controller's brief, not the source.
  MINOR: "a wall-clock kill is ALWAYS re-timed" is false at workers == 1 —
    and that is exactly the RUN_MATRIX_BOX_POOL=1 setting the same paragraph
    recommends.
  MINOR: the new doc tests pin string literals where this very file's idiom is
    to pin code (it already asserts against run_matrix.STAGED_STDOUT_NAME and
    scan_solutions.VERDICTS). Renaming box_pool.POOL_ENV or the
    retimed_serially payload key would leave the docs stale and the tests green.
Task 6: CONTROLLER RULING (reviewer concurred) — docs/superpowers/decisions/
  README.md:102-104 MUST be updated. Its "historical records" disclaimer is
  scoped to the ledger FILES it indexes; the index itself carries two live
  prescriptive sections ("Standing rules — Binding on all future work" and
  "## Open items"). Clincher: its running-contests bullet is the SAME item as
  the stage-3-scope carried-forward bullet the brief did order updated — one
  live list split across two files. The implementer flagged rather than
  silently skipping, which was the right failure mode.
Task 6: repo-wide sweep found NO other live index carrying the stale claim;
  remaining hits are past-tense narrative in dated documents, correctly left.
Task 6: fix round 1/5 dispatched (1 Important + 3 Minor + the ruling).
Task 6: fix round 1/5 (1 Important + 3 Minor + the ruling: 5 addressed, 0 open;
  commits b134f8d..a544a45). 321 tests OK, 148.4s.
Task 6: re-review round 1 — ALL ADDRESSED, new breakage: none. Reviewer
  independently counted goldenseed's .in files per group (7+7+8+20=42), checked
  problem.json declares exactly g1..g4 with no samples subtask, and confirmed
  _tests_by_group iterates problem.subtasks only — so 13x42=546 is right and
  the samples group is genuinely never run. Doc tests proven to BITE by
  temporarily renaming the emitted payload key (test failed as required) and
  by renaming box_pool.POOL_ENV (AttributeError); "retimed_serially" occurs
  exactly once in run_matrix.py, so inspect.getsource has no fallback
  occurrence to keep the test green. Repo reverted cleanly after each.
Task 6: complete (commits d12b457..a544a45, review clean, 1 fix round)

ALL TASKS COMPLETE. Proceeding to the final whole-branch review.

FINAL WHOLE-BRANCH REVIEW (21 commits, ea3087b..a544a45, ~3900 insertions):
  verdict SHIP WITH FIXES — and the fixes are PROSE ONLY, no code change.
  IMPORTANT (the whole-branch finding no per-task review could see): Task 1
    built a CROSS-PROCESS lease pool; Task 5 built a re-time that assumes a
    QUIET MACHINE; nobody owned the seam. _run_pass2 drains its OWN pool
    before re-timing, but a sibling invocation by the same user can hold up to
    pool_size-1 live boxes at that moment. Bounded, not unbounded: total live
    boxes never exceed pool_size, so CPU readings stay inside CONTENTION_BOUND;
    the unsound windows are the trusted re-time band and wall-kill re-kills,
    and only in the multi-invocation regime. Three docs asserted the
    machine-wide version, one contradicting itself inside a single paragraph.
  Checked and CLEAR: the unsandboxed checker never competes with a live
    sandbox (it runs from the serial loop after the executor shuts down, and a
    timeout returns FAIL = _SEVERITY[0], which can never be "OK", so it yields
    a spurious mismatch and never a masked hole); memory verdicts are
    per-cgroup and unaffected; disk/IO contention inflates WALL time, which is
    now re-timed; lease/run_dir/box/try-finally nesting correct on every exit
    path; pool.map abort semantics accurately documented; holes/_SEVERITY/
    classify/compare/group_verdict byte-unchanged.
  Final suite verified by the controller: 321 tests, OK, 147.7s.
Final fix wave (commit 6097822) — 9 prose corrections. Controller verified
  PROSE-ONLY by parsing both modules before and after, stripping every
  docstring, and comparing ASTs: IDENTICAL for run_matrix.py and box_pool.py.
  Implementer self-caught an error mid-draft: it first called an inflated-TL-
  causes-OK result a "mismatch", re-read compare(), and reclassified it as a
  HOLE (_FAILING contains TL; want in _FAILING and got == "OK" -> holes).
  Re-review confirmed the correction and the direction argument.
Fix-wave re-review: all 9 ADDRESSED, no new breakage, no new untrue claims.
  Two residuals at sites the list MISSED — flags.json's assumed text
  (run_matrix.py:1574, :1585) carrying the identical "every worker idle" claim,
  and SKILL.md:305-306's uncaveated "fully quiesced run".
CONTROLLER ADJUDICATION: these are the SAME finding as items 1 and 4 at missed
  sites, not new findings, so completing them finishes the approved wave rather
  than opening a second one. The flags.json instance matters MORE than the
  docstring it echoes: flags.json is what a setter reads to decide whether to
  trust a timing-band judgement, and that sentence is the stated reason to
  trust it. Dispatched; to be verified by AST comparison plus a suite run
  rather than a third review round, per the reviewer's own recommendation.

FOLLOW-UPS (not this branch):
  1. ProblemMetaError escapes main() and exits 1 (the "holes found" code) on a
     malformed problem.json. Pre-existing; human ruled it a follow-up. Final
     review CONFIRMED the reading and found an aggravator: on that crash
     invocation.json is never rewritten, so a STALE one showing holes: [] can
     green validating-solutions' completion gate on evidence describing a
     different package state. Shipping this branch does NOT make it likelier
     to fire. Priority raised.
  2. Harden the re-time mechanism itself (re-check the re-timed value against
     needs_serial_retime and flag if still ambiguous; or acquire the whole
     pool, which has an ordered-acquisition deadlock problem). Real design
     work — deliberately not attempted here.
  3. The wall-kill flag records only the re-timed cpu/wall time, never the
     original wall-killed reading; the near-TL flag DOES embed first_run_ms.
  4. run_matrix.py:1794's bare box_pool.pool_size() — latent, currently
     unreachable-with-a-raise, wrap it if the module is touched again.
  5. box_pool's /tmp fallback: mkdir(mode=0o700) rather than umask default.
  6. A leaked WORLD-WRITABLE staging root predating this branch sits in the
     user's project tree: ~/Projects/my_cp_problems/.run_matrix_stage_typs03yx
     (drwxrwxrwx, empty, 2026-07-31). Left in place per the read-only rule;
     reported to the user.

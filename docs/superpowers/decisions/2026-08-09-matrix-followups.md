# SDD ledger — plan: docs/superpowers/plans/2026-08-09-matrix-followups.md

Repo: /home/lamter/.claude/skills/competitive-programming
Branch: matrix-followups, cut from parallel-invocation-matrix (PR #6, open).
In place, not a worktree. Base: 003788a
Baseline: 321 tests, ~150s.

## Measured before dispatch (probed against a real package, driving main())

- malformed problem.json -> ESCAPED tools.problem_meta.ProblemMetaError, exit 1
- malformed @expect header -> ESCAPED tools.scan_solutions.ScanError, exit 1
- corrupted flags.json -> exit 0 (not an escape)
Two escapees, not the one recorded. ScanError is the likelier in practice.

- package_status._matrix() gates on holes==[] with NO freshness check at all;
  generated_at is written into the payload and never read back. So the gate is
  green on stale evidence after a clean run plus an edit, not only after a crash.

## Human rulings, binding

1. Staleness is fixed in the GATE (package_status._matrix), not by deleting
   invocation.json in run() -- that would break the documented "a refusal is a
   true no-op on the tree" doctrine.

## Progress

Task 1: implemented (commit 400728a) — PACKAGE_ERRORS caught at main()'s
  boundary. 328 tests OK (321 + 7).
Task 1: implementer found a THIRD escapee the controller's probe missed —
  flags.FlagError, raised from flags.append, which _run_pass2 calls on any
  banded/retimed result. The controller's "corrupted flags.json -> exit 0"
  probe was a FALSE NEGATIVE: it never produced a banded result, so
  flags.append was never reached. Confirmed DriftCheckError cannot escape
  (drift_check is not imported into run_matrix at all) and documented that as
  a deliberate absence. Also caught that the brief's Step 4 test design was
  broken (it assumed pool_size() is called exactly twice per run; pass 1
  leases per timed run, so the counter tripped mid-pass-1).
Task 1: review — spec ✅; quality: Changes needed.
  IMPORTANT (plan-mandated): the brief's Produces clause promised exit 2 for
    EVERY non-result failure; only the tools-exception half holds. A stdlib
    OSError from write_text on a full/read-only disk still exits 1 — the exact
    misread the task exists to kill — and the new docstring asserts the
    stronger property.
  IMPORTANT (plan-mandated): test_no_tools_exception_type_escapes_main claims
    "if a future module raises a new error type, this fails" — FALSE. It
    injects ProblemMetaError, already in the family. Same staleness shape that
    made the brief's own list wrong.
  MINOR: the flags test asserts only code == 2 under a heavily perturbed run,
    so any unrelated MatrixError passes it.
  MINOR: SKILL.md:350's exit-2 cause list not extended.
  NIT: _run_pass2's propagation paragraph doesn't mention FlagError.
Task 1: CONTROLLER RULING — make the CODE match the promise, don't narrow the
  promise. Add a final `except Exception` returning 2 WITH traceback.print_exc()
  to stderr. Exit 2 means "the matrix could not be run at all", which is
  precisely what a driver crash is; the traceback still reaches a human, so
  nothing is masked and only the exit code changes — to the correct one.
  PACKAGE_ERRORS stays a separate branch above it with a clean one-line
  message and no traceback, because those are package problems a user can act
  on rather than driver bugs. SystemExit/KeyboardInterrupt derive from
  BaseException and pass through untouched.
Task 1: reviewer independently derived the reachable error set from
  run_matrix's own namespace and got exactly PACKAGE_ERRORS, UNCOVERED: [].
  Also MUTATION-VERIFIED the frame-discriminating pool_size test by reverting
  the try/except and confirming it errors at the intended site.
Task 1: fix round 1/5 dispatched (2 Important + 2 Minor + 1 nit).
Task 1: fix round 1/5 (2 Important + 2 Minor + 1 nit: 5 addressed, 0 open;
  commits 400728a..bae9001). 332 tests OK.
Task 1: controller verification — simulated a full-disk OSError on the
  invocation.json write: EXIT 2 with the traceback preserved on stderr (was
  exit 1, i.e. "your package has a hole"). Independently injected a
  ControllerProbeError into tools/matrix_core.py: the enforcement test FAILED
  naming it, and passed again after removal, with a clean git status.
Task 1: re-review — ALL ADDRESSED, new breakage: none. Reviewer confirmed the
  broad `except Exception` costs nothing: the try spans ONLY
  `payload = run(...)`, so the HOLE/MISMATCH print loop is structurally
  outside it and a real result can never become exit 2 — a code-layout
  guarantee, not a runtime one. traceback.print_exc() writes to stderr
  (verified with redirect_stdout/redirect_stderr), so stdout parsers are
  unaffected. KeyboardInterrupt and SystemExit(7) both verified to propagate
  out of main() untouched, with the exit code preserved.
Task 1: DEFERRED (to Task 2) — the enforcement test's docstring does not
  advertise its limits. The reviewer DEMONSTRATED three real blind spots:
  (a) a module imported lazily inside a function never appears in
  vars(run_matrix); (b) a type reachable only TRANSITIVELY (imported by
  something run_matrix imports) is missed — reproduced by injecting a
  TransitiveError whose __module__ points outside the one-hop set, and
  `uncovered` came back empty; (c) an exception class defined inside a
  function body never appears in its module's vars(). None are live today
  (grep: zero local imports of tools modules, zero function-local exception
  classes), and all three are reachable by an AST sweep in principle — they
  are limits of THIS runtime one-hop introspection, not of static analysis.
  The test should say so.
Task 1: complete (commits 003788a..bae9001, review clean, 1 fix round)

Task 2: implemented (commit 9c0e5fe) — staleness gate in package_status._matrix,
  wall-kill flag records first_wall_ms, box_pool lock dir 0700 + ownership
  check. 343 tests OK (332 + 11).
Task 2: controller verification — drove a real run_matrix.run() then _matrix():
  done=True, "holes 0, mismatches 0" IMMEDIATELY after a clean run, so the .a
  answer files the matrix itself rewrites during pass 1 do NOT false-positive.
  Touching a solution afterwards flipped it to done=False with the staleness
  detail. (My brief's test code used Phase.ok; the real field is Phase.done —
  the implementer caught and corrected it.)
Task 2: review — spec ✅; quality: Approved, with findings.
  The reviewer built an EMPIRICAL COVERAGE MAP of the gate.
  CAUGHT: edits to any solutions/*, any tests/**, problem.json; a newly added
    solution; a new file in a new nested test subdir.
  NOT CAUGHT: deletion of a test or a solution; emptying a group; an edit whose
    mtime is restored (cp -p / tar x / rsync -a); edits under files/; a file
    inside a chmod-000 subdir (rglob swallows PermissionError).
  Filesystem mtime granularity here is ~4 ms, so the equal-mtime boundary is a
  REAL case, not theoretical — the strict `>` is load-bearing and pinned.
  IMPORTANT (plan-mandated): deletions are false-fresh — `if child.is_file()`
    skips directories, so removing a test leaves the gate green while
    invocation.json still certifies zero holes. This is the DANGEROUS
    direction. Reviewer confirmed statting directories cannot introduce
    false-stale, since pass 1's .a writes all precede the single
    invocation.json write and .build/, solutions.json, flags.json and the
    staging dir are all outside the walk.
  IMPORTANT (plan-mandated): _MATRIX_SOURCES omits the CUSTOM CHECKER. When
    checker_kind == "custom", run() compiles files/<checker_name>, and the
    checker decides OK vs WA on every cell of the matrix — edit it and verdicts
    flip with the gate green. Nothing records its provenance either, unlike
    testlib whose git rev IS pinned into the payload. Narrower than "add
    files/": validator/generator edits don't change verdicts until tests
    regenerate, and that regeneration is already caught.
  MINOR: the rationale comment says false-stale is mtime's weakness and calls
    that "the safe direction" — but the probe found THREE false-FRESH
    directions. Overclaims, in a project with a history of exactly that.
  MINOR: unguarded child.stat() in the walk can raise FileNotFoundError out of
    status(), contradicting the module docstring's "status() never raises" and
    R1. The artifact's own stat IS guarded — inconsistent.
  MINOR: an untriggered `except OSError` at :111-114.
  MINOR (out of scope, now folded in): review_checks.py:84-87 has its OWN
    _matrix() with no freshness check, returning [] when invocation.json is
    absent entirely. CORRECTION (2026-08-09, final-fix pass): the claim that
    followed this — that the combined gate in creating-problems was
    protected "only because package_status is ALSO required, a coincidence
    of composition" — was wrong when written. review_checks.run() calls
    _incomplete() (review_checks.py:198), which itself calls
    package_status.status() (review_checks.py:59); that is one staleness
    implementation reached by two paths, not two independent gates that
    happen to compose. Confirmed:
    review_checks.run() on a package with no invocation.json reports an
    incomplete-package finding (first incomplete phase: matrix) on its own,
    with no help from a separate package_status call. review_checks was
    always self-sufficient here.
Task 2: CONTROLLER RULING — fix both Importants (they fulfil the brief's
  intent rather than contradict it) and fold in the review_checks seam, because
  fixing one gate and leaving its twin with the identical hole is the
  fix-the-instance-not-the-class error this plan has already paid for twice.
  The 0755 lock-dir limitation the implementer disclosed is correctly scoped
  out, per the reviewer: a legitimately-owned 0755 dir is not other-writable,
  the lock files inside are 0600, and /run/user/<uid> is itself 0700 — the only
  leak is the ability to LIST which box ids are leased.
Task 2: fix round 1/5 dispatched (2 Important + 4 Minor).
Task 2: fix round 1/5 (2 Important + 4 Minor: 6 addressed; commit c282b2c).
  353 tests OK (343 + 10). _matrix's signature gained `problem` so it can reach
  the custom checker's filename; newest_source_mtime() is now PUBLIC and SHARED
  with review_checks rather than copied, so the two gates cannot drift apart.
Task 2: controller verification — deleting a test 50ms after a clean run now
  gives done=False with the staleness detail. CONFIRMED FIXED.
Task 2: controller MEASUREMENT — a narrow inherent blind spot the coverage
  statement did not name. Deleting a test IMMEDIATELY after run() returned gave
  done=True: the deletion did bump the directory mtime, but to a value EXACTLY
  EQUAL to invocation.json's, so strict `>` correctly declined to fire.
  Measured this filesystem's mtime granularity directly: ~4.0 ms, matching the
  reviewer's independent figure. This is NOT fixable here — `>=` is unavailable
  because pass 1's .a writes share a tick with invocation.json, so `>=` would
  make every fast clean run self-flag, which is the failure that makes a gate
  worthless. Reachable only by a SCRIPT that mutates a package within ~4 ms of
  a run finishing; no human workflow can hit it. Sent as an addendum to be
  named in the gate's stated limits, because a limits list complete except for
  the one the controller had to measure is the same overclaiming defect the
  round just fixed.
Task 2: addendum commit fd15e1a — the mtime-tick limit named in the gate's
  stated gaps. Controller verified comment-only by docstring-stripped AST
  comparison: logic identical in both package_status.py and review_checks.py.
Task 2: re-review round 1 — ALL round-1 findings CONFIRMED FIXED, and confirmed
  by DRIVING a real package rather than reading: deleted a solution file and a
  whole test-group subdirectory against live run_matrix.run() output, both flip
  the gate to stale via the parent directory's mtime; five consecutive clean
  runs all read fresh immediately afterwards, so closing the deletion gap
  introduced NO false-stale (the saving ordering — invocation.json's write_text
  is the literal last statement in run() — was re-confirmed, not assumed);
  stock-checker and validator edits correctly do not trigger staleness; a
  declared-but-missing checker file returns 0.0 without crashing; problem=None
  is safe. The untriggered except OSError was TESTED rather than deleted.
  RESIDUAL 1: newest_source_mtime is genuinely shared (one implementation, one
    import site) but the extra_files SELECTION logic is duplicated verbatim at
    package_status.py:211-213 and review_checks.py:115-117 — the duplication
    moved from the helper to its arguments, which is the exact drift shape the
    sharing was meant to prevent. Identical today and pinned by tests on both
    sides, so not a live bug.
  RESIDUAL 2: the limits comment omits a real gap — a MULTI-FILE custom checker.
    If files/<checker> #includes a local helper also under files/, editing that
    helper changes verdicts on next compile, and unlike validator/generator
    edits there is NO downstream tests/ regeneration to catch it. That
    regeneration argument is what justified excluding the rest of files/, so
    the narrowness is right but its stated justification has a hole.
Task 2: fix round 2/5 dispatched (hoist the selection into one function; name
  the multi-file-checker gap as an accepted trade rather than a proof).
Task 2: fix round 2/5 (2 residuals addressed; commit 87c8e8d). 353 tests OK
  (count unchanged — no test logic touched). extra_matrix_files() is now the
  single source of truth for "what counts as an extra source", defined once at
  package_status.py:200 and called from exactly two sites.
Task 2: re-review round 2 — BOTH CONFIRMED FIXED, new breakage: none. Reviewer
  diffed the two pre-hoist inline blocks and confirmed they were textually
  identical, so the hoist changed no behaviour for either caller, including the
  problem is None short-circuit. Also established the gate's SCOPE BOUNDARY by
  grepping what run_matrix actually compiles: only solutions and the checker.
  The stock checker, testlib.h and the compiler are legitimately OUT of scope —
  externally owned, not package-owned — and are captured in invocation.json's
  machine block for provenance but never diffed. Nothing else the matrix reads
  falls outside problem.json / solutions / tests / the custom checker.
Task 2: minor (deferred): extra_matrix_files' docstring does not state that a
  returned path may not exist on disk. Harmless — _mtime_or_zero returns 0.0 —
  and pre-existing, since the original inline comment did not say so either.
Task 2: minor (deferred): the in-scope/out-of-scope boundary (testlib, compiler,
  stock checker) is stated in this run's report but not in the source, unlike
  the five mtime-signal gaps which are. Nice-to-have, not a defect.
Task 2: complete (commits bae9001..87c8e8d, review clean, 2 fix rounds)

ALL FOLLOW-UP TASKS COMPLETE. Proceeding to the whole-branch review.

WHOLE-BRANCH REVIEW (7 commits, fd7c318..87c8e8d): SHIP WITH FIXES — prose only.
  The two tasks COMPOSE CORRECTLY. The reviewer walked the shared seam
  concretely: a crash caused by a package EDIT is itself an mtime bump past the
  untouched artifact, so the gate goes red — the two fixes reinforce rather
  than interfere. A crash caused by the ENVIRONMENT leaves sources untouched
  and the gate green, which is CORRECT: the old artifact still describes the
  current tree exactly. A crash mid-pass-2 (after pass 1 rewrote the .a files)
  is false-STALE, the safe direction. And a failure on the final write_text
  leaves a truncated artifact -> JSONDecodeError -> done=False, so genuine
  holes are lost but never reported clean.
  Genuine results cannot be swallowed by `except Exception`: the try spans only
  `payload = run(...)`, so the HOLE/MISMATCH print loop is structurally outside
  it and `return 1` is unreachable from the handler.
  IMPORTANT: three sites claimed PACKAGE_ERRORS produce a ONE-LINE message.
    False for the commonest exit-2 cause — controller measured a real compile
    failure at SIX lines, because _compile embeds all of g++'s stderr and
    main()'s handler is a bare print. Corrected to "a message naming the
    package problem, with no traceback", which is the true distinction.
  MINOR: the new stale-matrix kind was absent from three prose enumerations —
    off-diff prose made stale by an on-diff change, visible only at branch
    scope.
  MINOR: the limits list was incomplete a THIRD time, in a new direction: all
    five gaps described a SOURCE mtime reading low; none covered the ARTIFACT
    mtime reading HIGH (a clock stepped back, or a package restored from a
    machine with a fast clock, reads fresh against every later edit).
  LEDGER CORRECTION: the earlier "protected only because package_status is
    ALSO required — a coincidence of composition" note was WRONG when written.
    review_checks.run() -> _incomplete() -> package_status.status(), so there
    is ONE staleness implementation reached by two paths and review_checks is
    self-sufficient. Verified by running review_checks.run() alone on a package
    with no invocation.json. Corrected in place above.
Final fix wave (commit 35b1ba9) — 4 prose corrections + the ledger line.
  Controller verified PROSE-ONLY across run_matrix, package_status,
  review_checks and box_pool by comparing docstring-stripped ASTs with all
  string constants blanked: IDENTICAL in every module, so no runtime message
  changed either. 353 tests OK.

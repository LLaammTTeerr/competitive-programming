# SDD ledger — plan: docs/superpowers/plans/2026-07-30-problem-setting-stage-1.md

Repo: /home/lamter/.claude/skills/competitive-programming
Branch: problem-setting-stage-1 — in place, NOT a worktree. Task 12 runs
`claude plugin details competitive-programming`, which reads the installed
plugin directory; a worktree elsewhere would make that check meaningless.
Base: 5b37ee1 (main). Spec + plan committed as 35d68dd.

## Pre-flight scan — controller rulings

Three items where the plan's reference code or policy would draw a review
finding. None is a genuine plan-vs-intent conflict, so none was escalated;
all three are recorded here so the rulings are not silent.

1. Task 9 reference code calls `os.wait4` on a `subprocess.Popen` pid. Popen
   reaps its own child, so this double-reaps. The implementer is authorised to
   deviate from the reference code for correctness, provided `_run_once` still
   returns (elapsed_ms, killed, exit_code, peak_kb) with those meanings.
2. Task 9 reference code rebuilds a frozen `Outcome` via `type(outcome)(...)`.
   The implementer is authorised to import `Outcome` or use
   `dataclasses.replace` instead.
3. Tasks 6 and 9 specify manual verification only — the two riskiest pieces.
   Ruling: Task 9 must additionally land `tools/tests/test_run_matrix.py`
   wrapping its fixture run, skipped when `g++` or the testlib cache is
   unavailable. Task 6 stays manual: it has network and cache side effects
   that do not belong in a unit suite.

## Standing rulings (apply to every remaining task, no re-ask)

- **R1 (human, Task 1 review):** required-field access on externally-authored
  JSON must raise `ProblemMetaError` (or the module's equivalent), never a bare
  `KeyError`. The plan's reference code uses bare `dict["key"]` in several
  tasks; apply this ruling wherever it recurs without stopping again.
- **R2 (controller, Task 3 review):** where the plan's reference *code*
  contradicts the plan's own stated *purpose*, the stated purpose governs and
  the fix is dispatched without escalation. This is not a plan-vs-reviewer
  conflict — it is the plan disagreeing with itself, and only one reading is
  defensible. Reported to the human as a flag, not a question. Genuine
  plan-vs-intent conflicts still escalate.

## Human decision: the runner is ioi/isolate, with no fallback

Asked whether to enforce limits or only measure them, the human pointed at
https://github.com/ioi/isolate — the sandbox actually used at IOI — and chose
**isolate only, no direct backend**. The pipeline refuses to run where isolate
is absent. This supersedes the controller's earlier rlimits proposal.

Why it is the better answer: isolate's meta file reports `max-rss` and `cg-mem`
for the child itself, so the posix_spawn mm-inheritance bug cannot exist;
`--processes`/`--fsize`/`--wall-time`/`--extra-time` enforce rather than
observe; `status` (TO/SG/RE/XX) and `cg-oom-killed` map straight onto verdicts;
and `isolate-check-environment` validates CPU frequency scaling and ASLR, which
is the real threat to a timing model built on ratios.

Environment checked before recommending the install: systemd IS PID 1 on this
WSL2 box and `systemctl is-system-running` reports running, cgroup v2 has
memory/pids controllers and a user.slice. So the cg-keeper's requirement is met.
Missing: build-essential, pkg-config, libcap-dev, libseccomp-dev,
libsystemd-dev. isolate is not in apt. Install needs sudo and is setuid root,
so it is the human's to run, not the controller's.

Consequence accepted: no CI, container, or collaborator checkout can run the
pipeline without isolate. The error must name the install, not just fail.

### isolate is INSTALLED AND VERIFIED (2026-07-30)

isolate 2.6, setuid root at /usr/local/bin/isolate, built from cf03a90.
Human ran Option A: system user `isolate` (uid 999), `isolate:200000:65536` in
both /etc/subuid and /etc/subgid, `isolate.service` (cg-keeper) enabled+active.

**Box access model — this differs from isolate 1.x and Task 9b must not get it
wrong.** After `--init`, the box is owned by the mapped subuid (200000) with
mode 0700, so the invoking user CANNOT copy files into `box/`. The working
mechanism is a bind mount:
`--dir=/work=/host/path:rw --chdir=/work --stdin=/work/in --stdout=/work/out`.
Files the sandbox writes come back owned by 200000 but world-readable, and are
deletable by us because the parent directory is ours — verified.

**Meta-file contract, all four paths verified by real runs:**

| case | meta fields observed |
| --- | --- |
| OK   | NO `status` line at all; `exitcode:0`; `max-rss:1792`; `cg-mem:344` |
| TLE  | `status:TO`; `killed:1`; `time:1.084`; `message:Time limit exceeded` |
| MLE  | `status:SG`; `cg-oom-killed:1`; `cg-mem:65536`; `exitsig:9` |
| RE   | `status:RE`; `exitcode:3`; `message:Exited with error status 3` |

Two traps for the implementer:
1. **Success emits no `status` line.** Parse absent-status as OK; do not look
   for a literal "OK".
2. **MLE arrives as `SG`, not its own status.** `cg-oom-killed` must be tested
   BEFORE the signal case, or every out-of-memory kill reports as a crash.
Also: use `--cg-mem` (cgroup limit, gives cg-oom-killed) rather than `--mem`
(address space) for memory enforcement.

**The peak-RSS bug is dead at the source:** a trivial program reports
`max-rss:1792` under isolate, against `15744` from the posix_spawn driver.

## Progress

Task 1: implemented (commit d1c3bb7). Review: spec ✅; 2 ⚠️ items resolved by
  controller (branch = problem-setting-stage-1 ✓, both commit trailers ✓);
  1 Important plan-mandated finding escalated to human per process.
Task 1: minor (deferred): load() does not wrap OSError/FileNotFoundError in
  ProblemMetaError — same pattern as R1 but for a missing file.
Task 1: minor (deferred): load() has no docstring, inconsistent with the rest
  of the module.
Task 1: minor (deferred): no cycle detection on subtask depends_on; later
  graph-walking code should not assume acyclicity.
Task 1: fix round 1/5 (2 addressed, 0 open; commits d1c3bb7..71d4148)
Task 1: minor (deferred): redundant outer try/except in the constraints and
  subtasks loops (problem_meta.py ~44-45, ~86-87) — harmless, re-raises only.
Task 1: complete (commits 35d68dd..71d4148, review clean) — 9/9 tests passing

Task 2: implemented (commit 025a46c). Review: spec mostly ✅ but 3 Important
  R1 findings; 2 ⚠️ items resolved by controller (branch ✓, both trailers ✓).
  No human escalation needed — R1 is a standing ruling and these fall under it.
Task 2: minor (deferred): changes_if_wrong is not type-checked before .strip(),
  so passing None raises AttributeError rather than FlagError.
Task 2: minor (deferred): read() does not validate payload["schema"] against
  the module SCHEMA constant, so a future schema bump goes unnoticed.
Task 2: fix round 1/5 dispatched — findings: bare KeyError on records missing
  "id" (flags.py:68); bare AttributeError when flags.json top level is not a
  dict (flags.py:44); raw FileNotFoundError when problem_dir does not exist
  (flags.py:86-89).
Task 2: fix round 1/5 (3 addressed, 0 open; commits 025a46c..fcd1e60)
Task 2: complete (commits 71d4148..fcd1e60, review clean) — 10/10 tests passing

Task 3: implemented (commit dd1d6d4). Review: spec ❌; 2 Important, both
  reproduced by the reviewer with direct execution. Branch + trailers
  pre-verified by controller before dispatch.
Task 3: minor (deferred): no coercion of float bounds to int before emission —
  a JSON 1e9 would emit `= 1000000000.0;`.
Task 3: fix round 1/5 dispatched — findings: subtask-only bounds silently
  dropped because the subtask loop's skip tests the GLOBAL bound before
  effective_bound() is consulted (defeats the tool's stated purpose, R2 applied);
  identifier() can emit a digit-leading token that is not lexable as a C++
  identifier. Plus: add a g++ -fsyntax-only compile test, which closes the
  reviewer's ⚠️ that nothing in this task ever compiled the generated header.
Task 3: fix round 1/5 (2 addressed + tests added, 1 NEW open; commits
  dd1d6d4..5e28f46). Compile test confirmed to actually execute here, not skip
  (g++ 15.2.0 present); re-reviewer proved it does not swallow compile failures
  by injecting a syntax error. New breakage: the C_ prefix rule maps "1" and
  "c_1" onto the same emitted identifier.
Task 3: fix round 2/5 dispatched — render-time uniqueness check over all
  emitted identifiers, raising a named error on collision. Scoped deliberately
  wider than the re-review proposed: identifier() has always collapsed "len-a"
  and "len_a" onto LEN_A, so patching only the C_ case would leave a live
  collision. Also: use _has_bounds in the global loop too — the duplicated
  inline test is what produced fix-round-1's Finding 1.
Task 3: fix round 2/5 (3 addressed, 0 open; commits 5e28f46..a74a29e).
  Re-reviewer reasoned through the spurious-firing risk explicitly: the tracker
  keys on (identifier -> source_id) and raises only on mismatch, and
  problem_meta already rejects duplicate ids, so no legitimate revisit can
  falsely raise. Global-vs-subtask cross-collisions are caught, not suppressed.
Task 3: complete (commits fcd1e60..a74a29e, review clean) — 33/33 tests passing

Task 4: implemented (commit ebc4f7f). Review: spec ❌, 1 Important (R1),
  reproduced live with a 0xff byte. Branch + trailers pre-verified.
  PLAN ERRATUM: Task 4 Step 4 says "12 tests"; the brief specifies exactly 11
  test functions and 11 are present with matching names. Controller verified by
  counting both. Not a missing test — fix the count if the plan is ever reused.
Task 4: named risks CLEARED by reproduction, not assertion — `git log` with a
  bare pathspec under cwd returns the right file even with same-named files in
  sibling problem dirs; an untracked file exits 0 with empty stdout and does
  fall through to mtime.
Task 4: minor (deferred): parse_block does not require the comment block to
  close with */, so an unterminated block scans the rest of the file for stray
  @key-shaped lines.
Task 4: fix round 1/5 dispatched — path.read_text() is evaluated as an argument
  before parse_block runs, so `except ScanError` cannot catch its
  UnicodeDecodeError/OSError. Folding in one Minor (a test pinning the
  untracked-in-a-repo timestamp branch) because the round is already running and
  it closes a risk the brief named; this does not extend the loop.
Task 4: fix round 1/5 (1 of 2 addressed, 1 open; commits ebc4f7f..9620f53).
  R1 fix confirmed, and the invalid-UTF-8 test confirmed non-vacuous — it fails
  if the fix is reverted. Open: the untracked-file test git inits but never
  commits, so `git log` exits 128, the SAME branch as "no repo at all"; the
  exit-0/empty-stdout branch it was written to pin is still untested, and the
  test would pass with the guard deleted.
Task 4: fix round 2/5 dispatched — fix the untracked test to commit first, and
  prove it fails with the guard removed. Plus: commit 9620f53 added 10 tracked
  __pycache__/*.cpython-314.pyc files (controller verified: all 10 came from
  that one commit, none from the previous eight, and .gitignore has no Python
  entries). Re-reviewer graded this cosmetic; CONTROLLER OVERRULED IT UPWARD to
  Important — this repo ships as a marketplace plugin, so version-pinned
  bytecode would be distributed to every installer and churn on every test run.
  Implementer told to stop using `git add -A`.
Task 4: fix round 2/5 (2 addressed, 0 open; commits 9620f53..4084b3f).
  Re-reviewer reproduced BOTH git exit paths in a scratch copy: with history +
  untracked file → exit 0, empty stdout (the branch the guard exists for);
  without history → exit 128. Guard-removed failure evidence in the report is
  real output, not a claim. Controller independently confirmed 0 tracked .pyc
  and that .gitignore kept its prior entries.
Task 4: complete (commits a74a29e..4084b3f, review clean) — 46/46 tests passing

Task 5: implemented (commit 2e69fd4). Review: 1 Critical + 2 Important, all
  reproduced with constructed inputs. Branch, trailers, no-stray-pyc
  pre-verified by controller.
Task 5: fix round 1/5 dispatched —
  (a) CRITICAL R1: main() catches only FileNotFoundError and UnicodeDecodeError,
      so IsADirectoryError/PermissionError leak. Catch OSError broadly.
  (b) _SUBTASK counts a commented-out \subtask, producing FALSE drift on a
      statement that compiles and agrees with problem.json. Fix: strip LaTeX
      comments (minding \%) and scope matching to the subtasks environment.
  (c) _KEYLIST's non-greedy .*? stops at the first ] anywhere, so a permitted
      key with a bracketed value (origin = {... [Vòng 2]}) before the four read
      keys yields four false drift lines. Fix: brace-aware scan for the key list
      and depth-0 comma splitting.
  (b) and (c) are plan-mandated (my regexes); R2 applied — a tool whose purpose
  is being the statement's only drift guard cannot emit false drift.
Task 5: NOTE for the final review — the implementer's two "acceptable for scope"
  regex verdicts were both wrong, and both were reached by reasoning about what
  the fields mean instead of feeding an input through the function. Its own
  report contained the contradicting line ("document this limitation if
  published"). Third instance of a self-graded claim failing under execution.
Task 5: fix round 1/5 (3 addressed, 0 open; commits 2e69fd4..a5b3e31).
  Re-reviewer ran the false-NEGATIVE check explicitly: both fixes remove text
  before matching, so they could have silenced the guard while passing all six
  regression tests. Confirmed genuine drift is still reported for subtask
  points, time, and memory. Also confirmed the brace scanner terminates on
  unclosed [, unbalanced { and }, and a missing bracket, and that \% does not
  start a comment while a later real % on the same line still does.
Task 5: minor (deferred): _parse_keylist_braceaware tracks {} depth but not [],
  so an UNBRACED value containing a literal ] still truncates — same limitation
  the old regex had, not a regression.
Task 5: minor (deferred): brace depth can go negative on unbalanced } without
  being clamped or flagged; terminates safely but returns a garbage dict.
Task 5: complete (commits 4084b3f..a5b3e31, review clean) — 62/62 tests passing

Task 6: implemented (commit 46c6317). Controller independently verified the
  bootstrap prints /home/lamter/.cache/testlib and that rcmp6.cpp compiles
  warning-free under -Wpedantic -Werror against it — this de-risks Task 9 and
  the flight dogfood, both of which need that checker specifically.
Task 6: review Approved but logged 1 Important, so the loop triggered on the
  finding rather than the verdict label. Reviewer verified the race guard under
  REAL concurrency (two parallel instances, real network clone, shared empty
  cache: both exited 0, same path, no leftovers) and endorsed the sibling
  staging dir for the right reason — same-filesystem rename(2), where /tmp could
  cross a device and make mv -T a non-atomic copy.
Task 6: minor (deferred): `mv -T ... || true` swallows every mv failure, not
  just the lost-race case; the testlib.h check catches the state but the
  diagnostic won't name the cause.
Task 6: fix round 1/5 dispatched — add `trap 'rm -rf "$staging"' EXIT` (armed
  only inside the clone branch, since `set -u` would break a trap referencing an
  unset $staging on the cached path); add `mkdir -p` for the cache parent so a
  fresh container works. Folded the mkdir Minor into an already-running round.
Task 6: fix round 1/5 (2 addressed, 0 open; commits 46c6317..e5c7a2b).
  Re-reviewer independently reproduced the SIGTERM trap firing (exit 143,
  staging reclaimed) and the fresh-parent case, rather than trusting the
  report's transcript — it noted the report's own SIGTERM evidence was not a
  full transcription. Controller separately confirmed the cached path is
  unaffected by the trap under set -u.
Task 6: complete (commits a5b3e31..e5c7a2b, review clean) — script verified
  manually per ruling 3; 62/62 Python tests unaffected

Task 7: implemented (commit fb5e376), 20 tests (13 brief + 7 added).
  Controller independently probed the boundaries against the committed code:
  t_main 8/500/501/370/900 -> TL 1000/1000/1500/1000/2000, kill always 2*TL,
  TL always >= floor; exactly-at-TL accepted; slow-and-wrong reports TL banded;
  killed reports TL not banded. Imports are only __future__, math, dataclasses —
  no clock or process, which is what keeps this file testable.
Task 7: review — no functional defect, 1 Important + 2 Minor.
  RESOLVED BY CONTROLLER, not a finding: the reviewer's ⚠️ claimed Tasks 1–6
  artifacts were absent from the tree so the full suite was unverifiable. That
  was inferred from the diff and is wrong — controller ran it: 82/82 passing,
  all of tools/ present.
Task 7: fix round 1/5 dispatched — floor_ms and step_ms have zero coverage
  despite being contract parameters Task 9 depends on (behaviour verified
  correct by hand, so this is a regression-protection gap, not a bug). Folding
  in the Minor: two tests are restatements; replacing them with the
  already-on-a-step-multiple rounding branch (t_main=750) and time_ms=0, both
  currently untouched.
Task 7: fix round 1/5 (2 addressed, 0 open; commits fb5e376..b4067ca).
  Re-reviewer used MUTATION TESTING rather than inspection: broke floor_ms
  (test caught it, 500 vs 1000), broke step_ms (1600 vs 1500), and made ceil
  always round up (1500 vs 2000). Each new test provably distinguishes correct
  code from the defect it exists to catch. Strongest evidence standard in the
  run so far — worth reusing for the remaining tasks.
Task 7: complete (commits e5c7a2b..b4067ca, review clean) — 84/84 tests passing

Task 8: implemented (commit 305a91e). Review APPROVED, 0 Critical/0 Important.
  Controller probed independently: severity order holds (FAIL beats TL beats
  WA); expected OK / actual FAIL -> mismatch; expected WA / actual OK -> hole;
  group_verdict([]) raises a clear ValueError. Reviewer ran both requested
  mutations for real in a /tmp copy — WA-before-TL in _SEVERITY, and compare()
  routing everything to mismatches — and confirmed the tests catch each.
Task 8: OPEN QUESTION RESOLVED as not-a-defect: a solution or group present in
  `actual` but absent from `expected` is silently dropped. Traced to the brief's
  own reference implementation, and currently unreachable — scan_solutions
  enforces that @expect covers exactly the declared subtask ids, and run_matrix
  builds `actual` from the same manifest. Latent if run_matrix is ever changed
  to discover solutions from disk. Deferred as a documentation nit.
Task 8: minor (deferred): all 9 new tests repeat inline `from tools.matrix_core
  import ...` instead of using the file's existing top-level import.
Task 8: minor (deferred): test_empty_group_is_an_error asserts only
  assertRaises(ValueError), not the message — a mutant that drops the guard and
  falls through to the generic "unknown verdicts" raise still passes it, so the
  report's "clear, actionable message" claim is not actually pinned.
Task 8: minor (deferred): compare()'s outer loop is `sorted(expected)` but the
  inner group loop is unsorted — inconsistent determinism guarantee.
Task 8: complete (commits b4067ca..305a91e, review clean) — 93/93 tests passing

Task 9: implemented (commit 842b640), 95/95 tests. Reviewed on the most capable
  model — process/signal/timing risk justified the tier. Controller
  independently confirmed: clean fixture run holes 0 exit 0; broken fixture
  (0 0) holes 1 naming sol-wrong.cpp exit 1; tree clean after restore.
  Ruling 1 solved with os.posix_spawn + owned wait4; ruling 2 via
  dataclasses.replace; ruling 3 test executes here, does not skip.
Task 9: review found 3 Important, all by experiment, not reading.
  (a) peak_kb is floored by the DRIVER's RSS: posix_spawn copies the parent mm
      and exec_mmap folds its high-water into the child's signal->maxrss. A
      1280 KB program reported 15744 KB; after ballooning the parent to 317 MB
      the same program reported 322944 KB. Wrong for any solution under ~16 MB,
      makes the ML branch fire spuriously (ML outranks WA), and later solutions
      read higher than earlier ones — the exact cross-contamination the module
      docstring claims to avoid. The report's 52480==52480 evidence passed only
      because 50 MB clears the floor.
  (b) checker subprocess has no timeout; a `for(;;){}` custom checker compiled
      clean and hung the pipeline silently for 25 s until killed.
  (c) problem.io.input/output are ignored (plan-inherited) — a file-IO problem
      is silently mis-run rather than erroring. SCOPE DECISION: fail loudly with
      MatrixError; file IO is a later feature, not a Stage 1 one. Worth telling
      the human, since vnolymp/VOI packages commonly use .inp/.out.
Task 9: fix round 1/5 dispatched — the 3 Importants plus 4 small items in the
  same functions: pin the band path (reviewer showed compute_limits is
  patchable by name, so no sleep and no flakiness needed; mutating
  `if outcome.banded` to `if False` currently leaves the suite green); derive
  `killed` from the reaped status instead of hardcoding it, so an exit racing
  the deadline is not misreported as non-banded TL; make `code` sticky in
  _time_median so a crash on run 1 cannot be laundered by runs 2-3 into an
  accepted jury answer; and fix the band flag's `assumed` text, which claims a
  reclassification to a verdict that does not exist.
Task 9: minor (deferred): MatrixError surfaces as a traceback not a one-line
  stderr message (house style, matches scan_solutions/drift_check) — FIXED in
  the final fix wave: main() catches MatrixError, prints one line, returns 2.
Task 9: minors STRUCK AS ALREADY DEAD (final fix wave, verified against the
  code at that point — later rewrites fixed all three and nobody came back to
  strike them; leaving them would have cost Stage 2 three investigations of
  non-problems):
  - "no try/finally around the poll loop so KeyboardInterrupt orphans the
    child": there is no poll loop. 9b removed it entirely, and 9c's per-run
    box is torn down in a `finally` that catches BaseException.
  - "band re-run reuses the stale verdict_src for nondeterministic solutions":
    it does not. `_classify` re-runs the checker after the re-timing, so the
    verdict comes from the re-run's own output.
  - "PC_BASE_EXIT_CODE is 0 without -DTESTSYS so a quitp checker exits 0 ->
    OK": unmapped checker exit codes now default to FAIL, never OK/WA, and 7
    is documented as deliberately unmapped.
Task 9: fix round 1/5 (7 addressed, 0 open; commits 842b640..8a3bbb5), 99/99.
  Controller re-verified the fixture clean run and the 0 0 hole-fire.
Task 9: RESIDUAL RISKS, both routed to 9b, both corrected upward by the
  re-reviewer against the implementer's own framing:
  - the ru_maxrss fallback is NOT cold-start-only. Instrumented over 200-300
    calls it fires 1-3% of the time at scattered indices, and each firing
    reproduces the FULL contaminated value (~320 MB tracking the driver's
    ballast). On a correct low-memory solution that is a false-positive ML.
  - the ~7% low bias is always LOW, never high — VmHWM is monotonic so a poll
    can only miss the peak. An adversary solution sitting just over the memory
    limit can read as under it: a false-negative ML.
  Two opposite failure modes, both in memory classification, both inherent to
  polling /proc from outside the process. isolate's own accounting removes both.
Task 9: minor STRUCK AS ALREADY DEAD (final fix wave): "`killed` is now true
  for ANY SIGKILL, including an external OOM kill". It is not: `killed =
  status == "TO"`, i.e. isolate's own time-kill status and nothing else. An
  OOM arrives as status SG with cg-oom-killed and is read as `oom`.
Task 9: complete (commits 305a91e..8a3bbb5, review clean) — 99/99 tests passing

Task 9b: implemented (commit 9376299), 104/104, reviewed on the most capable
  model. Controller verified independently: runner=isolate, cg=true,
  metric=cpu, trivial adder peak_kb 3840 (was 15744), boxes cleaned, hole
  still fires, git clean.
Task 9b: verified GOOD by the reviewer against real runs and crafted meta
  files — both traps handled in the right order; XX raises before any verdict
  is derived; five isolate failure modes each give a named MatrixError; cleanup
  fires on a real exception path. It also checked the hazard this design most
  depends on: isolate truncates the meta file on every --run, so a stale
  verdict cannot be read.
Task 9b: CRITICAL — the driver permanently damages the user's source tree, and
  the report understated it as "world-writable for the run's duration".
  Controller confirmed on the live repo: tests/g1 left at drwxr-xrwx, .build at
  drwxrwxrwx, and — undisclosed in the report — the regenerated ANSWER KEY
  tests/g1/01.a is owned by mapped subuid 229247, not writable by lamter, not
  chmod-able by lamter. `git status` stays clean because git tracks neither
  ownership nor directory modes and both paths are gitignored. It also fires
  BEFORE the refuse-to-run check, so an absent isolate damages the tree and then
  declines to work.
Task 9b: fix round 1/5 dispatched — stage into a private mkdtemp outside the
  repository and copy results back as the user, rather than bind-mounting the
  repo. A finally that restores modes is NOT sufficient: it leaves the
  subuid-owned .a behind, which is the harder half. Plus a recovery step for
  damage already done. Four smaller items folded in: a crashing model diagnosed
  as "exited 0"; a wall kill reported as a CPU-limit breach; isolate's default
  --processes=1 silently failing multi-threaded solutions (make it explicit,
  don't inherit an undecided default); and a cleanup test whose comment claims
  exception-path coverage it does not have.
Task 9b: reviewer AGREED with the implementer's other two disclosed concerns and
  supplied better reasoning for one: a box-id collision cannot produce a wrong
  verdict, only a loud status:XX / Box not found -> MatrixError, because --init
  on an existing box returns 0.
Task 9b: fix round 1/5 (5 addressed, 0 open; commits 9376299..1fb6cee), 109/109.
  Controller verified the Critical is fixed AND the prior damage healed:
  tests/g1 755 lamter, .build 755 lamter, 01.a now uid 1000 and writable;
  refuse-to-run leaves the mode untouched; hole still fires; no boxes; git clean.
  Re-reviewer reproduced the ORIGINAL damage first, then ran the fixed driver
  over it to prove recovery works on a genuinely foreign-owned .a.
  Answer-key byte fidelity proven with a 300 KB pathological input (CRLF,
  embedded NULs, all bytes 0x01-0xFF, a 300 000-char line, no trailing newline):
  sha256 identical in and out. Also checked concurrency (two simultaneous runs
  both clean), strict umask 077, and mutation-tested the new cleanup assertion
  (no-op close_isolate_box -> test fails, so it is load-bearing).
Task 9b: minor (deferred) x5: a non-owner-writable tests/<group>/ surfaces as a
  bare PermissionError not a MatrixError; a missing staged output would become
  an EMPTY answer key rather than an error (unreachable on this isolate build);
  output is buffered whole in RAM with no --fsize cap; shutil.rmtree
  ignore_errors could leak the stage dir if a solution mkdirs a subuid-owned
  subdir in it; _time_median makes `killed` sticky-OR but `message` sticky-first,
  so a flaky model can produce incoherent diagnostic text.
Task 9b: NOTE for the final review — task-9b-report.md's Concerns section still
  claims "world-writable for the run's duration" as current design. That is now
  false and contradicted by the report's own addendum; stale text not removed.
Task 9b: NOTE for the final review — test_solution_output_lands_in_repo_owned_
  by_us_not_a_subuid globs over a copytree of the fixture. On THIS machine the
  fixture carries untracked gitignored uid-1000 artifacts that copytree
  propagates, so a total regression of the copy-back would still pass here. It
  is sound on a clean clone. Asserting post-run mtime or content would make it
  clone-independent.
Task 9b: complete (commits 8a3bbb5..1fb6cee, review clean) — 109/109 passing

Task 10: implemented (commit 8e9195a), 336-line SKILL.md, tools/ untouched.
  Controller verified plugin validate --strict passes, name matches directory,
  109/109 still green, and all nine required content markers present.
  Reviewer confirmed real grounding: the validator snippet compiles clean under
  -Wpedantic -Werror against the actual testlib.h, gen_constraints_header and
  drift_check produce exactly the documented output, O-02/O-09 cross-check
  against plan.md, and the ordering doctrine carries both arguments not just the
  sequence. Disambiguation steers 3 of 4 collision phrasings correctly; the
  fourth ("my brute force is too slow") correctly matches neither skill.
Task 10: fix round 1/5 dispatched — 2 Important.
  (a) CONTROLLER'S OWN ERROR, inherited from my task brief: the skill's FIRST
      command uses `$BASE`, which nothing defines. Run literally it exits 127.
      Investigated the alternatives: ${CLAUDE_PLUGIN_ROOT} is the documented
      convention and this plugin's .mcp.json uses it, but it is NOT exported
      into a bash shell — the harness substitutes it in MCP config only. What a
      skill actually has is the "Base directory for this skill: <abs path>"
      line in its invocation preamble. Requirement given: no runnable command
      may reference a variable the reader has not been told how to set.
  (b) R-01 and R-02 are conflated under one period. usage-guide.md:875 pins
      65536 to registerGen(...,1); plan.md:198 R-02 is version 0's "bit 31 of
      nextBits(63) never set", a different defect. The implementer's own
      self-review flagged the pairing as imprecise and rewrote the prose but
      left the wrong number.
Task 10: minor (deferred): the "enforce format strictly" / "name every
  variable" bullets lightly restate usage-guide.md, borderline against the
  skill's own principle of carrying only what the guide does not.
Task 10: PROCESS NOTE — the report claimed "every command was actually
  compiled/run" but its verification list omitted the bootstrap block, which is
  where the broken command was. A blanket claim narrower than its own evidence
  list is the same failure mode as the earlier read-not-run reports.
Task 10: fix round 1/5 (2 addressed, 0 open; commits 8e9195a..46ec609).
  Controller substituted a real path and ran the documented bootstrap: resolves
  TESTLIB=/home/lamter/.cache/testlib with usage-guide.md and plan.md present.
  Re-reviewer verified R-02's CONSEQUENCE against plan.md:198-213 — bias for any
  n > 2^31 (next(0LL, 4294967295LL) can never return >= 2^31, half the range
  unreachable), not a short period — and confirmed "versions 0/1 stay
  byte-identical forever" against plan.md:65-68 (tests/test-003_run-rnd pins
  them). Swept every bash block for undefined variables: none. The new evidence
  table covers all 7 commands plus the Python snippet and the Polygon DSL.
Task 10: complete (commits 1fb6cee..46ec609, review clean) — 109/109, skill
  validates, tools/ untouched

Task 10 REOPENED during Task 11 — an escape that got past two reviews and the
  controller. preparing-tests never tells the reader to cd, and `tools` is only
  importable with the plugin root as cwd:
    $ cd /tmp && python3 -m tools.gen_constraints_header
    ModuleNotFoundError: No module named 'tools'
  So every python3 -m tools.* command in that skill fails as written. The
  undefined-variable sweep in the last review missed it because the variables
  ARE defined — the working directory is what is wrong. "Defined" and "runnable
  in context" are different properties and only the second one matters.
  Found because Task 11's implementer hit it independently and documented a
  `cd "$PLUGIN_ROOT"` in the sibling skill's bootstrap. Fix dispatched: mirror
  validating-solutions' block verbatim, and add a working-directory column to
  the evidence table — that column is what would have caught it.
  LESSON for the final review: verifying a command runs is not enough; verify
  it runs from where the reader will actually be standing.
Task 10: fix round 2/5 (1 addressed; commits e034650..be38c4a). Controller
  verified from /tmp: both python3 -m tools.* commands succeed as written, and
  the two siblings' Bootstrap blocks are byte-identical.
Task 10: CONTROLLER RULING — re-review round 2 reported a HIGH "new breakage" at
  SKILL.md:75 (`g++ ... file.cpp -o file` fails from the plugin root). OVERRULED
  as a false positive: the line is introduced by "Compile everything the same
  way:" and is a flags TEMPLATE — file.cpp/file are placeholders nobody has.
  Making them absolute would degrade the skill. Not silently discarded; the
  ruling is here and the reviewer's underlying instinct was re-scoped rather
  than dropped.
Task 10: fix round 3/5 dispatched — the REAL gap the reviewer was circling: the
  skill never states where the reader stands for problem-relative work after
  `cd "$PLUGIN_ROOT"`. Asked for one paragraph fixing the convention (tools
  commands run from PLUGIN_ROOT taking the problem dir as an argument;
  everything problem-relative happens in the problem directory) and for the
  <problem-dir> angle-bracket placeholders to become a real "$PROBLEM" variable
  — a variable is followable in a way a placeholder is not, which is the shared
  lesson of rounds 1 and 2.
Task 10: asked the implementer to CHECK whether validating-solutions has the
  same gap and report it WITHOUT editing that file — it belongs to Task 11.
Task 10: fix round 3/5 (1 addressed; commit 356aa16). Controller ran the
  Bootstrap block plus both tools commands from /tmp using $PROBLEM against a
  scratch fixture: both succeed. Skill now references PROBLEM in 5 places.
  Symmetry check confirmed validating-solutions has the identical gap.
Task 10: complete (commits 1fb6cee..356aa16, 3 fix rounds) — 109/109, validates

Task 11: implemented (commit e034650), 257-line SKILL.md, tools/ untouched.
  Controller verified: name matches directory, plugin validate passes, plugin
  details now lists 5 skills, all required content present, bounded-claim
  phrasing present ("no solution in the zoo survives", never "the tests are
  strong").
Task 11: CREDIT — this implementer's Bootstrap block is what exposed Task 10's
  missing `cd`. It hit ModuleNotFoundError for real while writing the sibling
  and documented the fix; three passes of inspection on Task 10 had missed it.
  Independent reimplementation beat review here, which is the same argument the
  adversary zoo makes, applied to documentation.
Task 11: symmetry fix dispatched BEFORE review (cheaper than review->find->loop)
  — adopt PROBLEM= in Bootstrap and replace the <problem-dir> angle-bracket
  placeholders at :141 and :172 with "$PROBLEM", matching preparing-tests'
  wording rather than paraphrasing it.
Task 11: OPEN GAP carried forward by design — TL/ML zoo verdicts were confirmed
  by reading matrix_core.py, not by an end-to-end run, because the mini fixture
  has no slow or memory-heavy solution. Honestly disclosed. Task 12's flight
  dogfood is where it gets exercised; the final review inherits it.
Task 11: symmetry fix landed (commit 3be0f57). Controller verified from /tmp:
  no <problem-dir> placeholders remain, bootstrap blocks byte-identical apart
  from one word of per-skill wording, and scan_solutions + run_matrix both run
  clean (holes 0, exit 0).
Task 11: review — metadata block verified line-for-line against
  scan_solutions.py's parser; TL/band numbers exact against compute_limits;
  4 boundary phrasings route correctly. 2 Important.
  (a) The zoo table is wrong in two directions, confirmed by the controller:
      the parser accepts 8 tags; the table has 9 ROWS / 6 distinct tags and
      includes `main`, which the file's own Mission line defines as not part of
      the zoo; time-limit-exceeded-or-accepted is missing from the table and
      demoted to a footnote calling it "a tenth tag", which conflates rows with
      tags and does not reconcile. Compounding: the fan-out instruction points
      at this table, so an agent would never write a band-expected solution
      while the same page explains the band is why that tag exists.
  (b) Environment facts are restated near-verbatim from preparing-tests for
      three of four facts, but the fourth (no fallback runner) is referenced
      instead — an inconsistent line drawn inside one section.
Task 11: CONTROLLER RULING on (b) — the reviewer recommended REMOVING the
  duplicated TL/band and memory facts and referencing the sibling. OVERRULED.
  Skills load independently; a reader who invokes validating-solutions alone
  must not have to load preparing-tests to learn what TL means, and band
  semantics are core content for a skill about verdicts. The real defect is the
  inconsistency, so fix by LEVELLING UP: keep the facts, add the missing
  no-fallback statement, and have both skills name tools/matrix_core.py's
  compute_limits as the single source of truth so drift is resolvable.
  Routing the matching authority-pointer to preparing-tests separately.
Task 11: fix round 1/5 (2 Important + 2 Minor addressed; commit ef0aaa0).
  Zoo table now 9 rows with main excluded and time-limit-exceeded-or-accepted
  restored; "tenth tag" gone; no-fallback stated; compute_limits named as
  authority. One NEW error introduced: SKILL.md:132 says the rows map onto
  "six" tags — it was six while main was a row, is five now, and the sentence
  did not follow. Round 1 fixed an arithmetic error and created one in the same
  paragraph; both had the same cause, a hand-maintained count sitting next to a
  table with nothing tying them together. Asked whether the sentence needs a
  number at all.
Task 11: CONTROLLER'S OWN ERROR, found by the re-reviewer and traced to source —
  the band is written `[TL, 2×TL]` everywhere, but matrix_core.py:59 is
  `if time_ms > limits.tl_ms`, strictly greater. Exactly-at-TL is ACCEPTED, as
  Task 7 proved by running classify(1000, ...) -> OK. The correct notation is
  `(TL, 2×TL]`, open on the left. This wrong notation originates in MY spec
  (§5 and §10) and propagated into every dispatch and both skills. Fixing in
  validating-solutions now; the spec and preparing-tests need the same
  correction — carry to Task 12 / the final review.
Task 11: fix round 2/5 (2 addressed, 0 open; commit ee5683a). Re-reviewer
  verified all four boundary cases against classify: at-TL accepted, TL+1
  banded, at-kill still banded, above-kill killed-and-not-banded; units match
  (both sides milliseconds). The tag-count sentence is now number-free AND
  carries the verification command inline, which is better than dropping the
  number alone — a reader can check rather than trust.
Task 11: complete (commits 46ec609..ee5683a, 2 fix rounds) — 109/109, validates

Task 10: round 4 (commit 0ceb4e7) added the compute_limits authority pointer and
  found NO drift — stated TL numbers match DEFAULT_FLOOR_MS / DEFAULT_STEP_MS.

## Band-notation sweep (task 22) — in flight

The `[TL, 2×TL]` error is mine and propagated from the spec into six live
places. Confirmed extent by grep:
  tools/matrix_core.py:55   classify()'s OWN docstring — worst case, it
                            contradicts the comparison three lines below it
  tools/run_matrix.py:6     module docstring
  tools/run_matrix.py:801   inline comment
  skills/preparing-tests/SKILL.md:118
  spec:222                  the source it propagated from
  skills/validating-solutions  — already fixed under Task 11 round 2
  plan:33,1495,1741         — historical record of what was planned; NOT fixed,
                            deliberately, rewriting it would be revisionism
Dispatched as comments/docstrings/prose only, no behaviour change:
matrix_core.py:59 is correct and must not be touched. Survived reviews on
Tasks 7, 8, 9, 9b and 10 because every one checked the NUMBERS, which were
right, and none checked the INTERVAL, which was not.

Band sweep (task 22): complete (commit 17fc9ca), 6 sites fixed — the
  implementer found a 6th in test_run_matrix.py that the controller's list
  missed. Re-reviewer verified BOTH boundaries by execution: classify(1000,...)
  -> banded=False (open left), classify(2000,...) -> banded=True (closed
  right), so `(TL, 2xTL]` is right on both ends. Comment/docstring/prose only;
  109 tests unchanged. run_matrix.py:841's parenthesis confirmed to be prose,
  not interval notation. Only the 3 deliberately-historical plan occurrences
  remain.

Task 12: complete (commit 71641d7) — 0.5.0, README with the isolate
  prerequisite, plugin details lists 5 skills, 109/109.
Task 12 DOGFOOD RESULT — the acceptance test for the whole stage, and it
  passed on all three must-surface items:
  1. checker landed on stock rcmp6, not custom
  2. the start-vs-end-index WA solution was caught, with the killer tests named
     (the 110/10 suffix pair; g1/10, g2/10, g2/12)
  3. the `xâu con` assumed-definition ambiguity recorded by hand as flag
     amb-001 — still has no automated owner until Stage 2's reviewing-problems
  Package: problem.json, validator, 3 generators, 23 tests + 2 samples, an
  8-solution zoo, final invocation.json holes 0 / mismatches 0 across 184 rows.
  Task 11's open TL/ML gap is CLOSED: both were exercised end to end, status:TO
  and cg-oom-killed observed as the skills claim.

## CRITICAL found by the dogfood, not by review — task 23 (9c)

`run_matrix` reuses ONE isolate box for every --run, and isolate does not reset
the cgroup counters between runs. Controller reproduced against bare isolate,
independent of our code:
    run 1  hog (400 MB, --cg-mem=65536) -> cg-mem:65536 cg-oom-killed:1 SG
    run 2  tiny (allocates nothing, exit 0, SAME box)
                                        -> cg-mem:65536 cg-oom-killed:1
Two consequences, the second worse than the one the dogfood reported:
  - cg-oom-killed is sticky, so after any OOM every later solution classifies
    as ML — and ML outranks WA in _SEVERITY, so it OVERWRITES correct verdicts.
  - cg-mem is a box-lifetime high-water mark, so peak_kb is wrong for every run
    after the largest one, OOM or not. Every invocation.json produced so far
    with more than one memory-using solution has inflated figures for most rows.
Same class as the bug that MOTIVATED the isolate migration — contaminated
memory accounting — relocated from the parent process into the box.
The dogfood's workaround (rename the ML solution to sort last) is not a fix; it
demonstrates that ordering changes verdicts, which disqualifies the artifact.
Fix dispatched: fresh box per run, with the timing cost measured and reported.

### CONTROLLER CORRECTION — I overstated this bug

The implementer pushed back and was RIGHT. Verified properly:
    run 1 (200 MB)             max-rss:206080  cg-mem:205636
    run 2 (trivial, same box)  max-rss:1540    cg-mem:205636
`max-rss` RESETS per run; only `cg-mem` is sticky. And run_matrix.py:580 is
`peak_kb = int(meta.get("max-rss", "0"))` — cg-mem is never read for peak_kb.

So: peak_kb was NEVER contaminated, and no previously produced invocation.json
has an inflated memory column. The real bug is exactly what the implementer
scoped it to — cg-oom-killed sticky, causing false ML that OVERWRITES correct
verdicts because ML outranks WA. Severe, real, and worth the fix on its own.

I reached the wrong conclusion by watching cg-mem stick in a bare-isolate repro
and never checking which field the code reads — the exact failure mode I have
spent this plan telling implementers to avoid. Recorded here rather than
quietly amended.

Consequence: my wrong claim was written into run_matrix.py's module docstring
("peak_kb was inflated for every solution after the largest memory user"),
where it contradicts line 580. Correction dispatched — same shape as the band
bracket: my error, in a docstring, disagreeing with the code below it. That is
now TWICE in this plan, which is a pattern worth stating in the final review:
a controller assertion repeated into source comments gets no independent check
unless someone tests the claim itself.

Task 9c: complete (commits 71641d7..6f8fe7b, 112/112). Re-reviewer confirmed
  the new test FAILS against the pre-fix commit, so it is not vacuous; tested
  box collisions against real isolate including the active-run case, which
  fails EARLIER and more safely than documented ("This box is currently in use
  by another process", exit 2, both sides safe); simulated KeyboardInterrupt
  mid-run and confirmed the finally-guarded cleanup catches BaseException;
  independently measured overhead at 2.16 ms per call → ~0.55 s across
  flight's 253 runs against a ~58.5 s total, inside the ~1 s run-to-run spread.

## Dogfood skill findings (task 24) — dispatched

Six findings from following the skills against a real problem. All are skill
CLARITY defects, not tool bugs — the dogfood explicitly confirmed the checker
exit-code mapping, the band convention, and the bootstrap convention all work.
preparing-tests:
  - the reaching check silently does NOTHING for string-length bounds. A
    readToken-based `1 <= |A| <= 20` never registers with testlib's bounds
    analyzer; the log prints bare variable names, the command EXITS 0, and a
    reader sees success where nothing was checked. Worst possible shape for a
    verification step.
  - `ensure(cond, "msg")` is a compile error; the message form is `ensuref`,
    which the skill never mentions. Friction at the first compile.
validating-solutions:
  - the zoo table reads as a mandatory checklist; it is a menu. flight has no
    place an overflow bug could hide, so forcing that row would produce the
    strawman the skill itself forbids. Skips must be recorded with a reason —
    a silently absent class is indistinguishable from an overlooked one.
  - a TLE solution whose slowness is iterative CONVERGENCE needs a floor, or it
    returns WA at small inputs instead of TL and its @expect is wrong.
  - the arbiter protocol lists two disagreement causes; there is a third —
    "not converged enough" — which is neither a logic bug nor statement
    ambiguity. Cost the dogfood a full matrix run; the fix was raising a sweep
    cap 4000 -> 40000 with zero logic changes.
  - a zoo row's NAME is not a promise about the realized verdict. A NaN output
    is PE not WA, and because group_verdict collapses to the most severe
    verdict, one test's PE silently swallowed another test's WA in the same
    group. Derive @expect from an observed run, not from the row name.

## For the final whole-branch review

Branch `problem-setting-stage-1`, 44 commits at review time (merge-base
5b37ee1); the "35 commits" originally recorded here was wrong — count is
`git rev-list --count 5b37ee1..HEAD`.
Triage list: 22 deferred minors, 5 controller rulings, 3 explicit notes — all
tagged in this file. None was silently discarded.

Additional item found while assembling the above: commits e5c7a2b and 46c6317
carry IDENTICAL subjects ("Add the testlib bootstrap with a first-writer-wins
race guard"). Task 6's fix round reused the original subject instead of
describing the fix, so the history reads as though the same work landed twice.
Cosmetic, but it is the kind of thing that makes a later bisect confusing.

## Final review + fix wave — CLOSED

Final whole-branch review (opus) found 1 Critical + 11 Important. The Critical
was the THIRD relocation of one defect class: memory accounting contaminated by
something other than the process being measured — parent `mm` (Task 9) → box
cgroup (Task 9c) → the staging directory Task 9b introduced. `stage_dir` was
mkdtemp'd into /tmp, which is tmpfs, so a solution's stdout was charged against
its own `--cg-mem`. Controller reproduced: a 1.6 MB program writing 70 MB gave
`max-rss:1668 cg-mem:65536 cg-oom-killed:1` — a false ML at 2.5% of the limit.
The module docstring asserted the opposite as a guarantee.

One fix wave, 7 commits (fce3c44..82fa307), 112 → 151 tests. All 12 addressed.
Scoped re-review exercised the REAL tmpfs path rather than the mocked test:
forcing staging onto /dev/shm reproduced the false ML exactly; default disk
staging gives `oom=False` and the full 48 MB output. Also confirmed a truncated
answer file can never be accepted as jury truth (pass 1 raises), exit-2 breaks
no consumer, and all five previously-unrunnable skill commands now work from a
foreign cwd.

### Adjudicated residuals — parked, not discarded

No second fix wave is permitted, so these are parked with rulings. None is
load-bearing: none affects the correctness of `holes`, which is the artifact
the whole pipeline exists to produce.

1. **PARKED, and it is the uncomfortable one.** `validating-solutions:292` and
   `run_matrix.py:1256` both say "One line on stderr", which is false for a
   compile failure — `run_matrix.py:207-211` embeds the command and g++'s full
   stderr. Ruling: real but cosmetic; a one-word fix ("a message on stderr").
   Flagged prominently to the human because it is the FOURTH instance on this
   branch of a doc claim the code does not support, and the only one introduced
   by the fix wave that was meant to end them.
2. **PARKED.** `.gitignore:52-54` claims to catch stray `.run_matrix_stage_*/`
   directories, but staging lands beside the PROBLEM package, which is a
   different repository. The rule catches nothing but fixture runs. Ruling: the
   comment is wrong rather than the code; the leftover only occurs on SIGKILL.
3. **PARKED.** `flags.py` leaves a permanent `flags.json.lock` beside
   `flags.json` in every problem package, documented nowhere. Unlinking it is
   unsafe under flock, so the fix is documentation. Ruling: harmless, but both
   skills instruct writing to that register, so Stage 2 should mention it.
4. **PARKED.** `run_matrix.py:262-265` says a runaway leaves "a file of this
   size per test"; outputs are per (solution, group, test), so the worst case
   understates disk cost by the size of the zoo.
5. **PARKED.** The tmpfs refusal is unit-tested with a mocked `_filesystem_type`
   plus an anti-inertness guard. The controller and the re-reviewer both
   exercised the real path by hand. A ~5-line unmocked case against /dev/shm
   would close it outright.

## Cross-task pattern worth watching

Two of four implementers have reported a standing ruling as satisfied after
reading the code rather than executing the failing path, and were wrong both
times (Task 2: R1 "satisfied" by one `.get()`; Task 4: "file read error caught
and re-raised as ScanError" — disproven by running it). Reviewers at a higher
tier than the implementer have caught both. Keep reviewers above implementers on
transcription tasks, and require triggered-path evidence for error-handling
claims rather than a reading.

## Stage 2 carry-forward (from the final fix wave)

Two items deliberately NOT done in the final fix wave, both controller
rulings rather than oversights. They are recorded here because nothing else
holds them, and each has a named reason for deferring rather than dropping.

1. **`subtask.depends_on` cycle detection** (`tools/problem_meta.py`).
   `load()` validates that every `depends_on` names a known subtask, but not
   that the dependency graph is acyclic — `g1 -> g2 -> g1` loads cleanly
   today. Nothing in the pipeline currently walks the graph, so it is latent
   rather than live; the first consumer that does (a scoring or ordering
   pass) turns it into an infinite loop. Fix is a topological sort in
   `load()` with a named ProblemMetaError. Originally raised as a Task 1
   deferred minor and never revisited.

2. **Prune `run_matrix.py`'s narration.** The module is roughly half prose,
   with the 9b (repo-ownership) and 9c (box-lifetime cgroup counters)
   incidents each narrated three or four times across the module docstring,
   `IsolateHandle`, `_run_once`, and inline comments — and the final review
   is right that this repetition is the *structural cause* of the
   repeated-claim errors on this branch, including the "neither defect is
   possible here" guarantee that stood false for two tasks. Deferred, not
   dropped, because: it is a large comment refactor with real risk of losing
   hard-won measured detail (the exact meta-file fields, the before/after
   numbers, the reason the checker is unsandboxed); the code itself was
   reviewed as coherent with no residue from any rewrite; and it is not a
   correctness defect. Doing it well means deciding *where each fact lives
   once* — probably a `docs/` note for the incident history, with the module
   keeping only what a reader needs at the call site — not deleting prose.
   Note the fix wave added to the narration rather than reducing it (the
   staging/tmpfs incident is now a fourth narrated incident), so this is
   larger than when it was first raised.

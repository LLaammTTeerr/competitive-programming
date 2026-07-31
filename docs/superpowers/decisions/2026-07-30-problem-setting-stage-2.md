# SDD ledger — plan: docs/superpowers/plans/2026-07-30-problem-setting-stage-2.md

Repo: /home/lamter/.claude/skills/competitive-programming
Branch: problem-setting-stage-2, cut from problem-setting-stage-1 (NOT main —
PR #3 is open and main does not yet contain tools/). In place, not a worktree:
Task 6 and 7 run `claude plugin details`, which reads the installed plugin
directory, so a worktree elsewhere would make those checks meaningless.
Base: 72ec0ff (the plan commit). Stage 1 merge-base with main: 5b37ee1.

Stage 1 finished at 151 tests, 8 skills expected after this plan (5 today + 3).

## Pre-flight scan — controller rulings, not escalated

Two items where the plan's own text could draw a review finding. Neither is a
plan-vs-intent conflict, so neither went to the human; both are recorded so the
rulings are not silent.

1. **`status()` and `run()` are specified to "never raise".** A reviewer may
   read broad `except (ProblemMetaError, OSError)` handling as swallowing.
   Ruling: deliberate and load-bearing. `package_status` exists to inspect
   packages *under construction*, which are malformed by definition, and
   `review_checks` exists to audit a package that may be broken. A tool that
   dies on the thing it exists to inspect is useless. Both are specified to
   turn an unevaluable check into a `done=False` / `low` finding carrying the
   reason, which is strictly more informative than a traceback.
2. **Tasks 4, 5 and 6 have no red/green cycle.** Their deliverables are
   SKILL.md prose, so "write the failing test first" does not apply. Ruling:
   the same shape Stage 1 used for its two skills, where no reviewer raised it.
   The verification for prose is that every command in the file was actually
   run, from the directory a reader would be standing in — which Stage 1 proved
   is where prose skills actually fail.

## Standing rulings inherited from Stage 1 (still binding)

- **R1:** externally-authored data must never surface a bare stdlib exception;
  raise the module's own error type. Extended in Stage 1's final wave to cover
  wrong *types* and missing files, not just missing keys.
- **R2:** where the plan's reference code contradicts the plan's stated
  purpose, the purpose governs and the fix is dispatched without escalation.
- **Evidence standard:** a claim in a docstring or a skill is a testable
  assertion. Stage 1 shipped four instances of a comment asserting something
  the code did not do; two of them were the controller's own words transcribed
  into source. If a task writes "X is guaranteed", there must be a test that
  fails when X stops being true.
- **Verification standard:** an error path you have not triggered is not
  handled, and a command you have not run from a foreign working directory is
  not runnable. Both were established the hard way in Stage 1.

## Progress

Task 1: implemented (commit 3418e82), 151 -> 154 tests. Controller probed
  independently: self-cycle, two-node cycle, unknown-dep (still the PRE-EXISTING
  named error, so ordering is right and StopIteration is impossible), valid DAG.
Task 1: review — cycle logic verified correct on graph shapes the tests do not
  cover (three-node cycle not touching the first-visited subtask, disjoint
  components with one cyclic, fan-in). Trail reports the MINIMAL loop:
  g1->g2->g3->g2 prints "g2 -> g3 -> g2", excluding g1. 1 Critical.
Task 1: CRITICAL — unbounded recursion. Controller reproduced: a linear chain
  (not even a cycle) of 1000 subtasks raises a bare RecursionError; 900 loads.
  R1 forbids exactly this on hand-authored input.
  PATTERN, 7th instance in this project: the dispatch explicitly asked the
  implementer to construct a deep chain and run it, and to write "not exercised"
  if it did not. The report wrote BOTH — the honest admission and a confident
  "no limit needed" verdict — and the verdict is what shipped. Rule restated in
  the fix message: when you write "not exercised", stop there; do not follow it
  with a conclusion.
Task 1: fix round 1/5 dispatched — iterative traversal with an explicit stack
  (not a RecursionError catch, which would leave a real graph unprocessable),
  preserving the minimal-loop trail and the existing messages. Folding in the
  reviewer's Minor since it is the same lines: next(s for s in subtasks ...) is
  an O(n) scan per node, making the walk O(n^2); build a sid->Subtask dict once.
Task 1: fix round 1/5 (2 addressed; commits 3418e82..cae22f8), 159 tests.
  Controller verified independently: 2000- and 5000-node chains load, a cycle at
  depth 1500 raises a named error, minimal-loop trail survives the rewrite.
  Re-reviewer confirmed the traversal is genuinely iterative, the dict cannot
  mask the duplicate-id error (that check runs first), and the trail is still
  minimal.
Task 1: NEW finding, round 2 — the deep-chain regression test is VACUOUS for
  its stated purpose. It builds the chain so each subtask depends on an
  ALREADY-PROCESSED one; load() visits in declaration order, so the stack never
  exceeds depth 1. Re-reviewer ran it against pre-fix 3418e82: it passes there
  too. The orientation that triggers the bug is the opposite one — head
  declared first, each depending on its SUCCESSOR — which is what the
  controller's own probe used when it reproduced the RecursionError.
  Same class as Stage 1's test_solution_output_lands_in_repo_owned_by_us
  finding: a guard that would pass against a total regression of what it
  guards. Round 2 requires the test rebuilt in the deep orientation AND the
  pre-fix failure pasted.
Task 1: fix round 2/5 (1 addressed, 0 open; commits cae22f8..ac4ae57), 160.
  Controller ran the amended test file against problem_meta.py at 3418e82:
  2 ERRORS pre-fix, 160 pass post-fix. Re-reviewer identified the two errors as
  exactly the two deep tests (deep_reverse_chain_2000 and cycle_at_depth_1500),
  not one deep test plus unrelated breakage, and confirmed the retained
  forward-order case is renamed and docstringed to disclaim being a depth guard
  rather than silently implying coverage it does not have.
Task 1: complete (commits 72ec0ff..ac4ae57, 2 fix rounds) — 160/160

Task 2: implemented (commit f2137c5), 160 -> 178 tests. flight reports all 11
  phases [x], reproduced by both controller and reviewer.
Task 2: 3 Important, and they interlock.
  1. status() RAISES on an examples entry that is a bare string
     (AttributeError in _samples). Controller found it. problem_meta validates
     `examples` as an ARRAY but not as an array-of-OBJECTS, unlike constraints
     and subtasks which each use _object per entry.
     FIX BOUNDARY (reviewer's, and I agree): fix in problem_meta.load(), not in
     _samples — Task 3's review_checks iterates problem.examples too and would
     inherit the identical crash from a local guard.
  2. NEW, missed by the controller's probe: _matrix() crashes on three
     malformed invocation.json shapes — holes as a string with mismatches null,
     holes as an int, and a top-level list. Reproduced all three. No shared
     loader exists for invocation.json, so this fix belongs in _matrix().
  3. THREE OF THE HOSTILE TESTS NEVER REACH THE CODE THEY NAME. They build
     {"schema":1, <field>} only, and load() validates checker.kind BEFORE
     subtasks or examples, so all three die on the missing checker.
     Consequence: test_hostile_examples_entry_bare_string_does_not_raise PASSES
     because it never reaches the crash in finding 1 — the bug sat under a
     green test asserting it could not happen. The report's "verified across 9
     hostile scenarios" table has three invalid rows.
Task 2: PATTERN, 3rd vacuous guard in this project (after Stage 1's subuid test
  and Task 1's forward-order chain). Always the same shape: the test passes for
  a reason unrelated to what it claims to check. Fix round requires every
  hostile payload built from a COMPLETE valid problem.json with one field
  mutated, plus a reverted-guard demonstration for each.
Task 2: fix round 1/5 dispatched — the three findings plus a smoke test for
  main()'s exit codes 0/1/2, which currently has no coverage at all.
Task 2: fix round 1/5 (4 addressed, 0 open; commits f2137c5..0b8b103), 185.
  Controller re-probed all seven hostile inputs: all return normally.
  Re-reviewer did the revert-and-run liveness checks the implementer's report
  only CLAIMED — reverting the new _object() guard makes the bare-string test
  fail with the original AttributeError; reverting the _matrix isinstance
  guards makes all three matrix tests fail, one of them by silently returning
  done=True rather than crashing, which is the more dangerous failure.
  The examples fix landed in problem_meta.load() as required, mirroring the
  existing _object pattern; flight's two real examples entries still load.
  _matrix's detail messages distinguish four causes rather than one catch-all.
Task 2: minor (deferred): TestMain leaks 26 lines of stdout into the suite —
  two main() calls with no contextlib.redirect_stdout, despite StringIO and sys
  already being imported for apparently that purpose and never used. Reviewer
  confirmed by grep that no other test in the suite prints, so this is the sole
  source of noise. Violates the project's pristine-output bar; 2-line fix.
Task 2: minor (deferred): the except (TypeError, AttributeError) wrapping the
  holes/mismatches isinstance checks in _matrix is unreachable — by then both
  are proven lists, so len() cannot raise. Dead defensive code.
Task 2: complete (commits ac4ae57..0b8b103, 1 fix round) — 185/185

Task 3: implemented (commit 1ce4cfc), 185 -> 197 tests. Never-raises contract
  verified live by the reviewer against all 8 adversarial inputs; KINDS
  coverage, severity enum, deterministic ordering all clean. The _samples
  divergence from package_status._samples (both .in and .a here, .in only
  there) was judged coherent — "does it exist" vs "is it right".
Task 3: CRITICAL — _stale_header is a false-positive generator, and the report
  called it a real defect. Controller verified: flight's constraints.h has an
  older mtime than problem.json, but render(problem) is BYTE-IDENTICAL to the
  file (986 bytes both). render() reads only constraints and subtasks; the edit
  that bumped the mtime added `examples`. Regenerating would change nothing.
  Reviewer found it is not flight-specific: it fires HIGH on the module's OWN
  bundled fixture, copytree'd with no artificial setup, from a ~37s committed
  mtime skew. So it will fire on essentially every future problem.json edit
  that is not about constraints or subtasks.
  Same failure Stage 1 paid two rounds for in drift_check: a guard that cries
  wolf gets ignored, which is worse than no guard. Fix: compare render(problem)
  against the file content, which cannot false-positive.
Task 3: Important — 5 of 8 hostile scenarios were verified ad hoc and never
  persisted as tests (nonexistent dir, solutions/ as a file, tex_path as a
  directory, tex_path non-UTF-8, constraints.h without problem.json).
Task 3: THE MISSING ASSERTION — nothing in the suite asserts that a known-good
  untouched package produces ZERO findings. That is exactly what Step 5 claims
  about flight, and its absence is why the fixture false positive went
  unnoticed. Required in the fix round.
Task 3: fix round 1/5 dispatched — content comparison, the 5 missing tests, the
  zero-findings assertion, and a decision on the redundant isinstance guard in
  _matrix (reviewer removed it and all 12 tests still passed).
Task 3: fix round 1/5 (findings addressed; commits 1ce4cfc..9a2e9ba), 203 tests.
  Controller verified: flight now reports "no mechanical findings", and a
  tampered constraints.h is still caught, so the check did not go blind.
Task 3: REAL DEFECT FOUND IN THE STAGE 1 FIXTURE, by the new content check.
  tools/tests/fixtures/mini/files/constraints.h is a hand-written stub
  ("#pragma once / // Constraints") where a GENERATED header should be. It has
  been committed that way since Stage 1 Task 9. render() produces the real
  thing with VALUE_MIN/MAX and G1_VALUE_MIN/MAX. The mtime check could never
  have seen this; the content check found it immediately.
Task 3: NEW finding, round 2 — the zero-findings test REPAIRS the fixture
  instead of surfacing the defect. It regenerates constraints.h before
  asserting, which makes the claim "a package I just repaired produces zero
  findings" rather than "a known-good package does", and guarantees the fixture
  defect stays hidden. The dispatch had explicitly said: if the committed
  header does not match render(), that is a real fixture defect, say so rather
  than adjusting the test to tolerate it.
  Round 2 requires: regenerate and COMMIT the fixture header; drop the
  regeneration step from the test; keep only the legitimate setup (mini has no
  examples or samples by design); and prove liveness by reverting the header to
  the stub and watching the test fail.
Task 3: fix round 2/5 (1 addressed, 0 open; commits 9a2e9ba..db5c010), 203.
  The Stage 1 fixture defect is FIXED AT SOURCE: mini/files/constraints.h is now
  the generated header, committed. Controller confirmed mini's validator.cpp
  still compiles clean against it under -Wpedantic -Werror, so the stub was not
  load-bearing. The fixture as committed now yields exactly one finding —
  incomplete-package: samples — which is correct, mini has no samples by design.
  The regeneration step is gone from the test; the retained setup (examples,
  sample files, invocation.json) addresses only what mini legitimately lacks.
  Re-reviewer honestly reported it could NOT run the liveness check rather than
  claiming it — a good report. Controller settled it directly: with the
  committed header the test's setup yields NO findings; with the old stub it
  yields stale-constraints-header, so the test genuinely fails without the fix.
Task 3: complete (commits 0b8b103..db5c010, 2 fix rounds) — 203/203

Task 4: implemented (commit d77c19b), 258-line SKILL.md, tools/ untouched.
  Controller verified the bootstrap runs verbatim from /tmp; no undefined
  shell variables; validate --strict passes; 203 tests unchanged.
  Reviewer independently checked the separation arithmetic: 2e5 squared = 4e10,
  2e5 * log2(2e5) ~ 3.6e6 — both correct; the non-separating counter-example at
  n <= 2000 makes "boring" concrete. flight's subtask bounds and points match
  the real problem.json. The [x] problem_json output line matches
  package_status.py's format string byte-for-byte. All 5 boundary phrasings
  route correctly.
Task 4: Important — originality is described as "a flag (spec §6) … it must be
  raised", but the flag register cannot hold it. Controller confirmed:
  flags.append(kind="originality") raises FlagError, and none of the eight
  valid kinds fits. Spec §6's own flagged-items list excludes originality too.
  An agent following the text literally has no mechanism.
  RULING: shaping runs AT the blocking gate with the human present; the flag
  register exists for the autonomous phases where nobody is watching and
  changes_if_wrong prices an interruption nobody is there to make. So this is a
  gate-conversation item, not a register entry. Fix is to drop the flag framing
  and keep the substance. If the implementer disagrees it may PROPOSE a new
  kind with reasoning — flags.py is out of this task's scope and Task 6 already
  touches tools/, so that would route there. The register is closed by design
  and the spec says adding a kind is a deliberate act, not a silent one.
Task 4: minor folded in: "a few milliseconds" for 3.6e6 ops is ~36 ms, i.e.
  tens of ms — loose phrasing in the one section pitched as arithmetic not vibe.
Task 4: minor folded in: the worked problem.json example uses the spec's
  illustrative tags and depends_on rather than the real committed flight values,
  while being framed as "the flight example"; the reviewer cross-checked and
  hit the mismatch.
Task 4: fix round 1/5 (3 addressed, 0 open; commits d77c19b..2b3523e), 203.
  Originality is now a gate-conversation item and says so explicitly, naming
  why flags.json cannot hold it. The implementer chose NOT to propose a new
  flag kind — the register stays closed. Figure corrected to ~36 ms. Worked
  example now matches the real flight problem.json byte for byte.
  Re-reviewer swept every citation in the file — tools modules, spec sections,
  sibling skill names — and confirmed each target exists; the only
  "not built yet" marker is creating-problems, which is correct until Task 6.
Task 4: complete (commits db5c010..2b3523e, 1 fix round) — 203/203

## Known limitation, surfaced twice — for the final review

The test suite is NOT safe to run concurrently with itself. run_matrix derives
isolate box ids from `pid % 65536` plus a per-run counter, so two simultaneous
suite runs on the same machine can collide. Both a Task 3 reviewer and the Task
5 implementer hit it and each reported "pre-existing failures"; running the
suite alone gives 203/203 with no leftover boxes, confirmed by the controller
both times. Stage 1 established a collision fails LOUDLY (isolate status:XX ->
MatrixError) and cannot produce a wrong verdict, so this is ergonomics, not
correctness — but it has now cost two agents a false "pre-existing flake"
diagnosis, and it will mislead CI if the suite is ever parallelised.

Task 5: implemented (commit 2ffc39d). Controller confirmed 203/203 alone and no
  leftover isolate boxes, so the implementer's reported failures were this
  concurrency flake, not a regression.
Task 5: GOOD — every flag KIND named exists and the flags.append snippet runs
  correctly against a scratch dir, which is exactly the check Task 4 failed.
  The xâu con example is textually accurate against flight.tex:74-75 and is
  used twice for real leverage. Mechanical/judgement split is clean.
Task 5: CRITICAL — SKILL.md:193-194 claims `python3 -m tools.flags` "exposes
  the same append" and "writes the identical record". Controller verified:
  exit 0, no output, nothing written, and flags.py contains ZERO __main__
  blocks. An agent following it believes a judgement finding was durably
  recorded when nothing happened — the precise failure the register exists to
  prevent. Fix is to delete the claim; adding a CLI is out of Task 5 scope and
  would route to Task 6 if the implementer argues for it.
Task 5: Important — SKILL.md:156 invokes superpowers:requesting-code-review,
  whose protocol begins "Get git SHAs" and whose template is built on
  git diff BASE..HEAD. This skill states twice, correctly, that it audits a
  directory that may never have touched git, and ~/Projects/my_cp_problems is
  not a repo. Nothing tells the agent what to substitute. Fix: keep the
  principle (fresh context, independent reviewer), drop the diff plumbing, and
  give the dispatch shape this skill actually needs.
Task 5: CONTROLLER'S OWN ERROR — spec §11 lists "Unreached bounds" and my
  task-5 brief enumerated four judgement classes, silently dropping it with no
  rationale recorded. Verified absent from BOTH halves: not in review_checks
  KINDS, and testOverviewLogFileName appears 2x in preparing-tests and 0x in
  reviewing-problems. A package can pass this audit clean while a declared
  bound is never attained by any test. An audit that assumes an earlier phase
  did its job is not an audit. Fix: add it as a fifth judgement item with the
  runnable command, noting the Stage 1 dogfood finding that the overview log
  reports nothing useful for readToken-based string-length bounds.
Task 5: fix round 1/5 (4 addressed, 0 open; commits 2ffc39d..503f9b6), 203.
  The CLI claim was handled better than asked — not deleted but replaced with
  an explicit warning that flags.py has no __main__, so a reader who tries it
  knows why nothing happened. Dispatch now names its inputs concretely
  (problem dir, statement path, the five classes) instead of only saying
  "not a diff". Re-reviewer RAN the new reaching check from /tmp against
  flight: exit 0, bare variable names for the readToken bounds as the Stage 1
  dogfood predicted, and the awk fallback gives 1-6 for g1 and 1-20 for g2,
  matching the declared bounds. All "four classes" references updated to five,
  including Mission and "Done means" — zero stragglers.
Task 5: complete (commits 2b3523e..503f9b6, 1 fix round) — 203/203

Task 6: implemented (commits f138082, e4ac7c6). Review APPROVED — zero
  Critical, zero Important. First clean gate in Stage 2.
  Controller verified git history intact after a self-corrected --amend
  mishap: all prior commits reachable, exactly two new ones, correct subjects
  and trailers, both carry-forward greps clean, 8 skills registered.
  Reviewer executed every cited mechanism from /tmp against the real flight
  package rather than reading it — KIND_PREFIX, package_status, review_checks,
  and flags.py's changes_if_wrong guard. It also proved review_checks is NOT a
  guard that cannot fail, by feeding it a deliberately broken package
  (checker.kind: None) and confirming a MEDIUM finding with exit 1. The
  run_matrix docstring diff is comment-only, no behaviour change.
Task 6: minor (deferred): shaping-problems gained a reviewing-problems routing
  row the brief did not ask for — consistent with the other tables, disclosed
  by the implementer, harmless scope creep.
Task 6: minor (deferred): writing-statements still has no "Am I the right
  skill?" table and does not route to creating-problems, though the pipeline
  visits it twice. Predates the pipeline design and is outside spec §3's five
  new skills — a gap for a future task, not a defect of this diff.
Task 6: HANDOFF NOTE FOR TASK 7 — the stale "The plugin ships N skills: ..."
  enumeration sentences were DELETED, not renumbered, in four sibling files.
  Task 7 must know they are gone rather than merely out of date, and owns
  reconciling the count in the manifest and README.
Task 6: complete (commits 503f9b6..e4ac7c6, review clean, 0 fix rounds) — 203

Task 7: implemented (commit 9003c89). Part A verified: 0.6.0, 8 skills,
  validate --strict passes, 203 alone. marketplace.json bumped too — not in the
  brief's list but --strict requires plugins[0].version to track.
Task 7 DOGFOOD — both acceptance tests passed.
  B1: xâu con surfaced independently. Reviewer's evidence for genuineness: the
  subagent cited flight.tex:74-75, a two-line span more precise than either
  SKILL.md (no line number) or flags.json (line 74 only) records, and its
  class-4/5 factual claims check out against problem.json:22 and flight.tex:67
  while appearing in neither source. ZERO false positives. Caveat recorded: the
  dispatch prompt was not preserved, so independence cannot be audited — future
  runs of this acceptance test must keep that artifact.
  B2: xorcount is a COMPLETE package and real evidence, not a thin one. Six
  distinct bug mechanisms; four verdict kinds actually realized under isolate
  (WA, ML, TL with killed:True at 2100 ms, plus a genuine timing-band flag at
  1688 ms); every declared bound attained; three hand-verifiable samples;
  holes 0, mismatches 0.
Task 7: CRITICAL — reviewing-problems' dispatch says "hand the subagent the
  five judgement classes above", and those classes contain flight's ambiguous
  line AND its resolution. Handed over literally it gives the reviewer the
  answer. The dogfood stripped it manually, which is why B1 worked at all.
  Fix keeps the example (it is the skill's own proof that fresh context is
  needed) and changes the DISPATCH SPEC: relay names and generic definitions,
  never a worked example naming the package under review.
Task 7: HIGH, MISSED BY THE DOGFOOD, found by the reviewer — the reaching-check
  recipe is broken in BOTH preparing-tests and reviewing-problems.
  --testOverviewLogFileName opens "wb" and TRUNCATES every run, so looping over
  a group's tests leaves only the last test's log. Controller proved it on
  xorcount: the log reports a_i min-hit, k min-hit, n max-hit, while the group
  actually attains n 1..200000, k 1..262144, a 0..262143. The documented recipe
  manufactures false test-weakness findings and hides real ones, in the exact
  section the dogfood exercised. Fix: per-test log plus an external union.
Task 7: HIGH — preparing-tests:91-92 compiles "$PROBLEM/validator.cpp" but
  package_status.py:159 requires files/validator.cpp, and both flight and the
  mini fixture put it there. The justification at :95-99 is premised on the
  wrong location and is therefore also wrong.
Task 7: HIGH — solving-problems never mentions @tag/@expect/@algorithm/
  @complexity (grep: zero hits across it and its references/), so a main.cpp
  produced by following it fails package_status's model_solution phase.
Task 7: DROPPED two reported findings as not-defects — the implementer routed
  around things that were documented: hand-authored samples (preparing-tests
  :392-401 prescribes exactly that process) and the parallel-agents mandate
  (validating-solutions:181-187's rationale is one-named-failure-mode, not
  parallelism, and the deviation preserved it).
Task 7: fix round 1 dispatched with WIDENED SCOPE — the brief said
  report-don't-fix, but four are cheap documentation fixes and the final
  whole-branch review is next; fixing here avoids it re-finding them.
Task 7: fix round 1 (4 addressed; commits 9003c89..4846d5a), 203 alone,
  validate --strict passes, 8 skills.
  Controller PROVED the reaching-check fix on xorcount's real g2 tests by
  compiling the validator and running both recipes side by side:
    FIXED (union over 11 per-test logs): a_i min+max, k min+max, n min+max
                                          — all six bound-ends reached
    OLD  (one shared truncating log):     a_i min, k min, n max
                                          — three of six; rest read unreached
  Ground truth n 1..200000, k 1..262144, a 0..262143. The old recipe would
  have produced THREE false test-weakness findings on a package with none.
  Dispatch-payload spoiler fixed with "Operator-facing rationale — not part of
  the dispatch payload" markers plus a general never-relay rule; validator path
  corrected to $PROBLEM/files/ with the wrong justification paragraph rewritten;
  solving-problems now cross-references the metadata header.
Task 7: fix round 1 re-review — all 4 addressed, no new breakage. The
  re-reviewer verified the ensure()-blindness claim against testlib's
  addBoundsHit CALL SITES (not just prose), did a real compile to confirm the
  rewritten include justification, and diffed the two skills' reaching-check
  recipes: byte-for-byte identical, so they cannot drift. The per-test logs now
  live in a scratch dotdir created and removed in the same block — a strict
  improvement on the pre-fix version, which wrote into the package with no
  cleanup at all.
Task 7: minor (deferred): reviewing-problems:230 still calls the readToken
  paragraph "the thing that names the package", but the fix relocated that
  naming into the marked block below it. Wording imprecision only — the
  generic-definitions-only rule excludes it either way.
Task 7: complete (commits e4ac7c6..4846d5a, 1 fix round) — 203/203, 8 skills

## Stage 2 summary for the final review

Branch problem-setting-stage-2, 17 commits off 82fa307 (stage-1 tip).
203 tests, 8 skills, plugin 0.6.0, validate --strict clean.
Triage list: 4 deferred minors, all tagged in this file. Nothing discarded.
Both acceptance tests passed: reviewing-problems independently found the
xâu con assumed definition in flight, and creating-problems drove xorcount
from G1 to a complete package with real TL/ML/WA verdicts under isolate.

## Final fix wave (whole-branch review of Stage 2)

One dispatch, no second wave. Full detail in `final-fix-report.md`; this is the
ledger line. 203 -> 214 tests, 8 skills, `validate --strict` clean.

1. **The "never raises" contract was false — fixed at the loader.** Six
   ordinary `problem.json` typos crashed `package_status.status()` and
   `review_checks.run()`, both of which document that they never raise. New
   `problem_meta._string()` beside `_object`/`_array`/`_integer`, applied to
   `checker.name`, `subtasks[].id`, `constraints[].id`, and each `depends_on`
   entry. The collision case (`"n"` and `"N"` both uppercasing to `N_MIN`)
   cannot be caught in `load()` — it is a property of the C++ identifier
   `render()` derives, not of the document — so `review_checks._stale_header`
   grew an `except ProblemMetaError` and it becomes a `low` finding instead of
   a traceback. This mattered because `creating-problems:207` calls
   `package_status` on every resume: a traceback there is precisely the failure
   the Resumability section argues cannot happen. Six tests, one per row.
2. **shaping-problems:157 — the worked example's algorithm did not terminate.**
   "at most 2^12 prefixes" over an unbounded coin stream. Verified: with
   A=000000, B=111111 (both legal at |A|,|B| <= 6), 3586 of 4096 length-12
   streams complete neither pattern. Row rewritten to describe what the shipped
   g1-passing solution actually does — an absorbing chain over <= 2^5 raw window
   states solved by power iteration, per sol-exhaustive-tinyn.cpp's own
   @algorithm. 2^12 figure dropped.
3. **shaping-problems:251-266 — "Done means" named the wrong package.** It sent
   the agent at `~/Projects/my_cp_problems/flight` and predicted nonzero exit
   with a `next:` line; flight prints `complete` and exits 0. Gate is now about
   the package being shaped; phase enumeration corrected to PHASE_ORDER
   (`constraints_header` sits between `statement` and `model_solution`); the
   "verified against flight" note moved out of the gate.
4. **validating-solutions:322-325 — the one control-flow edge the gate model
   hangs on.** Step 3 said the exit is `writing-statements` (route and continue)
   while `creating-problems` and `reviewing-problems` both draw STOP, matching
   spec §7. Fixed in `validating-solutions`, the outlier; the two correct copies
   untouched.
5. **Two more vacuous guards closed.** `test_constraints_h_without_problem_json`
   claimed problem.json was absent while setUp copied it — now unlinks for real.
   Eight `assertTrue(result)` hostile tests replaced with kind/severity/`what`
   assertions. Proof: gutting five of six check functions to `return []` left
   13/18 green before, 8/20 after (failures 5 -> 12). The 8 survivors are five
   tests targeting the deliberately-un-gutted `_incomplete`, plus three negative
   assertions that no output-deleting mutation can falsify by construction —
   confirmed by gutting all six, which leaves exactly those three.
6. **tools/tests/test_skill_docs.py added** — the first test in this repo that
   guards prose. Extracts fenced bash blocks from both skills and asserts the
   reaching-check recipe is identical, locating blocks by content marker rather
   than line number. Three of its five tests guard the extractor itself, so a
   matcher that silently found nothing cannot make the comparison pass. It
   caught real drift on day one: block 1's comment had already diverged
   ("first number is the shortest A" vs "first line is the shortest value").
7. **Minors swept.** review_checks docstring no longer describes the mtime check
   deleted in 9a2e9ba; the reaching-check loop now checks the validator's exit
   code in both copies (an empty log reads as "unreached" — the exact false
   finding the per-test-log fix removed); rcmp6 corrected from "6 significant
   digits" to 1e-6 absolute-or-relative, verified against rcmp6.cpp:5,8 and
   testlib.h:564-576; reviewing-problems' t_A corrected from "first index at
   which A occurs" to flight.tex:27-31's ending-at definition (start-vs-end is
   what sol-start-index.cpp encodes); the off-alphabet "1a0a1" illustration
   replaced with "101"/"10011"; TestMain's 26-line stdout leak captured and
   turned into two assertions; reviewing-problems:230 repointed at the marked
   Operator-facing blocks (the deferred minor from Task 7 — now closed);
   README gained the not-parallel-safe warning.
8. **Not requested but required:** `FIXTURE` in test_package_status.py and
   test_review_checks.py was repo-root-relative, so the suite died in setUp from
   any other cwd. Both now anchor to `Path(__file__).parent`, matching
   test_run_matrix.py. This is what made the "run from a non-plugin-root
   directory" verification rule satisfiable at all.

Controller rulings honoured: `package_status.py:79-80`'s unreachable except left
in place along with the reachable twin at `review_checks.py:114-116`;
`writing-statements` not restructured; flight's rcmp6 statement mismatch not
chased; the reaching-check duplication kept, with item 6's test as the guard.

### First Stage 3 item: the writing-statements routing gap

`writing-statements` is now the target of **five inbound routes with zero
outbound**. Inbound: the "Am I the right skill?" rows in `shaping-problems:35`,
`preparing-tests:34` and `creating-problems:38`; `preparing-tests:455`'s
hand-back for `\Examples`; and the pipeline's second visit drawn in
`creating-problems:150,174` and spec §7. Outbound: none — `writing-statements`
has no `## Am I the right skill?` section at all, so an agent routed into it has
no documented way back out, and the one edge that should leave it (the
unresolvable-HIGH stop) is owned by `creating-problems` instead.

That asymmetry is why this fix wave had to correct `validating-solutions`
step 3 rather than let it route to `writing-statements` and continue: routing
into a skill with no exits is how a pipeline loses track of where it is. The
missing boundary table was already deferred to Stage 3 by controller ruling;
this makes it the **first** Stage 3 item, not merely one of them.

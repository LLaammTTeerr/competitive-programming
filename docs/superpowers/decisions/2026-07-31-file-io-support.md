# SDD ledger — plan: docs/superpowers/plans/2026-07-31-file-io-support.md

Repo: /home/lamter/.claude/skills/competitive-programming
Branch: problem-setting-stage-3, cut from problem-setting-stage-2 (NOT main —
PRs #3, #4, #5 are all open and stacked). In place, not a worktree.
Base: cee3278 (the Stage 3 scope commit). Plan commit: see git log.

Stage 2 finished at 214 tests, 8 skills, plugin 0.6.0.

## Decisions made by the human, binding

1. **NO_OUTPUT is a new verdict ranked next to FAIL** (index 1 in _SEVERITY),
   NOT reused RE and NOT "empty file, let the checker decide". Rationale they
   accepted: reporting a filename typo as WA is the confident-wrong-verdict
   failure in miniature, which is the one thing this pipeline exists to avoid.
2. **This run covers file IO only.** The writing-statements routing gap stays
   scoped but unimplemented.

## Controller findings before dispatch, verified by running

- `run_matrix.py` has ZERO references to validator/generator (grep -c = 0), and
  the checker at :877 is `subprocess.run([checker, test_in, out, ans])` — three
  file paths. The scope doc's "testlib tools are unaffected" was flagged in PR
  #5 as read-not-run; it is now RUN and CONFIRMED.
- `--chdir={bin_label}` already exists at the isolate cmd, and bin_label is
  mounted WITHOUT :rw. That single line is why a file-IO solution cannot write
  its output today. The fix is to point it at stage_label.
- `classify()` needs NO signature change: checker_verdict flows through its
  passthrough at matrix_core.py:65, and time is decided first at :59-62, so a
  TL run can never be misreported NO_OUTPUT. Adding to _SEVERITY is necessary
  and sufficient. Recorded so no implementer "helpfully" widens the signature.

## Standing rulings inherited from Stages 1-2 (still binding)

- **R1:** externally-authored data must never surface a bare stdlib exception.
- **R2:** where reference code contradicts stated purpose, purpose governs.
- **Evidence standard:** a docstring claim is a testable assertion. This
  project shipped four docstrings asserting what the code did not do.
- **Verification standard:** an error path not triggered is not handled; a
  command not run from a foreign cwd is not runnable.
- **Vacuous guards:** five recorded across Stages 1-2, plus eight assertTrue-only
  tests found by the final review. A test that passes against a gutted
  implementation is not a test. Expect reviewers to mutate.

## Progress

Task 1: implemented (commit ab5ae6f), 214 -> 220 tests.
Task 1: CONTROLLER'S PLAN WAS WRONG, TWICE, and the implementer caught both:
  (a) the brief's dot-segment test case "../escape.out" is caught by the
      SEPARATOR check first, so the dot-segment branch would have shipped
      untested — a vacuous guard authored by the controller. Implementer added
      a bare ".." case. Reviewer confirmed by neutering only that branch:
      exactly test_io_input_rejects_bare_dot_segment goes red, and the brief's
      own case stays green. The branch is reachable, not dead code.
  (b) _string's real signature is _string(value, path, what) positional, not
      the keyword form the brief invented. Implementer adapted; reviewer
      confirmed the message style matches the house convention.
Task 1: review — spec OK, quality approved. Full gut of _io_name turns 5/6 red
  (only the accept-test survives, correctly). Suite run alone: 220 OK.
Task 1: minor (deferred): two rejection tests use bare assertRaises with no
  message assertion, inherited verbatim from the brief's pseudocode; the other
  three assert the field name but not the reason. Branch mutation covers this
  in practice. Flagged for the final review to triage.
Task 1: complete (commit d4f2031..ab5ae6f, 0 fix rounds) — 220/220
Task 2: implemented (commit 63b77c0), 220 -> 224 tests.
Task 2: review — spec OK, quality approved, ZERO findings. Reviewer ran three
  mutations: NO_OUTPUT moved to end -> 2 red; moved to index 0 ahead of FAIL ->
  test_no_output_ranks_just_below_fail red on group_verdict(["FAIL","NO_OUTPUT"])
  == "FAIL", which is exactly the masking claim the comment makes, so the
  comment is a live assertion and not decoration; removed entirely -> 2 red.
  classify() signature byte-identical (verified by diff, not by reading the
  report). Relative order of the pre-existing seven verdicts unchanged.
Task 2: complete (commit ab5ae6f..63b77c0, 0 fix rounds) — 224/224
Task 3: implemented (commit 8858037), 224 -> 231 tests. DONE_WITH_CONCERNS.
Task 3: CONTROLLER'S PLAN WRONG A THIRD TIME — the brief's memory test (4.4 MB
  against a 64 MB limit) was VACUOUS: reviewer ran it and it returns oom=False
  on tmpfs AND on ext4, so it could never have caught the historical bug it was
  written to guard. Implementer strengthened it to 48 MB/32 MB unprompted;
  reviewer confirmed that version gives oom=True on tmpfs, oom=False on ext4.
  Three plan defects now, all caught by implementers, all the same shape: a
  test whose numbers look right but whose mechanism cannot fire.
Task 3: all four review mutations go red (--chdir->bin_label: 3 tests; delete
  staged_result.unlink: 1; force no_output=False: 2; force file_io=False: all 5).
  No vacuous guard among the seven new tests.
Task 3: implementer concerns 1/2/3 adjudicated IN ITS FAVOUR, no action:
  1. deviating from the brief's `replace(result, no_output=True)` is correct —
     no `result` exists there, and an early return leaves a stale stdout_dest
     that would feed a PREVIOUS solution's answer to the checker.
  2. the unbriefed run.out collision guard is real: reviewer stripped it and got
     dest = b'REAL-ANSWER\n\x00\x00\x00\x00\x00\x00STDOUT-AFTER\n' — isolate's
     stdout fd and the solution writing at independent offsets. Silent corruption.
  3. see the vacuous-test entry above.
Task 3: concern 4 (=_time_median does not forward/sticky-OR no_output) confirmed
  genuinely unreachable today. TASK 4 MUST: (a) thread io_input/io_output through
  _time_median, (b) add `no_output = no_output or r.no_output` to the sticky-OR
  block, (c) pass it to the rebuilt RunResult at ~line 953 — omitting (c) drops
  it silently even if (b) is done. Carry this into the Task 4 dispatch.
Task 3: 3 findings -> fix round 1 (2 Important + 1 promoted from Minor):
  1. shutil.copyfile discards _ensure_sandbox_readable's heal; every file-IO run
     fails at umask 077 and blames isolate. One-line fix.
  2. PermissionError escapes _run_once uncaught on a umask(077) solution — bare
     stdlib exception on solution-controlled state, R1 violation, aborts a whole
     matrix mid-run.
  3. PROMOTED from the reviewer's Minor: io.input == io.output is unguarded, and
     reviewer ran it — a solution writing nothing gets the TEST INPUT handed back
     as its answer and fed to the checker. Silent confident-wrong-verdict, the
     one failure class this pipeline exists to prevent. Promoted because severity
     follows consequence, not blast radius.
Task 3: fix round 1/5 (3 addressed; commits 8858037..8d6ad3b), 231 -> 235 tests.
  Re-reviewer reproduced ALL THREE failures against the PRE-fix commit and then
  confirmed each gone post-fix — both halves, which is the standard this project
  kept failing. Pre-fix transcripts matched the original reviewer's verbatim.
  Finding 2's forbidden collapse held: the MatrixError fires before no_output
  could be set, and its message states "not the same as producing no output".
  Finding 3's test asserts the specific damage (dest.exists() == False), not
  merely that something raised.
  Mutation table, 4/4 red: delete _ensure_sandbox_readable(staged_in) -> the
  strict-umask test; swallow OSError and force no_output=True -> the bare-OSError
  test; delete the problem_meta cross-field guard -> the load-time test; delete
  the _run_once collision guard -> the direct-call test.
  Placement ruling accepted: primary guard in problem_meta.load() (a cross-field
  property _io_name structurally cannot see, and load time precedes compilation
  so the setter is pointed at the wrong file), second guard retained in
  _run_once (called directly by tests, and the failure there is silent).
Task 3: complete (commits 63b77c0..8d6ad3b, 1 fix round) — 235/235
Task 3: NOTE FOR TASK 4, re-confirmed unreachable at 8d6ad3b — _time_median's
  signature has no io params and its _run_once call at :1000 passes positionals
  only, so every call is stdin-mode. Task 4 must do all three of (a) thread
  io_input/io_output through _time_median, (b) no_output = no_output or
  r.no_output in the sticky-OR block, (c) pass it to the rebuilt RunResult at
  ~:953. Omitting (c) drops it silently even if (b) is done.
Task 4: implemented (commit f172cfa), 235 -> 240 tests (+6 new, -1 that asserted
  the now-deleted refusal). DONE_WITH_CONCERNS.
Task 4: HUMAN DECISION (asked, consented) — the implementer added a refusal not
  in the plan: under file IO, pass 1 raises if the MODEL solution exits 0 without
  creating io.output. Argument accepted: deleting the file-IO refusal makes an
  empty .a answer key reachable for the first time, and every later verdict would
  be measured against it — one silent cause producing a whole matrix of confident
  wrong verdicts. LamTer chose KEEP over revert and over flag-and-continue.
  Ruling recorded because it is a behaviour change beyond the approved plan.
Task 4: BRIEF WRONG TWICE MORE (5 controller plan defects now):
  (a) result["rows"] does not exist — the real key is payload["results"];
  (b) _classify cannot `return "NO_OUTPUT"` as the brief said — it returns an
      Outcome, and early-returning would bypass classify()'s time-before-
      correctness rule that Task 2's committed tests pin. Implemented as
      verdict_src = "NO_OUTPUT" instead, preserving the rule.
  The plan remains the weakest artifact in this run; implementers have caught
  every defect in it so far.
Task 4: carried to Task 6 — skills/validating-solutions/SKILL.md:285 still says
  "the file-IO guard", now false. Task 6 owns that file, so deferred not lost.
SCOPE CHANGE (human, mid-run): the writing-statements routing table — Stage 3
  scope item 2, which LamTer had earlier excluded when choosing "file IO only" —
  is now BACK IN, to ship in the SAME branch/PR as the file-IO work. Becomes
  Task 7, after Task 6. Recorded because it reverses an earlier explicit ruling.
  Content per docs/superpowers/specs/2026-07-31-stage-3-scope.md item 2: it is
  the target of five inbound routes with zero outbound and has no boundary table
  at all — only one prose handoff at skills/writing-statements/SKILL.md:174.
Task 4: review — spec OK, quality approved, NO Critical. All six mutations red,
  including (c) alone: test_time_median_carries_no_output_from_any_run_not_just_
  the_last genuinely exercises the median path (runs=3, a marker file makes only
  run 1 silent, and it asserts dest=="later" so runs 2-3 really wrote). The
  three-part trap is defused. Reviewer also built an end-to-end package with a
  solution that segfaults BEFORE fopen: verdicts {boom: RE, main: OK, wrong: WA},
  holes [], mismatches [] — ordering holds, the checker never sees a missing file.
Task 4: IMPORTANT, adjudicated by the controller as a carry-forward rather than a
  fix round — the implementer's item 4 UNDERCOUNTED. Three stale skill-doc claims
  exist, not one, and TASK 6 STEP 4 MUST FIX ALL THREE:
    - skills/validating-solutions/SKILL.md:101 "File IO is rejected loudly by
      run_matrix"
    - skills/validating-solutions/SKILL.md:285 "the file-IO guard"
    - skills/preparing-tests/SKILL.md:115-119 "Only stdin/stdout problems are
      supported... rejected loudly by run_matrix.py"
  No test pins those strings, so nothing goes red meanwhile — which is exactly
  why they need to be on Task 6's list explicitly. Task 6 owns all three files,
  so no code change is needed at f172cfa and no fix round is opened.
Task 4: minor (deferred): the pass-1 model guard is "revertible alone" in 3
  hunks, not 1 — reverting leaves main()'s exit-code docstring and _stage_base's
  rationale naming a guard that no longer exists.
Task 4: minor (deferred): the retargeted test_matrix_error_exits_2_so_it_is_not_
  read_as_a_hole asserts only code == 2 with no message assertion, and the
  refusal it now rides on has its own dedicated test — any other MatrixError
  would satisfy it. Non-vacuous (goes red under mutation f) but loosely pinned.
Task 4: complete (commits 8d6ad3b..f172cfa, 0 fix rounds) — 240/240
Task 5: implemented (commit c222924), 240 -> 245 tests. Test-only, 74 lines,
  ZERO production changes.
Task 5: CONTROLLER'S PLAN WRONG A SIXTH TIME, and this is the worst one — the
  brief specified BUILDING an io drift check that ALREADY EXISTED. Controller
  verified independently: at the plan's base commit d4f2031, drift_check.py:153-154
  and :178-186 already compare the statement's input/output keys against
  problem.json, and they have since drift_check.py's ORIGINAL commit 2e69fd4.
  The implementer found this, reframed the task to the real gap (test coverage),
  and changed no production code. Reframing endorsed by controller and reviewer.
Task 5: review — spec OK, quality CHANGES NEEDED, 1 Critical. The implementer's
  own mutation (disable both comparisons -> 3 red) reproduced exactly. But the
  two NEW false-positive-regression tests are VACUOUS:
    - test_commented_out_input_key_is_ignored survives _strip_comments being made
      a no-op, because the commented line's key becomes the literal "% input"
      after .strip() (which does not strip %), landing in a different dict key.
    - test_input_word_inside_another_keys_value_is_ignored survives both
      brace-depth loops being disabled, because its braced value contains no ,
      and no ] — only an =, which pair.split("=",1) handles regardless.
  Control proving the mutations were real: the PRE-EXISTING
  test_origin_key_with_bracketed_value went red under the same brace mutation.
  6th and 7th instance of the vacuous-guard pattern. Critical despite no
  production defect, because it is the failure mode this codebase keeps
  repeating and the report explicitly declined to run these two mutations.
Task 5: minor (folded into the fix): report attributes the tests' motivation to
  "the brief's explicit warning"; the brief contains no such warning.
Task 5: fix round 1/5 dispatched — rebuild both tests so each depends on the
  mechanism it names (comment fixture where stripping % changes the outcome;
  braced value containing a , or a ]), with both mutation transcripts pasted.
Task 5: fix round 1/5 (1 Critical + 1 minor addressed; commits c222924..f97c9d7),
  245 tests both before and after (test rewrites, not additions).
  Re-reviewer verified BOTH halves per test: mutation A (_strip_comments -> no-op)
  turns the comment test red plus the pre-existing subtask test, and leaves the
  brace test alone; mutation B (both depth+-=1 lines removed) turns the brace test
  red AND moves the control test_origin_key_with_bracketed_value, and leaves the
  comment test alone. Each mutation flips exactly its own test — so the two are
  now independently mechanism-dependent, not coincidentally red.
  Over-correction checked and clear: both assert check(PROBLEM, tex) == [] against
  a MATCHING problem object, so the empty-list assertion is meaningful; neither
  reports drift on a valid statement.
Task 5: complete (commits f172cfa..f97c9d7, 1 fix round) — 245/245
Task 5: LESSON, worth carrying — the implementer's own articulation of why it
  skipped these two mutations, and the crispest statement of this project's
  recurring failure: "exercises existing code" is NOT the same as "the test's
  assertion actually depends on that code's correctness." Seven vacuous guards
  on record now; every one fits that sentence.
Task 6: implemented (commit c4a7477), 245 -> 252 tests. Dogfood package
  `pairsum` (pairsum.inp/pairsum.out) built at a temp path, driven end to end.
Task 6: THE DOGFOOD FOUND A REAL DRIVER DEFECT that five review passes missed —
  _run_once unlinked only the three staging names it knows, so a solution writing
  ANY OTHER filename left it behind owned by that box's subuid; the next run
  (fresh box, different subuid) could not reopen it and returned RE instead of
  NO_OUTPUT. Order-dependent, 1 in 12 tests, and it CROSSES SOLUTIONS.
  Fixed with _clear_stage_dir() before every run, plus two regression tests.
  Reviewer reproduced the defect against pre-fix code (run 2 -> crashed=True
  exit_code=4 status=RE) and confirmed the fix.
Task 6: IMPORTANT — the reviewer established the consequence is WORSE than the
  implementer's report said, and this is the headline of the whole task.
  It built a package whose "wrong-answer" solution is actually correct (a genuine
  hole) and also writes a debug file. PRE-FIX: holes [], mismatches [WA->RE].
  POST-FIX: holes [WA->OK]. So litter could HIDE A HOLE — falsifying the exact
  claim the invocation matrix exists to make, and the one non-circular claim in
  the whole pipeline. The report named the cross-solution risk but never named
  this consequence. Recorded here because the report is gitignored.
Task 6: 7TH CONTROLLER PLAN DEFECT, adjudicated in the implementer's favour —
  the brief demanded holes:[], mismatches:[] AND a NO_OUTPUT row in the SAME run.
  Impossible by design: NO_OUTPUT is undeclarable (absent from VERDICTS), ranks
  second in _SEVERITY, and compare() files a hole only when got == "OK", so a
  NO_OUTPUT group verdict can never match a declaration and can never be a hole
  — it is ALWAYS a mismatch. Reporting two runs was correct.
  RULING: a clean shipped package must never contain a NO_OUTPUT row. It means
  the harness could not evaluate the run — a package defect, not a solution
  class — and exit 1 rightly refuses to call it clean.
Task 6: Task 4's trap-defusing test was rewritten (it had DEPENDED on the leak
  and documented it as a contract). Reviewer re-ran all three mutations
  individually with caches cleared: (c) alone -> FAILED. Trap stays defused.
Task 6: documentation verified complete by the reviewer's OWN two-pass grep of
  every *.md — no stale file-IO claim remains in shipped prose; the only hits are
  historical records under docs/superpowers/, correctly untouched. The README's
  "file-IO is rejected" line NEVER EXISTED (git log -S across all branches).
Task 6: minors (deferred): (1) _clear_stage_dir's MatrixError branch is reachable
  — a solution that mkdirs a non-empty subdir aborts the matrix and leaves a
  stage dir needing root to remove, so "no staging directories left behind" is
  not universal; loud-not-wrong. (2) README stray blank line at :79.
  (3) test_every_document_states_what_file_io_does_not_change dumps ~10 KB into
  its failure message. (4) RETIRED_CLAIMS includes the generic substring
  "rejected loudly by".
Task 6: complete (commits f97c9d7..c4a7477, 0 fix rounds) — 252/252
Task 7: implemented (commit b859585), 252 -> 260 tests. Prose-only in
  skills/writing-statements/SKILL.md plus a new pinning test.
Task 7: CORRECTED THE CONTROLLER AGAIN — real inbound-route count is SIX, not
  the five carried from the Stage 2 review into the Stage 3 scope doc:
  3 boundary-table rows (shaping-problems:35, preparing-tests:34,
  creating-problems:38) + 3 in-run handoffs (preparing-tests:487,
  creating-problems:150, creating-problems:174), across 4 source skills, plus a
  soft successor claim at shaping-problems:278. The spec likely collapsed
  creating-problems' two diagram arrows into one.
Task 7: also corrected the dispatch — reviewing-problems:297 is NOT a route. It
  is prose inside a flags.append example explaining why the reviewer did NOT
  hand off, and validating-solutions' only mention is an explicit ANTI-route.
  So the STOP-vs-continue edge Stage 2 fixed is not re-opened by this table.
Task 7: open observations from the implementer, not fixed here —
  (a) creating-problems' diagram omits constraints_header (a generated artifact,
      not a dispatched phase); the new prose explains the divergence from
      PHASE_ORDER, the diagram still does not.
  (b) running-contests is now the plugin's ONLY skill nothing routes to — the
      exact mirror of the gap this task closed, carried from Stage 2 unaddressed.
Task 7: process note — a `git checkout` reverting mutation M2 discarded
  uncommitted edits; re-applied and mutations re-run from cp backups. Same
  hazard the Task 4 reviewer warned about (mutation sweeps and live edits on one
  file). No loss, but worth naming twice.
CONTROLLER DEVIATION, flagged: Task 7 got NO separate task review. Folded into
  the final whole-branch review instead, on the grounds that it is prose-only and
  the final pass covers the same diff. Deviation from subagent-driven-development's
  per-task gate, recorded so it is not silent.
FINAL whole-branch review (opus, problem-setting-stage-2..b859585): NO Critical,
  2 Important, 3 Minor. It confirmed the branch's central claim BY FALSIFICATION —
  built a package where staging litter hid a genuine hole pre-fix and showed the
  shipped code reports it — and MEASURED backward compatibility at 207/207
  identical verdicts vs stage-2 on a real stdin/stdout package (flight, copied,
  original never touched). 25 mutations found NO vacuous guard: the first time
  this project's recorded weak spot has come up clean.
FINAL fix wave (commit ae7ef47), 260 -> 270 tests. Six findings, all fixed:
  I-1 MERGE BLOCKER, and it was the branch's OWN new surface: source.read_bytes()
    followed whatever the SOLUTION left at io.output. Demonstrated: a symlink to
    /etc/hostname was read as the driver's own uid OUTSIDE the sandbox and handed
    to the checker as the answer — in pass 1 that lands in the jury's .a key; and
    a FIFO blocked _run_once forever, hanging the matrix and leaking the box.
    Fixed with os.lstat (NOT stat) + S_ISREG refusal. The three-way distinction
    survives: absent -> no_output, irregular -> refuse, unreadable -> MatrixError.
  I-2 _clear_stage_dir's two error branches had ZERO coverage — the newest
    function on the branch and the one the holes claim rests on. 8th instance of
    the recorded pattern. Test-only fix + close_isolate_box now warns on stderr
    instead of silently leaving subuid-owned dirs.
  M-1 reciprocal writing-statements row in reviewing-problems.
  M-2 stdin mount skipped in file-IO mode — closed a PRE-EXISTING exposure
    (a solution could open /host1/01.a and read the jury's answers) for free.
  M-3 mixed IO now refused at load. Implementer chose problem_meta over a message
    tweak; re-reviewer endorsed (the shape was already unrunnable, so no working
    package regresses) but noted load() is called by six tools, so a
    half-converted problem.json now hard-fails four of them; package_status
    degrades gracefully by design.
  Sweep: README blank line, RETIRED_CLAIMS generic substring, 10 KB failure dump
    (measured 12,627 -> 1,408 chars).
FINAL re-review: MERGE. Every fix backed by a test that dies when the fix is
  reverted; mutation table 9/9 red including os.lstat -> os.stat caught by name.
  One nit accepted: os.lstat can raise OSError subclasses other than
  FileNotFoundError which now escape bare; judged unreachable (staging dir is
  ours, a solution cannot chmod it; problem_meta refuses path separators so
  ENOTDIR is out; symlink loops are not followed by lstat).
OUTSTANDING, needs the human: .test-scratch/.run_matrix_stage_vh3s4g5l/ is
  subuid-owned litter from a reviewer probe and needs
  `sudo rm -rf` — gitignored, so `git status` is clean and it blocks nothing.

# SDD ledger — plan: docs/superpowers/plans/2026-07-29-parallel-contest-solving.md

Branch: parallel-contest-solving
Base at start: 5efb5f8 (plan committed)

Pre-flight scan: one issue found and resolved by the controller, not escalated —
Task 1 inserts ~10 lines near SKILL.md:43, so every `SKILL.md:N-M` line number
written in the plan for Tasks 6 and 7 is stale by the time those tasks run.
Resolution: implementers locate sections by heading text, never by the plan's
line numbers. Carried into every dispatch. Task 7 Step 3 re-verifies all
citations mechanically, which is the plan's own net for this.

No plan-vs-rubric conflicts found. Quoting spec wording verbatim into the skill
file is the deliverable, not duplication.

Task 1: complete (commits 5efb5f8..348fc84, review clean)
Task 2: complete (commits 348fc84..af1d5d9, review clean)
Controller ruling (applies to Tasks 3-7): parallel-mode.md uses anchor links
(../SKILL.md#heading) not line-number citations. Where the plan's verbatim
blockquotes contain `SKILL.md:N-M`, implementers convert that citation to the
equivalent anchor link and keep all other wording verbatim. Rationale: the file's
established convention, and anchor links cannot drift as line numbers shift.
This makes plan Task 7 Step 3 (citation-drift check) largely a no-op.
Task 3: complete (commits af1d5d9..eb24d50, review clean)
Task 3: minor (deferred): Allocation section says "a problem" where Task 2 defined "problem unit" (merged version pairs). No contradiction, but a skimming reader could misread. Final review to triage.
Task 3: minor (deferred): task-3-report falsely claims an anchor precedent existed in the Roles section. Report-accuracy only; the shipped anchor is correct and verified.
Task 4: review found 2 Important, 2 Minor. Fix round 1/5 dispatched (resumed implementer adf9558a284ab8d8a).
  Important 1: term `dossier checkpoint` promised by brief Interfaces but absent from file; Task 5 consumes it. Traced to brief, not implementer.
  Important 2: orchestrator dossier-read access unstated. Implementer dropped spec's observability line, conflating two senses of "live". Leaves Allocation stage-2 priority and Progress reporting with no stated information source.
Task 4: minor (deferred): solution.cpp lacks a writer marker in the layout block while the other two files have one.
Task 4: minor (deferred): layout block hardcodes joiner-1-findings.md; Allocation allows multiple joiners, so a literal reader may infer a one-joiner cap.
Task 4: fix round 1/5 (2 addressed, 0 open; commits cb9b13e..ed64a7d)
Task 4: complete (commits eb24d50..ed64a7d, review clean)
Task 5: complete (commits ed64a7d..eccd489, review clean)
Task 6: complete (commits eccd489..f2ec169, review clean)
Task 6: minor (routed to Task 7): parallel status-line header drops the word "mode" and the ordering-signal field vs the two serial examples. Brief-specified, not implementer error. Task 7 owns consistency reconciliation.
Controller decision: Task 7 is scoped to plan Steps 1-7 ONLY. Step 8 (live end-to-end
contest run) makes real submissions to the user's Codeforces account — outward-facing
and not reversible. The user approved implementation and testing but never specifically
approved submitting under their account. Surface it as a decision instead of doing it.
Task 7: complete (commits f2ec169..e08ccda). Plan Steps 1-7 done; Step 8 NOT run (controller decision).
Task 7: fixed 2 latent ambiguities found via walkthroughs (clearance veto scope; solution.cpp writer marker) + Task 6 status-header minor.
Task 7: triaged deferred minors - Task 3 "a problem" vs "problem unit": no change recommended; Task 4 joiner-1-findings hardcode: cosmetic, left; Task 3 report-accuracy: no action.
Task 7: open gap (not fixed) - Allocation never states that a fleet shrinking for want of a distinct job is not "stopping early"; the Finish-the-set guardrail could push an orchestrator to manufacture jobs.
Task 7: open gap (not fixed) - IOI "stated assumption" has no stated home; evidence-packet "known gaps" is the implicit answer.
Task 7: DESIGN VERIFIED ON PAPER ONLY. No dossier ever created, no clearance ever granted, one-submitter invariant never exercised against a real judge.
Task 7: review found 1 Important (gap 4), 1 Minor (gap 5); gaps 1-3 fixes upheld as in-scope.
  Gap 1 (fixed): clearance veto said "sits in the dossier" but dossier.md is the main agent's file; a joiner's counterexample would not have vetoed, inverting the adversary role. Now names the whole directory.
  Gap 2 (fixed): solution.cpp had no declared writer, a hole in the single-writer invariant.
  Gap 3 (fixed): parallel-IOI ambiguity silently overrode SKILL.md's don't-silently-guess trigger. Reviewer ruled this REQUIRED by brief Step 5, not creep.
Task 7: fix round 1/5 dispatched (resumed a53e0aca015005419) — gap 4: fleet shrinking for want of a distinct job must not read as "stopping early" against the Finish the set guardrail.
Task 7: minor (deferred): gap 5 — the IOI "stated assumption" has no explicit home; evidence packet "known gaps" is the implicit answer. Risk is the assumption never reaching the orchestrator, the only party that can relay it to the user.
Task 7: fix round 1/5 (gap 4 Important addressed, 0 open; commit e08ccda..6ad32f4). Placed in parallel-mode.md ## Allocation, not the SKILL.md guardrail site; SKILL.md untouched this round.
Task 7: fix round 1/5 (1 addressed, 0 open; commits e08ccda..6ad32f4)
Task 7: complete (commits f2ec169..6ad32f4, review clean)
All 7 tasks complete. Dispatching final whole-branch review.
FINAL REVIEW: NOT ready to merge. 1 Critical, 5 Important, 7 Minor. Serial regression CLEAN. 47/47 anchors resolve. All mechanical constraints hold.
  C1: promotion reassigns the main role with no mechanism to stop the outgoing main; both can submit. dossier.md's "current main agent" field is unwritable by the orchestrator (single-writer), so the seam is mutually blocking.
  I1: dossier root is a bare relative path; agents in separate contexts can diverge and the coordination layer fails silently OPEN.
  I2: joiner-1-findings.md hardcoded, no naming rule; two concurrent joiners collide, clobbering a counterexample. (Upgrades deferred minor #4.)
  I3: SKILL.md (always loaded) implies every agent submits; the one-submitter rule lives only in the reference, which the pointer does not mandate reading.
  I4: allocation stage 1 has no entry for starting an unstarted unit; units beyond the ceiling may never begin.
  I5: veto has no mandated enforcement point, and "unrefuted" is unrecordable (joiner owns the file, main agent cannot write it).
  Pattern: strong where one task owned a rule, weak at every two-task seam. Fix with ONE agent holding both files.
Dispatching single fix wave (opus) for C1 + I1-I5 + cheap M2/M3 + gap-5 tweak.
Final fix wave: commit a2326b9. Scoped re-review: all 6 findings ADDRESSED, no serial drift, 69/69 anchors, growth 275->435 judged warranted.
  C1 verdict: window closed structurally against a running agent (orchestrator controls resumption, not interrupts). Residual is orchestrator non-compliance, not agent non-compliance. Liveness soft spot: no guaranteed turn boundary for a debugging incumbent, so the wait is unbounded — costs liveness, not safety.
Residual after re-review: 1 Important + 3 Minor.
  Important: `adversary` is the only job name without an index; two concurrent adversaries (one per solution, permitted by the distinct-job rule) both write adversary-findings.md. Reopens I2's silent counterexample loss.
  Minor 1: stage 0 doesn't say a PARKED main still holds the role; could staff a second main.
  Minor 2: ## Limits contradicts itself (denies capping at unit count, then defaults to min(#units,5)); means UNSOLVED units.
  Minor 3: clearance bullets 2 and 3 overlap with no stated precedence.
Controller ruling: dispatching one more SMALL fix pass beyond the nominal single wave. Deviation is deliberate and reported to the user. Rationale: the Important is a one-word rename closing a silent-data-loss path, the Minors are one clause each, and a live contest run was about to exercise this text. Controller verifies mechanically afterward; no controller-authored edits.
Residual fix: commit 0377663 (+3 lines net). adversary -> adversary-N chosen over one-per-unit, since one-per-unit would have silently narrowed Allocation's per-solution rule. 3 minors closed.
Controller verified mechanically: no unindexed adversary token, no adversary-findings.md, both constraint greps empty, only the 2 shipped files differ from main, solving-problems + mcp-server zero diff.
BRANCH COMPLETE. Proceeding to the user-approved live end-to-end run on a finished contest.

LIVE RUN — Codeforces 1971 (Round 944 Div 4), FINISHED, ICPC mode, parallel, scope A-D.
Result: 4/4 Accepted, 4 submissions, 0 rejected attempts, 0 penalty.
  A 384776535 AC 31ms (1 attempt) | B 384776661 AC 31ms (1) | C 384776752 AC 31ms (1) | D 384777507 AC 15ms (1)
Mechanisms exercised and confirmed working:
  - Capability binding (all 4 bound to real cf_ tools, stated before any submission)
  - Ranking by rating from list-problems; no scout wave needed
  - Absolute dossier root (I1 fix) — 4 dossier dirs, no path divergence
  - Clearance gate: 4 granted, each preceded by the mandatory directory read (I5 fix)
  - One-submitter invariant: held. 4 submissions, 4 distinct problems, never 2 agents submitting one problem.
  - Joiner role: adversary-1 on D never submitted, wrote only adversary-1-findings.md (indexed name = residual fix)
  - Single-writer: verified by mtime. Adversary touched no file it did not own.
  - Veto path: clearance on D HELD while adversary live; released on SOUND verdict.
  - Fleet shrink: A/B/C freed slots; no distinct job available within scope -> fleet shrank rather than manufacturing work (gap-4 rule).
NOT exercised: allocation stage 0 (every unit staffed from wave 1 because scope A-D <= ceiling 5); a live counterexample actually blocking clearance; version-pair merge (none in this contest); IOI mode entirely; degraded mode.
Design friction observed live: adversary read dossier.md describing the OLD approach while main agent replaced it mid-flight. Checkpoint-based-not-live is real. Agent handled it by scoping its verdict to current code rather than reporting a stale counterexample.
Notable: D's initial formula (1+count("10")) PASSED ALL 6 OFFICIAL SAMPLES and was wrong; stress testing caught it on 0110110. The verification bar directly prevented a WA + penalty.

RUN 2 — Codeforces 2245 (Div1+Div2), FINISHED, ICPC, parallel, full contest A-H.
Atomic-write rule added first: commit 65845b9.
Accepted so far: A 384779200, B 384779365, E 384780220 — all 1st attempt, 0 rejected.
NEW COVERAGE CONFIRMED:
  - Stage 0 fired: ceiling set below unit count, E started unstaffed, A's freed slot started E -> E converted to a 2500-pt solve. Pre-review text could never have staffed it.
  - Version-pair merge: D agent compared D1/D2 section by section, confirmed word-for-word identical except bounds, requested dual-index clearance from one source.
  - Atomic writes: PROVEN IN THE WILD. D's adversary died mid-write (API error). Left NO findings file and NO orphaned .tmp; main agent's files untouched. In-place writing could have left a torn file read as complete -> silent fail-open.
  - Single-writer under crash: adversary worked in its own scratch dir, snapshotted the solution binary rather than recompiling over it.
NEW DESIGN DEFECTS FOUND BY THIS RUN (none caught by the review chain):
  1. Distinct-job eligibility has no notion of SOLUTION STABILITY. An adversary can be spawned onto a mid-iteration solution and record a counterexample against a version that no longer exists, which then blocks clearance under the veto.
  2. Adversaries are PRICED WRONG. Stage 1 treats an adversary slot as cheap absorbable capacity, but an independent adversary (the only kind worth having) costs ~1 full solve, and on a hard problem finishes AFTER the main agent.
  3. Stage 2 priority ("likeliest to convert into a solve") does not apply to adversary allocation at all - an adversary never converts anything into a solve.
  4. No rule for a PENDING adversary. The veto is absolute for a RECORDED counterexample; the text is silent on holding clearance for an adversary that has not reported. "Hold until it reports" was controller judgment, not in the skill.
  5. A DEAD joiner is indistinguishable on disk from a joiner never assigned. Assignment is not recorded durably, so the fact that a check was outstanding lived only in orchestrator context. After compaction the orchestrator would read a clean directory and clear, never knowing.
Controller ruling: D cleared on its OWN evidence, not the adversary's. Dead agent's "All checks pass" treated as a hint, not an evidence packet; its verdict recorded as UNKNOWN.
USER CORRECTION (acted on, commit cad39a2 to solving-problems): stress tests use SMALL cases only.
  Rationale recorded in the skill: brute force is exponential, so larger N buys exponentially fewer
  iterations and unreadable failures. Bugs large N would expose (overflow/TLE/recursion) cannot be
  caught by an oracle diff anyway - the oracle is too slow to run there. Cover those with a timing
  run + validity checker instead.
  EMPIRICALLY VINDICATED MINUTES LATER: C's main agent stalled 600s and was killed by the watchdog.
  Forensics: stress_input.txt = 1,881,681 bytes (large-n case), stress_output.txt = 0 bytes, no
  dossier.md, no orphaned .tmp. It generated a 1.9MB stress case, ran it against a brute force,
  emitted nothing, hung. Exactly the practice the user flagged.
  Controller self-correction: I had praised E's exhaustive sweep to n=17 as the run's strongest
  evidence. Wrong weighting - most of that sweep was waste; the valuable parts were oracle
  INDEPENDENCE (literal game rules, not the characterization) and the OEIS completeness check.
  D was the model and I failed to single it out: oracle diffs at n<=3/n<=4, large runs covered by a
  VALIDITY CHECKER instead of an oracle.
DESIGN DEFECT #6 (found by C's death): the checkpoint discipline specifies four points to READ the
  dossier and never says when to WRITE it. Agents therefore write it last - precisely when it is
  useless for crash recovery. C died with a working solution.cpp and zero record of what it was.
  Fix candidate: mandate writing the dossier as soon as a candidate list exists, before solution code.
C respawned (a6c843883c10ce427) with corrected stress guidance + write-dossier-early.
RUN 2 RESULTS: 8/9 solved (H outstanding). 11 submissions, 11 accepted, 0 rejected, all 1st attempt.
  A 384779200 | B 384779365 | C 384782574 | D2 384780892 | D1 384780942 | E 384780220 | F 384782055 | G 384782640
INTERACTIVE COVERAGE CLOSED (G, 3500pts, Accepted 1st attempt): agent built a real mock interactor
  (holds hidden tree, answers by statement rule, counts queries vs 30n, diffs final edges), drove it
  over a pipe, measured worst budget use 21991/30000 = 73.3% across 11 adversarial shape families,
  and EXPLICITLY did not diff the sample - naming it as a transcript. Flush discipline correct.
  No ILE on the real judge.
C RESPAWN = clean A/B on the stress-testing correction. Same problem, same model, only guidance
  changed: predecessor watchdog-killed at 600s on a 1.9MB oracle diff; replacement Accepted 1st
  attempt in 347s using exhaustive n<=8 + a separate timing run at n=2e5.
DESIGN DEFECT #7: nothing cleans up or marks a dead agent's leavings. C's respawn inherited
  brute.py/construct.py/stress_input.txt from the killed predecessor with no marker distinguishing
  unverified dead-agent scratch from live work. Controller had to say "treat as untrusted" by hand.
  Same family as #5.
STILL UNTESTED after two full contests: IOI mode entirely (both contests ICPC/points-scored);
  every failure path - debug loop, ~3-attempt stuck trigger, parking, debrief-to-user, main-role
  transfer (the C1 fix), and a counterexample actually BLOCKING a clear. Nothing has failed yet,
  so the design's most intricate machinery has never run.
RUN 2 CLOSED: H stopped by the user at ~50min (still in design phase, empty directory).
  This is a legitimate termination per the skill - "the run ends when every problem is Accepted, or
  when the user stops it" - NOT a controller retirement. Exercises the user-stop branch, previously
  untested.
FINAL: 2245 = 8/9 solved. Combined across both contests = 12 problems, 13 submissions, 13 accepted,
  0 rejected, all first attempt. Range: 800-rated Div4 A through 3500-pt Div1 interactive.
DEFECT #8 FIXED: commit c1761ec - dossier must exist before design work. Skeleton written immediately
  after reading the statement, then kept current. Also makes an empty directory diagnostic (one state
  instead of four). VERIFIED WORKING on H respawn: 1403-byte dossier on disk immediately, carrying
  restatement, limits, and 4 structural observations - vs the first attempt's 50 minutes and nothing.
DESIGN DEFECT #9 (found by user suggestion, not by review): allocation stage 1 makes joiners PARASITIC
  on the main agent's candidate list. A joiner needs an unclaimed candidate to pull or a solution to
  attack, so before the main agent has produced candidates NO distinct job exists and no joiner can be
  assigned. That means parallel exploration is impossible exactly when it is most valuable - at the
  start of a hard problem, before anyone has committed to an approach. The brainstorm had "convert
  breadth into depth" as a concept; the shipped eligibility rule cannot express it.
  Controller deviation (deliberate, user-requested): spawned candidate-1 (path-shape decomposition)
  and candidate-2 (bitset reachability, exploiting n<=100) on H with distinct assigned ANGLES rather
  than claimed candidates, since no candidate list exists. Fix candidate: allow an "unexplored angle"
  as a distinct job when the unit has no claimed approach yet.

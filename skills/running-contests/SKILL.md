---
name: running-contests
description: >
  Orchestrate solving an entire competitive programming contest end to end on
  any judge — Codeforces, AtCoder, CodeChef, Kattis, DMOJ, oj.uz, a gym or a
  virtual round — binding at runtime to whatever judge MCP is installed (fetch
  the problem list, fetch statements, submit, poll verdicts) and delegating the
  algorithm design and C++ to the competitive-programming:solving-problems
  skill. Use this whenever the user wants to work through a whole contest or
  problem set rather than a single problem — phrasings like "solve this
  contest", "grind contest 1998", "do the whole round", "solve problems A–F",
  "run through this contest and submit until AC", or any mention of ICPC-style
  or IOI-style contest mode. Trigger even if the user only gives a contest ID
  or URL and says "go". For a single isolated problem with no contest loop and
  no auto-submission, use competitive-programming:solving-problems directly
  instead.
---

# Contest Orchestrator

Drive a full contest on any competitive programming judge: pull the problems,
solve them one at a time, submit, read the verdict, and iterate to Accepted
before moving to the next — delegating the actual thinking and C++ to the
**competitive-programming:solving-problems** skill and using a **judge MCP** for
everything that touches the judge.

This skill is the *loop and the judge interface*. It does not re-implement
algorithm design — solving-problems already does that well. Keep the division clean:
solving-problems decides *what code to write*; this skill decides *what problem to work
on, when to submit, how to read the result, and what to do next*.

## Before you start — establish the run

Settle these three things (ask only for what the user hasn't already given):

1. **Which contest, on which judge.** A contest ID or URL. Infer the judge from
   the URL's domain — codeforces.com, atcoder.jp, codechef.com, open.kattis.com,
   dmoj.ca, oj.uz. Ask only when it is genuinely ambiguous, such as a bare
   number with no judge named.
2. **Which mode** — `ICPC` or `IOI`. They change submission strategy (see
   [Modes](#modes)). If the user hasn't said, ask which one.
3. **Which judge interface** — bind the four capabilities below to real tools
   before you open a single problem.

## Judge interface — the capability contract

This skill never hardcodes a judge's tool names. It needs four **capabilities**,
and binds each one to whatever tool the installed MCP actually provides:

| Capability | What it must give you | Used at |
|---|---|---|
| **list-problems** | the contest's problem indices and names; ideally solve counts, points or difficulty | [Ordering](#ordering--easiest-first) |
| **get-statement** | one problem's full statement, limits and samples | loop step 1 |
| **submit** | send source code and a language for one problem | loop step 4 |
| **poll-verdict** | a submission's verdict or score | loop step 5 |

Bind them once, before the first problem:

1. **Read `references/judges.md`** for the judge the user named. An entry there
   gives you the server, the expected bindings, and the judge's quirks — scoring
   rule, language ids, contest URL shapes.
2. **Discover the tools at runtime.** Call `ToolSearch` with the judge name plus
   capability words ("codeforces contest problems", "atcoder submit",
   "submission verdict") to load the real tool definitions, and read their
   actual parameter names. MCPs vary and a registry entry can go stale — **the
   loaded schema always wins over anything written down.** Never guess a schema.
3. **Bind each capability to one concrete tool** and write the binding down.
4. **State the binding in your first status update**, so the user can correct a
   mis-binding before any submission happens.
5. **If a capability has no tool**, go to
   [When no MCP covers this judge](#when-no-mcp-covers-this-judge). Don't
   improvise a tool name and don't abandon the run.

After this step, reason in capabilities. Concrete tool names live in your
binding and in `references/judges.md` — not in the loop.

## When no MCP covers this judge

A missing MCP moves the judge I/O to the user; it does not end the contest. Say
plainly which capabilities you could not bind, then **offer** this mode — don't
slide into it silently.

| Missing capability | What you do instead |
|---|---|
| **list-problems** | Read the problem list off the contest page with WebFetch, or ask the user for it. |
| **get-statement** | Fetch the problem URL with WebFetch, or ask the user to paste the statement. |
| **submit** | Hand over the final source file path and the exact language to select, and ask the user to submit it. |
| **poll-verdict** | Ask the user to report the verdict verbatim — including the failing test number or the per-subtask scores, which you need in order to debug. |

**Check a fetched statement before you solve it.** It is usable only if it
carries the constraints, the limits, and the samples. If WebFetch returns a
truncated page, a JavaScript shell, or a login wall, stop and ask for a paste.
Solving a partial statement burns a full cycle and produces confidently wrong
code.

Everything else here is unchanged in degraded mode — the ordering, the
per-problem loop, the verification bar for the mode, the stuck triggers, the
progress reporting. Only the judge I/O is manual.

## Autonomy model — hybrid

Run the contest **autonomously**, but with the solving-problems per-problem *approval
checkpoint suppressed*. You still use the solving-problems full reasoning workflow
(restate → constraints → complexity budget → classify → design → edge cases →
template → clean C++ → sample check), but you do **not** stop after the plan to
wait for a sign-off on every problem. The whole point is to keep moving.

Pause and ask the user **only** when one of these hybrid triggers fires:

- **Ambiguous statement.** The problem is genuinely underspecified or you're
  torn between two readings that give different answers. Don't silently guess on
  something load-bearing — surface it.
- **Stuck.** You've made ~3 *distinct* fix attempts on a problem (different
  ideas or bug fixes, not cosmetic retries) and still can't get Accepted, or
  you've worked the problem properly — tried the moves in
  [When a problem won't fall](#when-a-problem-wont-fall) — and still have no
  algorithm that fits the constraints. This trigger asks the user for *help on
  that problem*; it is not permission to retire it. Reading a statement and
  finding it hard does not fire it.
- **Something surprising or destructive.** A bound tool returns errors you
  can't interpret, rate-limits you, the contest looks already over, or anything
  that makes continuing feel wrong.

Outside those triggers, proceed without asking. When you do pause, give a tight
status snapshot (see [Progress reporting](#progress-reporting)) so the user can
decide fast.

### What "suppressed" covers — the approval checkpoint, nothing else

The **only** thing this skill removes from solving-problems is the pause for sign-off.
Every other rule in solving-problems stays in force at full strength, and that includes
its **Code quality** section — meaningful names, decomposition into helper
functions, modern C++ idioms, no cryptic macros. Contest code is code the user
will read, review, and keep. Submit it in the shape you'd be willing to show
them, on the first submission, not after they ask.

A running clock is **not** an exemption. Time pressure is the normal condition of
this skill — if the deadline excused sloppiness, the rule would never apply at
all. Clean structure is also *faster* here, because unreadable code hides
verdict-costing bugs: a matrix solution whose dimension lives in a global `K1`
with fixed `[12][12]` arrays silently overruns when a subtask allows a larger
`k`, and scores a partial. The same code with the size held on the object cannot
express that bug at all.

The single exception is the solving-problems **Black magic** section, which suspends the
quality rules explicitly and only after a correct solution provably still TLEs on
constant factors. Nothing else suspends them.

| Rationalization | Reality |
|---|---|
| "Only 30 minutes left, clarity later" | Clean naming costs seconds while writing, and there is rarely a "later" — the user has to ask, as they did. |
| "It's throwaway contest code" | It lands in the user's repo and gets reviewed. Nothing here is throwaway. |
| "I'll refactor after it gets AC" | A resubmit costs a full judge round-trip. Write it once. |
| "Short names are contest convention" | Convention among humans golfing by hand. You type at no cost; there is no tradeoff to make. |
| "The algorithm is the hard part, style is cosmetic" | The derivation belongs in a comment for exactly that reason — a reader cannot re-derive a greedy from `pq` and `P`. |
| "Cleaning up risks breaking a working solution" | Then verify the refactor the same way you verified the original: samples plus a stress run. |

**Red flags — you are rationalizing:** naming real data `a`, `x`, `v`, `tmp`,
`P`, `K1`; a single `main()` carrying parse, algorithm, and output together; a
derivation that exists only in your reasoning and not in the file; the thought
"I'll tidy it if they complain."

## Ordering — easiest first

Solve in **increasing difficulty**, not necessarily alphabetical. If the
**list-problems** capability exposes solve counts, points or difficulty,
order by that (most-solved, or lowest points/difficulty, first). If it doesn't,
fall back to problem-index order (A, B, C… or 1, 2, 3…), which on most judges is
already roughly easy-to-hard. State the order you chose in your first status
update so the user can override.

## What you are optimizing

The rule below is the **ICPC/Codeforces penalty model**, the most common one. If
your judge scores differently — AtCoder's points per problem with penalties only
separating equal scores, an IOI-style subtask total — read that judge's actual
rule (`references/judges.md`, or the contest page) and re-derive from it. Two
consequences survive every scoring system in use, so treat them as fixed: **a
solve beats no solve**, and **an attempt on a problem you have not solved costs
almost nothing.**

Get this right before you make a single strategic decision, because the obvious
reading of "minimize penalty" is wrong and it will cost you problems.

Rank is decided by **problems solved**, first and always. Penalty only separates
entrants who solved the *same number*, and it is computed **over solved problems
only**: each solved problem contributes the time of its accepted submission plus
a fixed charge per rejected attempt *on that problem*. A problem you never solve
contributes nothing at all — **its wrong submissions are free.**

Three consequences, none of them negotiable:

- **A solve with penalty beats no solve.** Always. No penalty total outranks one
  more problem.
- **An attempt on an unsolved problem is free.** The only real costs are your
  time and the judge's patience. "It might be wrong" is never a reason to leave a
  finished solution unsubmitted — it is a reason to verify harder *first*, and
  then submit.
- **Penalty is a tiebreak objective, not a stopping rule.** It tells you to
  verify before you submit. It never tells you to leave a problem unattempted,
  and it never justifies ending the run early.

## Modes

The modes differ in **the goal**, **how careful you are before hitting submit**,
and **how you use the judge**. ICPC drives every problem to Accepted; IOI drives
each problem toward its maximum score, where a partial is real, bankable
progress.

### ICPC mode — verify before you submit

A rejected attempt on a problem you go on to solve adds penalty, so **be
convinced the solution is right before you submit.** How convinced, and how you
get there, is your judgment per problem — calibrate the verification to the risk:

- **Always**: the solution compiles locally and passes every provided sample
  exactly — on an interactive problem, there is no sample file to pass; use the
  [interactive verification floor](#interactive-problems) instead.
- **Raise the bar** — add a stress test against a brute-force oracle (per
  the solving-problems stress-testing method) *before* submitting — when the solution is
  the kind that's easy to get subtly wrong: greedy/ad-hoc arguments you can't
  fully prove, tricky edge cases, tight constraints, fiddly geometry or modular
  math, or anything where "passes samples" is weak evidence.
- **Lower the bar** — samples alone are fine — for straightforward
  implementation problems where the logic is transparent and the samples
  exercise it.

Only submit once you'd bet on it. If the verdict still comes back wrong, treat
the judge's feedback as a strong signal that a hidden case broke it, and
stress-test before the next submit even if you skipped it the first time.

This bar governs **when** you submit, never **whether**. Once you have a solution
you cannot improve further — no oracle left to write, no case left to check, no
suspicion left to chase — submit it. On a problem you haven't solved, the attempt
costs nothing, and an unsubmitted solution scores exactly as well as no solution.

### IOI mode — submissions are cheap, use them to debug, maximize score

IOI-style judging returns a **score**, not a binary pass/fail. Submit freely —
the judge is your fastest oracle. Make sure a submission compiles and passes
samples first — on an interactive problem, clear the [interactive verification
floor](#interactive-problems) instead — so you don't waste round-trips on
trivially broken code. But don't stress-test pre-emptively — let the judge point
you at what's failing, then reproduce and fix it.

There are two kinds of IOI problem, and they have **different stopping rules**.
Identify which one you're on from the statement before deciding when a problem is
"done".

#### Traditional (subtask) problems — get the perfect score

These score by discrete subtasks/tests (e.g. "subtask 1: N ≤ 1000, 30 points";
"Partial, 60 points"). A perfect score is achievable, so **the target is full
marks — get 100%.** Don't settle for a partial as the finish line here.

- **Read which subtasks failed.** They map to constraint tiers (small N, special
  cases, full constraints). A partial tells you *which* regime breaks, which
  points straight at the missing idea (full marks on N ≤ 1000 but TLE on
  N ≤ 10⁶ → you need a faster algorithm for the last subtask, not a bug fix).
- Iterate submit → read what failed → improve → resubmit until you reach full
  marks. A partial is progress toward 100%, not a stopping point.
- The only reason to stop below full is the stuck trigger (see
  [When a problem won't fall](#when-a-problem-wont-fall)) — at which point
  surface the best partial to the user rather than looping silently.

#### Special / custom-scoring (optimization) problems — maximize, then check in

These grade a *quantity* you produce (minimize a cost, maximize a packing, get
close to an unknown optimum) on a continuous or relative scale. There's often no
clean "perfect" — just better and better scores. You can recognize one from the
statement: a scoring *formula* or custom checker, wording like "your score is…",
"as close as possible", "minimize"/"maximize", partial credit on a continuous
scale, or "output any valid construction" graded by quality rather than a single
fixed correct answer. Here the goal is **the highest score you can reach**, and
the stopping rule is about diminishing returns plus keeping the user in the loop,
not hitting 100%:

- **Push the score up** with successive improvements — better heuristics, tuning,
  smarter construction — resubmitting to measure each gain.
- **When gains plateau, ask the user whether they want more.** Don't quietly stop
  the moment progress slows, and don't grind indefinitely on your own judgment —
  surface the current score and ask if it's good enough or worth pushing further.
- **If the problem states or implies a theoretical limit** (a provable upper
  bound, a known optimum, a max score) **and you've reached close to it** — the
  remaining gap is small enough that further effort isn't worth it — you may
  stop. **But notify the user first** with the score and the bound, and let them
  confirm or redirect before you move on. Never silently stop near the limit.

## The per-problem loop

For each problem, in the chosen order:

1. **Fetch the statement** via the **get-statement** capability. Read it fully —
   constraints, time/memory limits, and all samples.
2. **Solve it with competitive-programming:solving-problems.** Run its workflow to get correct,
   constraint-fitting C++ — but skip its approval checkpoint (see
   [Autonomy model](#autonomy-model--hybrid)). The solving-problems **Code quality**
   rules apply in full to what you submit; the clock does not relax them (see
   [What "suppressed" covers](#what-suppressed-covers--the-approval-checkpoint-nothing-else)).
   Compile and run it against every sample locally — on an interactive
   problem, run the [interactive verification floor](#interactive-problems)
   instead.
3. **Verify to the mode's bar.** Apply the [ICPC](#icpc-mode--verify-before-you-submit)
   or [IOI](#ioi-mode--submissions-are-cheap-use-them-to-debug-maximize-score) standard above
   before deciding to submit.
4. **Submit** via the **submit** capability. Pick the C++ language from the ids
   that tool actually offers — discover them, don't assume a numbering. A
   judge's language ids mean nothing on another judge.
5. **Poll the verdict** via the **poll-verdict** capability. Submissions judge
   asynchronously. Poll until the verdict leaves "In queue"/"Running"/"Testing",
   at a reasonable interval (a few seconds between checks); don't hammer it, and
   don't assume an immediate result.
6. **Act on the verdict** (see the table below).
7. **Decide done or continue**, by mode and problem type:
   - **ICPC** → done means Accepted. Anything else, debug and resubmit, respecting
     the stuck trigger.
   - **IOI, traditional subtask** → done means **full marks**. Keep improving
     toward 100%; only stop below full at the stuck trigger, and then surface the
     best partial to the user.
   - **IOI, special / custom-scoring** → done means you've maximized the score and
     **checked in with the user**: either gains plateaued and they said it's good
     enough, or you reached close to a theoretical limit and notified them before
     stopping. Don't move on from a special problem on your own judgment without
     that check-in.
   Record the accepted / best submission before moving to the next problem.

Do the problems strictly one at a time — fully resolve (AC, full marks, a
user-confirmed stop on a special problem, or a user-directed skip) the current
problem before fetching the next.
Don't interleave.

### Verdict handling

Judges spell verdicts differently — `AC`/`OK`/`Accepted`, `WA`/`Wrong answer`,
`TLE`, `MLE`, `RE`, `CE`, `ILE`/`Idleness limit exceeded`. Match on **meaning**,
not on the exact string. A verdict that maps to no row is surprising: report it
rather than guessing.

| Verdict | What it means | Response |
|---|---|---|
| **Accepted (AC / OK)** | Passed all tests / full marks | Record; move to next problem. |
| **Partial (score < max)** | Subtask/graded judging: some tests or subtasks passed, others didn't, or a graded score below max | Read *which* subtasks failed — they map to constraint tiers and point at the missing idea (usually a faster algorithm or an unhandled case for the harder tier). On a **traditional** IOI problem, keep improving toward full marks. On a **special/optimization** problem, push the score higher, then check in with the user before stopping. If an *ICPC* problem returns a partial, it uses subtask scoring — treat it as a subtask IOI problem for that one. |
| **Wrong Answer on test N** | Logic bug | Reproduce test N's category if possible; find the counterexample (stress test if needed); fix. In IOI, N itself is the lead. |
| **Time Limit Exceeded** | Too slow | Re-check the complexity budget vs constraints. Usually the *algorithm* is wrong-class — go back to the solving-problems constraint table, not micro-optimization. Only reach for constant-factor tricks once the class is provably right. |
| **Memory Limit Exceeded** | Too much memory | Shrink data structures / reuse buffers; reconsider the approach if it's structurally heavy. |
| **Runtime Error on test N** | Crash | Suspect out-of-bounds, overflow, stack overflow from deep recursion, division by zero, bad `assert`. |
| **Compilation Error** | Didn't build | Read the compiler message; fix and resubmit. Doesn't count as a "fix attempt" toward the stuck threshold — it's mechanical. |
| **Idleness Limit Exceeded** | Interactive/flush issue, or not reading input | Flush after each write — see [Interactive problems](#interactive-problems). If the problem isn't interactive, you are not reading input to end of stream. |

Count only *distinct algorithmic/logic fix attempts* toward the ~3-attempt stuck
threshold. Compilation errors, typos, and trivial mechanical corrections don't
count.

## Interactive problems

Some problems talk to the judge instead of reading a fixed input. The statement
gives it away: an **Interaction** section, a query format, a query budget, and
usually no output specification. A judge MCP may flag it too — the Codeforces
server returns `interactive: true`.

They break three assumptions the normal loop makes:

- **Flush after every write.** Use `cout << … << endl;` or an explicit
  `cout.flush()` after each query. Buffered output deadlocks against the judge
  and scores Idleness Limit Exceeded — the fast-I/O habit of avoiding `endl` is
  exactly wrong here.
- **The sample is a transcript, not a test file.** Its two blocks are the two
  sides of a dialogue. Piping the sample input into your program and diffing the
  output proves nothing; don't report that as verification.
- **Stress testing needs a mock interactor**, not a brute-force oracle: a
  program that holds a hidden instance, answers queries by the statement's rule,
  counts them against the budget, and checks your final answer. Write that when
  an interactive problem needs stress testing, and drive your solution through a
  pipe.

**The verification floor.** Since the sample can't be diffed, it can't stand in
for the ICPC "passes every sample" gate, IOI's "passes samples first", or loop
step 2 — build the mock interactor above and use it as the floor instead. Before
you submit, run the solution against it on the statement's sample instance, then
on a few small random instances, and check the query count against the budget on
each run. That is the minimum for *any* interactive submission, independent of
the "raise the bar" stress-testing call in ICPC mode, which is about how much
*more* scrutiny a risky solution needs on top of this floor.

Read the query budget as a constraint like any other — it usually names the
intended algorithm (about n log n queries → sorting or binary search; about 2n →
a linear scan; about log n → binary search on the answer).

## When a problem won't fall

### Moves that break a stuck problem

Before you conclude a problem is beyond you, spend the effort on these. They
change the outcome far more often than staring at the statement harder, and each
one converts a problem that "needs the intended solution" into one that doesn't:

- **Shrink the state space with a proved bound.** A model that is obviously too
  big is often small once you bound what an *optimal* solution can actually use —
  an exchange argument, a monotonicity, a fixed point. Derive the bound, prove it
  leaves optimality intact, and the intractable model becomes the algorithm.
- **Profile before you optimize.** When a correct solution is too slow, measure
  which phase burns the time before rewriting anything. The bottleneck is
  routinely somewhere other than the algorithm you were about to replace —
  rebuilding a structure every iteration, allocation, or a search range you never
  tightened. Rewriting the wrong phase costs hours and buys nothing.
- **Test the assumption you can't prove.** A modelling step you're unsure of
  ("does this simplification lose optimality?") is a hypothesis, not a blocker.
  Write the exact, even exponential, oracle for tiny inputs and check it. Cheaper
  than a proof, more reliable than intuition, and it either unblocks you or hands
  you the counterexample.
- **Reach for the standard theory.** A problem that looks impossible is often a
  named result you haven't connected yet. Before inventing, ask what family it
  belongs to — the answer is frequently a textbook theorem plus bookkeeping.

### Asking for help

If you hit the stuck trigger (~3 distinct failed fix attempts, or the moves above
exhausted with no approach that fits the constraints), **stop and ask the user** —
this was their explicit choice. Present a compact debrief:

- The problem (index + one-line summary) and its constraints.
- What you tried: each approach, and the verdict that killed it (e.g. "greedy →
  WA on test 4", "O(N²) DP → TLE").
- **In IOI, the best score so far and which subtasks it covers** (e.g. "60/100,
  subtasks 1–2; subtask 3 needs an O(N log N) approach I don't have yet").
- Your best current hypothesis about the intended solution, if you have one.
- Concrete options, e.g.: *keep trying with a specific new idea I describe* /
  *bank the current partial and move on* (IOI) / *park it and come back after the
  rest* / *you give me a hint or the intended approach* / *drop it for good*.
  Default to parking; only the user may drop a problem for good.

Then wait for their call. Don't loop silently forever, and don't skip on your
own — surface it.

**Parking is not dropping.** A parked problem goes back on the queue as soon as
everything else is resolved, and the run is not finished while one sits parked.
Coming back with fresh context — and with the easier problems' techniques in
hand — cracks parked problems often enough that skipping the return is a real
loss.

## When the contest is over — and when it isn't

The run ends when **every problem is Accepted**, or when **the user** stops it.
Those are the only two endings you may declare.

While any problem is unsolved and you have budget left, the next action is always
to work on one of them. Solving easiest-first guarantees that what remains at the
end is the hardest material in the set — that is the expected shape of a contest
in progress, not a signal to stop. If you are unsure whether budget remains, ask;
don't assume it's gone.

**You may not retire a problem on your own judgment.** Not "the expected value is
low", not "it's rated 3500", not "I don't see the intended solution". Those are
inputs to *how* you attack a problem, never to *whether* you do.

| Rationalization | Reality |
|---|---|
| "Submitting something unproven costs penalty" | Not on a problem you haven't solved — it costs nothing. You have the scoring rule backwards; re-read [What you are optimizing](#what-you-are-optimizing). |
| "These are 3500s, the marginal expected value is low" | Nonzero expected value plus remaining budget is a reason to attack, not to stop. Stopping early scores zero with certainty. |
| "I've already spent a lot on this one" | Sunk cost. The only question is whether the *next* stretch cracks it. |
| "I don't see the intended solution" | You were never asked for the intended one — only for *a* solution inside the limits. |
| "Better to deliver a clean 8/11 than a messy attempt" | There is nothing to keep clean. Rejected attempts on unsolved problems are invisible in the standings. |
| "I'll write up why the rest are unsolved" | An explanation is not a solve. Write it after the budget is actually gone, not instead of trying. |
| "The user can ask me to continue if they want" | They asked for the contest. Continuing is the default; stopping is the thing that needs their say-so. |

**Red flags — you are about to stop too early:** the words "marginal expected
value", "pragmatically", "given the remaining budget", "not worth it", or "the
intended solution eludes me"; drafting a final summary or a README while problems
are still open; listing what you *didn't* solve as though it were a deliverable.
All of these mean: pick the most tractable unsolved problem and start on it.

## Progress reporting

Keep the user oriented without spamming. Report at natural boundaries: after
each Accepted, and whenever you pause. A good status line is compact:

```
Codeforces 1998 · ICPC mode · order by solves · judge MCP: codeforces
A ✅  B ✅  C 🔁 (WA test 3, fixing)  D–F ⏳
Attempts: A×1  B×2  C×2
```

In IOI mode, show scores instead of a binary tick so the user sees where points
stand:

```
Codeforces 1998 · IOI mode · order by index · judge MCP: codeforces
A 100  B 100  C 60 🔁 (subtask 3 TLE, need faster)  D 0 ⏳  E–F ⏳
Score: 260  ·  Attempts: A×1  B×1  C×2
```

Include the submission verdict (or new score) when one just came back. Don't paste full source
into every update — the user can ask to see a solution if they want it.

## Guardrails

- **One contest, one judge, the user's.** Only operate on the contest the user
  named, on the judge they named. Don't fetch or submit anywhere else.
- **Respect the judge.** Poll politely, don't spam submissions in ICPC mode, and
  if a bound tool rate-limits or errors in a way you can't parse, pause and
  report.
- **Correctness over speed of loop.** The goal is Accepted problems, not a fast
  wrong pass. In ICPC especially, a considered submission beats a rushed one.
- **Fair play is the user's call.** Solve the problems on their behalf as asked;
  if a contest is clearly live and rated, it's the user's responsibility how
  they use this — you don't need to police it, but don't disguise what you're
  doing either.
- **Preserve working solutions.** Keep each Accepted solution available in case
  the user wants to review or resubmit it.
- **Finish the set.** Solved problems are the score; everything else is a
  tiebreak. Keep going while problems are open and budget remains — see
  [When the contest is over](#when-the-contest-is-over--and-when-it-isnt).

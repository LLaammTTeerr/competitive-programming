---
name: validating-solutions
description: >
  Use when writing deliberately-wrong solutions for a competitive programming
  problem, cross-checking a model solution against alternatives, stress
  testing, or judging whether a test suite is strong enough. Triggers on
  wrong solution, brute-force oracle, greedy that fails, stress test,
  cross-check, are my tests strong enough, invocation matrix, expected
  verdict, holes, TLE margin. This attacks an existing test suite; to write
  the generator, validator or checker itself use
  competitive-programming:preparing-tests instead.
---

# Validating solutions

Mission: **attack**. This skill owns the zoo of deliberately-wrong solutions,
the invocation matrix that runs every solution against every subtask, and the
arbiter that resolves disagreements between solutions that are all supposed
to be correct. It never builds test data — that is `preparing-tests` — and it
never claims "the tests are strong"; the only claim it makes is *"no solution
in the zoo survives"*.

## Am I the right skill?

Routing happens before a skill loads, so a description cannot ask a
question. If the request plausibly means one of these instead, **ask before
doing anything** — one question, options being each neighbour and "both, in
this order".

| If it's really about | Use |
|---|---|
| The generator, validator, or checker itself — `registerGen`, `registerValidation`, `wcmp`/`ncmp`, the test data doesn't exist yet | `competitive-programming:preparing-tests` |
| The model solution's own algorithm is wrong or too slow, no test suite involved yet | `competitive-programming:solving-problems` |
| A finished idea that needs the whole pipeline sequenced, with gates | `competitive-programming:creating-problems` |

Ask only when genuinely ambiguous. **"Write me a checker" is not ambiguous —
that's `preparing-tests`. "Are these tests good enough?" is not ambiguous
either — that's here**, because "good enough" is a strength question and
strength is this skill's mission. **"Make my tests stronger" leans here**
too — strength is measured by throwing more of the zoo at the suite, not by
writing another generator family — but if the honest answer turns out to be
"the zoo found a hole", the exit is back to `preparing-tests` for a killer
test, so say that rather than silently generating one yourself. "My brute
force is too slow" is neither skill: no test suite is in play, so it's a
`solving-problems` question — don't let the word "brute force" pull it here
just because the zoo's arbiter is also called a brute.

## Bootstrap

`$BASE` is not an environment variable the harness sets — it is not exported
into a shell, only into MCP config. What you actually have is the line **"Base
directory for this skill" printed in this skill's own invocation preamble.
Substitute that literal path for `BASE` below:

```bash
BASE="<the path from this skill's own 'Base directory for this skill' line>"
PLUGIN_ROOT="$BASE/../.."
PROBLEM="<absolute path to the problem directory you are validating>"
TESTLIB="$(bash "$PLUGIN_ROOT/tools/bootstrap_testlib.sh")"
cd "$PLUGIN_ROOT"
```

Every `python3 -m tools.*` command below is a module inside `tools/`, which
is only importable with `PLUGIN_ROOT` as the working directory — `cd` there
first, or every invocation fails with `ModuleNotFoundError: No module named
'tools'` before it does anything.

Two different directories matter from here on, and neither is implicit:
`python3 -m tools.*` always runs from `$PLUGIN_ROOT` and takes `$PROBLEM` as
an argument, so it is unaffected by where the problem lives. Everything
problem-relative — reading `solutions/*.cpp`, writing `solutions.json` and
`invocation.json` — happens **inside `$PROBLEM`**. Keep `$PROBLEM` set and
pass it explicitly in every command below rather than relying on whatever
directory the previous command left you in.

## Environment facts this skill's results depend on

Every solution runs inside the `ioi/isolate` sandbox
(<https://github.com/ioi/isolate>) — there is no fallback runner, and
`run_matrix` refuses to start rather than silently falling back to something
unsandboxed. (`preparing-tests` covers installing and configuring it; that
setup is a one-time machine concern shared by both skills.) Given that, every
number in `invocation.json` means the following, and if these ever disagree
with what you observe, `tools/matrix_core.py`'s `compute_limits` and
`classify` are the single source of truth, not this paragraph:

- **Timing is CPU time**, not wall clock. `TL = max(2 x t_main, 1000 ms)`,
  rounded up to the nearest 500 ms; the sandbox kills at `2 x TL`. A result
  landing in `[TL, 2xTL]` is **flagged, never given a verdict** — it is the
  honest home for a result too close to call on different hardware, and it
  is why the zoo has a `time-limit-exceeded-or-accepted` tag: a solution you
  expect to time out but only barely goes there, not into a flat `TL`.
- **Memory is kernel-enforced.** `--cg-mem` plus `cg-oom-killed` in isolate's
  own meta file *is* the ML signal — not a polled RSS reading compared
  against a limit after the fact.
- **Only stdin/stdout problems are supported.** File IO is rejected loudly by
  `run_matrix`, not silently mishandled.
- **`isolate` defaults to one process.** A multi-threaded or multi-process
  wrong solution is not judged on timing at all — `run_matrix` still records
  whatever CPU time isolate measured before the crash, but the crash itself
  (not the clock) decides the verdict, which comes back `RE`. Real judges
  usually limit processes too, so this is defensible — but it is worth
  stating plainly, because a setter who writes a threaded TLE solution and
  gets `RE` back can burn an hour assuming the *harness* is broken before
  realizing the sandbox's own single-process default is what fired.

## The zoo

`main` is not a zoo class — it's the reference: the one solution the zoo
attacks *with*, never a solution the zoo attacks. It defines both the
expected answers and the timing baseline, and every other tag in this table
is `main` on trial one way or another, so it does not get a row of its own.

The zoo itself is nine rows, each with a job — not just a name:

| Class | Job |
|---|---|
| `accepted`, alternative algorithm | cross-check oracle — worth nothing unless genuinely independent, not a transcription of `main` |
| `accepted`, exhaustive, tiny-N | **the arbiter.** Exists to break ties between disagreeing `accepted` solutions, not to pass the suite |
| `wrong-answer`, plausible greedy | what a contestant actually submits at 2am |
| `wrong-answer`, boundary | dies on n=1, all-equal, or another degenerate shape |
| `wrong-answer`, overflow | `int` where `long long` is needed — kills any suite that never reaches the value bound |
| `wrong-answer`, misread statement | e.g. start- vs end-index, off-by-one on an inclusive range |
| `time-limit-exceeded` | correct, wrong complexity class |
| `time-limit-exceeded-or-accepted` | the honest home for a solution expected to land in `[TL, 2xTL]` — a result too close to call on other hardware, tagged that way rather than as a flat `TL` |
| `memory-limit-exceeded` | correct, allocates too much |

`scan_solutions.py` accepts eight `@tag` values in total (confirm with
`python3 -c "from tools.scan_solutions import TAGS; print(TAGS)"`):
`main`, `accepted`, `wrong-answer`, `time-limit-exceeded`,
`time-limit-exceeded-or-accepted`, `memory-limit-exceeded`,
`presentation-error`, `failed`. The nine zoo rows above map onto six of
those tags (`accepted` and `wrong-answer` each cover several rows); `main`
is the reference, not a row; `presentation-error` and `failed` are
Polygon's remaining two and are rarely needed in this pipeline (a stock
checker never emits PE, and `failed` is for a checker/package bug, not a
deliberately-wrong solution).

Two rules make the zoo worth writing:

- **Each wrong solution is wrong in exactly one named way.** One wrong in
  three ways proves nothing about which test caught it — a solution that is
  simultaneously off-by-one *and* `int`-overflowing gives no signal about
  whether the suite reaches the overflow bound, because the off-by-one might
  have caught it first on every test.
- **Wrong solutions must be plausible, not strawmen.** The bar is *"would a
  competent contestant submit this at 2am?"* A greedy nobody would write
  catches nothing and inflates the report with a class that was never a real
  risk.

## Writing the zoo is a fan-out

N wrong solutions are N independent tasks with no shared state — each only
needs the statement, the one named way it must be wrong, and the metadata
block below. **Invoke `superpowers:dispatching-parallel-agents`** and tell
each agent exactly one class from the table above; an agent told "write a
wrong solution" with no named failure mode will reach for whatever is
easiest to type, which is exactly the strawman the second rule forbids.

## The metadata block

Solution metadata lives in the `.cpp`'s own header comment, never in a
hand-written `solutions.json` — metadata beside the code cannot desynchronize
from it, and renaming the file cannot orphan it. `solutions.json` is a scan
product, regenerated every run:

```bash
python3 -m tools.scan_solutions "$PROBLEM"
```

The exact format `tools/scan_solutions.py` parses (confirmed against its
source, not paraphrased from memory):

```cpp
/**
 * @tag        wrong-answer
 * @expect     g1=WA g2=WA
 * @algorithm  Compares first occurrence by START index rather than END index.
 * @why-wrong  Diverges from the model exactly when |A| != |B|.
 * @complexity O(|A| + |B|)
 */
```

- **`@tag`** must be one of Polygon's eight: `main`, `accepted`,
  `wrong-answer`, `time-limit-exceeded`, `time-limit-exceeded-or-accepted`,
  `memory-limit-exceeded`, `presentation-error`, `failed`. Anything else is a
  scan error, not a warning.
- **`@expect`** verdicts are `OK WA TL ML PE RE`, one `group=VERDICT` token
  per declared subtask id. The scanner requires **exact** coverage: a missing
  group or an unknown one both reject the file — there is no partial credit
  for covering most subtasks.
- **`@why-wrong`** is optional; `@algorithm` and `@complexity` are not.
- **Exactly one `main`** is required across the whole `solutions/` directory
  — zero or two both fail the scan.

## Running the matrix

```bash
python3 -m tools.run_matrix "$PROBLEM" "$TESTLIB"
```

This builds every solution, times `main` as the median of 3 runs per test,
derives `TL`/`kill` from that, then runs every solution in the manifest —
`main` included — once each (re-timed only if a result lands in the band),
checks each result, and writes `invocation.json`. `main`'s own pass-2 run
appears in `results` alongside the rest, which is how you see its own `OK`
recorded rather than only inferred.

**This skill never re-implements timing** — no shell `time`, no wall-clock
stopwatch in a bash loop, no second opinion on what counts as too slow. The
tool owns the clock; reading its output is this skill's whole job. Exit 0
means every expectation was met; **exit 1 means
holes or mismatches exist**, printed to stdout as it exits — that is the
signal to keep reading, not to retry the command.

## Reading the result

`invocation.json`'s `holes` and `mismatches` are two different failures with
two different owners:

- **A hole** is the *suite's* failure: a solution declared wrong that no test
  killed (`expected` was failing, `actual` came back `OK`). Hand it back to
  `preparing-tests` for a test that actually exercises the named way that
  solution is wrong — a hole is never fixed by writing a different wrong
  solution.
- **A mismatch** is anything else. The one that matters most is two
  `accepted`-class solutions — including `main` itself — disagreeing with
  each other; that is a *correctness* problem, and it routes to the arbiter
  below, never to a guess about which one to trust.

To name the test that killed a given cell, read `results`, filtered by
solution and group, for the entry whose `verdict` isn't `OK`:

```bash
python3 -c "
import json
data = json.load(open('$PROBLEM/invocation.json'))
for r in data['results']:
    if r['solution'] == '<file>.cpp' and r['group'] == '<group>' and r['verdict'] != 'OK':
        print(f\"{r['solution']} {r['group']}/{r['test']} -> {r['verdict']}\")
"
```

## The arbiter

Runs only when two `accepted`-class solutions disagree on some input X:

1. Shrink X to the minimal case that still reproduces the disagreement.
2. Run the tiny-N exhaustive brute (the `accepted`, exhaustive, tiny-N zoo
   entry) on the shrunk case. Whichever solution it agrees with is right.
3. If the brute cannot decide — or cannot even be written, because the
   behaviour genuinely is not defined anywhere in the statement — that is
   **statement ambiguity**, and the exit is `writing-statements`. Never
   silently pick a side because one solution "looks more careful."
4. **Hard stop after 3 rounds regardless of outcome**, escalating with the
   minimal case reached so far — an arbiter that can run forever is not an
   arbiter, it's a stall.

**Invoke `superpowers:systematic-debugging`** for the shrink-and-diagnose
loop in steps 1–2: this is a debugging loop wearing a different name, and its
core rule — understand before proposing a fix — is exactly the discipline
that keeps step 3 honest instead of becoming a coin flip.

## Strength is three obligations, not one

- **Adversarial** — every rejected solution fails, and the report names the
  test that killed it. Never *"the tests are strong"* — always *"no solution
  in the zoo survives"*.
- **Reaching** — every declared bound is actually attained by some test in
  its group, not merely legal under it.
- **Structural** — a per-shape checklist: min and max sizes, all-equal,
  all-distinct, value extremes, degenerate structures (star / path /
  caterpillar for trees), anti-hash and anti-quicksort inputs wherever the
  model solution invites them (a hash set, a naive `sort`).

A suite can pass every declared bound and still be weak in the third sense —
reaching says the maximum size exists somewhere; structural says the
adversarial *shapes* at that size exist too.

## Done means

`invocation.json`'s `holes` is `[]`, and every failing (`WA`/`TL`/`ML`/`PE`/
`RE`) cell in `mismatches` and `results` names the specific test that
realized it — never just the group. **Invoke
`superpowers:verification-before-completion`** before reporting either
claim: `holes: []` is the claim, the `invocation.json` this skill just wrote
is the evidence, and "I re-read the zoo and it looks complete" is not a
substitute for running the matrix and reading its exit code.

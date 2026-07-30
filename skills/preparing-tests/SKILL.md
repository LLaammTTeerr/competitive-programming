---
name: preparing-tests
description: >
  Use when writing the generator, validator, or checker for a competitive
  programming problem with testlib, generating test data grouped into
  subtasks, or choosing sample tests. Triggers on testlib, generator,
  validator, checker, registerGen, registerValidation, wcmp/ncmp/rcmp6, test
  data, subtask groups, Polygon tests script. This builds the test data; for
  judging whether that data is strong enough, and for writing
  deliberately-wrong solutions, use
  competitive-programming:validating-solutions instead.
---

# Preparing tests

Mission: a test suite that is **legal** (every test satisfies the declared
bounds), **reaching** (every declared bound is actually attained by some
test), and **answerable** (a checker exists that can tell two outputs apart).
This skill owns the contract — checker, validator, generators, sample
selection. It does not judge whether the contract survives an attack; that is
`validating-solutions`.

## Am I the right skill?

Routing happens before a skill loads, so a description cannot ask a
question. If the request plausibly means one of these instead, **ask before
doing anything** — one question, options being each neighbour and "both, in
this order".

| If it's really about | Use |
|---|---|
| Is my suite strong enough? Will a wrong solution survive it? A zoo of deliberately-wrong solutions, the invocation matrix, `@expect` tags | `competitive-programming:validating-solutions` |
| What N, what subtask ladder, is this problem original, what difficulty | `competitive-programming:shaping-problems` |
| The prose: story, `\InputFile`, `\Constraints` itemize, `\Examples` | `competitive-programming:writing-statements` |
| A finished idea that needs the whole pipeline sequenced, with gates | `competitive-programming:creating-problems` |

Ask only when genuinely ambiguous. **"Write me a validator" is not
ambiguous. "Make my tests better" is** — that could mean the generators here
need another family, or that the zoo in `validating-solutions` hasn't found
the hole yet. When in doubt, ask which.

## Bootstrap

`$BASE` is not an environment variable the harness sets — it is not exported
into a shell, only into MCP config. What you actually have is the line **"Base
directory for this skill" printed in this skill's own invocation preamble.
Substitute that literal path for `BASE` below:

```bash
BASE="<the path from this skill's own 'Base directory for this skill' line>"
PLUGIN_ROOT="$BASE/../.."
PROBLEM="<absolute path to the problem directory you are preparing>"
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
problem-relative — compiling `validator.cpp` and `gen-*.cpp`, running the
validator over test files, writing `files/` and `tests/` — happens **inside
`$PROBLEM`**. Keep `$PROBLEM` set and pass it explicitly in every command
below rather than relying on whatever directory the previous command left
you in.

Then **read `$TESTLIB/docs/usage-guide.md` for the API and `$TESTLIB/plan.md`
for known defects** before writing a line of `validator.cpp`, `check.cpp`, or
any `gen-*.cpp`.

No testlib API is reproduced in this file, and that is deliberate: the guide
is 902 lines and versioned against the exact header the pipeline compiles
against, so a paraphrased method signature goes stale the moment a bug in
testlib is fixed upstream. This file carries only what the guide does not —
subtask binding, ordering doctrine, and the traps below, curated from the
fork's own audit rather than duplicated from it.

Compile everything the same way:

```bash
g++ -std=c++17 -O2 -Wpedantic -Werror -I"$TESTLIB" file.cpp -o file
```

Never `-ffast-math` — testlib detects it at runtime and aborts.

## Two things the pipeline assumes, stated up front

**Only stdin/stdout problems are supported.** `problem.json`'s `io.input` /
`io.output` must be `"stdin"` / `"stdout"`. File-based IO (`flight.inp` /
`flight.out`, the shape most VOI-style packages use) is rejected loudly by
`run_matrix.py` — it is a later feature, not a silent partial mode. If the
problem was scoped around file IO, that is a `shaping-problems` decision to
revisit, not something to route around here.

**Every solution and generator run is measured under `ioi/isolate`**, not a
bare `fork`/`exec`. There is no fallback runner, and `run_matrix.py` refuses
to start rather than silently falling back to something unsandboxed. If
`isolate --version` fails, this machine needs: `isolate` on `PATH`
(<https://github.com/ioi/isolate>), a system `isolate` user with
`isolate:200000:65536` registered in `/etc/subuid` and `/etc/subgid`, and
`systemctl enable --now isolate.service` so the cgroup keeper is running.
That setup is a one-time machine concern, not a per-problem one, but a
generator or validator you can't yet run inside the sandbox is a generator
you haven't actually tested — see the TDD section below.

Two consequences worth internalizing before writing any timing-sensitive
code:

- **Timing is CPU time**, as isolate reports it, never wall clock — far
  less sensitive to what else is running on the box. `TL = max(2 × t_main,
  1000 ms floor)`, rounded up to the nearest 500 ms; the sandbox kills at
  `2 × TL`. A result landing in `[TL, 2×TL]` is flagged as `timing-band` and
  never given a pass/fail verdict — it is a coin flip on different hardware,
  not a number to argue with.
- **Memory is enforced by the kernel**, not observed. isolate's `--cg-mem`
  plus its `cg-oom-killed` meta field *is* the ML signal — there is no
  polled RSS reading to second-guess, and none of that reasoning belongs in
  a generator or validator you write; it lives entirely in `run_matrix.py`.

## The order is the doctrine: checker, then validator, then generators

Building in any other order produces a diagnosable but wasteful failure mode:
skip straight to generators and you learn about an illegal bound only after
a thousand tests already violate it; skip the checker and "do these two
solutions agree?" has no answer whenever more than one output is valid for
an input (unsorted permutations, ties, multiple optimal answers). Each step
below depends on the previous one existing first.

### 1. Checker

Unique answer for every valid input → reach for a **stock checker** before
writing anything: 21 ship in `$TESTLIB/checkers/`, most usefully `ncmp`
(sequences of ints/longs), `wcmp` (tokens, any whitespace), `rcmp6` (real
numbers to 6 significant digits — the natural choice for a float answer),
`yesno`, and `lcmp` (line-by-line). Multiple valid answers → a custom
checker, only then.

**Never write a custom checker when a stock one covers the problem.** A
mis-parse of `ans` in a hand-written checker surfaces as `quitf(_fail, …)` —
it breaks the *package*, not a submission, because a read failure on `inf`
or `ans` is jury data failing to parse, and jury data is never `_wa`.

Two rules regardless of stock or custom:

- **There is no `registerChecker`.** Checkers use
  `registerTestlibCmd(argc, argv)`.
- **Checkers must never `assert`.** An assertion failure is a crash with no
  verdict; `quitf(_fail, "…")` is a crash *with* one. Use it.

### 2. Validator — before any generator exists

`files/constraints.h` is generated, not written:

```bash
python3 -m tools.gen_constraints_header "$PROBLEM"
```

It reads `problem.json`'s `constraints` (global bounds) and each subtask's
`bounds` (structured overrides, e.g. `g1` narrowing `n` to `<= 6`) and emits
`static const long long` constants such as `N_MIN` / `N_MAX` and
`G1_N_MAX`. **Never hand-write this header.** The reason it exists at all:
per testlib's own O-09, opts are silently generator-only —
`registerValidation` exposes only `--testset` / `--group` / `--testCase`, so
a validator cannot take a bound on the command line no matter how it's
written. Compile-time constants generated from the one source of truth are
what make drift between the validator and `problem.json` impossible rather
than merely discouraged.

Note the split this depends on: `problem.json` subtasks carry **both**
`bounds` (structured `{"min":…, "max":…}`, machine-readable, feeds this
header) **and** `constraints_text` (prose, feeds the statement's subtask
table). A single prose field cannot generate a `constexpr`; that is why the
schema carries both rather than one.

Write the validator against that header:

```cpp
#include "testlib.h"
#include "constraints.h"

int main(int argc, char* argv[]) {
    registerValidation(argc, argv);   // never the bare form — see below

    int n = inf.readInt(N_MIN, N_MAX, "n");
    inf.readSpace();
    int m = inf.readInt(M_MIN, M_MAX, "m");
    inf.readEoln();

    if (validator.group() == "g1") {
        ensure(n <= G1_N_MAX);
    }

    inf.readEof();
    return 0;
}
```

- **`registerValidation(argc, argv)`, never bare.** `registerValidation()`
  with no arguments silently disables `--testset` / `--group` / `--testCase`
  — the validator will build, run, and pass, and simply never check the
  subtask-specific bound you thought it was checking.
- **Name every variable** (`"n"`, not omitted) — Polygon's bounds analysis
  is keyed on the name string.
- **Branch on `validator.group()`** for subtask-specific tightening; the
  global bound is always enforced regardless of group.
- **Enforce format strictly**: `readSpace()`, `readEoln()`, `readEof()`
  between and after every token. A validator that accepts extra whitespace
  accepts a test the judge's real input parser might not.

Once the validator exists, drift-check the statement against it:

```bash
python3 -m tools.drift_check "$PROBLEM" <statement.tex>
```

This catches `problem.json`'s limits, IO mode, or subtask point totals
disagreeing with the `.tex` — the statement is never templated (that would
fight vnolymp), so this comparison is the only thing standing between the
two documents and silent disagreement.

### 3. Generators — only after the validator can reject bad input

- **`registerGen(argc, argv, 2)`, always.** Versions 0 and 1 are frozen for
  compatibility and each carries its own measured `rnd` defect rather than
  sharing one: under version 1, `rnd.next(0, 1)` repeats with period 65536
  (R-01, fixed only behind version 2 — versions 0/1 themselves stay
  byte-identical forever, never patched in place); under version 0, bit 31 of
  the underlying 63-bit draw is never set at all (R-02), which biases any
  `next(long long)` call over a range wider than 2^31 rather than just
  repeating a small one. A large random test built on version 0 or 1 is
  quietly less random than it looks, for two different reasons depending on
  which one was used — version 2 is the only one without a known `rnd` defect.
- **`opt<bool>("f", false)`, never `has_opt("f")`.** `has_opt` arms testlib's
  unused-opts check but — per O-02 — never marks the opt as used, so the
  generator writes a complete, plausible-looking test to stdout and *then*
  dies at exit with `FAIL Opts: unused key 'f'`. A pipeline that trusts the
  file on disk over the exit code picks up an artifact from a run that
  actually failed.
- **Opts are generator-only** (O-09, the same finding the validator section
  cites): a generator may read bounds from its command line; a validator or
  checker may not. This is exactly why `constraints.h` exists — it is the
  channel that carries bounds to the two programs that cannot take them as
  arguments.
- **Every generator is a pure function of its command line.** No reading
  files, no hidden state — reproducibility means the same invocation
  produces the same test forever.

Five families, and writing them is independent work with no shared state —
invoke `superpowers:dispatching-parallel-agents` to fan them out:

1. **Random** — the bulk of each subtask, sized within its bounds.
2. **Max-size** — every declared maximum hit simultaneously, at least once
   per subtask.
3. **Boundary/degenerate** — n=1, all-equal, all-distinct, empty where
   legal, single-element, the smallest legal size.
4. **Structured-adversarial** — shapes that break a specific plausible wrong
   algorithm: anti-hash strings, near-sorted-but-not, a star/path/caterpillar
   graph, a value distribution that breaks a greedy tie-break.
5. **Hand-written** — the handful of cases you thought of directly from
   reading the statement, too specific for any generator to reproduce by
   chance.

### Tests script

Polygon syntax, one line per test, grouped:

```
gen-random.exe 1 1000 100 > $
gen-max.exe --n=1000 > $
gen-boundary.exe --shape=all-equal > $
```

Validate every test under its own `--group` before it ever reaches a
solution:

```bash
./validator --testset tests --group g1 < tests/g1/01.in
```

A test that validates against the wrong group's bounds, or against no group
at all, is not verified — it is merely present.

## TDD on the validator and checker, before any generator exists

**REQUIRED:** `superpowers:test-driven-development` applies here literally,
not by analogy. The validator *is* the test; the generator is the code under
test. Feed the validator a deliberately-illegal input — `n` one past its max,
a missing trailing newline, a stray extra token — and assert it exits
nonzero, **before** the first generator is written:

```bash
printf '1001 5\n' | ./validator --testset tests --group g1; echo "exit: $?"
# expect nonzero — g1 caps n at 1000
```

This is the single most repeated lesson from building this pipeline's
tooling: **an error path you have not triggered is not handled.** Reading
the validator and concluding "this correctly rejects n > 1000" is not
verification — the checked-but-not-run version of that exact claim was wrong
more than once while this tooling was built, every time for a different
reason (a read that raised before the code that seemed to guard it, a
"passing" check that was measuring the wrong process's memory, a regex
sign-off that misfired on ordinary input). What caught each one was the
same move: **construct the failing input and run it.** Do that here, for
every bound and every format rule, before trusting the validator to reject
anything a generator might later produce.

## Reaching check

A bound in `problem.json` that no test attains is a hole — the suite claims
a limit it never actually tests. Confirm every declared bound is hit,
per group:

```bash
./validator --testset tests --group g1 --testOverviewLogFileName g1-overview.log < tests/g1/01.in
# repeat per test, or loop over the group; then inspect the log for any
# bound whose "hit" side never appears
```

Read the log rather than assuming; a bound that is declared but never
reached in any test is exactly the shape of `flags.py`'s `test-weakness`
kind — record it there if you find one:

```python
from tools import flags
flags.append(problem_dir, phase="prepare-tests", severity="medium",
              kind="test-weakness",
              what="g1's n <= 6 bound is never attained by any test in tests/g1/",
              assumed="added gen-max.exe --n=6 to close it",
              changes_if_wrong="g1's test set")
```

## Samples last

2–3 tests, small enough to trace by hand, chosen to exercise the *interesting*
rule in the problem rather than its trivial path — the case that actually
distinguishes a correct solution from a plausible wrong one, not just "n=3,
nothing special happens". Produce them the same way as every other test: the
model solution plus the checker. **Never hand-compute a sample's expected
output** — a wrong sample is the most expensive error a package can carry,
because it looks authoritative, contradicts the real tests, and a contestant
finds it before the setter does.

Once samples exist, hand back to `writing-statements` to wire them in with
`\exmpfile` and write `\Explanation` — that skill owns the prose, this one
owns the data behind it.

## Done means

- Every test validates under its own `--group` — not just "the validator
  passes on this file", but passed with the specific group flag that test is
  supposed to belong to.
- Every declared bound, global and per-subtask, is reached by some test.

**REQUIRED:** `superpowers:verification-before-completion` before reporting
either claim. Show the commands that produced the evidence — the validator
invocations per group and the reaching-check log excerpt — not an assertion
that they were run.

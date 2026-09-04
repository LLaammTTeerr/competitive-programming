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
| Auditing a finished package end to end — statement ambiguity, assumed definitions, unproven solution steps, no new phase to run | `competitive-programming:reviewing-problems` |
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

**The working directory stays `$PLUGIN_ROOT` for everything below.** That
is the one `cd` in this file, and nothing later moves you. `python3 -m
tools.*` requires it (see above) and takes `$PROBLEM` as an argument;
every other command — compiling `validator.cpp` and `gen-*.cpp`, running
the validator over test files, writing `files/` and `tests/` — names
`$PROBLEM` explicitly in its paths, `"$PROBLEM/files/validator"` and
`"$PROBLEM/tests/g1/01.in"` rather than `./validator` and `tests/g1/01.in`.
Every command block below is written that way and is runnable as-is from
wherever you are. Do not rely on whatever directory the previous command
left you in, and do not silently `cd "$PROBLEM"` instead — a half-relative
file is how a command that "worked when I ran it" fails for the next
reader.

Then **read `$TESTLIB/docs/usage-guide.md` for the API and `$TESTLIB/plan.md`
for known defects** before writing a line of `validator.cpp`, `check.cpp`, or
any `gen-*.cpp`.

No testlib API is reproduced in this file, and that is deliberate: the guide
is 902 lines and versioned against the exact header the pipeline compiles
against, so a paraphrased method signature goes stale the moment a bug in
testlib is fixed upstream. This file carries only what the guide does not —
subtask binding, ordering doctrine, and the traps below, curated from the
fork's own audit rather than duplicated from it.

Compile everything the same way — with `$PROBLEM` spelled out on both
sides, since the working directory is `$PLUGIN_ROOT`, not the problem.
**`validator.cpp` lives in `$PROBLEM/files/`, not `$PROBLEM/`** — confirmed
against `tools/package_status.py`'s own `validator` phase check
(`files / "validator.cpp"`) and against the in-repo fixture
(`tools/tests/fixtures/mini/files/validator.cpp`).
A validator built at `$PROBLEM/validator.cpp` compiles and runs, but
`package_status` will never see it as done — it checks one specific path,
not "a validator exists somewhere in this directory":

```bash
g++ -std=c++17 -O2 -Wpedantic -Werror -I"$TESTLIB" \
    "$PROBLEM/files/validator.cpp" -o "$PROBLEM/files/validator"
```

No `-I"$PROBLEM/files"` is needed here, and none should be added: with
`validator.cpp` and the generated `constraints.h` both in `$PROBLEM/files/`,
`#include "constraints.h"` resolves against the *including file's own*
directory — which already is `files/` — with no extra include path
required. (An earlier version of this section put the validator at
`$PROBLEM/` and, from that wrong premise, argued `-I"$PROBLEM/files"` was
required to reach `constraints.h` from there — that reasoning no longer
applies now that the validator and the header are colocated.)

Never `-ffast-math` — testlib detects it at runtime and aborts.

## Two things about the pipeline, stated up front

**Both IO modes are supported, and the test-data tools are the same in
either.** `problem.json`'s `io.input` / `io.output` are either the sentinels
`"stdin"` / `"stdout"` or a pair of bare filenames — file-based IO
(`flight.inp` / `flight.out`, the shape most VOI-style packages use) runs
end to end. `problem_meta.py` validates the pair at load and refuses a path
separator, a dot-segment, or the two names being equal, so anything that
reaches the sandbox is a plain filename inside its working directory.

What that does **not** change is everything this skill builds:

- **Generators and validators are unaffected.** They are stdin/stdout
  testlib tools in both modes — a generator writes the test to stdout, a
  validator reads it from stdin — and *nothing in `tools/` ever executes
  either one* (`run_matrix.py`'s only subprocesses are `g++`, `isolate`,
  the checker, and `git`). You run them yourself, exactly as the commands
  below show, and the redirections below are correct for a file-IO problem
  without a single change.
- **The checker already takes three file paths** — `checker <input>
  <output> <answer>` — which is testlib's interface regardless of how the
  solution obtained its output. `run_matrix.py` hands it paths it has
  already copied out of the sandbox, so a stock checker (`wcmp`, `ncmp`,
  `rcmp6`) is the same choice in both modes.
- **The solution is the only thing that differs**: it opens `io.input` and
  `io.output` by relative name in its working directory, which the driver
  arranges (`--chdir` into the one writable mount, the test staged there
  under `io.input`). A model solution that writes to stdout in a file-IO
  package makes `run_matrix.py` refuse outright rather than bank an empty
  answer file, and any *other* solution that writes the wrong filename gets
  the verdict `NO_OUTPUT` — see `validating-solutions`.
- **The statement must agree.** `tools/drift_check.py` compares the
  vnolymp `input =` / `output =` keys against `problem.json`, the same way
  it compares bounds; a statement promising `flight.inp` while
  `problem.json` says `stdin` is reported as drift.

**Every *solution* run is measured under `ioi/isolate`**, not a bare
`fork`/`exec`. There is no fallback runner, and `run_matrix.py` refuses to
start rather than silently falling back to something unsandboxed.
Generators, validators and checkers are **not** sandboxed — nothing in
`tools/` executes a generator at all, and you run them directly, as
yourself, exactly as the commands below show. Do not assume a generator
run carries any of the sandbox's guarantees about time, memory, or what it
may touch on this machine.

If `isolate --version` fails, this machine needs: `isolate` on `PATH`
(<https://github.com/ioi/isolate>), a system `isolate` user with
`isolate:200000:65536` registered in `/etc/subuid` and `/etc/subgid`, and
`systemctl enable --now isolate.service` so the cgroup keeper is running.
That setup is a one-time machine concern, not a per-problem one, and it
only blocks `validating-solutions`, not the work in this skill.

Two consequences worth internalizing before writing any timing-sensitive
code, and if these ever disagree with what you observe, `tools/matrix_core.py`'s
`compute_limits` and `classify` are the single source of truth, not this
paragraph:

- **Timing is CPU time**, as isolate reports it, never wall clock — far
  less sensitive to what else is running on the box. `TL = max(2 × t_main,
  1000 ms floor)`, rounded up to the nearest 500 ms; the sandbox kills at
  `2 × TL`. A result exactly at `TL` is accepted — the comparison is
  strictly-greater — so the band is `(TL, 2×TL]`, open at `TL` and closed at
  `2×TL`; only a result strictly over `TL` and up through `2×TL` is flagged
  as `timing-band` and never given a pass/fail verdict — it is a coin flip
  on different hardware, not a number to argue with.
- **Memory is measured by the kernel**, not polled. ML is isolate's own
  `max-rss` for the child strictly over `memory_mb`, or a `cg-oom-killed`
  from the cgroup — whose `--cg-mem` cap sits a fixed 256 MB *above*
  `memory_mb`, because on cgroup v2 a solution's dirty output pages are
  charged to it until written back. None of that reasoning belongs in a
  generator or validator you write; it lives entirely in `run_matrix.py`.

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
numbers within `1e-6` **absolute *or* relative** error — its own `setName`
says "max absolute or relative error", and `testlib.h`'s `doubleCompare`
accepts a value that clears *either* test, not both; it is emphatically not
"6 significant digits", which would be a relative-only rule. The natural
choice for a float answer, and the one to name in the statement verbatim so
the promised tolerance matches the enforced one),
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
- **`ensure(cond)` takes exactly one argument.** `ensure(cond, "message")` is
  a compile error (`macro 'ensure' passed 2 arguments, but takes just 1`) —
  confirmed by compiling it. Use `ensuref(cond, fmt, ...)` if you want a
  custom message; `ensure` always builds its own from the condition text.

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

**Read `references/test-generation.md` before designing the families** — it
carries the design doctrine the family names alone do not: the kill policy
for OI-style subtasks versus ICPC-style, subtask separation, parameter
saturation with `rnd.wnext`, the sizes at which each naive complexity class
actually dies, the shape catalogue, how rare corner cases should be, and the
multi-test `T` policy.

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
"$PROBLEM/files/validator" --testset tests --group g1 < "$PROBLEM/tests/g1/01.in"
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
printf '1001 5\n' | "$PROBLEM/files/validator" --testset tests --group g1
echo "exit: $?"   # expect nonzero — g1 caps n at 1000
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
a limit it never actually tests. Confirm every declared bound is hit, per
group — **with one log file per test, never a single shared log for the
whole group.**

`--testOverviewLogFileName` opens its target with `"wb"` (confirmed against
`testlib.h`'s own handling of that option): every invocation **truncates**
the file rather than appending to it. Loop several tests over the same log
path — the shape the previous version of this section itself showed — and
only the *last* invocation's hits survive; every earlier test's contribution
is silently overwritten, not merged. The result still looks clean (exit 0,
a plausible-looking log with some hits in it), not obviously broken, which
is what makes this dangerous rather than merely wrong: a group where every
bound really is reached, but reached by different tests, reads back as
"most bounds unreached" — indistinguishable, from the log alone, from a
genuinely weak suite.

```bash
rm -rf "$PROBLEM/.reach-g1" && mkdir -p "$PROBLEM/.reach-g1"
i=0
ok=1
for f in "$PROBLEM"/tests/g1/*.in; do
    i=$((i+1))
    "$PROBLEM/files/validator" --testset tests --group g1 \
        --testOverviewLogFileName "$PROBLEM/.reach-g1/$i.log" < "$f" \
        || { echo "validator REJECTED $f" >&2; ok=0; }
done
# A rejected test leaves an EMPTY log, and an empty log contributes nothing to
# the union below — which reads back as "that bound is unreached". Skipping
# this check manufactures the exact false finding this section exists to
# prevent, so fix every rejection before reading the union at all.
[ "$ok" = 1 ] || echo "UNION IS NOT EVIDENCE — fix the rejections first" >&2
# union across every per-test log, not just the last one written
cat "$PROBLEM"/.reach-g1/*.log | grep -E '": (min|max)-value-hit' | sort -u
rm -rf "$PROBLEM/.reach-g1"   # scratch output, not a package artifact
```

A bound whose `min-value-hit` or `max-value-hit` line never appears
**anywhere in the union** — not merely absent from the last test's log —
is genuinely unreached. Repeat per group.

**Even fixed this way, it only sees bounds read as numbers.** A `readInt` / `readLong` /
`readDouble` with a min and max registers `constant-bounds` plus a
`min-value-hit` / `max-value-hit` line — that is what makes the log
meaningful. A string read with `readToken(pattern, "A")` or `readLine`
registers only a bare `variable "A"` line, with no min, no max, and no hit
tracking at all, because the bound (a length, checked against the pattern
or an explicit `A.size()` check) was never expressed to testlib as a
number. Confirmed against a real validator: a length-bounded
`readToken("[a-z]{1,20}", "A")`, run through `--testOverviewLogFileName`,
produces exactly `variable "A"` and nothing else — exit 0, clean-looking
log, checking nothing. This is a common bound shape — a length-bounded
string, `1 <= |A| <= 20` — and the reaching check silently does nothing
for it, and a clean run reads as "nothing to report" when the
truth is "this mechanism cannot see this bound".

**The same blindness applies to a subtask-tightened numeric bound enforced
via `ensure()`** — exactly the pattern the Validator section above
recommends (`if (validator.group() == "g1") ensure(n <= G1_N_MAX);`).
`n` itself is still read once, against the *global* range, for the
hit-tracker's bookkeeping — so `g1`'s tightened `n <= G1_N_MAX` never
registers its own `max-value-hit`; only the (usually uninteresting) global
max does. Confirmed empirically: a group whose every test genuinely reaches
its subtask-tightened maximum still shows no `max-value-hit` line for that
variable in the union above. `ensure()`-tightened bounds are the standard
way this pipeline expresses subtask bounds, not an edge case, so treat
every such bound as belonging to the fallback check below by default,
rather than trusting a hit-tracker line that will never appear for it.

For any length (or otherwise non-numeric) bound, fall back to inspecting
the tests directly — confirm the minimum and maximum are each attained in
each group, e.g. (assuming `A` is the sole token on line 1 of each test,
adjust the field/line selector to match your own format):

```bash
awk 'FNR==1{print length($1)}' "$PROBLEM"/tests/g1/*.in | sort -n | sed -n '1p;$p'
# first line is the shortest value in the group, second the longest;
# compare both against the declared bound by hand
```

Read the log (or the fallback check's output) rather than assuming; a
bound that is declared but never reached in any test is exactly the shape
of `flags.py`'s `test-weakness` kind — record it there if you find one:

```python
# run from $PLUGIN_ROOT; pass the same absolute path $PROBLEM holds
from tools import flags
flags.append("/absolute/path/to/problem", phase="prepare-tests", severity="medium",
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

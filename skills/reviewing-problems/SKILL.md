---
name: reviewing-problems
description: >
  Use when auditing a competitive programming problem package before it
  ships — review this problem, audit the package, is this problem ready, is
  the statement ambiguous, check my statement. Triggers on statement
  ambiguity, assumed definitions, unproven algorithm invariant, checker or
  validator disagreeing with the stated format, package audit, flags.json.
  This is not /code-review, which audits a diff — this audits a finished
  directory on disk, with no git history involved at all. Use
  competitive-programming:validating-solutions instead to attack an existing
  test suite with deliberately-wrong solutions.
---

# Reviewing problems

Mission: an end-to-end audit of a problem package, split into two halves on
purpose. The mechanical half — constraint drift, incomplete phases, orphan
solutions, matrix holes, a stale generated header, a declared sample that
doesn't exist on disk — is a program's job, already written, and this skill
never redoes it by hand. The judgement half — is any sentence in the
statement readable two ways, does a term get used as though the reader
already knows it, does an `@algorithm` comment claim an invariant with no
argument behind it, does the checker actually match what the statement
promises, is every declared bound actually attained by some test — is what
this skill exists for, because no tool can do it.

## Am I the right skill?

Routing happens before a skill loads, so a description cannot ask a
question. If the request plausibly means one of these instead, **ask before
doing anything** — one question, options being each neighbour and "both, in
this order".

| If it's really about | Use |
|---|---|
| A diff, a PR, a set of commits | `/code-review` — that audits **changed lines**, with a base and a head SHA; this skill has no notion of a diff at all, only a directory on disk that may never have touched git |
| Is my test suite strong enough against a zoo of deliberately-wrong solutions | `competitive-programming:validating-solutions` |
| A finished idea that needs the whole pipeline sequenced, with gates | `competitive-programming:creating-problems` — **Stage 2, not built yet.** Say so and stop; do not attempt the handoff. |

The plugin ships seven skills: `solving-problems`, `running-contests`,
`preparing-tests`, `validating-solutions`, `writing-statements`,
`shaping-problems`, `reviewing-problems`. `creating-problems` above is
**not among them** — it cannot be invoked. If the request really belongs to
it, say that it is not built yet and stop, rather than offering a handoff
that will fail; do not silently sequence this skill after the others
yourself either.

Ask only when genuinely ambiguous. **"Review this problem before I ship it"
is not ambiguous — that's here. "Review my last three commits" is** — that's
`/code-review`, and the difference is not cosmetic: `/code-review` walks a
diff between two SHAs, and this skill has nothing to diff against — it reads
the package as it sits on disk, whether or not it has ever been committed.

## Bootstrap

`$BASE` is not an environment variable the harness sets — it is not exported
into a shell, only into MCP config. What you actually have is the line **"Base
directory for this skill" printed in this skill's own invocation preamble.
Substitute that literal path for `BASE` below:

```bash
BASE="<the path from this skill's own 'Base directory for this skill' line>"
PLUGIN_ROOT="$BASE/../.."
PROBLEM="<absolute path to the problem directory you are reviewing>"
TESTLIB="$(bash "$PLUGIN_ROOT/tools/bootstrap_testlib.sh")"
cd "$PLUGIN_ROOT"
```

Every `python3 -m tools.*` command below is a module inside `tools/`, which
is only importable with `PLUGIN_ROOT` as the working directory — `cd` there
first, or every invocation fails with `ModuleNotFoundError: No module named
'tools'` before it does anything. **The working directory stays
`$PLUGIN_ROOT` for everything below.** `$PROBLEM` is passed as an argument
to every command, never `cd`'d into.

## Run the mechanical half first — do not redo it by hand

```bash
python3 -m tools.review_checks "$PROBLEM" "$PROBLEM/<name>.tex" "$TESTLIB"
```

This reports constraint drift (`problem.json` vs the `.tex` vs
`constraints.h`), an incomplete phase, an orphan solution file the scan
never picked up, matrix holes and mismatches, a stale generated
`constraints.h`, and a sample declared in `problem.json` whose `.in`/`.a`
files are missing on disk. **Exit 1 means findings; read them, fix what they
name, and re-run until exit 0.** Do not re-derive any of this by reading
`problem.json` and the `.tex` side by side yourself — the tool exists
precisely because that comparison is mechanical, and hand-checking it a
second time spends effort on a question already answered while leaving less
attention for the half a tool genuinely cannot do.

## The judgement half — this is what the skill is for

Five classes. None of them can be answered by a diff, a schema check, or a
string comparison — each one requires reading the prose or the code the way
a contestant, or the compiler, actually will.

### 1. Statement ambiguity

Any sentence with two readings. Read every constraint, every I/O
description, every rule about ties or edge cases, and ask: is there a second
legitimate parse of this sentence that a careful contestant could land on?
If yes, that is a finding regardless of whether the intended reading is
"obvious" to whoever wrote it — obviousness to the author is exactly what
this class is immune to (see the next section).

### 2. Assumed definitions

A term used as though the reader already knows it, with no definition
anywhere in the statement. **The live example, and it must be treated as a
real defect, not a hypothetical:** `flight`'s own constraint line says

> một trong hai xâu có thể là **xâu con** của xâu còn lại

`xâu con` reads as *substring* (contiguous) to most Vietnamese contestants
and as *subsequence* (not necessarily contiguous) to some — the two
readings disagree on whether `"101"` is a `xâu con` of `"1a0a1"`-shaped
inputs in the general sense, and the unambiguous phrasing is `xâu con liên
tiếp`. It is **not fatal** in `flight`'s case — the body of the statement
defines the win condition precisely via `t_A`, the first index at which `A`
occurs, so a careful reader resolves the ambiguity from context even though
the constraint line alone does not settle it. But it **survived its own
author's verification pass and would have shipped** unflagged. State this
plainly when reviewing: this class of defect is invisible to whoever wrote
the statement, because they already know which reading they meant and
cannot see the sentence the way a first-time reader does. That is exactly
why this skill runs with fresh context rather than inline — see below.

### 3. Unproven solution steps

An `@algorithm` header comment (the metadata block `validating-solutions`
reads via `scan_solutions`) that asserts an invariant with no argument
behind it — "maintains the shortest prefix such that..." with nothing
showing why that prefix stays shortest across the update it claims to
handle. A comment that states a conclusion without the reasoning that gets
there is not a proof, and a solution can be correct by accident while its
own justification is false — which means the justification cannot be
trusted to guard against the next edit.

### 4. Checker/validator disagreement with the stated format

The statement promises two reals to `1e-6` absolute error but
`problem.json`'s checker is `wcmp` (bare token compare, no numeric
tolerance at all) instead of `rcmp6`; or the validator's `readInt`/`readToken`
bounds accept an input shape the statement's prose explicitly forbids. This
is a three-way comparison — statement prose, `problem.json`'s declared
checker/constraints, and what the validator or checker actually enforces in
code — and the mechanical half only checks two of those three against each
other (`drift_check` compares `problem.json` to the `.tex`); it does not
read English or Vietnamese prose to see whether `wcmp` is the wrong stock
checker for a problem that promises a numeric tolerance.

### 5. Unreached bounds

A declared bound that no test actually attains — the suite claims a limit it
never tests. `review_checks` does not check this; it is a hole in an
*earlier* phase (`preparing-tests`'s own reaching check) that this audit
re-verifies rather than trusting was done. Re-run the same mechanism
`preparing-tests` documents, per group, instead of assuming it was run
correctly the first time:

```bash
"$PROBLEM/validator" --testset tests --group g1 \
    --testOverviewLogFileName "$PROBLEM/g1-overview.log" < "$PROBLEM/tests/g1/01.in"
# repeat for every test in the group (or loop over the group), then read
# the log for any declared bound whose min-value-hit / max-value-hit line
# never appears
```

**Known limitation, inherited from `preparing-tests`'s own dogfood
finding:** this only sees bounds read as *numbers* — `readInt`/`readLong`/
`readDouble` with an explicit min/max register a hit line; a length bound
expressed via `readToken(pattern, "A")` (`flight`'s own `1 <= |A| <= 20`
shape) registers only a bare `variable "A"` line with no hit tracking at
all, so a clean log for that variable means "this mechanism cannot see this
bound," not "nothing to report." For any such bound, inspect the tests
directly instead:

```bash
awk 'FNR==1{print length($1)}' "$PROBLEM"/tests/g1/*.in | sort -n | sed -n '1p;$p'
# first line is the shortest value in the group, second the longest;
# compare both against the declared bound by hand
```

A bound that turns out unreached is a `test-weakness` flag — hand it back to
`preparing-tests` for a test that closes it; this audit records the gap, it
does not grow the test suite itself.

## Run as a subagent with fresh context, not inline

**Invoke `superpowers:requesting-code-review`** for the *principle*, not its
mechanism: that skill's own protocol starts from `BASE_SHA`/`HEAD_SHA` and a
`git diff`, which this skill has nothing to supply — a problem package may
never have touched git at all, and `## Am I the right skill?` above says so
directly. Take from it only what actually transfers: **dispatch a fresh
subagent rather than reviewing inline.** The dispatch this skill needs has
no diff range in it at all — hand the subagent the problem directory path,
the statement path, and the five judgement classes above, and let it read
the package the way a contestant would,
with none of the context that produced it. This is not optional convenience
— it is the whole reason this skill exists as a separate step rather than a
final read-through by whoever just finished writing the statement. A
reviewer that inherited the assumptions of the agent that wrote the
statement **cannot see the assumed definition**: the `xâu con` example above
survived exactly this — its own author's verification pass — because the
author already knew which reading was meant and read the sentence through
that knowledge rather than against it. Dispatching with fresh context is
what makes the difference between a rubber-stamp and a review.

## Recording findings

**Mechanical findings it fixes and re-runs** — go back to `review_checks`,
fix what it named, run it again until exit 0. **Judgement calls it flags**,
through `tools/flags.py`:

```python
# run from $PLUGIN_ROOT; pass the same absolute path $PROBLEM holds
from tools import flags
flags.append(
    "/absolute/path/to/problem", phase="review", severity="high",
    kind="statement-ambiguity",
    what="constraint line uses 'xâu con', readable as substring or "
         "subsequence; body defines occurrence precisely via t_A so it "
         "is not fatal, but the line itself is not self-disambiguating",
    assumed="left as-is because the body resolves it; flagged rather than "
            "silently edited since changing constraint prose is a "
            "writing-statements decision",
    changes_if_wrong="the constraint itemize line in the .tex, and any "
                      "contestant reading that relied on the ambiguous "
                      "phrase without reaching the t_A definition",
)
```

`flags.py` has no CLI — `python3 -m tools.flags` builds and exits with no
output and nothing written. The Python snippet above is the only documented
way to record a flag; do not invoke the module directly and assume it did
anything.

**The valid kinds are a closed set of eight**, confirmed against the source
rather than paraphrased — `flags.append` raises `FlagError` on anything
else:

```bash
python3 -c "from tools.flags import KIND_PREFIX; print(sorted(KIND_PREFIX))"
```

```
['algorithm-choice', 'checker-choice', 'constraint-drift', 'review-judgement', 'sample-choice', 'statement-ambiguity', 'test-weakness', 'timing-band']
```

The two this skill reaches for most are `statement-ambiguity` (classes 1 and
2 above) and `review-judgement` (class 3, and anything else that doesn't fit
one of the other seven kinds more precisely) — but pick whichever kind
actually names the finding rather than defaulting to these two on reflex:
class 4's checker/validator disagreement is usually `checker-choice`, and
class 5's unreached bound is `test-weakness`, the same kind
`preparing-tests` itself uses for the identical finding.

**Every flag needs `changes_if_wrong` filled in** — `flags.append` rejects a
blank one. That field is what prices an interruption: it is the answer to
"if this judgement call turns out to be wrong, what has to change?", written
down *before* anyone decides whether chasing it now is worth interrupting
the pipeline for.

## The one hard stop

An **unresolvable HIGH statement ambiguity** — a sentence with two
legitimate readings that nothing later in the statement resolves, unlike the
`xâu con` case where `t_A` settles it. That is the one finding this skill
does not flag and continue past: stop, and get a human decision on the
correct reading before doing anything else, because every other artifact
downstream (validator, checker, model solution, tests) is built against
whichever reading gets picked, and building against the wrong one wastes
all of it. **Everything else flags and continues** — an assumed definition
the body resolves, an unproven `@algorithm` step, a checker/validator
disagreement — none of those blocks the audit from finishing; they go in
`flags.json` with `changes_if_wrong` populated and the review moves on.

## Done means

- `python3 -m tools.review_checks "$PROBLEM" "$PROBLEM/<name>.tex" "$TESTLIB"`
  exits 0 — no mechanical findings remain.
- Every judgement finding from the five classes above is either fixed
  directly (and the mechanical check re-run to confirm nothing regressed)
  or recorded in `flags.json` with `changes_if_wrong` populated.
- No unresolved HIGH statement ambiguity remains — either it was resolved,
  or the hard stop above is still in effect and the audit is not done.

**Invoke `superpowers:verification-before-completion`** before reporting
either claim: `review_checks`'s own exit code is the evidence for the first,
reading `flags.json` back (not recalling what was written) is the evidence
for the second — "I fixed the ambiguity" is not a substitute for re-running
`review_checks` and reading its exit code.

---
name: creating-problems
description: >
  Use when creating a competitive programming problem end to end — from an
  idea, finished or half-formed, to a Polygon-ready package with a
  statement, tests, a model solution, and machine-readable evidence the
  package is ready to ship. Triggers on create a problem, prepare a full
  problem package, set a problem end to end, take this idea to a Polygon
  package, run the whole problem-setting pipeline. This is the umbrella
  over shaping-problems, preparing-tests, validating-solutions,
  writing-statements, and reviewing-problems: whenever a request spans two
  of those five — "build this from scratch", "take this idea all the way
  through" — this skill is the answer, not any one sibling.
---

# Creating problems

Mission: sequence the whole problem-setting pipeline (spec §7) from an idea
to a package `reviewing-problems` signs off on, owning the two things no
sibling owns on its own — the gate model (spec §6) and the loop-back edges
between phases. It does none of the phase work itself: `shaping-problems`
picks the numbers, `preparing-tests` builds the test data,
`validating-solutions` attacks it, `writing-statements` writes the prose,
`reviewing-problems` audits the result. This skill decides *which phase
runs next*, dispatches it, and reacts to what it reports back.

## Am I the right skill?

Routing happens before a skill loads, so a description cannot ask a
question. If the request plausibly means only one phase, use that sibling
directly rather than paying for the whole pipeline:

| If it's really about | Use |
|---|---|
| Only the numbers — is this problem original, what `N`, what subtask ladder, no test data or prose in view yet | `competitive-programming:shaping-problems` |
| Only the test data — checker, validator, generators, sample selection, for a `problem.json` that already exists | `competitive-programming:preparing-tests` |
| Only attacking an existing suite — the zoo, the invocation matrix, is it strong enough | `competitive-programming:validating-solutions` |
| Only the prose — story, `\InputFile`, `\Constraints`, `\Examples`, translating an existing statement | `competitive-programming:writing-statements` |
| Only auditing a finished package, no new phase to run | `competitive-programming:reviewing-problems` |
| Solving a problem yourself, not setting one | `competitive-programming:solving-problems` |

**"Both" already has a name: this skill.** A request that names two of the
five above in one breath — "take this idea from nothing to a Polygon
package", "build a problem and make sure the tests are strong" — is not an
ambiguity to ask about; it is the definition of what this skill sequences.
Proceed directly rather than asking which sibling was meant. Ask only when
the request is genuinely a single phase dressed up in pipeline language —
"is my test suite strong enough" is `validating-solutions` alone, not this
skill, even though the word "suite" could in principle mean the whole
package.

## Bootstrap

`$BASE` is not an environment variable the harness sets — it is not exported
into a shell, only into MCP config. What you actually have is the line **"Base
directory for this skill" printed in this skill's own invocation preamble.
Substitute that literal path for `BASE` below:

```bash
BASE="<the path from this skill's own 'Base directory for this skill' line>"
PLUGIN_ROOT="$BASE/../.."
PROBLEM="<absolute path to the problem directory you are creating>"
TESTLIB="$(bash "$PLUGIN_ROOT/tools/bootstrap_testlib.sh")"
cd "$PLUGIN_ROOT"
```

Every `python3 -m tools.*` command below is a module inside `tools/`, which
is only importable with `PLUGIN_ROOT` as the working directory — `cd` there
first, or every invocation fails with `ModuleNotFoundError: No module named
'tools'` before it does anything. **The working directory stays
`$PLUGIN_ROOT` for everything below.** `$PROBLEM` is passed as an argument
to every command, never `cd`'d into.

## Two entry modes, detected at G1

The first thing this skill does is work out which of two situations it is
in — before writing anything:

- **A finished idea and algorithm.** The human already knows the operation,
  roughly what `N` should be, and how the intended solution works. There is
  no design dialogue to run — prepare exactly that: write `problem.json`
  from the decisions already on the table (or dispatch a short subagent to
  do it) and move straight into the phase sequence below.
- **A half-idea.** "Something with strings and probability," a variant
  that's not yet been shown to separate an intended solution from a naive
  one, a story with no numbers behind it yet. **Delegate to
  `shaping-problems`** — it owns originality, the `N`-separation arithmetic,
  and the subtask ladder, and it invokes `superpowers:brainstorming` for the
  open-ended dialogue this skill has no business running itself.

Either way, the phase this mode-detection produces is **G1**, below.

## The gate model

**One blocking gate: G1 — idea, story, subtasks.** It is the only point in
the whole pipeline where this skill stops and waits for a human decision,
because it is the input, it is creative, and it produces `problem.json` —
the file every later phase treats as authoritative. Whether G1 is satisfied
by preparing a finished idea directly or by a full `shaping-problems` run,
it does not close until `problem.json` loads and validates.

**Everything after G1 flags and continues.** Algorithm choice, a borderline
TLE reclassified to `time-limit-exceeded-or-accepted`, stock-vs-custom
checker, sample selection, every reviewer judgement call — none of these
stop the pipeline. Each is recorded the moment it happens, through
`tools/flags.py`:

```python
# run from $PLUGIN_ROOT; pass the same absolute path $PROBLEM holds
from tools import flags
flags.append(
    "/absolute/path/to/problem", phase="<phase-name>", severity="medium",
    kind="algorithm-choice",
    what="...", assumed="...", changes_if_wrong="...",
)
```

Flags emit **inline, the moment the judgement call happens** — not batched
at the end of a phase — so a human watching the run in real time can
interrupt on any one of them without waiting for the phase to finish.
**`changes_if_wrong` is mandatory** (`flags.append` rejects a blank one):
that field is what makes flag-and-continue safe rather than reckless — it
prices the interruption *before* anyone decides whether to make one, rather
than after the fact. The eight valid `kind`s are a closed set, confirmed
against the source rather than guessed:

```bash
python3 -c "from tools.flags import KIND_PREFIX; print(sorted(KIND_PREFIX))"
```

```
['algorithm-choice', 'checker-choice', 'constraint-drift', 'review-judgement', 'sample-choice', 'statement-ambiguity', 'test-weakness', 'timing-band']
```

**The one exception.** An **unresolvable HIGH `statement-ambiguity`** stops
the pipeline — the only finding this skill does not flag past. Every other
judgement call invalidates at most the one phase it was made in; a genuine,
unresolved statement ambiguity invalidates the whole package, because
everything downstream (validator, checker, model solution, tests) gets
built against whichever reading was assumed. The cost of guessing wrong
there exceeds the cost of waiting, which is exactly backwards from every
other flag in the register. This is the same hard stop the arbiter
(`validating-solutions`) and the audit (`reviewing-problems`) both reach for
independently — this skill is what enforces it as an actual stop rather
than a note in a log nobody reads.

## The phase sequence, and its loop-back edges

```
  writing-statements ──> statement, NO \Examples yet
           │              (constraint table = single source of truth)
           v
  solving-problems  ──> sol-main.cpp                        [@tag main]
           │
           v
  preparing-tests   ──> checker              FIRST
                    ──> validator.cpp        SECOND
                    ──> gen-*.cpp            THIRD
                    ──> tests, grouped to subtasks
           │
           v
  validating-solutions ──> the zoo, each with @tag and @expect
                       ──> invocation matrix: every solution × every group
           │
           ├─ rejected solution SURVIVED ─────> suite too weak
           │                                    └─> back to preparing-tests
           │                                        (another generator family)
           ├─ accepted solutions DISAGREE ────> the arbiter
           │                                    ├─> back to solving-problems
           │                                    │   (sol-main was wrong)
           │                                    └─> STOP: unresolvable HIGH
           │                                        statement-ambiguity
           └─ every expectation met ──> pick 2–3 tiny samples
                                        └─> back to writing-statements
                                            for \Examples + \Explanation
```

The statement cannot finish first — `writing-statements` refuses to author
samples, because a sample is test data and test data comes from the
generator and the model solution, not from prose. So the pipeline visits
`writing-statements` twice: once to write everything except `\Examples`,
once at the end to wire in the samples `preparing-tests` picked. The
checker precedes the validator and the generators for the same reason
`preparing-tests` itself gives: "do these two solutions agree?" has no
answer without a checker, and generating a thousand tests before the
validator exists means learning about an illegal bound only after they're
all built.

Both loop-backs out of `validating-solutions` are real edges this skill
follows, not hypotheticals to describe and ignore: a surviving rejected
solution means the suite lied about being strong, so it goes back to
`preparing-tests` for a test that actually reaches the failure mode — never
patched by writing a different wrong solution. A disagreement between two
`accepted`-class solutions goes to the arbiter inside `validating-solutions`
first; only if the arbiter itself cannot decide — the behaviour genuinely
isn't defined anywhere in the statement — does it surface here as the one
hard stop above.

## Resumability

State lives entirely in files on disk — `problem.json`, `files/`,
`solutions/`, `tests/`, `invocation.json`, `flags.json`, the `.tex` — never
in a separate state file this skill maintains itself. Where the pipeline
currently stands is a question about what exists and parses, answered by:

```bash
python3 -m tools.package_status "$PROBLEM" "$TESTLIB"
```

Its first `[ ]` line, and the `next:` phase it prints, is where a
re-entering run resumes. This is why the phase list matters more than any
narrative of "what happened last time": **a pipeline that cannot restart
after an interruption is one nobody interrupts**, and the entire flag
register above is built on the premise that interrupting is safe. If
resuming required replaying a session transcript instead of reading the
directory, every flag's promise — "you can stop and look at this" — would
be false in practice, because stopping would cost the ability to resume.

## Phases run as subagents

**Invoke `superpowers:subagent-driven-development`.** Each phase in the
sequence above — the two `writing-statements` passes, `solving-problems`,
`preparing-tests`, `validating-solutions` — is dispatched as its own fresh
subagent, exactly as that skill's task loop describes: a subagent per unit
of work, a review after each one, no shared context bleeding from one phase
into the next. A review subagent fires after each phase and once more at
the end, in both cases via `reviewing-problems` — the mechanical half
(`tools/review_checks.py`) plus the five judgement classes, dispatched with
fresh context so it cannot inherit the assumptions of whichever phase just
ran.

## `superpowers:receiving-code-review` is load-bearing here, not decorative

A reviewer subagent will produce findings that are simply wrong — not
occasionally, as a matter of course, because it is reading a package with
fresh eyes and no access to the reasoning that produced it. In a pipeline
that fixes every mechanical-sounding finding without asking first, a
hallucinated constraint violation ("the validator accepts `n = 0` but the
statement says `n >= 1`" when it does not) would get a correct validator
"fixed" into a broken one, silently, because nothing in the loop stopped to
check whether the finding was true before acting on it. `receiving-code-review`'s
verify-before-implementing discipline is what stands between "a subagent
said so" and a change actually landing — apply it to every finding
`reviewing-problems` returns here, the same way `subagent-driven-development`
already applies it to its own task reviewers.

## `superpowers:writing-plans`, conditionally

The standard sequence above — one pass through each phase, the ordinary
loop-backs — needs no separate plan file; the sequence itself is the plan,
and `subagent-driven-development`'s task loop is enough structure. **Invoke
`superpowers:writing-plans`** only when a problem needs more than that: a
subtask ladder that doesn't decompose into the usual linear rungs, several
independent checker candidates that need comparing before one is chosen, a
statement that must be assembled into a multi-problem booklet alongside
others already in flight, or any other shape where the phase sequence
itself needs designing before it can be executed. Reach for it as an
exception, not a default — most problems fit the sequence above exactly as
drawn.

## Done means

```bash
python3 -m tools.package_status "$PROBLEM" "$TESTLIB"
```

reports `complete` (every phase `[x]`, no `next:` line), **and**

```bash
python3 -m tools.review_checks "$PROBLEM" "$PROBLEM/<name>.tex" "$TESTLIB"
```

exits 0. Both are required — `package_status` says every phase produced its
artifact, `review_checks` says the mechanical half of the audit found
nothing wrong across all of them at once (constraint drift, an orphan
solution, a matrix hole, a stale matrix (`invocation.json` no longer
describes the current package — re-run the matrix), a stale generated
header, a sample declared but missing on disk). Neither claim substitutes
for the other: a package can have every phase present and still drift, and
`review_checks` has nothing to check if a phase never ran.

**REQUIRED:** `superpowers:verification-before-completion` before reporting
either claim — run both commands and show their exit codes and output, not
a recollection of having run them earlier in the session.

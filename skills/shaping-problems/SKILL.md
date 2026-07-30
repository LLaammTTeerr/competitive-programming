---
name: shaping-problems
description: >
  Use when shaping a competitive programming problem idea into numbers: is
  this problem already known, what difficulty is intended, what N separates
  the intended solution from the naive one, and what subtask ladder pays for
  real partial insight rather than for typing. Triggers on problem idea, is
  this problem interesting, what constraints, choose N, pick N, subtask
  ladder, difficulty, partial scoring, is this problem already known. This
  owns the numbers; for the Vietnamese prose use
  competitive-programming:writing-statements, and for sequencing the whole
  pipeline with gates use competitive-programming:creating-problems instead.
---

# Shaping problems

Mission: turn an idea into `problem.json` — the one blocking gate in the
whole pipeline (spec §6). Four judgements, in order: is this problem already
known, what `N` separates the *intended* solution from the *naive* one, what
subtask ladder pays for distinct insight rather than for typing, and what
that adds up to as structured JSON. This skill owns the **numbers**. It does
not own prose (`writing-statements`) and it does not own open-ended dialogue
about what the problem even is (`superpowers:brainstorming`, which it
delegates to rather than competes with).

## Am I the right skill?

Routing happens before a skill loads, so a description cannot ask a
question. If the request plausibly means one of these instead, **ask before
doing anything** — one question, options being each neighbour and "both, in
this order".

| If it's really about | Use |
|---|---|
| The prose: story, `\InputFile`, `\Constraints` itemize, `\Examples` | `competitive-programming:writing-statements` |
| A finished idea that needs the whole pipeline sequenced, with gates | `competitive-programming:creating-problems` — **Stage 2, not built yet.** Say so and stop; do not attempt the handoff. |
| Solving this problem yourself — no shaping decision in play | `competitive-programming:solving-problems` |

The plugin ships six skills: `solving-problems`, `running-contests`,
`preparing-tests`, `validating-solutions`, `writing-statements`,
`shaping-problems`. `creating-problems` above is **not among them** — it
cannot be invoked. If the request really belongs to it, say that it is not
built yet and stop, rather than offering a handoff that will fail; do not
silently sequence the other skills yourself either.

Ask only when genuinely ambiguous. **"Help me pick N" is not ambiguous.
"Help me design a problem" is** — that could mean the numbers here, the
story in `writing-statements`, or the open-ended "I don't even have an idea
yet" that belongs to `superpowers:brainstorming`. When in doubt, ask which.

## Bootstrap

`$BASE` is not an environment variable the harness sets — it is not exported
into a shell, only into MCP config. What you actually have is the line **"Base
directory for this skill" printed in this skill's own invocation preamble.
Substitute that literal path for `BASE` below:

```bash
BASE="<the path from this skill's own 'Base directory for this skill' line>"
PLUGIN_ROOT="$BASE/../.."
PROBLEM="<absolute path to the problem directory you are shaping>"
cd "$PLUGIN_ROOT"
```

The only `tools/` command this skill runs is `python3 -m tools.package_status`
(Done means, below), and every `python3 -m tools.*` module is only importable
with `PLUGIN_ROOT` as the working directory — `cd` there first, or it fails
with `ModuleNotFoundError: No module named 'tools'` before it does anything.
**The working directory stays `$PLUGIN_ROOT` for the rest of this skill.**
`$PROBLEM` is passed as an argument, never `cd`'d into.

## The brainstorming override — state this or the two skills fight

`superpowers:brainstorming` hard-gates on presenting a design and prescribes
exactly **one** terminal action: invoke `writing-plans`, and no other skill.
That is correct in its own domain (an implementation plan) and wrong here.
**This skill's terminal state is a completed `problem.json` handed to
`creating-problems` — never `writing-plans`.** Say so explicitly the moment
`brainstorming` is invoked from inside this skill, or brainstorming's own
gate will try to route the finished design somewhere this pipeline never
goes.

- **Idea is vague** ("something with strings and probability", "a Penney's
  game variant, not sure what makes it interesting yet") — invoke
  `superpowers:brainstorming` for the dialogue, then apply the overridden
  terminal state above once it converges.
- **Idea already arrives finished** (a named operation, a rough size, a
  story already in mind) — skip `brainstorming` entirely. Running a dialogue
  skill on a decision that is already made produces transcript, not signal.

## Originality — before anything else

Before `N`, before subtasks: **is this already a known problem?** Strip the
flavor text and name the underlying operation in one sentence — "count
inversions after each swap", "shortest path with at most `k` free edges",
"first player to complete their pattern in a random coin sequence" — then
search *that sentence*, not the retold story, against what you or the setter
already know of Codeforces, AtCoder, and other archives.

A retelling of Penney's game with aeroplanes instead of coins is still
Penney's game, and **that is fine** — reusing a known core with a new skin is
a legitimate way to build a problem — as long as the setter knows it and
decides on purpose, rather than discovering it in review after the tests are
built. If the search turns up the same operation under the same constraints,
say so and let the human decide whether to proceed anyway, angle the
constraints differently, or pick a different idea. This is a flag
(spec §6), not the blocking gate — it does not stop the skill, but it must
be raised before the numbers below are chosen, because "already known" can
change which `N` is even interesting.

## Difficulty and the separation constraint

The core judgement, and it is arithmetic, not a vibe: choose `N` so the
**intended** solution fits inside the time limit and the **naive** one does
not.

Work the numbers at roughly 10⁸ operations/second. If the intended solution
is `O(n log n)` and the naive one is `O(n²)`, then at `n = 2·10⁵`:

- naive: `n² ≈ 4·10¹⁰` operations — around 400 s, wildly over any sane limit
- intended: `n log₂ n ≈ 2·10⁵ × 18 ≈ 3.6·10⁶` operations — a few milliseconds

That gap is the whole point of the constraint. Compare it against a
constraint that fails to separate: `n ≤ 2000` puts the same naive `O(n²)` at
`4·10⁶` operations — comfortably inside any time limit. Both solutions pass.
**A constraint that fails to separate the intended solution from the naive
one is the most common reason a problem is boring** — the contestant who
writes the naive solution passes anyway, and the insight the problem was
built to reward goes unrewarded. Pick `N` (and every other size parameter —
alphabet size, value range, query count) by first writing down the naive
complexity, the intended complexity, and checking the two land on opposite
sides of the time budget at the constraint you're about to declare — not by
picking a round number and hoping.

`limits.time_ms_published` in `problem.json` is this skill's proposal from
that arithmetic; `limits.time_ms_computed` is filled in later, once
`preparing-tests`/`validating-solutions` actually time the model solution
(spec §5) — shaping proposes the budget, it does not measure it.

## The subtask ladder

Each rung must pay for a **distinct insight**, not for typing. A rung that
only shrinks `n` without changing which algorithm clears it is a rung that
pays for patience — a setter who writes `g1: n ≤ 1000, g2: n ≤ 100000` where
the same `O(n log n)` sort passes both has built one subtask with a coffee
break in the middle, not two subtasks.

Worked example — `flight` (spec §4's own sample problem: two coin sequences
`A`, `B`, first one to complete its pattern in a random coin stream wins;
find the probability `A` wins):

| Subtask | Bound | What it actually admits |
|---|---|---|
| `g1` (40%) | `\|A\|, \|B\| ≤ 6` | Brute-force enumeration over coin sequences up to the point one pattern completes — at most `2^12` prefixes, trivial to enumerate directly. No automaton needed. |
| `g2` (60%) | `\|A\|, \|B\| ≤ 20` | The brute force's state space is now astronomically larger. Requires building the Aho–Corasick automaton over `{A, B}` and solving a linear system over its states for absorption probabilities. |

This ladder has **exactly one real rung** — `g1` rewards recognizing the
brute-force path exists at all, `g2` rewards building the automaton. That is
the right shape for a two-subtask problem, not a deficiency: a ladder is not
obligated to have more rungs than the problem has distinct insights, and
inventing a third rung here (say, `|A|, |B| ≤ 12`) would only interpolate
between the same two algorithms without rewarding anything new.

## What it hands over

A completed `problem.json` — the human never types JSON, this skill writes
it from the decisions made above. Changing a decision later means
**re-opening this gate, not editing the file directly**, because the file is
the record of the decision, not just its encoding.

Required shape (schema 1, validated by `tools/problem_meta.py`):

```jsonc
{
  "schema": 1,
  "name": "flight",
  "title": { "vi": "Chuyến bay đầu tiên" },
  "tags": ["probability", "strings", "automaton"],
  "limits": { "time_ms_published": 1000, "memory_mb": 256 },
  "io": { "input": "stdin", "output": "stdout" },
  "checker": { "kind": "stock", "name": "rcmp6" },
  "constraints": [
    { "id": "len_a", "expr": "1 \\le |A| \\le 20", "min": 1, "max": 20 },
    { "id": "len_b", "expr": "1 \\le |B| \\le 20", "min": 1, "max": 20 }
  ],
  "subtasks": [
    { "id": "g1", "points": 40,
      "bounds": { "len_a": {"max": 6}, "len_b": {"max": 6} },
      "constraints_text": ["|A|, |B| \\le 6"],
      "depends_on": [] },
    { "id": "g2", "points": 60,
      "bounds": {},
      "constraints_text": ["Không có ràng buộc gì thêm"],
      "depends_on": ["g1"] }
  ],
  "examples": []
}
```

Field notes, since a wrong shape here fails to load rather than fails
quietly:

- **`constraints`** is the *structured* form — `min`/`max` as JSON integers,
  never floats (`tools/gen_constraints_header.py` f-strings a bound straight
  into a C++ `static const long long`; a float like `0.5` silently truncates
  to `0`, after which the generated validator rejects every legal test).
  `expr` is the human-readable LaTeX-ish rendering of the same bound; it is
  never parsed, only displayed.
- **`subtasks[].bounds`** carries the same structured `min`/`max`, keyed by
  constraint `id`, narrowing (never widening) the global bound for that
  subtask — this is what `gen_constraints_header.py` compiles into
  `G1_LEN_A_MAX` and friends for the validator.
- **`subtasks[].constraints_text`** is the prose twin of `bounds` — it is
  what `writing-statements` renders into the subtask table in the `.tex`.
  Neither field can generate the other: a structured bound can't produce
  readable Vietnamese, and prose can't become a `constexpr`. Both are
  required, not either-or.
- **`points`** across all subtasks must sum to exactly 100.
- **`checker.kind`** is `"stock"` (name one of testlib's 21, e.g. `rcmp6` for
  a real-valued answer to 6 significant digits) unless the problem has
  multiple valid outputs, in which case `"custom"` — but that decision, and
  writing the custom checker, belongs to `preparing-tests`, not here; this
  skill only records which kind was chosen.

## Done means

`problem.json` loads and the `problem_json` phase reports done:

```bash
python3 -m tools.package_status "$PROBLEM"
```

Run for real against the `flight` example above, starting from `/tmp` (not
`$PLUGIN_ROOT`) and following Bootstrap's `BASE` → `PLUGIN_ROOT` → `cd`
exactly as written, to confirm the relative arithmetic resolves rather than
only reads correctly. First line of output:

```
[x] problem_json         loaded
```

The command's overall exit code is nonzero and `next:` names a later phase
(`statement`, then `model_solution`, and on) — expected, since this skill's
job ends at `problem_json`; everything after that line belongs to
`preparing-tests`, `validating-solutions`, and `writing-statements`'s second
pass, sequenced by `creating-problems`. Only the `problem_json` row is this
skill's own claim.

A `problem_json` phase of `[ ]` means `problem.json` failed to parse or
failed validation — read `tools/problem_meta.py`'s `ProblemMetaError`
message (printed in the `detail` column) to find which field, and fix
`problem.json` directly; there is no separate "shaping" state file to
reconcile against it.

Hand the directory to `creating-problems` once this phase is `[x]` — that
skill sequences everything downstream (`preparing-tests`,
`validating-solutions`, `writing-statements`'s `\Examples` pass) and owns the
flag register those phases write into.

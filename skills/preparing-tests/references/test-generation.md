# Test-generation doctrine

Design notes for [preparing-tests](../SKILL.md): what each file in a group is
*for*, before a line of `gen-*.cpp` is written. Load this when planning the
five generator families — it decides what the random, max-size and
structured-adversarial families are actually aimed at, and the tests script
is much cheaper to get right than to fix.

This is the design side. The verification side is the per-group `@expect`
matrix in `competitive-programming:validating-solutions`, which runs every
solution against every group and reports what the suite really does. Nothing
here is evidence; it is what to build so the matrix comes back the way you
intended.

## Kill policy by format

The question "must every wrong solution die?" has two answers, and picking
the wrong one ruins a package in a way that is hard to see afterwards.

**ICPC-style** — all-or-nothing, one verdict for the whole submission.
Every solution that is not the intended algorithm must fail somewhere in the
suite, and so must an intended algorithm implemented badly: an extra log
factor, a hopeless constant, `int` where the real bound needs `long long`.
There is no partial credit to protect, so there is no reason to leave a
slower class anywhere to stand.

**OI-style (subtasks)** — each group carries points, and a solution's score
is the sum of the groups it passes. Kill the naive solution *on the top
group*, and leave it scoring on the groups its insight actually pays for.
"Kill everything" is wrong here: a contestant who found the O(N log N)
observation but not the O(N) one is supposed to score for it, and a suite
that times them out everywhere has deleted the problem's whole middle. The
groups are the grading scheme; generating them all at full brutality
silently converts an OI problem into an ICPC one.

The consequence for the intended solution is the same asymmetry. On
ICPC-style, an intended solution with poor constants failing is a finding.
On OI-style, an intended solution that is slightly over budget should lose
the one or two most brutal files and keep the rest — so do not make every
file in the top group a maximal kill.

## Subtask separation

A group is a complexity boundary, not a range of smaller examples. Unless a
group deliberately contains an earlier one, no solution written for an
earlier group may score in a later group.

The leak is almost always undersized files rather than a wrong declared
bound. A group declared `n <= 1000000` whose generated files never exceed
`n = 5000` is solved by the O(N²) solution that was only meant to clear
`g1` — the group's declaration says one thing and its data says another,
and the declaration is not what runs. Push a later group's files to the
bound it declares: around `10^5` and up when the bound is `10^6`, with at
least one file exactly at `10^6`.

Apply the same reasoning to every parameter that drives time or memory, not
only to `n`. When `q`, `m`, the value magnitude, or a total-length quantity
also decides the cost, maxing `n` alone leaves the separation open on the
axis that mattered.

Then check it rather than reasoning about it: the `@expect` matrix already
runs each weaker solution against every group, and a weaker solution
declaring `g3=TL` that comes back `OK` is exactly this leak, reported
mechanically. Write the `@expect` rows from an observed run, as
`validating-solutions` requires, and the separation is checked for free.

## Parameter saturation

Within a group, most files should sit at **≥ 90% of every bound that
matters at once** — not 90% of one bound with the others incidental. A
uniformly random parameter essentially never lands near its maximum: it
clears the top 10% one time in ten, and across `k` independent bounds all
at once, one time in `10^k`. A group of fifty uniformly random files can
therefore contain no genuinely large case at all.

`rnd.wnext(from, to, type)` with `type > 0` returns the maximum of
`type + 1` independent draws, so the chance a draw misses the top 10% of
the range is `0.9^(type+1)`: `type = 4` still misses 59% of the time,
`type = 20` misses 11%, `type = 40` misses 1.4%. Bias in the tens, not in
the single digits, when the point of the file is to be large.

**Saturation is not the reaching check.** A group where every file sits at
98% of a bound never attains that bound, and the validator's
`--testOverviewLogFileName` union will correctly report it unreached. The
max-size family exists to hit each declared maximum exactly, at least once
per group; saturation decides what the *other* forty files do. Run the
per-test-log loop in [SKILL.md](../SKILL.md#reaching-check) — one log per
test, unioned — and treat its output as the answer, not this section.

## Brute-kill table

Rough sizes at which a naive solution stops being survivable, assuming
~10^8 simple operations per second and a 1 s budget.

Aim for roughly ten times the budget, not one. `TL` is
`max(2 × t_main, 1000 ms floor)` and the band `(TL, 2×TL]` is reported as
`timing-band` with no pass/fail verdict at all, so a naive solution has to
land past `2×TL` — more than four times the model solution's own time — to
be a decisive kill rather than a coin flip on the next machine.
`tools/matrix_core.py` is the source of truth for that arithmetic.

| Naive class | Kills at | Shape that makes it real |
|---|---|---|
| `O(N!)` | `N ≥ 13` | nothing prunes: no repeated values, no early exit |
| `O(2^N · N)` | `N ≥ 25` | no dominated items, so meet-in-middle gains nothing |
| `O(N³)` | `N ≥ 1000` | dense; `min(n, m)` large, not `10^6 × 1` |
| `O(N² log N)` | `N ≥ 10^4` | — |
| `O(N²)` | `N ≥ 3·10^4` | `N = 10^4` is one budget, i.e. inside the band |
| `O(N√N)` | `N ≥ 10^6` | — |
| `O(N · Q)` per-query scan | `N·Q ≥ 10^9` | maximise **total asked range length**, not `N` and `Q` alone |
| `O(N · maxA)` value DP | product `≥ 10^9` | large values, not many small ones |
| `O(N · d(A))` divisor loop | total divisors `≥ 10^9 / N` | highly composite values (`735134400` has 1344 divisors) |
| `O(depth)` per tree query | bamboo, `N ≥ 2·10^5` | query pairs far apart; see the tree note below |

## Shape catalogue

Random is one shape among many and it is rarely the adversarial one. Each
group wants a deliberate spread.

- **Trees** — bamboo (maximum depth), star (maximum degree), caterpillar
  (a spine with leaves, defeating both), random.
  A uniformly random labelled tree, the shape a Prüfer-sequence generator
  produces, has height `Θ(√N)`; a random recursive tree, where each node
  attaches to a uniformly random earlier node, has height `~log N`. Neither
  reaches worst-case depth, so **a bamboo is required either way** — do not
  assume a random tree is deep, and do not assume it is shallow.
- **Arrays and sequences** — sorted, reversed, all-equal, alternating,
  few-distinct, and random over a small value range.
- **Numbers** — highly composite values, primes, powers of two, and the
  declared maximum value.
- **Graphs** — dense at the bound, sparse at the bound, disconnected, and
  many small components, subject to whatever connectivity the statement
  actually promises.
- **Strings** — unary, period 2, and random over a small alphabet.

When a new problem introduces a shape not listed here, derive it the same
way: name the quantity the naive solution's cost depends on, and build the
input that maximises it.

## Corners present but rare

Every group carries a handful of files that hit corner cases — `n = 1`, all
values equal, an empty answer, the maximum possible answer — and no more
than a handful. Present, so a solution that forgot the corner is caught;
rare, so the group as a whole still measures the intended complexity.

Corner cases are small and fast, and a group that is mostly corners lets a
slower class survive it. Where a parameter switches between a cheap special
branch and the general expensive one, keep the volume on the expensive
branch and spend a few files on the cheap one.

## Multi-test `T` policy

When the input carries `T` test cases, `T` is another bound to saturate,
with one exception on OI-style problems.

**ICPC-style:** every file at maximum `T`. A corner case belongs *inside* a
maximal file as one of its cases, not as a file with a small `T`.

**OI-style (subtasks):** most files at `T` near its maximum, biased with
`rnd.wnext` as above — plus one file with a small `T` and a maximum-size
case in it. That file is what lets a solution slightly over budget per case
still score, which is the same partial-credit reasoning as the kill policy
above.

**Never invent a Σ-constraint the statement does not state.** If the
statement bounds only `T` and the per-case `n`, then every one of the `T`
cases may legally be maximal, and the suite should contain files where they
are. Quietly generating as though `Σn` were bounded produces a suite far
weaker than the declared bounds allow — and a validator generated from
`problem.json` will not object, because the constraint being respected was
never declared.

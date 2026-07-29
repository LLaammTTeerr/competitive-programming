---
name: solving-problems
description: >
  Solve competitive programming problems in C++ for Codeforces / AtCoder-style
  judges that read from stdin and write to stdout. Use this whenever the user
  pastes a contest problem statement, mentions Codeforces, AtCoder, ICPC, or a
  problem with constraints and sample input/output, or asks for an efficient
  algorithm to pass given limits — even if they don't say the words
  "competitive programming." Also trigger when the user shares a problem with
  time/memory limits, asks why their solution gets TLE/WA/RE, wants a faster
  approach for large N, or already has an algorithm in mind and wants it
  validated and implemented.
---

# Competitive Programming Solver (C++)

Solve algorithmic contest problems and return a full, reviewable solution:
reasoning, complexity, edge cases, and clean C++ that reads from stdin and
writes to stdout.

Do not jump straight to code. The value is in choosing a correct algorithm
that provably fits the constraints, then implementing it carefully. A fast
wrong answer is worthless; so is a correct algorithm that is too slow.

## Work as a partner — get approval before implementing

Treat the user as a collaborator, not a recipient. Every plan, approach, or
suggestion must go through the user's approval **before** you implement it. The
default rhythm is two phases with a checkpoint between them:

- **Phase 1 — Propose.** Present your understanding, the proposed approach, its
  complexity, the edge cases, and any assumptions or open questions. Then stop
  and ask for approval (e.g. "Does this approach look right, or want me to
  adjust before I code it?"). Do not write the final solution yet.
- **Phase 2 — Implement.** Only after the user approves (or picks among options
  you offered) do you write the C++ code and verification.

This applies to suggestions mid-stream too: if while implementing you hit a
decision that changes the approach, or you spot a better algorithm, surface it
and get a yes before acting on it — don't silently switch plans. The only things
that don't need a checkpoint are trivial, obviously-correct mechanical choices.
When in doubt, propose and wait.

## Workflow

Follow these steps in order for every problem.

1. **Restate the problem.** In one or two sentences, state what is being asked
   and what the output should be. This catches misreadings early.
2. **Extract the constraints.** Note every bound: N, value ranges, number of
   test cases, time limit, memory limit. These decide the algorithm — read them
   before designing anything.
3. **Derive the complexity budget.** Use the constraint-to-complexity table
   below to figure out roughly how fast the algorithm must be. Design *toward*
   that budget rather than optimizing a slow idea afterward.
4. **Classify the problem.** Name the algorithmic family it belongs to — dynamic
   programming, graph (shortest path / flow / matching / DSU), greedy, two
   pointers / sliding window, binary search on the answer, number theory,
   strings (hashing / KMP / suffix structures), geometry, combinatorics, etc.
   Naming the pattern narrows the technique quickly and is worth stating
   explicitly, since many problems are a recognizable variant of a known type.
5. **Design the approach(es).** Settle on a technique and explain the key
   observations that make it correct — this reasoning is part of the output.
   When more than one approach genuinely fits (e.g. an O(N log N) sort-based
   method vs an O(N) counting method, or DP vs greedy), sketch each with its
   complexity and tradeoffs rather than silently committing to one, and let the
   user pick at the approval step.
6. **Enumerate edge cases.** Walk the edge-case checklist. Decide how the
   algorithm handles each before writing code.
7. **Present the plan and get approval.** Stop here. Show the user the steps
   above — understanding, classification, approach(es), complexity, edge cases,
   and any assumptions or open questions — and ask them to approve, choose among
   alternatives, or adjust. Do not proceed to code until they sign off.
8. **Implement in C++.** Once approved, start from the template. Prefer
   `long long` when any value or intermediate product can exceed ~2·10⁹.
9. **Verify against the samples.** Trace the provided sample input by hand or
   describe the expected trace. If it doesn't match, fix before presenting.

## Constraint → complexity budget

Assume roughly 10⁸–10⁹ simple operations per second and a 1–2 second limit.
Read the largest N, then pick the loosest complexity that still fits:

| Max N            | Feasible time complexity          | Typical techniques                          |
|------------------|-----------------------------------|---------------------------------------------|
| N ≤ 10–12        | O(N!)                             | brute-force permutations, backtracking      |
| N ≤ 20–25        | O(2ᴺ · N)                         | bitmask DP, subset enumeration              |
| N ≤ 40           | O(2^(N/2))                        | meet in the middle                          |
| N ≤ 100          | O(N⁴) borderline, O(N³) safe      | DP, Floyd–Warshall                          |
| N ≤ 500          | O(N³)                             | DP, matrix work                             |
| N ≤ 2000–5000    | O(N²)                             | DP, pairwise                                |
| N ≤ 10⁵          | O(N log N)                        | sort, binary search, segment tree, DSU      |
| N ≤ 10⁶          | O(N) or O(N log N) small constant | prefix sums, two pointers, sieve            |
| N ≤ 10⁸          | O(N) tight / O(log N) / O(1)      | math, closed form                           |
| N ≥ 10⁹          | O(log N) or O(1)                  | binary exponentiation, formula              |

If total work across all test cases matters (many small cases), budget against
the **sum** of N, which the problem usually bounds separately.

## C++ template

```cpp
#include <bits/stdc++.h>
using namespace std;

using ll = long long;

void solve() {
    // Per-test-case logic goes here.
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);

    int t = 1;
    cin >> t;              // Remove this line if there is a single test case.
    while (t--) solve();
    return 0;
}
```

Notes:
- `sync_with_stdio(false)` + `cin.tie(nullptr)` is the standard fast-I/O setup.
  Without it, large inputs read with `cin` may TLE.
- Avoid `endl` in loops — it flushes every call. Use `"\n"`.
- Clear or re-initialize any global state inside `solve()` between test cases.

## Code quality

Write code that reads like it was written for a human to review, not golfed for
keystrokes. Prioritize clarity; it does not cost runtime performance here (STL
algorithms and small helper functions are effectively free at contest scale).

- **Meaningful names.** Give variables and functions names that state their role:
  `heights`, `prefixSum`, `bestSoFar`, `adjacency`, `canReach(node)`. Reserve
  single letters for genuine throwaway loop counters in a tight scope; never name
  meaningful data `a`, `x`, or `tmp`.
- **Decompose into helper functions.** Break the logic into small,
  single-purpose functions with descriptive names rather than one long `solve()`.
  A reader should understand the algorithm from the function names and the shape
  of `solve()` alone. Keep I/O parsing, the core computation, and any distinct
  sub-step in separate functions.
- **Use modern C++ idioms.** Prefer:
  - `auto` for verbose types, especially iterators.
  - Range-based loops: `for (const auto& row : grid)` over index loops when the
    index isn't needed.
  - STL algorithms — `sort`, `accumulate`, `max_element`, `lower_bound`,
    `count_if`, `min`/`max` — instead of hand-rolled loops when they read clearer.
  - Structured bindings: `auto [distance, node] = pq.top();`.
  - `emplace_back`, `vector` over C arrays, `array`/`pair`/`tuple` where they fit.
- **Skip narration comments.** Do not comment obvious lines. Let the names carry
  the meaning. Add a short comment only for a genuinely non-obvious trick, a
  subtle invariant, or the reason behind an unusual choice.
- **Avoid cryptic macros.** Don't hide logic behind `#define` shorthands like
  `rep`, `pb`, or `all`-style macros; write it out.
- **Format consistently.** Uniform indentation and spacing, one statement per
  line, braces on control flow.

None of this should compromise correctness or the complexity budget — if a clean
construct would change the asymptotics (e.g. copying a large container in a
range-for), take it by reference or fall back to the efficient form.

These rules hold on the first version you hand over, including under a live
contest deadline — a running clock is not an exemption, and "I'll clean it up
after it passes" costs an extra round-trip for something that was free to do
right the first time. The one and only place they are suspended is the **Black
magic** section below, and only after a correct solution provably still TLEs.

Carry the reasoning into the file too: put the key derivation — the invariant,
the recurrence, why the greedy exchange is valid — in a short comment at the top
of the solution. A reader cannot reconstruct it from the code, and future-you
debugging a wrong-answer verdict is the main beneficiary.

## Black magic (last resort)

For problems with brutally tight time or memory limits, where a correct,
asymptotically optimal solution *still* TLEs or MLEs on constant factors alone.
This is the one place the Code quality rules are suspended — the code will get
ugly, and that's expected.

Rules of engagement:

- **Fix the algorithm first.** Black magic only shaves constant factors. If the
  complexity class is wrong, none of it helps — go back and find a better
  algorithm. Confirm the approach is provably optimal before reaching here.
- **Escalate cheapest-to-ugliest, stop when it passes.** In order: (1) compiler
  pragmas + fast I/O, (2) memory layout / cache, (3) swapping slow STL
  containers, (4) branchless and bitset tricks, (5) hand-written SIMD. Levels
  1–2 are nearly free; only go deeper if still failing.
- **Propose before applying.** Per the partnership rule, tell the user you've
  exhausted algorithmic options and want to escalate to low-level optimization,
  and get approval — this trades away all readability and portability.
- **Keep the clean version.** Preserve the readable solution; the optimized one
  is bug-prone, so test both against the samples and stress-test them.
- Assumes a GCC / Codeforces-style judge with AVX2 available. Verify the judge
  supports these before relying on them.

The full toolbox — optimization pragmas, custom fast readers, cache and memory
layout, container replacements, branchless/bitset tricks, and AVX2 SIMD with
examples — is in `references/black-magic.md`. Load that file only when a problem
actually reaches this stage.

## Edge-case checklist

Consider each before finalizing:
- **Minimum sizes:** N = 0 and N = 1. Does the loop/DP degenerate correctly?
- **Maximum values:** plug in the largest allowed inputs and check for overflow.
- **All equal / already sorted / reverse sorted** inputs.
- **No valid answer:** does the problem require printing -1, 0, or "NO"?
- **Negative numbers or zero,** if the range allows them.
- **Single vs many test cases:** is global state reset each time?
- **Duplicate elements,** if the logic assumes distinctness.

## Common pitfalls

- **Integer overflow.** `int` holds up to ~2.1·10⁹. If a value or an
  intermediate product (e.g. `a * b`) can exceed that, use `ll`. A frequent bug
  is `int a, b; ll c = a * b;` — the multiply happens in `int`. Cast first:
  `ll c = (ll)a * b;`.
- **Modular arithmetic.** Take the mod after every add/multiply. For
  subtraction, normalize negatives: `((x % M) + M) % M`.
- **Recursion depth.** Deep recursion (≈10⁵+) can overflow the stack; prefer
  iterative solutions or increase reliance on explicit stacks.
- **Floating point.** Avoid comparing doubles with `==`; use an epsilon, or
  reformulate with integers when possible.
- **Off-by-one and indexing.** Be explicit about 0- vs 1-based indexing and keep
  it consistent.

## Stress testing (only when asked)

Do **not** stress-test by default. Run it only when the user asks for it, or
offers a solution that's getting wrong-answer verdicts and agrees to it. When a
solution passes the samples but fails hidden tests and the failing case is
unknown, you may *offer* stress testing — but wait for a yes before doing it.

The method finds a minimal failing case automatically:

1. **Brute force oracle.** Write a simple, obviously-correct, possibly slow
   solution that is easy to trust.
2. **Random generator.** Write a generator that emits small random inputs valid
   under the constraints (small N so the brute force is fast and failures are
   readable).
3. **Diff in a loop.** Run both solutions on many generated inputs and compare
   outputs. On the first mismatch, print the offending input and both outputs,
   then stop.
4. **Debug against the minimal case.** Shrink the failing input if needed, then
   fix the main solution and re-run the loop until it survives many iterations.

Deliver these as separate runnable pieces — the main solution, the brute force,
the generator, and a short driver (a shell loop works, since the programs read
stdin) — so the user can run the comparison themselves.

## When the user already has an algorithm

Sometimes the user supplies their own approach and asks you to implement it.
Do **not** skip straight to code. Faithfully implementing a flawed or incomplete
algorithm is worse than useless — it hides the bug behind working-looking code.
Act as a critical collaborator first:

1. **Pressure-test correctness.** Think hard about whether the approach actually
   solves the problem. Actively look for counterexamples. If it's greedy, ask
   whether the greedy choice is provably optimal; if DP, check the state
   definition and transitions cover every case; if it relies on a claim
   ("the answer is always the median"), sanity-check that claim.
2. **Surface ambiguity and fill gaps.** Identify what the user left unspecified —
   tie-breaking rules, base cases, initialization, how empty or boundary inputs
   are handled, output format on "no solution." Resolve each with a clearly
   stated assumption, or ask if it genuinely changes the answer.
3. **Enumerate edge cases** the approach might mishandle, and note how the
   implementation will deal with them.
4. **Assess complexity** against the constraints. If it likely exceeds the time
   or memory limit, say so plainly and suggest what to change.
5. **Flag problems before coding — talk it through, don't silently "fix."** If
   the algorithm looks wrong or slightly off, tell the user exactly what the
   issue is and propose a correction. Get agreement before implementing. Never
   quietly implement a different algorithm than the one they described, and never
   quietly implement a version you believe is broken.
6. **Then implement.** Once the approach is sound (or the user confirms the fix),
   write the solution from the C++ template, minding the pitfalls, and finish
   with complexity and sample verification.

If the algorithm is already correct and complete, say so in a sentence, confirm
your read of it and any assumptions, and get the go-ahead before implementing.

## Output format

Deliver the response in two phases, with the approval checkpoint between them.

**Phase 1 — the plan (send this first, then stop and wait):**

**1. Understanding** — one or two sentences restating the task.

**2. Classification** — the algorithmic family the problem belongs to (DP, graph,
greedy, two pointers, binary search on the answer, number theory, strings, etc.).

**3. Approach** — the key observations and the algorithm, explained well enough
that a reader could reconstruct it. State *why* it is correct. If more than one
approach is viable, present each with its complexity and tradeoffs so the user
can choose.

**4. Complexity** — time and space in Big-O, plus one line confirming it fits
the constraints (e.g. "N ≤ 2·10⁵, so O(N log N) ≈ 3.6·10⁶ ops — comfortable").

**5. Edge cases & assumptions** — the specific cases considered and how the
solution handles them, plus any ambiguity you resolved or open question.

Then ask for approval — something like "Does this look right, or want changes
before I code it?" — and wait.

**Phase 2 — the implementation (only after approval):**

**6. Code** — the complete, compilable C++ solution in one block.

**7. Verification** — trace the provided sample(s) through the logic and confirm
the output matches.

If the problem statement is ambiguous or a constraint seems missing, raise it in
Phase 1 rather than guessing silently.

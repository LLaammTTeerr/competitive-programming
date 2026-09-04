# Judge-agnostic contest orchestration + interactive statement parsing

Status: **shipped** (see
[`../decisions/2026-07-29-parallel-contest-solving.md`](../decisions/2026-07-29-parallel-contest-solving.md)).
Historical record; where it disagrees with the code, the code wins.

Two independent changes to the `competitive-programming` plugin:

1. `running-contests` stops being Codeforces-specific and drives a contest on any
   judge, binding to whatever judge MCP is available at runtime.
2. The Codeforces MCP's statement parser stops discarding the **Interaction**
   section (and every other non-standard named section).

They share no code and can land in either order.

---

## Task 1 — make `running-contests` judge-agnostic

### Problem

`skills/running-contests/SKILL.md` names Codeforces throughout: its description,
its title, its discovery instructions, its language guidance, and its scoring
model. A user running an AtCoder or CodeChef contest gets a skill that describes
a judge they are not using. `solving-problems` already targets "Codeforces /
AtCoder-style judges" and needs no change.

### Design

#### Capability contract

The skill names four **capabilities**, never tool names:

| Capability | What it must provide | Used by |
|---|---|---|
| list-problems | the contest's problem indices and names; ideally solve counts / points / difficulty | ordering |
| get-statement | one problem's full statement, limits, samples | loop step 1 |
| submit | send source + language for a problem | loop step 4 |
| poll-verdict | a submission's verdict or score | loop step 5 |

Discovery procedure, run once at the start of a contest:

1. Consult `references/judges.md` for the named judge — it gives the expected
   server, capability bindings, and quirks.
2. Call `ToolSearch` with the judge name plus capability words ("atcoder
   submit", "codeforces contest problems") to load the real tool schemas. Read
   the actual parameter names; never guess a schema.
3. Bind each of the four capabilities to a concrete tool.
4. State the binding in the first status update, so the user can correct a
   mis-binding before any submission happens.

Every section after discovery refers to capabilities only. No `cf_*` tool name
appears outside `references/judges.md`.

#### Degraded mode — no MCP for this judge

When one or more capabilities cannot be bound, report exactly which are missing,
then **offer** a human-in-the-loop run (opt-in; do not assume it):

- **get-statement missing** → fetch the problem URL with WebFetch, or ask the
  user to paste the statement. If the fetch comes back truncated or
  JS-rendered — no samples, no limits — stop and ask for a paste rather than
  solving a partial statement.
- **submit missing** → present the final source path and the language to use,
  and ask the user to submit.
- **poll-verdict missing** → ask the user to report the verdict verbatim.

Everything else — ordering, the per-problem loop, verification to the mode's
bar, stuck triggers, progress reporting — is unchanged in degraded mode. Only
the judge I/O becomes manual.

#### Interactive problems

A new short section, enabled by task 2 surfacing these sections for the first
time. Recognise an interactive problem from an Interaction section in the
statement, or an absent output specification. Consequences:

- Flush after every write.
- The sample is a dialogue transcript, not a runnable test file: diffing program
  output against the sample output does not apply.
- Stress testing requires writing a mock interactor, not a brute-force oracle
  over a fixed input file.

#### Sections generalised in place

- **Establish the run** settles three things: which contest *and which judge*
  (inferred from the URL domain; ask only for a bare contest ID), which mode
  (ICPC / IOI, unchanged), and which judge interface (the binding above).
- **Title and intro** → "Contest Orchestrator". The division of labour is
  restated judge-neutrally: `solving-problems` decides what code to write; this
  skill decides what to work on, when to submit, and how to read the result; a
  judge MCP is the interface to the judge.
- **Frontmatter description** triggers on any judge — Codeforces, AtCoder,
  CodeChef, Kattis, DMOJ/oj.uz, ICPC/IOI-style sets, or a bare contest URL from
  any domain — and keeps the existing "single isolated problem →
  `solving-problems`" disambiguation.
- **Ordering** keys off "if the judge exposes solve counts / points /
  difficulty", falling back to index order.
- **Language selection** discovers valid language ids from the submit
  capability. No hardcoded Codeforces `programTypeId`s.
- **Verdict table** keeps its rows but gains a note to match verdicts by
  *meaning*, not by string: judges spell them differently (AC/OK, WA, TLE, MLE,
  RE, CE, ILE).
- **What you are optimizing** is relabelled as the ICPC/Codeforces penalty
  model, with an instruction to read the judge's actual scoring rule when it
  differs (AtCoder points, IOI subtasks). Two invariants are stated as holding
  everywhere: a solve beats no solve, and an attempt on a problem you have not
  solved is nearly free.
- **Guardrails** extend "one contest, the user's contest" to "one judge".

#### `skills/running-contests/references/judges.md` (new)

- A **Codeforces** entry: server name, the binding for all four capabilities
  (`cf_list_contest_problems`, `cf_get_problem_statement`,
  `cf_submit_solution`, `cf_get_submission_status` / `cf_wait_for_verdict`), the
  `gym` and `group_id` parameters, language id handling, the penalty rule,
  contest URL shapes, and interactive-problem quirks.
- A **judge not listed** paragraph pointing back at the generic contract and
  degraded mode.
- An **entry template** for adding a judge once its MCP exists.

No speculative AtCoder or CodeChef entries. Inventing tool names for servers
that do not exist yet would be fiction that later contradicts the real server.

#### Manifests

`README.md`'s skill table and the `plugin.json` / `marketplace.json`
descriptions drop "Codeforces" for the contest skill. Plugin version
0.2.0 → 0.3.0 in both manifests.

### Out of scope

No new MCP servers. No changes to `solving-problems`.

---

## Task 2 — recover the missing Interaction section

### Problem

`cf_get_problem_statement` on
<https://codeforces.com/contest/2206/problem/A> returns a statement with no
interaction protocol: no query format, no query budget, no flush requirement.
The output jumps from the legend straight to the Example.

**Root cause**, verified against the live page and `src/cf_mcp/statement.py`:
the parser models a statement as a fixed set of named divs. Codeforces puts
*non-standard* named sections — Interaction, and Scoring on subtask problems —
in **class-less** top-level divs, exactly like the legend. The legend loop
(`statement.py:241-247`) takes the first class-less div and `break`s, discarding
every later one.

2206A's top-level divs are: `header`, class-less (legend), class-less
(**Interaction**), `sample-tests`, `note`. There is no `input-specification` or
`output-specification` at all, so `_section()` finds nothing and the entire
protocol is lost.

### Design

Parse in **document order** instead of by fixed field.

- `parse_statement` walks `root.find_all("div", recursive=False)` once, in
  order, classifying each div:
  - `header` → skip (handled separately, as today)
  - class-less **without** a `section-title` child → the legend; the first one
    wins
  - class-less **with** a `section-title` child → a titled section, captured as
    `{title, body}`
  - `input-specification` / `output-specification` / `note` / `sample-tests` →
    as today
- `Statement` gains an ordered `sections` list holding every titled section.
  `input_spec`, `output_spec` and `note` remain as named fields so existing
  consumers keep working, and they also enter the ordered list — so
  `to_markdown` renders each section where Codeforces actually put it, rather
  than in a hardcoded order.
- `Statement.interactive: bool` — true when a captured section is titled
  Interaction (case-insensitive, tolerating a title that merely starts with
  "Interaction"), or the legend contains the phrase "interactive problem"
  (case-insensitive).
- `to_dict` gains `interactive` and `sections`. No existing key changes shape.
- When `interactive`, the markdown labels the Example as an **interaction
  transcript, not a runnable test file**, so nothing downstream diffs it like a
  normal sample.
- `cf_get_problem_statement`'s docstring documents the two new keys.

### Tests

In `mcp-server/tests/test_offline.py`, following its inline-fixture convention:

- A fixture mirroring 2206A's real shape (legend + class-less Interaction, no
  input/output spec): the Interaction body survives into `sections` *and* into
  the markdown, and `interactive` is true.
- A subtask fixture with a class-less **Scoring** section: proves the fix is
  general, not an Interaction special-case.
- A section-order assertion.
- The existing statement tests, unchanged, as the regression guard that ordinary
  problems still parse identically.

### Verification before claiming done

1. Run the new parser against the saved real 2206A page; confirm the query
   format, the query limit, and the flush requirement appear in the markdown.
2. Run the full server suite (`uv run --extra dev pytest -q`).
3. Fetch a normal problem through the live MCP and diff its markdown against the
   current parser's output to prove no regression on ordinary statements.

### Out of scope

The interactive sample stays as two `pre` blocks (the input side and the output
side). Reconstructing a true interleaved transcript would mean guessing turn
boundaries that Codeforces does not mark; flagging it as a transcript is the
honest fix.

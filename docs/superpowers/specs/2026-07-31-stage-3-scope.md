# Stage 3 scope

Status: **scope, not a plan.** Written 2026-07-31, after Stage 2 shipped (PR #4).
Nothing here is agreed for implementation yet.

Two items, in order. Item 1 is a capability gap that blocks a whole class of
Vietnamese problems; item 2 is a routing gap that Stage 2 made worse.

---

## Item 1 — file-based IO (`.inp` / `.out`)

### Why it matters

`run_matrix.run()` refuses any problem whose `io.input` is not `stdin`
(`tools/run_matrix.py:1007`). VOI-style and vnolymp-style problems commonly
use `<name>.inp` / `<name>.out`, so the pipeline stops at the invocation
matrix for that entire class. `flight` happens to be stdin/stdout, which is
why this has not bitten yet.

The refusal is correct and must stay until the replacement is proven. It
exists because a file-IO problem run through the stdin path feeds the model
solution empty stdin, discards its real output, and reports a **confident
wrong verdict** — found during Stage 1's dogfood. A pipeline whose only
claim is "there is evidence for this package" cannot ship that failure mode.

### What actually changes

Smaller than it looks. The chokepoint is one function.

**`_run_once()` (`run_matrix.py:673`)** takes `stdin_path` and `stdout_dest`,
mounts the input's directory read-only, mounts a rw staging dir, and passes
`--stdin=<label>/<name>` and `--stdout=<stage>/<name>`. File IO replaces
those two flags with:

- stage the test input into the **rw staging dir** under the `io.input`
  filename, before the run
- add `--chdir=<stage_label>` so the solution's cwd is that directory
  (isolate supports `-c/--chdir`; verified)
- after the run, read `io.output` back out of the staging dir instead of
  the staged stdout file

The rest of the driver is unaffected because it already speaks in paths.

**Unaffected — confirm, don't assume:** validator, generators and checker are
testlib tools. Validators and generators are stdin/stdout by construction;
the checker already receives `input output answer` as three *file paths*.
None of them should need changing, which makes this a solution-invocation
change only. Verify rather than trust — this document has been wrong about
"unaffected" before.

### Where it will go wrong

Three named risks, each earned by a bug this project already shipped.

1. **Memory accounting.** Contaminated three separate times in Stage 1, each
   fix relocating the defect: parent `mm` via `posix_spawn`, then the box
   cgroup's sticky `cg-oom-killed`, then the staging dir on tmpfs charging a
   solution's own stdout against its `--cg-mem`. A new writable file inside
   the box is exactly that shape a fourth time. The staging dir must stay
   disk-backed, and the acceptance check is a small program writing a large
   `.out` under a tight limit **not** being killed.

2. **A missing output file must be a verdict, not a crash — and not a
   confident wrong one.** If the solution never creates `io.output`, that is
   the precise failure the current refusal protects against. It needs its
   own outcome, distinct from `WA` on empty output, and `matrix_core`'s
   severity ordering has to place it. Decide the verdict kind *before*
   writing the driver change.

3. **`io.input`/`io.output` are unvalidated free strings today**
   (`problem_meta.py:359-360` — `io.get("input", "stdin")`). Stage 2's
   `_string()` sweep did not reach them. A path separator or `..` in either
   value reaches a `--dir` mount. Validate shape at load: a bare filename,
   no separators, no dot-segments.

### Also in scope for the item

- `drift_check` should cover the io keys — the statement's vnolymp
  `input =` / `output =` must agree with `problem.json`, which is the same
  class of drift the tool already guards for bounds.
- `preparing-tests` and `validating-solutions` both document stdin/stdout
  assumptions in prose. Whatever changes, `test_skill_docs.py` is the place
  to pin it.

### Definition of done

A file-IO problem — not `flight` — driven end to end to `holes: 0`,
with the three risks above each demonstrated closed by a run, not a reading.

---

## Item 2 — `writing-statements` routing

Stage 2's final review: it is now the target of **five inbound routes with
zero outbound**, and it has no routing table at all — one prose handoff at
`skills/writing-statements/SKILL.md:174` ("Then hand off to test
generation"). Every other skill in the set carries an explicit boundary
table naming what it does, what it does not, and where each exit goes.

It was correctly deferred through both stages: it is a Stage 1 file and sits
outside the design spec's §3 skill set. That reasoning does not survive a
third stage — it is the terminus of the largest number of routes in the
pipeline and the only one that cannot say where control goes next.

Scope: a boundary/routing table matching the other seven, and its exits
wired to the phases that actually follow (samples → statement → the
`creating-problems` phase sequence).

---

## Carried forward from Stage 2

- **`running-contests` is an orphan** — no skill references it, not even
  `solving-problems`. Pre-existing, unexamined. Decide: wire it or retire it.
- ~~**The test suite is not parallel-safe with itself.**~~ **Resolved**
  2026-08-09 by `docs/superpowers/plans/2026-08-09-parallel-invocation-matrix.md`:
  box ids are leased from a per-user, cross-process `flock` pool instead of
  derived from `pid`, `_run_once` owns its meta file and staging directory, and pass 2 runs
  on the lease pool.
- **`review_checks.run()` triggers `scan()` three times**, each spawning one
  `git log` per solution — 24 subprocesses per audit on `flight`. Cosmetic
  until a package has 100 solutions.

## Not in scope

- Interactive problems.
- Multi-file / multi-test-per-file formats.
- Anything that changes the `holes` definition, which is the pipeline's one
  non-circular claim and should outlive every stage.

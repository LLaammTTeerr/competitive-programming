# Invocation-Matrix Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five follow-ups the parallel-invocation-matrix review triaged as ship-but-fix, the most serious being that a crash in `run_matrix` exits `1` — the code `validating-solutions` reads as "the matrix found holes" — so a typo in a package reports as a finding *about* the package.

**Architecture:** Two tasks. Task 1 fixes the exit-code contract at its boundary: `main()` currently catches only `MatrixError`, and two other exception types defined in `tools/` reach it unwrapped. Task 2 closes the staleness gap the exit-code fix cannot reach, by making `package_status._matrix()` compare `invocation.json` against the sources it describes, plus three small independent corrections. Nothing here touches the parallel machinery.

**Tech Stack:** Python 3.10+ stdlib only (hard project constraint). `ioi/isolate` 2.6.

**Branch:** `matrix-followups`, cut from `parallel-invocation-matrix` (PR #6, open). These fixes touch `main()`, `_run_pass2` and `box_pool.py`, all changed by that PR, so this stacks on it rather than on `main` — matching this repo's precedent of stacked PRs #3–#5.

## Global Constraints

- **stdlib only.** No third-party imports in `tools/`. No `requirements.txt`, no venv.
- **R1 (standing):** externally-authored data must never surface a bare stdlib exception.
- **Evidence standard (standing):** a docstring or prose claim is a testable assertion. If you write "X is guaranteed", a test must fail when X stops being true. This project has shipped false docstrings repeatedly; six were corrected during the parallel branch alone.
- **Verification standard (standing):** an error path you have not triggered is not handled. Every new `raise` and every new branch needs a test that actually reaches it.
- **The `holes` definition does not change.** `_SEVERITY` does not change. `classify()` and `compute_limits()` are not touched.
- **No verdict may become less trustworthy than it is today.**
- **Never modify anything under `~/Projects/my_cp_problems/`.** Clean up isolate boxes; verify with `ls -a` — plain `ls` hides the dot-prefixed `.run_matrix_*` roots.
- Full suite must pass: `python3 -m unittest discover -s tools/tests -t .` from the repo root. **Baseline is 321 tests, ~150s on an idle machine.**

---

## Evidence (measured, not assumed)

`main()`'s docstring declares the contract `validating-solutions` reads:

```
0 — every solution's @expect was met.
1 — the matrix ran and found holes and/or mismatches.
2 — the matrix could not be run at all.
```

It catches only `MatrixError` (`run_matrix.py:1876`). Six exception classes are defined under `tools/`: `MatrixError` (RuntimeError), `BoxPoolError` (RuntimeError, converted at both `lease()` sites by `_leased_box`), and four `ValueError` subclasses — `ProblemMetaError`, `ScanError`, `DriftCheckError`, `FlagError`.

Probed against a real package, driving `main()` directly:

| Injected fault | Result |
|---|---|
| malformed `problem.json` | **ESCAPED** `tools.problem_meta.ProblemMetaError` |
| malformed `@expect` header in a solution | **ESCAPED** `tools.scan_solutions.ScanError` |
| corrupted `flags.json` | exit 0 (not an escape) |

Two escapees, not the one recorded. `ScanError` is the likelier of the two in practice — it fires on a typo in a solution's metadata header, which a setter edits far more often than `problem.json`.

Both surface as a traceback and exit **1** via Python's default handler, so `validating-solutions` reads a crash as "keep reading, there are findings". `run()`'s first statement is `load(...)`, and `scan(...)` runs immediately after `open_isolate_box`.

**The staleness gap the exit-code fix cannot close.** `run()` writes `invocation.json` only at its very end (`run_matrix.py:1849`). `load()` fails before that, so a crash leaves any previous artifact in place. `package_status._matrix()` (`package_status.py:62-84`) then reads it and passes the gate on `holes == [] and mismatches == []` with **no freshness check whatsoever** — `generated_at` is written into the payload and never read back. This is not only a crash problem: after a clean run, editing a solution or adding a test leaves the gate green on evidence describing a package state that no longer exists.

**Human ruling:** fix it in the *gate*, not by deleting the artifact. Deleting `invocation.json` early in `run()` would break the module's documented "a refusal is a true no-op on the tree" doctrine — a missing-isolate refusal would destroy valid prior evidence.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/run_matrix.py` | the sandboxed driver | `main()` catches the package-error family; wrap the bare `pool_size()`; wall-kill flag records the original reading |
| `tools/package_status.py` | phase gate over a package | `_matrix()` reports stale evidence as not-passing |
| `tools/box_pool.py` | box-id leases | `/tmp` fallback created 0700 and verified owned |
| `tools/tests/test_run_matrix.py` | | exit-code and flag tests |
| `tools/tests/test_package_status.py` | | staleness tests |
| `tools/tests/test_box_pool.py` | | lock-dir ownership tests |

**Why `main()` and not per-site conversions.** `_leased_box` converts `BoxPoolError` at its two call sites because there are exactly two and they are adjacent. `ProblemMetaError` and `ScanError` arise from different modules at different depths, and the property that matters is a *boundary* one: nothing crosses `main()` as an unhandled exception. A boundary catch states that invariant in one place and cannot be defeated by a future call site the way a per-site list can. Record the reasoning where the catch lives.

---

### Task 1: Make the exit-code contract hold at the boundary

**Files:**
- Modify: `tools/run_matrix.py:1866-1880` (`main()`), and `:1798` (the bare `box_pool.pool_size()`)
- Test: `tools/tests/test_run_matrix.py`

**Interfaces:**
- Produces: `main()` returns `2` for every failure that is not a hole/mismatch result; no exception type defined under `tools/` escapes it.
- Consumes: `MatrixError`, `box_pool.BoxPoolError`, `problem_meta.ProblemMetaError`, `scan_solutions.ScanError`.

- [ ] **Step 1: Write the failing tests**

Add to `tools/tests/test_run_matrix.py`, in a class based on `PackageFixture` (it needs a real package on disk):

```python
class ExitCodeContractTest(PackageFixture):
    """`main()`'s exit codes are a contract `validating-solutions` reads.

    Exit 1 means "the matrix ran and found holes and/or mismatches" — a
    statement about the *package*. Anything that prevents the matrix from
    running is exit 2. A crash reported as exit 1 is a crash read as a
    finding, which is the misread `main()`'s own docstring says it exists
    to prevent.
    """

    def _main(self):
        return run_matrix.main(["run_matrix.py", str(self.problem_dir),
                                str(self.testlib_dir)])

    def test_a_malformed_problem_json_exits_2_not_1(self):
        (self.problem_dir / "problem.json").write_text("{not json",
                                                       encoding="utf-8")
        self.assertEqual(self._main(), 2)

    def test_a_malformed_expect_header_exits_2_not_1(self):
        # Likelier in practice than a bad problem.json: a setter edits
        # solution headers constantly.
        path = self.problem_dir / "solutions" / "sol-main.cpp"
        path.write_text(path.read_text(encoding="utf-8")
                        .replace("g1=OK", "g1=NOPE"), encoding="utf-8")
        self.assertEqual(self._main(), 2)

    def test_a_package_error_prints_to_stderr_and_nothing_to_stdout(self):
        # stdout is the results channel. A caller that parses stdout must
        # not receive a half-line of nothing and read it as "no holes".
        (self.problem_dir / "problem.json").write_text("{not json",
                                                       encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self._main()
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("problem.json", err.getvalue())

    def test_no_tools_exception_type_escapes_main(self):
        # The boundary property itself, asserted rather than assumed: if a
        # future module raises a new error type through run(), this fails.
        (self.problem_dir / "problem.json").write_text("{not json",
                                                       encoding="utf-8")
        try:
            self._main()
        except BaseException as exc:  # noqa: BLE001 - that is the point
            self.fail(f"{type(exc).__module__}.{type(exc).__name__} escaped main()")

    def test_a_real_hole_still_exits_1(self):
        # The contract's other half: exit 2 must not swallow genuine
        # findings. Declare the wrong solution as correct so the suite has
        # a hole to report.
        path = self.problem_dir / "solutions" / "sol-wrong.cpp"
        path.write_text(path.read_text(encoding="utf-8")
                        .replace("g1=WA", "g1=TL"), encoding="utf-8")
        self.assertEqual(self._main(), 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tools.tests.test_run_matrix.ExitCodeContractTest -v`
Expected: the first four FAIL — `ProblemMetaError`/`ScanError` escape as tracebacks. `test_a_real_hole_still_exits_1` should already PASS; if it does not, stop and report, because the contract's working half is broken.

- [ ] **Step 3: Implement the boundary catch**

Add to the imports: `from tools.problem_meta import Problem, ProblemMetaError, load` (extend the existing line) and `from tools.scan_solutions import ScanError, scan`.

Above `main()`:

```python
# Every exception type this pipeline raises for a package it cannot use.
# `main()` catches the family rather than a list of call sites, because the
# property that has to hold is a *boundary* one: nothing reaches a caller as
# an unhandled exception, whatever future module raises it. A per-site
# conversion list — the shape `_leased_box` uses for `BoxPoolError`, which
# is right there because it has exactly two adjacent call sites — cannot
# state that invariant, and is defeated by the next call site someone adds.
#
# Measured before this existed: a malformed `problem.json` surfaced
# `ProblemMetaError` and a malformed `@expect` header surfaced `ScanError`,
# both as tracebacks exiting 1 — the code `validating-solutions` reads as
# "the matrix ran and found holes". A typo in a package reported as a
# finding about that package.
PACKAGE_ERRORS = (MatrixError, box_pool.BoxPoolError, ProblemMetaError, ScanError)
```

and in `main()` replace `except MatrixError as exc:` with `except PACKAGE_ERRORS as exc:`.

Update `main()`'s docstring so the exit-2 line names what it now covers, and say that the boundary — not a list of call sites — is what guarantees it.

- [ ] **Step 4: Wrap the bare `pool_size()`**

`run_matrix.py:1798` is the one `box_pool` call in the module not routed through `_leased_box`. It is currently unreachable-with-a-raise (`lease()` already called `pool_size()` successfully inside `open_isolate_box` under the same environment), but "currently unreachable" is not "handled". With `PACKAGE_ERRORS` in place a `BoxPoolError` here already exits 2 rather than 1 — so this step is about the *message*, not the code:

```python
        try:
            workers = box_pool.pool_size()
        except box_pool.BoxPoolError as exc:
            raise MatrixError(
                f"cannot size the worker pool: {exc}"
            ) from exc
```

Test it by forcing the environment to change between `open_isolate_box` and pass 2:

```python
    def test_a_bad_pool_size_at_pass_two_is_a_matrix_error(self):
        real = box_pool.pool_size
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) > 1:            # first call is open_isolate_box's
                raise box_pool.BoxPoolError("synthetic pool failure")
            return real()

        with mock.patch.object(box_pool, "pool_size", flaky):
            with self.assertRaises(run_matrix.MatrixError) as ctx:
                run_matrix.run(self.problem_dir, self.testlib_dir)
        self.assertIn("worker pool", str(ctx.exception))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tools.tests.test_run_matrix -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m unittest discover -s tools/tests -t .`
Expected: `OK`, 321 baseline + the new tests.

- [ ] **Step 7: Commit**

```bash
git add tools/run_matrix.py tools/tests/test_run_matrix.py
git commit -m "fix: no tools exception escapes main() as exit 1"
```

---

### Task 2: Stale evidence, the wall-kill flag's lost reading, and the lock-dir mode

Three independent corrections. They share a task because each is small and none depends on the others; a reviewer can still reject one and accept its neighbours.

**Files:**
- Modify: `tools/package_status.py:62-84` (`_matrix`)
- Modify: `tools/run_matrix.py:1556-1580` (the wall-kill flag)
- Modify: `tools/box_pool.py` (`_default_lock_dir` / `lock_dir`)
- Test: `tools/tests/test_package_status.py`, `tools/tests/test_run_matrix.py`, `tools/tests/test_box_pool.py`

**Interfaces:**
- Consumes: `Phase` from `package_status`; the wall-kill stub harness from the parallel branch's Task 5 tests.
- Produces: `_matrix()` returns `Phase("matrix", False, ...)` naming staleness when `invocation.json` predates its sources.

- [ ] **Step 1: Write the failing tests for the staleness gate**

```python
class MatrixFreshnessTest(unittest.TestCase):
    """`invocation.json` is evidence about a package state. When the package
    has moved on, the evidence does not become wrong — it becomes about
    something else, and the gate must not accept it.

    This is not only a crash concern. `run_matrix` writes the artifact at
    the very end of a successful run, so a crash leaves an older one in
    place; but a *clean* run followed by editing a solution leaves exactly
    the same stale-green state, and that is the commoner case.
    """

    def _package(self, *, holes=(), mismatches=()):
        # ... build a minimal problem dir with problem.json, solutions/,
        # tests/<group>/ and an invocation.json carrying `holes`/`mismatches`
        # ... (reuse this file's existing fixture helper if one exists)

    def test_a_fresh_clean_matrix_passes(self):
        d = self._package()
        self.assertTrue(_matrix(d).ok)

    def test_an_invocation_older_than_a_solution_is_stale(self):
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(d / "solutions" / "sol-main.cpp", (later, later))
        phase = _matrix(d)
        self.assertFalse(phase.ok)
        self.assertIn("stale", phase.detail.lower())

    def test_an_invocation_older_than_a_test_is_stale(self):
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        test_file = next((d / "tests").rglob("*.in"))
        os.utime(test_file, (later, later))
        self.assertFalse(_matrix(d).ok)

    def test_an_invocation_older_than_problem_json_is_stale(self):
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(d / "problem.json", (later, later))
        self.assertFalse(_matrix(d).ok)

    def test_staleness_is_reported_before_holes(self):
        # A stale artifact reporting zero holes must not read as "clean".
        # Order matters: the detail a reader sees has to name the reason
        # they cannot trust the number, not the number.
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(d / "problem.json", (later, later))
        self.assertIn("stale", _matrix(d).detail.lower())

    def test_a_stale_artifact_with_holes_still_fails(self):
        d = self._package(holes=[{"solution": "x", "group": "g1",
                                  "expected": "WA", "actual": "OK"}])
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(d / "problem.json", (later, later))
        self.assertFalse(_matrix(d).ok)

    def test_an_equal_mtime_is_not_stale(self):
        # Boundary: a file written in the same second as the artifact is
        # not evidence of a later edit. Strictly-newer is the test, or a
        # fast clean run flags itself stale.
        d = self._package()
        stamp = (d / "invocation.json").stat().st_mtime
        os.utime(d / "problem.json", (stamp, stamp))
        self.assertTrue(_matrix(d).ok)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `python3 -m unittest tools.tests.test_package_status.MatrixFreshnessTest -v`
Expected: every staleness test FAILS — `_matrix()` has no freshness notion at all. `test_a_fresh_clean_matrix_passes` and `test_an_equal_mtime_is_not_stale` should pass already.

- [ ] **Step 3: Implement the freshness check**

```python
# What `invocation.json` is evidence *about*. A matrix result describes a
# specific package state; when any of these is newer than the artifact, the
# artifact has not become wrong, it has become a statement about something
# else — and the gate must not accept it as current.
#
# mtime is the signal, and its weakness is known and deliberate: a
# `git checkout` rewrites mtimes without changing content, so this can
# report stale when nothing meaningful moved. That direction is the safe
# one — a false "stale" costs a re-run, a false "fresh" greens a package on
# evidence describing a different tree. `generated_at` inside the payload
# was considered and rejected as the source of truth: it records when the
# matrix ran, not what it ran against, so it cannot detect an edit made
# afterwards.
_MATRIX_SOURCES = ("problem.json", "solutions", "tests")


def _newest_source_mtime(problem_dir: Path) -> float:
    newest = 0.0
    for name in _MATRIX_SOURCES:
        path = problem_dir / name
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    newest = max(newest, child.stat().st_mtime)
    return newest
```

and in `_matrix`, after the payload parses and **before** the holes/mismatches verdict:

```python
    if _newest_source_mtime(problem_dir) > path.stat().st_mtime:
        return Phase("matrix", False,
                     "invocation.json is stale: a solution, test or "
                     "problem.json changed after it was written — re-run "
                     "the matrix")
```

Placing it before the holes check is the point: a stale artifact reporting zero holes must name staleness, not report "clean".

- [ ] **Step 4: The wall-kill flag's lost reading**

`run_matrix.py:1556-1580` captures `first_run_ms = r.cpu_ms` before `_time_median` reassigns `r`, but for a **wall-clock** kill the number that explains the kill is the *wall* time, and it is never captured. A reader of `flags.json` sees the re-timed result and cannot tell how far past the ceiling the original run went. The near-TL flag embeds its original reading; this one should too.

Capture `first_wall_ms = r.wall_ms` alongside `first_run_ms`, and include it in the wall-kill flag's `what` text.

Test it with the Task 5 wall-kill stub harness, asserting the original wall reading appears in the flag record:

```python
    def test_the_wall_kill_flag_records_the_original_wall_reading(self):
        # ... stub a wall-clock kill as the parallel branch's Task 5 test
        # does, then:
        banded = [f for f in register["flags"] if f["kind"] == "timing-band"]
        self.assertTrue(any(str(FABRICATED_WALL_MS) in f["what"]
                            for f in banded))
```

- [ ] **Step 5: The `/tmp` lock-dir mode and ownership**

`_default_lock_dir()` falls back to `/tmp/run_matrix-boxes-<uid>`, and `lock_dir()` creates it with `mkdir(parents=True, exist_ok=True)` at the caller's umask. Two things follow, and the second is the one that matters:

```python
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
```

`mode=0o700` is safe under any umask, since umask only strips bits and 0700 has none to strip. But `exist_ok=True` means a directory **squatted** by another user before our first `mkdir` is silently used. Add a check after creation and raise `BoxPoolError` if the directory is not a real directory, is a symlink, or is not owned by this uid:

```python
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise BoxPoolError(
            f"the box-lease directory {path} is not a directory owned by "
            f"this user (uid {st.st_uid}, mode {stat.filemode(st.st_mode)}). "
            "Another user may have created it first. Remove it, or set "
            f"${LOCK_DIR_ENV} to a directory you own."
        )
```

Test both: that a fresh fallback directory is created `0700`, and that a directory owned by another uid raises. The ownership test can be driven by pointing `$RUN_MATRIX_BOX_LOCK_DIR` at a path and monkeypatching `os.lstat` to report a foreign uid — the standing verification rule requires the raise be triggered, not merely written.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m unittest discover -s tools/tests -t .`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add tools/package_status.py tools/run_matrix.py tools/box_pool.py tools/tests/
git commit -m "fix: stale matrix evidence, wall-kill flag reading, lock-dir ownership"
```

---

## Explicitly out of scope

- **Hardening the re-time mechanism itself** — the "every worker idle" guarantee is per-process while the lease pool is cross-process, so a sibling invocation can be running during a serial re-time. The final review called this real design work, and the obvious fix (acquire every lease before re-timing) has an ordered-acquisition deadlock trap. It needs its own plan with brainstorming first; folding it into a mechanical batch would recreate exactly the "nobody owned the seam" failure that produced it.
- **The leaked staging directory** at `~/Projects/my_cp_problems/.run_matrix_stage_typs03yx` — inside the tree this project may never modify. The user removes it: `rmdir ~/Projects/my_cp_problems/.run_matrix_stage_typs03yx`.
- **Capping `pool_size()` at the core count.** Oversubscription is documented as an operator hazard in `README.md` and `validating-solutions`; turning it into a hard cap is a policy change, not a defect fix.

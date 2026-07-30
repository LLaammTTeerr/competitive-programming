# Problem-Setting Pipeline, Stage 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the pipeline — `shaping-problems` (idea → numbers), `reviewing-problems` (an end-to-end audit that runs as a fresh-context subagent), and `creating-problems` (the umbrella that sequences everything and owns the gates).

**Architecture:** Two new `tools/` modules make the mechanical half of review and orchestration deterministic — `package_status.py` answers "which phase is this package in?", `review_checks.py` answers "what is mechanically wrong with it?". The three skills carry only judgement: what N separates intended from naive, whether a sentence has two readings, when to stop. Stage 1's rule holds — anything a tool can decide, a tool decides.

**Tech Stack:** Python 3.10+ stdlib only; the Stage 1 `tools/` package; `ioi/isolate`; `qhhoj/testlib`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-30-problem-setting-pipeline-design.md`, §6 (gates and flags), §7 (pipeline), §8, §11, §12.
- **Branch:** `problem-setting-stage-2`, cut from `problem-setting-stage-1` (PR #3 is open; `main` does not yet contain `tools/`). Never commit on `main` or on `problem-setting-stage-1`.
- **Python:** 3.10+, **stdlib only**. A third-party import is a plan violation.
- **Tests:** `python3 -m unittest discover -s tools/tests -t . -v` from the repo root. **151 pass today; none may regress.** The `run_matrix` tests require isolate and now *fail* rather than skip when it is absent — set `CP_ALLOW_SANDBOX_SKIP=1` only if you genuinely lack it.
- **`git add <explicit paths>` only.** Never `git add -A`.
- Commit messages: imperative, no conventional-commits prefix, ending with exactly:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017fQbXswuDyUTXGnVzPME8n
  ```
- **Every skill's frontmatter `name:` must equal its directory name**, one level under `skills/`.
- **The bootstrap block is fixed and is copied verbatim** from `skills/preparing-tests/SKILL.md`. It cost three fix rounds in Stage 1 to get right. No runnable command may reference a variable the reader has not been told how to set, and `python3 -m tools.*` requires `PLUGIN_ROOT` as the working directory.
- **Claims in docstrings and skills are testable assertions.** Stage 1 shipped four instances of a comment asserting something the code did not do. If you write "X is guaranteed", there must be a test that fails when X stops being true.

## What Stage 1 left for this plan

Three carry-forwards, each with a named reason for deferring rather than dropping:

1. **`subtask.depends_on` cycle detection** — `problem_meta.load()` checks that every `depends_on` names a known subtask but not that the graph is acyclic; `g1 → g2 → g1` loads cleanly. Latent until something walks the graph. Stage 2's `package_status` is the first thing that does.
2. **`run_matrix.py:1256` and `validating-solutions:292` say "One line on stderr"** — false for a compile failure, which emits several. The fourth instance of a doc claim the code does not support.
3. **`flags.py` leaves a permanent `flags.json.lock`** beside `flags.json` in every problem package, documented nowhere.

---

## File structure

```
tools/
  package_status.py          NEW  which pipeline phase is a package in
  review_checks.py           NEW  the mechanical half of the audit
  problem_meta.py            MODIFY  add cycle detection
  run_matrix.py              MODIFY  one-line docstring correction
  tests/
    test_package_status.py   NEW
    test_review_checks.py    NEW
    test_problem_meta.py     MODIFY  cycle cases
skills/
  shaping-problems/SKILL.md      NEW
  reviewing-problems/SKILL.md    NEW
  creating-problems/SKILL.md     NEW
  validating-solutions/SKILL.md  MODIFY  stderr wording, and the routing table
  preparing-tests/SKILL.md       MODIFY  routing table (the Stage 2 skills now exist)
.claude-plugin/plugin.json       MODIFY  0.5.0 -> 0.6.0
README.md                        MODIFY  three rows, layout, flags.json.lock note
```

`package_status` and `review_checks` are separate because they answer different questions and fail differently: status is "how far along is this", review is "what is wrong with this". `creating-problems` needs the first to resume; `reviewing-problems` needs the second to audit.

---

### Task 1: Branch, and `depends_on` cycle detection

**Files:**
- Modify: `tools/problem_meta.py`
- Test: `tools/tests/test_problem_meta.py`

**Interfaces:**
- Consumes: `ProblemMetaError`, `Subtask`, `load`.
- Produces: `load()` now raises `ProblemMetaError` naming the cycle when `depends_on` is cyclic. No signature change.

- [ ] **Step 1: Cut the branch**

```bash
cd ~/.claude/skills/competitive-programming
git checkout problem-setting-stage-1
git checkout -b problem-setting-stage-2
git status --short   # must be empty
```

- [ ] **Step 2: Append the failing tests to `tools/tests/test_problem_meta.py`**

```python
    def test_rejects_a_self_dependency(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["depends_on"] = ["g1"]
        with self.assertRaisesRegex(ProblemMetaError, "g1"):
            load(write(bad))

    def test_rejects_a_two_node_cycle(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["depends_on"] = ["g2"]
        bad["subtasks"][1]["depends_on"] = ["g1"]
        with self.assertRaisesRegex(ProblemMetaError, "cycle"):
            load(write(bad))

    def test_accepts_a_diamond_which_is_not_a_cycle(self):
        ok = json.loads(json.dumps(VALID))
        ok["subtasks"].append({"id": "g3", "points": 0, "bounds": {},
                               "constraints_text": [], "depends_on": ["g1", "g2"]})
        ok["subtasks"][1]["depends_on"] = ["g1"]
        problem = load(write(ok))
        self.assertEqual(problem.subtask_ids(), ["g1", "g2", "g3"])
```

- [ ] **Step 3: Run and confirm they fail**

Run: `python3 -m unittest tools.tests.test_problem_meta -v`
Expected: the two rejection tests FAIL (no error raised — a cycle loads cleanly today); the diamond test passes already.

- [ ] **Step 4: Implement, in `load()`, after the existing `depends_on` existence check**

```python
    order: dict[str, int] = {}
    visiting: set[str] = set()

    def visit(sid: str, trail: list[str]) -> None:
        if sid in order:
            return
        if sid in visiting:
            loop = trail[trail.index(sid):] + [sid]
            raise ProblemMetaError(
                f"{path}: subtask dependency cycle: {' -> '.join(loop)}"
            )
        visiting.add(sid)
        for dep in next(s for s in subtasks if s.id == sid).depends_on:
            visit(dep, trail + [sid])
        visiting.discard(sid)
        order[sid] = len(order)

    for s in subtasks:
        visit(s.id, [])
```

A self-dependency `g1 -> g1` produces the trail `g1 -> g1`, so both tests' regexes match.

- [ ] **Step 5: Run tests, then the full suite**

Run: `python3 -m unittest tools.tests.test_problem_meta -v` then `python3 -m unittest discover -s tools/tests -t . -v`
Expected: new tests pass; total rises from 151 to 154; nothing regresses.

- [ ] **Step 6: Commit**

Subject: `Reject cyclic subtask dependencies in problem.json`

---

### Task 2: `tools/package_status.py`

**Files:**
- Create: `tools/package_status.py`
- Test: `tools/tests/test_package_status.py`

**Interfaces:**
- Consumes: `problem_meta.load`, `ProblemMetaError`, `Problem`; `scan_solutions.scan`, `ScanError`.
- Produces:
  - `@dataclass(frozen=True) Phase(name: str, done: bool, detail: str)`
  - `PHASE_ORDER: tuple[str, ...]` = `("problem_json", "statement", "constraints_header", "model_solution", "checker", "validator", "generators", "tests", "zoo", "matrix", "samples")`
  - `status(problem_dir: str | Path, testlib_dir: str | Path | None = None) -> list[Phase]` — one entry per `PHASE_ORDER` name, in that order, never raising for a malformed package (a phase that cannot be evaluated is `done=False` with the reason in `detail`)
  - `next_phase(phases: list[Phase]) -> str | None` — the first `not done`, or `None`
  - `main(argv) -> int` — prints one line per phase, exits 0 when all done, 1 otherwise

- [ ] **Step 1: Write the failing test**

```python
import json, shutil, tempfile, unittest
from pathlib import Path

from tools.package_status import PHASE_ORDER, next_phase, status

FIXTURE = Path("tools/tests/fixtures/mini")


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "p"
        shutil.copytree(FIXTURE, self.dir,
                        ignore=shutil.ignore_patterns(
                            ".build", "invocation.json", "solutions.json",
                            "flags.json", "*.a"))

    def phases(self):
        return {p.name: p for p in status(self.dir)}

    def test_reports_every_phase_in_order(self):
        names = [p.name for p in status(self.dir)]
        self.assertEqual(tuple(names), PHASE_ORDER)

    def test_a_package_with_problem_json_reports_that_phase_done(self):
        self.assertTrue(self.phases()["problem_json"].done)

    def test_a_missing_problem_json_does_not_raise(self):
        (self.dir / "problem.json").unlink()
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)
        self.assertIn("problem.json", phases["problem_json"].detail)

    def test_a_malformed_problem_json_does_not_raise(self):
        (self.dir / "problem.json").write_text("{ not json", encoding="utf-8")
        self.assertFalse(self.phases()["problem_json"].done)

    def test_tests_phase_needs_every_declared_group(self):
        self.assertTrue(self.phases()["tests"].done)
        shutil.rmtree(self.dir / "tests" / "g1")
        phases = self.phases()
        self.assertFalse(phases["tests"].done)
        self.assertIn("g1", phases["tests"].detail)

    def test_matrix_phase_is_not_done_without_invocation_json(self):
        self.assertFalse(self.phases()["matrix"].done)

    def test_matrix_phase_is_not_done_when_holes_remain(self):
        (self.dir / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": [{"solution": "x", "group": "g1"}],
                        "mismatches": []}), encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["matrix"].done)
        self.assertIn("hole", phases["matrix"].detail.lower())

    def test_matrix_phase_is_done_when_clean(self):
        (self.dir / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": [], "mismatches": []}),
            encoding="utf-8")
        self.assertTrue(self.phases()["matrix"].done)

    def test_samples_phase_needs_both_the_entry_and_the_files(self):
        self.assertFalse(self.phases()["samples"].done)
        problem = json.loads((self.dir / "problem.json").read_text(encoding="utf-8"))
        problem["examples"] = [{"test": "tests/samples/01", "note": "n"}]
        (self.dir / "problem.json").write_text(json.dumps(problem), encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["samples"].done)
        self.assertIn("tests/samples/01", phases["samples"].detail)

    def test_next_phase_is_the_first_incomplete_one(self):
        self.assertEqual(next_phase(status(self.dir)), "matrix")

    def test_next_phase_is_none_when_everything_is_done(self):
        done = [type(p)(name=p.name, done=True, detail="") for p in status(self.dir)]
        self.assertIsNone(next_phase(done))
```

- [ ] **Step 2: Run and confirm it fails**

Run: `python3 -m unittest tools.tests.test_package_status -v`
Expected: `ModuleNotFoundError: No module named 'tools.package_status'`

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""Report which pipeline phase a problem package has reached.

`creating-problems` resumes from files on disk rather than from a state file —
this module is how it works out where to resume. Every check is a question about
what exists and parses, never about what a previous run claimed to have done.

`status()` never raises. A package under construction is malformed by
definition, and a resumption tool that crashes on the thing it exists to inspect
is useless; an unevaluable phase is `done=False` with the reason in `detail`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.problem_meta import Problem, ProblemMetaError, load
from tools.scan_solutions import ScanError, scan

PHASE_ORDER = (
    "problem_json", "statement", "constraints_header", "model_solution",
    "checker", "validator", "generators", "tests", "zoo", "matrix", "samples",
)


@dataclass(frozen=True)
class Phase:
    name: str
    done: bool
    detail: str


def _problem(problem_dir: Path) -> tuple[Problem | None, str]:
    try:
        return load(problem_dir / "problem.json"), ""
    except (ProblemMetaError, OSError) as exc:
        return None, str(exc)


def _statement(problem_dir: Path) -> Phase:
    found = sorted(problem_dir.rglob("*.tex"))
    if found:
        return Phase("statement", True, ", ".join(p.name for p in found))
    return Phase("statement", False, "no .tex anywhere under the problem directory")


def _tests(problem_dir: Path, problem: Problem | None) -> Phase:
    if problem is None:
        return Phase("tests", False, "problem.json did not load")
    missing = [
        s.id for s in problem.subtasks
        if not sorted((problem_dir / "tests" / s.id).glob("*.in"))
    ]
    if missing:
        return Phase("tests", False, f"no .in files for group(s): {', '.join(missing)}")
    return Phase("tests", True, f"{len(problem.subtasks)} group(s) populated")


def _matrix(problem_dir: Path) -> Phase:
    path = problem_dir / "invocation.json"
    if not path.exists():
        return Phase("matrix", False, "invocation.json not written yet")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return Phase("matrix", False, f"invocation.json unreadable: {exc}")
    holes, mismatches = data.get("holes", []), data.get("mismatches", [])
    if holes or mismatches:
        return Phase("matrix", False,
                     f"{len(holes)} hole(s), {len(mismatches)} mismatch(es)")
    return Phase("matrix", True, "holes 0, mismatches 0")


def _samples(problem_dir: Path, problem: Problem | None) -> Phase:
    if problem is None:
        return Phase("samples", False, "problem.json did not load")
    if not problem.examples:
        return Phase("samples", False, "problem.json declares no examples")
    missing = []
    for entry in problem.examples:
        stem = entry.get("test", "")
        if not (problem_dir / f"{stem}.in").exists():
            missing.append(f"{stem}.in")
    if missing:
        return Phase("samples", False, f"declared but absent: {', '.join(missing)}")
    return Phase("samples", True, f"{len(problem.examples)} sample(s)")


def _zoo(problem_dir: Path, problem: Problem | None) -> Phase:
    if problem is None:
        return Phase("zoo", False, "problem.json did not load")
    try:
        entries = scan(problem_dir, problem)["solutions"]
    except (ScanError, OSError) as exc:
        return Phase("zoo", False, str(exc))
    wrong = [e for e in entries if e["tag"] != "main"]
    if not wrong:
        return Phase("zoo", False, "only the model solution is present")
    return Phase("zoo", True, f"{len(entries)} solution(s), {len(wrong)} adversary")


def _model(problem_dir: Path, problem: Problem | None) -> Phase:
    if problem is None:
        return Phase("model_solution", False, "problem.json did not load")
    try:
        entries = scan(problem_dir, problem)["solutions"]
    except (ScanError, OSError) as exc:
        return Phase("model_solution", False, str(exc))
    mains = [e["file"] for e in entries if e["tag"] == "main"]
    return Phase("model_solution", bool(mains), ", ".join(mains) or "no @tag main")


def _checker(problem_dir: Path, problem: Problem | None,
             testlib_dir: Path | None) -> Phase:
    if problem is None:
        return Phase("checker", False, "problem.json did not load")
    if problem.checker_kind == "custom":
        src = problem_dir / "files" / problem.checker_name
        return Phase("checker", src.exists(),
                     str(src) if src.exists() else f"custom checker absent: {src}")
    if testlib_dir is None:
        return Phase("checker", True, f"stock {problem.checker_name} (not verified)")
    src = Path(testlib_dir) / "checkers" / f"{problem.checker_name}.cpp"
    return Phase("checker", src.exists(),
                 f"stock {problem.checker_name}"
                 if src.exists() else f"no such stock checker: {src}")


def _file_phase(name: str, path: Path, note: str) -> Phase:
    return Phase(name, path.exists(), str(path) if path.exists() else note)


def status(problem_dir, testlib_dir=None) -> list[Phase]:
    problem_dir = Path(problem_dir)
    problem, why = _problem(problem_dir)
    files = problem_dir / "files"
    gens = sorted(files.glob("gen-*.cpp"))
    return [
        Phase("problem_json", problem is not None,
              "loaded" if problem is not None else why or "problem.json missing"),
        _statement(problem_dir),
        _file_phase("constraints_header", files / "constraints.h",
                    "run gen_constraints_header"),
        _model(problem_dir, problem),
        _checker(problem_dir, problem, testlib_dir),
        _file_phase("validator", files / "validator.cpp", "files/validator.cpp absent"),
        Phase("generators", bool(gens),
              ", ".join(g.name for g in gens) or "no files/gen-*.cpp"),
        _tests(problem_dir, problem),
        _zoo(problem_dir, problem),
        _matrix(problem_dir),
        _samples(problem_dir, problem),
    ]


def next_phase(phases: list[Phase]) -> str | None:
    for phase in phases:
        if not phase.done:
            return phase.name
    return None


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print("usage: package_status.py <problem-dir> [testlib-dir]", file=sys.stderr)
        return 2
    phases = status(argv[1], argv[2] if len(argv) == 3 else None)
    for phase in phases:
        print(f"[{'x' if phase.done else ' '}] {phase.name:<20} {phase.detail}")
    remaining = next_phase(phases)
    print(f"\nnext: {remaining}" if remaining else "\ncomplete")
    return 0 if remaining is None else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run tests, then the full suite**

Expected: 12 new tests pass; suite rises to 166; nothing regresses.

- [ ] **Step 5: Run it against the real `flight` package**

```bash
cd ~/.claude/skills/competitive-programming
python3 -m tools.package_status ~/Projects/my_cp_problems/flight "$(bash tools/bootstrap_testlib.sh)"
```
Expected: every phase `[x]` and `complete` — `flight` is a finished package. If any phase reports incomplete, that is either a real gap in `flight` or a bug in this module; say which in your report.

- [ ] **Step 6: Commit**

Subject: `Report which pipeline phase a problem package has reached`

---

### Task 3: `tools/review_checks.py`

**Files:**
- Create: `tools/review_checks.py`
- Test: `tools/tests/test_review_checks.py`

**Interfaces:**
- Consumes: `problem_meta.load`/`ProblemMetaError`/`Problem`; `drift_check.check`; `scan_solutions.scan`/`ScanError`; `package_status.status`/`next_phase`.
- Produces:
  - `@dataclass(frozen=True) Finding(kind: str, severity: str, what: str, where: str)` with `severity` in `("high", "medium", "low")`
  - `KINDS: tuple[str, ...]` = `("constraint-drift", "incomplete-package", "orphan-solution", "sample-not-reproducible", "matrix-hole", "matrix-mismatch", "stale-constraints-header")`
  - `run(problem_dir, tex_path=None, testlib_dir=None) -> list[Finding]` — never raises; a check that cannot run becomes a `low` finding explaining why
  - `main(argv) -> int` — prints findings, exit 0 when none, 1 when any

**This module is the *mechanical* half of the audit only.** Statement ambiguity, assumed definitions and unproven solution steps are judgement and belong to the skill. Do not attempt them here.

- [ ] **Step 1: Write the failing test**

```python
import json, shutil, tempfile, unittest
from pathlib import Path

from tools.review_checks import KINDS, run

FIXTURE = Path("tools/tests/fixtures/mini")


class TestRun(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "p"
        shutil.copytree(FIXTURE, self.dir,
                        ignore=shutil.ignore_patterns(
                            ".build", "invocation.json", "solutions.json",
                            "flags.json", "*.a"))

    def kinds(self, **kw):
        return {f.kind for f in run(self.dir, **kw)}

    def test_every_finding_uses_a_declared_kind_and_severity(self):
        for finding in run(self.dir):
            self.assertIn(finding.kind, KINDS)
            self.assertIn(finding.severity, ("high", "medium", "low"))

    def test_an_unfinished_package_reports_incomplete(self):
        self.assertIn("incomplete-package", self.kinds())

    def test_a_malformed_problem_json_does_not_raise(self):
        (self.dir / "problem.json").write_text("{ not json", encoding="utf-8")
        self.assertTrue(run(self.dir))

    def test_holes_in_invocation_json_are_reported(self):
        (self.dir / "invocation.json").write_text(json.dumps(
            {"schema": 1, "holes": [{"solution": "sol-wrong.cpp", "group": "g1",
                                     "expected": "WA", "actual": "OK"}],
             "mismatches": []}), encoding="utf-8")
        findings = [f for f in run(self.dir) if f.kind == "matrix-hole"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "high")
        self.assertIn("sol-wrong.cpp", findings[0].what)

    def test_mismatches_are_reported_separately_from_holes(self):
        (self.dir / "invocation.json").write_text(json.dumps(
            {"schema": 1, "holes": [],
             "mismatches": [{"solution": "sol-alt.cpp", "group": "g2",
                             "expected": "OK", "actual": "WA"}]}), encoding="utf-8")
        self.assertIn("matrix-mismatch", self.kinds())
        self.assertNotIn("matrix-hole", self.kinds())

    def test_a_solution_file_absent_from_the_scan_is_an_orphan(self):
        (self.dir / "solutions" / "notes.txt").write_text("x", encoding="utf-8")
        self.assertNotIn("orphan-solution", self.kinds())
        (self.dir / "solutions" / "sol-orphan.cpp").write_text(
            "int main(){}\n", encoding="utf-8")
        findings = [f for f in run(self.dir) if f.kind == "orphan-solution"]
        self.assertEqual(len(findings), 1)
        self.assertIn("sol-orphan.cpp", findings[0].what)

    def test_a_constraints_header_older_than_problem_json_is_stale(self):
        header = self.dir / "files" / "constraints.h"
        header.parent.mkdir(exist_ok=True)
        header.write_text("#pragma once\n", encoding="utf-8")
        import os, time
        old = time.time() - 3600
        os.utime(header, (old, old))
        self.assertIn("stale-constraints-header", self.kinds())

    def test_a_fresh_constraints_header_is_not_reported(self):
        header = self.dir / "files" / "constraints.h"
        header.parent.mkdir(exist_ok=True)
        header.write_text("#pragma once\n", encoding="utf-8")
        self.assertNotIn("stale-constraints-header", self.kinds())

    def test_statement_drift_is_reported_when_a_tex_is_given(self):
        tex = self.dir / "mini.tex"
        tex.write_text(
            "\\begin{problem}[input = stdin, output = stdout,\n"
            "  time = 9, memory = 256,\n]{Mini}\n"
            "\\begin{subtasks}\\subtask{100}{x}\\end{subtasks}\n"
            "\\end{problem}\n", encoding="utf-8")
        findings = [f for f in run(self.dir, tex_path=tex)
                    if f.kind == "constraint-drift"]
        self.assertTrue(findings)
        self.assertEqual(findings[0].severity, "high")
```

- [ ] **Step 2: Run and confirm it fails**

Expected: `ModuleNotFoundError: No module named 'tools.review_checks'`

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
"""The mechanical half of a problem-package audit.

Everything here is a question a program can answer: does the statement agree
with problem.json, is a phase missing, is a solution file absent from the scan,
did the matrix leave a hole, is the generated header older than the source it
was generated from.

Deliberately *not* here: statement ambiguity, assumed definitions, and unproven
solution steps. Those are judgement, they belong to `reviewing-problems`, and a
tool that pretended to answer them would produce confident nonsense.

`run()` never raises: an audit that dies on the package it is auditing tells you
nothing. A check that cannot run becomes a `low` finding naming the obstacle.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.drift_check import check as drift
from tools.package_status import next_phase, status
from tools.problem_meta import Problem, ProblemMetaError, load
from tools.scan_solutions import ScanError, scan

KINDS = (
    "constraint-drift", "incomplete-package", "orphan-solution",
    "sample-not-reproducible", "matrix-hole", "matrix-mismatch",
    "stale-constraints-header",
)


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: str
    what: str
    where: str


def _drift(problem: Problem | None, tex_path: Path | None) -> list[Finding]:
    if problem is None or tex_path is None:
        return []
    try:
        issues = drift(problem, Path(tex_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding("constraint-drift", "low",
                        f"statement unreadable: {exc}", str(tex_path))]
    return [Finding("constraint-drift", "high", issue, str(tex_path))
            for issue in issues]


def _incomplete(problem_dir: Path, testlib_dir) -> list[Finding]:
    phases = status(problem_dir, testlib_dir)
    remaining = next_phase(phases)
    if remaining is None:
        return []
    detail = next(p.detail for p in phases if p.name == remaining)
    return [Finding("incomplete-package", "medium",
                    f"first incomplete phase: {remaining} ({detail})",
                    str(problem_dir))]


def _orphans(problem_dir: Path, problem: Problem | None) -> list[Finding]:
    if problem is None:
        return []
    try:
        scanned = {e["file"] for e in scan(problem_dir, problem)["solutions"]}
    except (ScanError, OSError) as exc:
        return [Finding("orphan-solution", "low",
                        f"solution scan failed: {exc}", str(problem_dir))]
    return [
        Finding("orphan-solution", "medium",
                f"{path.name} is in solutions/ but not in the scan", str(path))
        for path in sorted((problem_dir / "solutions").glob("*.cpp"))
        if path.name not in scanned
    ]


def _matrix(problem_dir: Path) -> list[Finding]:
    path = problem_dir / "invocation.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [Finding("matrix-hole", "low",
                        f"invocation.json unreadable: {exc}", str(path))]
    out = [
        Finding("matrix-hole", "high",
                f"{h.get('solution')} survived {h.get('group')} "
                f"(expected {h.get('expected')})", str(path))
        for h in data.get("holes", [])
    ]
    out += [
        Finding("matrix-mismatch", "high",
                f"{m.get('solution')} on {m.get('group')}: expected "
                f"{m.get('expected')}, got {m.get('actual')}", str(path))
        for m in data.get("mismatches", [])
    ]
    return out


def _stale_header(problem_dir: Path) -> list[Finding]:
    header = problem_dir / "files" / "constraints.h"
    source = problem_dir / "problem.json"
    if not header.exists() or not source.exists():
        return []
    if header.stat().st_mtime >= source.stat().st_mtime:
        return []
    return [Finding("stale-constraints-header", "high",
                    "constraints.h is older than problem.json; regenerate it "
                    "with `python3 -m tools.gen_constraints_header`", str(header))]


def _samples(problem_dir: Path, problem: Problem | None) -> list[Finding]:
    if problem is None:
        return []
    out = []
    for entry in problem.examples:
        stem = entry.get("test", "")
        inp, ans = problem_dir / f"{stem}.in", problem_dir / f"{stem}.a"
        if not inp.exists() or not ans.exists():
            out.append(Finding(
                "sample-not-reproducible", "high",
                f"sample {stem} is declared in problem.json but "
                f"{'input' if not inp.exists() else 'answer'} is missing",
                str(inp)))
    return out


def run(problem_dir, tex_path=None, testlib_dir=None) -> list[Finding]:
    problem_dir = Path(problem_dir)
    try:
        problem = load(problem_dir / "problem.json")
    except (ProblemMetaError, OSError):
        problem = None
    findings: list[Finding] = []
    findings += _drift(problem, tex_path)
    findings += _incomplete(problem_dir, testlib_dir)
    findings += _orphans(problem_dir, problem)
    findings += _matrix(problem_dir)
    findings += _stale_header(problem_dir)
    findings += _samples(problem_dir, problem)
    rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda f: (rank[f.severity], f.kind, f.what))


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 4:
        print("usage: review_checks.py <problem-dir> [statement.tex] [testlib-dir]",
              file=sys.stderr)
        return 2
    findings = run(argv[1],
                   tex_path=argv[2] if len(argv) > 2 else None,
                   testlib_dir=argv[3] if len(argv) > 3 else None)
    for f in findings:
        print(f"{f.severity.upper():<7} {f.kind:<26} {f.what}\n{'':>7} at {f.where}")
    print(f"\n{len(findings)} mechanical finding(s)" if findings
          else "\nno mechanical findings")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run tests, then the full suite**

Expected: 9 new tests pass; suite rises to 175; nothing regresses.

- [ ] **Step 5: Run it against the real `flight` package**

```bash
cd ~/.claude/skills/competitive-programming
python3 -m tools.review_checks ~/Projects/my_cp_problems/flight \
        ~/Projects/my_cp_problems/flight/flight.tex "$(bash tools/bootstrap_testlib.sh)"
```
Expected: `no mechanical findings`. `flight` is complete and clean, so any finding here is either a real defect in `flight` or a false positive in this module — investigate and say which. A false positive is the more serious of the two: this module gates the audit.

- [ ] **Step 6: Commit**

Subject: `Add the mechanical half of the problem-package audit`

---

### Task 4: `skills/shaping-problems/SKILL.md`

**Files:**
- Create: `skills/shaping-problems/SKILL.md`

**Interfaces:**
- Consumes: nothing in `tools/`.
- Produces: a skill named `shaping-problems` whose terminal state is a completed `problem.json` handed to `creating-problems`.

- [ ] **Step 1: Load `superpowers:writing-skills` and follow it**

- [ ] **Step 2: Write the file**

Frontmatter `name: shaping-problems`. The description must own **numbers**, so it does not collide with `writing-statements` (prose) or `brainstorming` (generic dialogue). Trigger vocabulary: *problem idea, is this problem interesting, what constraints, choose N, subtask ladder, difficulty, partial scoring, is this problem already known*. End with the neighbour disclaimer naming `writing-statements` for prose and `creating-problems` for the whole pipeline.

Required content:

1. **`## Am I the right skill?`** table naming `writing-statements`, `creating-problems`, `solving-problems`, with the contrast line *"Help me pick N" is not ambiguous. "Help me design a problem" is.*
2. **The brainstorming override, stated explicitly.** `superpowers:brainstorming` hard-gates on presenting a design and prescribes exactly one terminal action — invoke `writing-plans`, and no other skill. Here the terminal state is a completed `problem.json` handed to `creating-problems`. Say so, or the two fight. Invoke `brainstorming` for the dialogue when the idea is vague; skip it when the user arrives with a finished idea.
3. **Originality.** Before anything else: is this a known problem? Name the check — search the statement's core operation, not its story. A retelling of Penney's game with aeroplanes is still Penney's game, and that is fine as long as the setter knows it.
4. **Difficulty and the separation constraint.** The core judgement: choose N so the *intended* solution fits and the *naive* one does not. Give the arithmetic — if the intended solution is `O(n log n)` and the naive is `O(n²)`, then at 10⁸ operations/second, `n = 2·10⁵` makes the naive one ~4·10¹⁰ operations and the intended ~3.6·10⁶. State that a constraint which fails to separate them is the most common reason a problem is boring.
5. **The subtask ladder.** Each rung must pay for a *distinct insight*, not for typing. A rung that only reduces `n` without changing which algorithm works is a rung that pays for patience. Give the `flight` ladder as a worked example — `|A|,|B| ≤ 6` admits brute-force enumeration over coin sequences; the full constraint requires the automaton — and note that this ladder has exactly one real rung, which is honest for a two-subtask problem.
6. **What it hands over.** A completed `problem.json`: `name`, `title.vi`, `tags`, `limits`, `io`, `constraints` (with structured `min`/`max`), `subtasks` (with `bounds` **and** `constraints_text`), `checker`. The human never types JSON — the skill writes it from the decisions. Changing it later means re-opening the gate, not editing the file.
7. **Done means** `problem.json` loads through `python3 -m tools.package_status <dir>` with the `problem_json` phase `[x]`.

- [ ] **Step 3: Verify**

```bash
cd ~/.claude/skills/competitive-programming
claude plugin validate . --strict
grep -c '^name: shaping-problems$' skills/shaping-problems/SKILL.md   # 1
```

- [ ] **Step 4: Commit**

Subject: `Add shaping-problems: constraints, difficulty and the subtask ladder`

---

### Task 5: `skills/reviewing-problems/SKILL.md`

**Files:**
- Create: `skills/reviewing-problems/SKILL.md`

**Interfaces:**
- Consumes: `tools/review_checks.py`, `tools/package_status.py`, `tools/flags.py`.
- Produces: a skill named `reviewing-problems`, runnable standalone against any problem directory.

- [ ] **Step 1: Load `superpowers:writing-skills` and follow it**

- [ ] **Step 2: Write the file**

Frontmatter `name: reviewing-problems`. Description triggers on *review this problem, audit the package, is this problem ready, check my statement, is the statement ambiguous*. Disclaim `/code-review` explicitly — that audits a **diff**; this audits a **problem package**.

Required content:

1. **`## Am I the right skill?`** naming `/code-review`, `validating-solutions`, `creating-problems`.
2. **Bootstrap** — copied verbatim from `skills/preparing-tests/SKILL.md`, including `PROBLEM=` and `cd "$PLUGIN_ROOT"`.
3. **Run the mechanical half first, and do not redo it by hand:**
   ```bash
   python3 -m tools.review_checks "$PROBLEM" "$PROBLEM/<name>.tex" "$TESTLIB"
   ```
   It reports constraint drift, incomplete phases, orphan solutions, matrix holes and mismatches, a stale `constraints.h`, and samples declared but absent. Exit 1 means findings.
4. **Then the judgement half, which no tool can do.** This is the skill's real content:
   - **Statement ambiguity** — any sentence with two readings.
   - **Assumed definitions** — a term used as though the reader already knows it. **The worked example is real and must be included:** the `flight` statement's constraint line says `xâu con`, which reads as *substring* to most Vietnamese contestants and *subsequence* to some; the unambiguous form is `xâu con liên tiếp`. It was not fatal — the body defines occurrence precisely via `t_A` — but it survived the author's own verification pass and would have shipped. Say plainly that this class of defect is invisible to the person who wrote the statement, which is why this skill runs with fresh context.
   - **Unproven solution steps** — a `@algorithm` header comment claiming an invariant with no argument behind it.
   - **Checker/validator disagreement with the stated format** — the statement says two reals to 1e-6 but the checker is `wcmp` (token compare), or the validator accepts input the statement forbids.
5. **Run as a subagent with fresh context, not inline.** State the reason: a reviewer that inherited the assumptions of the agent that wrote the statement cannot see the assumed definition. Invoke `superpowers:requesting-code-review`.
6. **Mechanical findings it fixes and re-runs; judgement calls it flags** — via `python3 -m tools.flags`, or `from tools.flags import append`. Every flag needs `changes_if_wrong` filled in; that field is what prices an interruption before someone decides to make one.
7. **The one hard stop:** an unresolvable HIGH statement ambiguity. Everything else flags and continues.
8. **Done means** `review_checks` exits 0 and every judgement finding is either fixed or recorded in `flags.json` with `changes_if_wrong` populated. Invoke `superpowers:verification-before-completion`.

- [ ] **Step 3: Verify, and run the real acceptance test**

```bash
cd ~/.claude/skills/competitive-programming
claude plugin validate . --strict
grep -c '^name: reviewing-problems$' skills/reviewing-problems/SKILL.md   # 1
python3 -m tools.review_checks ~/Projects/my_cp_problems/flight \
        ~/Projects/my_cp_problems/flight/flight.tex "$(bash tools/bootstrap_testlib.sh)"
```
Expected: `no mechanical findings` — `flight` is clean mechanically. **The `xâu con` defect is deliberately invisible to the tool**; it is the judgement half's job, and Task 7 is where the skill gets tested against it.

- [ ] **Step 4: Commit**

Subject: `Add reviewing-problems: the mechanical audit plus the judgement half`

---

### Task 6: `skills/creating-problems/SKILL.md`, and the Stage 1 carry-forwards

**Files:**
- Create: `skills/creating-problems/SKILL.md`
- Modify: `skills/preparing-tests/SKILL.md`, `skills/validating-solutions/SKILL.md` (routing tables; stderr wording)
- Modify: `tools/run_matrix.py` (docstring only)

**Interfaces:**
- Consumes: every other skill, `tools/package_status.py`.
- Produces: a skill named `creating-problems`.

- [ ] **Step 1: Load `superpowers:writing-skills` and follow it**

- [ ] **Step 2: Write `creating-problems/SKILL.md`**

Frontmatter `name: creating-problems`. Description triggers on *create a problem, prepare a full problem package, set a problem end to end, take this idea to a Polygon package*. It is the "both" answer for every collision between the other skills — say so.

Required content:

1. **`## Am I the right skill?`** naming all five siblings, noting this one is the umbrella and the right answer whenever a request spans two of them.
2. **Two entry modes, detected at G1** — a finished idea and algorithm → prepare exactly that; a half-idea → delegate to `shaping-problems`.
3. **The gate model, exactly as the spec has it.** One blocking gate: **G1 — idea, story, subtasks**, which produces `problem.json`. Everything else **flags and continues**: algorithm choice, borderline TLE reclassification, checker stock-vs-custom, sample selection, every reviewer judgement call. Flags are emitted inline the moment they happen so an interruption is possible in real time. `changes_if_wrong` is mandatory because it prices the interruption. **The one exception:** an unresolvable HIGH statement ambiguity stops the pipeline, because that is the only case where continuing invalidates the whole package rather than one phase.
4. **The phase sequence**, with the loop-back edges drawn — statement (no `\Examples`) → model solution → `preparing-tests` → `validating-solutions` → samples → back to `writing-statements`. A surviving rejected solution routes back to the generators; disagreeing accepted solutions route to the arbiter, and from there to the model solution — or, when the arbiter cannot settle the disagreement and the cause is an unresolvable HIGH statement ambiguity, to the pipeline **stop** described in item 3. That case does not route to `writing-statements`; all three skills must agree on this single edge.
5. **Resumability**, and how it works: state lives entirely in files on disk, and `python3 -m tools.package_status "$PROBLEM" "$TESTLIB"` reports the first incomplete phase. Re-entering picks up there. Say why this matters — a pipeline that cannot restart after an interruption is one nobody interrupts, which defeats the flag register.
6. **Phases run as subagents.** Invoke `superpowers:subagent-driven-development`. A review subagent fires after each phase and at the end, via `reviewing-problems`.
7. **`superpowers:receiving-code-review` is load-bearing, not decorative.** A reviewer subagent will produce some findings that are simply wrong, and in a pipeline that fixes mechanical findings without asking, a hallucinated constraint violation would otherwise get a correct validator "fixed" into a broken one. Say that in those terms.
8. **`superpowers:writing-plans`** conditionally, when a problem needs more than the standard pipeline.
9. **Done means** `package_status` reports every phase complete and `review_checks` exits 0.

- [ ] **Step 3: Update both existing routing tables**

`preparing-tests/SKILL.md` and `validating-solutions/SKILL.md` currently mark `shaping-problems` and `creating-problems` as "Stage 2, not built yet. Say so and stop." All three now exist — remove that wording and route to them normally. Also add `reviewing-problems` as a neighbour in both.

- [ ] **Step 4: Fix the two carry-forward doc defects**

`tools/run_matrix.py:1256` and `skills/validating-solutions/SKILL.md:292` both claim "One line on stderr". A compile failure emits several, because `_compile`'s `MatrixError` embeds the command and g++'s full stderr. Reword both to "a message on stderr" — the exit code and the absence of a traceback are the parts that matter and are correct.

Add to `README.md`: `flags.py` leaves a permanent `flags.json.lock` beside `flags.json` in every problem package. Unlinking it is unsafe under `flock`, so it is documented rather than removed; problem repositories should gitignore it.

- [ ] **Step 5: Verify**

```bash
cd ~/.claude/skills/competitive-programming
claude plugin validate . --strict
claude plugin details competitive-programming      # expect 8 skills
python3 -m unittest discover -s tools/tests -t . -v
grep -rn 'not built yet' skills/                   # expect no matches
grep -rn 'One line on stderr' tools/ skills/       # expect no matches
```

- [ ] **Step 6: Commit**

Two commits: `Add creating-problems: the umbrella that owns the gates` and `Route to the Stage 2 skills and correct the stderr claim`.

---

### Task 7: Manifest, README, and the dogfood

**Files:**
- Modify: `.claude-plugin/plugin.json`, `README.md`

- [ ] **Step 1: Bump and document**

`plugin.json`: `version` to `0.6.0`; extend `description` to mention problem shaping, package review and end-to-end creation. `README.md`: three rows in the component table, the three skill directories and the two new `tools/` modules in the layout block.

- [ ] **Step 2: Verify the plugin**

```bash
claude plugin validate . --strict
claude plugin details competitive-programming     # expect 8 skills
python3 -m unittest discover -s tools/tests -t . -v
```

- [ ] **Step 3: The acceptance test — run `reviewing-problems` against `flight`**

This is what all of Stage 1 pointed at. `flight` is mechanically clean, so the mechanical half must report nothing, and the judgement half must find the thing a tool cannot:

**The `xâu con` assumed definition must surface**, in the constraint line of `~/Projects/my_cp_problems/flight/flight.tex`. It is already recorded as flag `amb-001` from the Stage 1 dogfood — so the honest test is whether the skill finds it *independently*, reading the statement fresh. Run the review without looking at `flags.json` first, then compare.

Report: did it find `xâu con`? Did it find anything else? Did it report anything that is not real? A false positive here matters more than a miss — this skill's whole value is that its findings are trustworthy.

- [ ] **Step 4: The second acceptance test — run `creating-problems` end to end on a new problem**

Pick something small and genuinely new — a two-subtask problem you can state in three sentences. Drive it from G1 to a complete package. Report where the skills were unclear, wrong, or hard to follow; that is the most valuable output of this task, exactly as it was in Stage 1 where the dogfood found a Critical eleven reviews had missed.

Do **not** commit the new problem directory to this repository.

- [ ] **Step 5: Commit**

Subject: `Bump to 0.6.0 for the shaping, review and creation skills`

---

## Self-review

**Spec coverage.** §6 gates and flags → Task 6 content items 3 and 5. §7 pipeline and loop-backs → Task 6 item 4. §8 `shaping-problems` → Task 4, including the brainstorming terminal-state override (item 2). §11 `reviewing-problems` → Tasks 3 and 5; every checklist item in §11 is assigned — drift, unreached bounds, holes and checker/validator disagreement are mechanical (Task 3) except the last, which is judgement (Task 5 item 4); ambiguity, assumed definitions and unproven steps are judgement (Task 5 item 4); "runs as a subagent with fresh context" is Task 5 item 5. §12 `creating-problems` → Task 6, with `receiving-code-review`'s rationale stated in the spec's own terms (item 7).

**Carry-forwards.** Cycle detection → Task 1. "One line on stderr" → Task 6 step 4. `flags.json.lock` → Task 6 step 4.

**Deliberately not in this plan:** the `run_matrix.py` narration prune (a large comment refactor, no correctness content, parked in Stage 1's ledger), and the remaining parked residuals from Stage 1's final review, which were triaged as correctly deferred.

**Placeholder scan:** clean — every code step carries real code, and the three SKILL.md tasks specify required content item by item rather than saying "write the skill".

**Type consistency:** `Phase(name, done, detail)` and `PHASE_ORDER` are defined in Task 2 and consumed by name in Task 3's `_incomplete`. `Finding(kind, severity, what, where)` and `KINDS` are defined in Task 3 and referenced in Task 5's skill content. `status(problem_dir, testlib_dir=None)` and `next_phase(phases)` keep the same signatures in both tasks. `run(problem_dir, tex_path=None, testlib_dir=None)` is used with keyword arguments in Task 3's tests and positionally in `main`, which matches the definition.

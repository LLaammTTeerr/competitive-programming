# Problem-Setting Pipeline, Stage 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `tools/` — deterministic, dependency-free Python that owns metadata, flags, the constraints header, the solution scan, drift checking and the invocation matrix — plus the two SKILL.md files that carry the doctrine `tools/` cannot.

**Architecture:** Executable tooling at plugin root under `tools/`, stdlib-only Python 3 so there is no venv and no dependency to resolve. Pure functions (limits, classification, holes) are separated from the process driver so the numeric core is unit-testable without compiling C++. The two skills reference the tools by path relative to their own base directory and contain no reimplementation of what a tool already does.

**Tech Stack:** Python 3.10+ (stdlib only: `json`, `dataclasses`, `subprocess`, `os.wait4`, `statistics`, `re`, `unittest`), bash, C++17 with `qhhoj/testlib`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-30-problem-setting-pipeline-design.md`. Every requirement there applies.
- **Python:** 3.10+, **stdlib only**. Adding any third-party dependency is a plan violation.
- **Tests:** `python3 -m unittest discover -s tools/tests -t . -v`, run from the plugin root. Zero deps.
- **C++ compile flags, everywhere:** `-std=c++17 -O2 -Wpedantic -Werror -I"$TESTLIB"`. Never `-ffast-math`.
- **Branch:** all work on `problem-setting-stage-1`, never on `main`.
- **Commit style:** imperative mood matching this repo's history (`Add writing-statements: …`), **not** conventional-commits prefixes. Every commit message ends with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017fQbXswuDyUTXGnVzPME8n
  ```
- **Generated files carry a header** naming the tool that wrote them and saying "do not edit".
- **Timestamps are derived, never written by hand** — `git log -1 --format=%cI -- <file>`, falling back to `stat` mtime.
- **`generated_at` appears only in `invocation.json` and `flags.json`.** Putting it in every file makes every run produce a diff, which trains the reader to stop reading diffs.

## Spec amendments made by this plan

1. **`subtasks[]` gains structured bounds.** The spec wrote subtask constraints as prose (`"|A| <= 6"`), which `gen_constraints_header.py` cannot turn into a constant. Subtasks now carry both:
   - `bounds` — machine-readable overrides of the global constraints, feeding `constraints.h`
   - `constraints_text` — prose, feeding the statement's subtask table and the drift check
2. **`run_matrix.py` reports `mismatches` alongside `holes`.** The spec defined only `holes` (a rejected solution that survived). The "accepted solution disagrees" exit needs the opposite direction, so a second array records every expectation that differed in any other way.
3. **Median-of-3 applies to the model solution and to band re-runs only.** Adversary solutions get one run; a result landing in `[TL, kill]` is re-run three times before being reported. Three runs of everything triples pipeline cost for no gain outside the band.

## File structure

```
competitive-programming/
  tools/
    __init__.py                    package marker
    problem_meta.py                load + validate problem.json; shared dataclasses
    flags.py                       the flag register
    gen_constraints_header.py      problem.json -> files/constraints.h
    scan_solutions.py              solution header comments -> solutions.json
    drift_check.py                 problem.json vs the .tex
    matrix_core.py                 PURE: limits, classification, holes
    run_matrix.py                  driver: compile, run, check, write invocation.json
    bootstrap_testlib.sh           clone/cache qhhoj/testlib
    tests/
      __init__.py
      test_problem_meta.py  test_flags.py  test_gen_constraints_header.py
      test_scan_solutions.py  test_drift_check.py  test_matrix_core.py
      fixtures/mini/             a tiny complete problem used by several tests
  skills/preparing-tests/SKILL.md
  skills/validating-solutions/SKILL.md
  .claude-plugin/plugin.json       version 0.4.0 -> 0.5.0
  README.md                        component table + layout block
```

`matrix_core.py` is split from `run_matrix.py` deliberately: the numeric decisions (what the limit is, what verdict a time implies, what counts as a hole) are the part that must be right, and they are testable without compiling anything or running a clock.

---

### Task 1: Branch, package skeleton, and `problem_meta.py`

**Files:**
- Create: `tools/__init__.py`, `tools/tests/__init__.py`, `tools/problem_meta.py`
- Test: `tools/tests/test_problem_meta.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `load(path) -> Problem`; `ProblemMetaError`; dataclasses `Problem`, `Subtask`, `Constraint`, `Bound`. `Problem` fields: `name: str`, `title: dict[str,str]`, `tags: list[str]`, `time_ms_published: int`, `time_ms_computed: int|None`, `memory_mb: int`, `input: str`, `output: str`, `checker_kind: str`, `checker_name: str`, `constraints: list[Constraint]`, `subtasks: list[Subtask]`, `examples: list[dict]`. `Constraint` fields: `id: str`, `expr: str`, `min: int|None`, `max: int|None`. `Subtask` fields: `id: str`, `points: int`, `bounds: dict[str, Bound]`, `constraints_text: list[str]`, `depends_on: list[str]`. `Bound` fields: `min: int|None`, `max: int|None`.

- [ ] **Step 1: Create the branch**

```bash
cd ~/.claude/skills/competitive-programming
git checkout -b problem-setting-stage-1
mkdir -p tools/tests/fixtures/mini
touch tools/__init__.py tools/tests/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tools/tests/test_problem_meta.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from tools.problem_meta import ProblemMetaError, load

VALID = {
    "schema": 1,
    "name": "flight",
    "title": {"vi": "Chuyến bay đầu tiên"},
    "tags": ["probability", "strings"],
    "limits": {"time_ms_published": 1000, "time_ms_computed": 740, "memory_mb": 256},
    "io": {"input": "stdin", "output": "stdout"},
    "checker": {"kind": "stock", "name": "rcmp6"},
    "constraints": [
        {"id": "len_a", "expr": "1 \\le |A| \\le 20", "min": 1, "max": 20},
        {"id": "len_b", "expr": "1 \\le |B| \\le 20", "min": 1, "max": 20},
    ],
    "subtasks": [
        {"id": "g1", "points": 40,
         "bounds": {"len_a": {"max": 6}, "len_b": {"max": 6}},
         "constraints_text": ["$|A| \\le 6$ và $|B| \\le 6$"],
         "depends_on": []},
        {"id": "g2", "points": 60, "bounds": {},
         "constraints_text": ["Không có ràng buộc gì thêm"],
         "depends_on": ["g1"]},
    ],
    "examples": [{"test": "sample-01", "note": "A thắng"}],
}


def write(payload):
    tmp = Path(tempfile.mkdtemp()) / "problem.json"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    return tmp


class TestLoad(unittest.TestCase):
    def test_loads_valid_document(self):
        problem = load(write(VALID))
        self.assertEqual(problem.name, "flight")
        self.assertEqual(problem.time_ms_published, 1000)
        self.assertEqual(problem.checker_name, "rcmp6")
        self.assertEqual([s.id for s in problem.subtasks], ["g1", "g2"])
        self.assertEqual(problem.subtasks[0].bounds["len_a"].max, 6)
        self.assertIsNone(problem.subtasks[0].bounds["len_a"].min)
        self.assertEqual(problem.constraints[0].max, 20)

    def test_rejects_unknown_schema(self):
        bad = dict(VALID, schema=2)
        with self.assertRaisesRegex(ProblemMetaError, "schema"):
            load(write(bad))

    def test_rejects_points_not_summing_to_100(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["points"] = 30
        with self.assertRaisesRegex(ProblemMetaError, "100"):
            load(write(bad))

    def test_rejects_duplicate_subtask_id(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][1]["id"] = "g1"
        with self.assertRaisesRegex(ProblemMetaError, "duplicate"):
            load(write(bad))

    def test_rejects_dependency_on_unknown_subtask(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][1]["depends_on"] = ["g9"]
        with self.assertRaisesRegex(ProblemMetaError, "g9"):
            load(write(bad))

    def test_rejects_subtask_bound_naming_unknown_constraint(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["bounds"] = {"len_z": {"max": 6}}
        with self.assertRaisesRegex(ProblemMetaError, "len_z"):
            load(write(bad))

    def test_rejects_unknown_checker_kind(self):
        bad = json.loads(json.dumps(VALID))
        bad["checker"]["kind"] = "magic"
        with self.assertRaisesRegex(ProblemMetaError, "magic"):
            load(write(bad))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run it and confirm it fails**

Run: `cd ~/.claude/skills/competitive-programming && python3 -m unittest tools.tests.test_problem_meta -v`
Expected: `ModuleNotFoundError: No module named 'tools.problem_meta'`

- [ ] **Step 4: Implement `tools/problem_meta.py`**

```python
"""Load and validate problem.json — the pipeline's single source of truth."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = 1
CHECKER_KINDS = ("stock", "custom")


class ProblemMetaError(ValueError):
    """problem.json is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Bound:
    min: int | None = None
    max: int | None = None


@dataclass(frozen=True)
class Constraint:
    id: str
    expr: str
    min: int | None = None
    max: int | None = None


@dataclass(frozen=True)
class Subtask:
    id: str
    points: int
    bounds: dict[str, Bound] = field(default_factory=dict)
    constraints_text: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Problem:
    name: str
    title: dict[str, str]
    tags: list[str]
    time_ms_published: int
    time_ms_computed: int | None
    memory_mb: int
    input: str
    output: str
    checker_kind: str
    checker_name: str
    constraints: list[Constraint]
    subtasks: list[Subtask]
    examples: list[dict]

    def constraint(self, cid: str) -> Constraint:
        for c in self.constraints:
            if c.id == cid:
                return c
        raise KeyError(cid)

    def subtask_ids(self) -> list[str]:
        return [s.id for s in self.subtasks]

    def effective_bound(self, subtask_id: str, constraint_id: str) -> Bound:
        """Global bound, narrowed by the subtask's override if it has one."""
        base = self.constraint(constraint_id)
        bound = Bound(base.min, base.max)
        for sub in self.subtasks:
            if sub.id != subtask_id:
                continue
            override = sub.bounds.get(constraint_id)
            if override is not None:
                bound = Bound(
                    override.min if override.min is not None else bound.min,
                    override.max if override.max is not None else bound.max,
                )
        return bound


def load(path: str | Path) -> Problem:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProblemMetaError(f"{path}: not valid JSON: {exc}") from exc

    if raw.get("schema") != SCHEMA:
        raise ProblemMetaError(
            f"{path}: unsupported schema {raw.get('schema')!r}, expected {SCHEMA}"
        )

    limits = raw.get("limits", {})
    io = raw.get("io", {})
    checker = raw.get("checker", {})

    if checker.get("kind") not in CHECKER_KINDS:
        raise ProblemMetaError(
            f"{path}: checker.kind is {checker.get('kind')!r}, "
            f"expected one of {CHECKER_KINDS}"
        )

    constraints = [
        Constraint(id=c["id"], expr=c["expr"], min=c.get("min"), max=c.get("max"))
        for c in raw.get("constraints", [])
    ]
    seen_c: set[str] = set()
    for c in constraints:
        if c.id in seen_c:
            raise ProblemMetaError(f"{path}: duplicate constraint id {c.id!r}")
        seen_c.add(c.id)

    subtasks = [
        Subtask(
            id=s["id"],
            points=s["points"],
            bounds={
                k: Bound(v.get("min"), v.get("max"))
                for k, v in s.get("bounds", {}).items()
            },
            constraints_text=list(s.get("constraints_text", [])),
            depends_on=list(s.get("depends_on", [])),
        )
        for s in raw.get("subtasks", [])
    ]

    seen_s: set[str] = set()
    for s in subtasks:
        if s.id in seen_s:
            raise ProblemMetaError(f"{path}: duplicate subtask id {s.id!r}")
        seen_s.add(s.id)

    total = sum(s.points for s in subtasks)
    if subtasks and total != 100:
        raise ProblemMetaError(f"{path}: subtask points sum to {total}, must be 100")

    for s in subtasks:
        for dep in s.depends_on:
            if dep not in seen_s:
                raise ProblemMetaError(
                    f"{path}: subtask {s.id!r} depends on unknown subtask {dep!r}"
                )
        for cid in s.bounds:
            if cid not in seen_c:
                raise ProblemMetaError(
                    f"{path}: subtask {s.id!r} bounds unknown constraint {cid!r}"
                )

    return Problem(
        name=raw["name"],
        title=raw.get("title", {}),
        tags=list(raw.get("tags", [])),
        time_ms_published=limits["time_ms_published"],
        time_ms_computed=limits.get("time_ms_computed"),
        memory_mb=limits["memory_mb"],
        input=io.get("input", "stdin"),
        output=io.get("output", "stdout"),
        checker_kind=checker["kind"],
        checker_name=checker["name"],
        constraints=constraints,
        subtasks=subtasks,
        examples=list(raw.get("examples", [])),
    )
```

- [ ] **Step 5: Run tests and confirm they pass**

Run: `python3 -m unittest tools.tests.test_problem_meta -v`
Expected: 7 tests, all PASS

- [ ] **Step 6: Commit**

```bash
git add tools/__init__.py tools/tests/__init__.py tools/problem_meta.py tools/tests/test_problem_meta.py
git commit
```
Message: `Add problem.json loader with cross-field validation` plus the two required trailers.

---

### Task 2: `flags.py` — the flag register

**Files:**
- Create: `tools/flags.py`
- Test: `tools/tests/test_flags.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `append(problem_dir, *, phase, severity, kind, what, assumed, changes_if_wrong, now=None) -> dict` returning the written record; `read(problem_dir) -> list[dict]`; `FlagError`; constants `SEVERITIES`, `KIND_PREFIX`.

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_flags.py`:

```python
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools import flags

FIXED = datetime(2026, 7, 30, 14, 2, 11, tzinfo=timezone(timedelta(hours=7)))


class TestAppend(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def append(self, **overrides):
        payload = dict(
            phase="prepare-tests",
            severity="high",
            kind="statement-ambiguity",
            what='"xâu con" reads as substring or as subsequence',
            assumed="substring (contiguous)",
            changes_if_wrong="sol-main, gen-boundary, 3 tests in g1",
            now=FIXED,
        )
        payload.update(overrides)
        return flags.append(self.dir, **payload)

    def test_writes_record_with_derived_id_and_timestamp(self):
        record = self.append()
        self.assertEqual(record["id"], "amb-001")
        self.assertEqual(record["at"], "2026-07-30T14:02:11+07:00")
        self.assertEqual(record["severity"], "high")

    def test_numbers_within_a_prefix_independently(self):
        self.append()
        self.append()
        third = self.append(kind="algorithm-choice", severity="medium")
        fourth = self.append()
        self.assertEqual(third["id"], "alg-001")
        self.assertEqual(fourth["id"], "amb-003")

    def test_read_returns_every_record_in_order(self):
        self.append()
        self.append(kind="timing-band", severity="low")
        ids = [r["id"] for r in flags.read(self.dir)]
        self.assertEqual(ids, ["amb-001", "tim-001"])

    def test_file_is_valid_json_with_generated_at(self):
        self.append()
        payload = json.loads((self.dir / "flags.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], 1)
        self.assertIn("generated_at", payload)
        self.assertEqual(len(payload["flags"]), 1)

    def test_rejects_unknown_kind(self):
        with self.assertRaisesRegex(flags.FlagError, "vibes"):
            self.append(kind="vibes")

    def test_rejects_unknown_severity(self):
        with self.assertRaisesRegex(flags.FlagError, "catastrophic"):
            self.append(severity="catastrophic")

    def test_rejects_empty_changes_if_wrong(self):
        with self.assertRaisesRegex(flags.FlagError, "changes_if_wrong"):
            self.append(changes_if_wrong="")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m unittest tools.tests.test_flags -v`
Expected: `ModuleNotFoundError: No module named 'tools.flags'`

- [ ] **Step 3: Implement `tools/flags.py`**

```python
"""The flag register: every autonomous judgement call the pipeline makes.

Flags do not stop the pipeline. `changes_if_wrong` is mandatory because it is
what prices an interruption before the reader decides to make one.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

SCHEMA = 1
FILENAME = "flags.json"
SEVERITIES = ("low", "medium", "high")

# Kinds are a closed set so the register stays scannable. Adding one is a
# deliberate act, not a typo.
KIND_PREFIX = {
    "statement-ambiguity": "amb",
    "algorithm-choice": "alg",
    "timing-band": "tim",
    "checker-choice": "chk",
    "sample-choice": "smp",
    "review-judgement": "rev",
    "test-weakness": "tst",
    "constraint-drift": "drf",
}


class FlagError(ValueError):
    """A flag was malformed."""


def _path(problem_dir: str | Path) -> Path:
    return Path(problem_dir) / FILENAME


def read(problem_dir: str | Path) -> list[dict]:
    path = _path(problem_dir)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("flags", [])


def append(
    problem_dir: str | Path,
    *,
    phase: str,
    severity: str,
    kind: str,
    what: str,
    assumed: str,
    changes_if_wrong: str,
    now: datetime | None = None,
) -> dict:
    if kind not in KIND_PREFIX:
        raise FlagError(f"unknown flag kind {kind!r}; known: {sorted(KIND_PREFIX)}")
    if severity not in SEVERITIES:
        raise FlagError(f"unknown severity {severity!r}; known: {SEVERITIES}")
    if not changes_if_wrong.strip():
        raise FlagError("changes_if_wrong is mandatory — it prices the interruption")

    stamp = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    prefix = KIND_PREFIX[kind]
    existing = read(problem_dir)
    n = sum(1 for r in existing if r["id"].startswith(f"{prefix}-")) + 1

    record = {
        "id": f"{prefix}-{n:03d}",
        "phase": phase,
        "severity": severity,
        "kind": kind,
        "what": what,
        "assumed": assumed,
        "changes_if_wrong": changes_if_wrong,
        "at": stamp,
    }

    payload = {
        "schema": SCHEMA,
        "generated_at": stamp,
        "flags": existing + [record],
    }
    path = _path(problem_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return record
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `python3 -m unittest tools.tests.test_flags -v`
Expected: 7 tests, all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/flags.py tools/tests/test_flags.py
git commit
```
Message: `Add the flag register with a closed set of flag kinds`

---

### Task 3: `gen_constraints_header.py`

**Files:**
- Create: `tools/gen_constraints_header.py`
- Test: `tools/tests/test_gen_constraints_header.py`

**Interfaces:**
- Consumes: `tools.problem_meta.load`, `Problem`, `Bound`.
- Produces: `render(problem) -> str`; `main(argv) -> int` writing `<problem_dir>/files/constraints.h`. Emitted identifiers are `<CONSTRAINT_ID>_MIN` / `_MAX` globally and `<SUBTASK_ID>_<CONSTRAINT_ID>_MIN` / `_MAX` per subtask, all upper-case with non-alphanumerics replaced by `_`.

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_gen_constraints_header.py`:

```python
import unittest

from tools.gen_constraints_header import identifier, render
from tools.problem_meta import Bound, Constraint, Problem, Subtask

PROBLEM = Problem(
    name="flight",
    title={"vi": "Chuyến bay đầu tiên"},
    tags=[],
    time_ms_published=1000,
    time_ms_computed=740,
    memory_mb=256,
    input="stdin",
    output="stdout",
    checker_kind="stock",
    checker_name="rcmp6",
    constraints=[
        Constraint(id="len_a", expr="1 \\le |A| \\le 20", min=1, max=20),
        Constraint(id="alphabet", expr="A in {0,1}*"),
    ],
    subtasks=[
        Subtask(id="g1", points=40, bounds={"len_a": Bound(max=6)},
                constraints_text=["$|A| \\le 6$"], depends_on=[]),
        Subtask(id="g2", points=60, bounds={}, constraints_text=[], depends_on=["g1"]),
    ],
    examples=[],
)


class TestIdentifier(unittest.TestCase):
    def test_upper_cases_and_replaces_punctuation(self):
        self.assertEqual(identifier("len_a"), "LEN_A")
        self.assertEqual(identifier("sum-n"), "SUM_N")


class TestRender(unittest.TestCase):
    def setUp(self):
        self.header = render(PROBLEM)

    def test_marks_itself_generated(self):
        self.assertIn("do not edit", self.header.lower())
        self.assertIn("gen_constraints_header.py", self.header)
        self.assertIn("#pragma once", self.header)

    def test_emits_global_bounds(self):
        self.assertIn("static const long long LEN_A_MIN = 1;", self.header)
        self.assertIn("static const long long LEN_A_MAX = 20;", self.header)

    def test_skips_constraints_without_numeric_bounds(self):
        self.assertNotIn("ALPHABET_MIN", self.header)
        self.assertNotIn("ALPHABET_MAX", self.header)

    def test_emits_narrowed_subtask_bounds(self):
        self.assertIn("static const long long G1_LEN_A_MAX = 6;", self.header)
        self.assertIn("static const long long G1_LEN_A_MIN = 1;", self.header)

    def test_subtask_without_override_inherits_global(self):
        self.assertIn("static const long long G2_LEN_A_MAX = 20;", self.header)

    def test_carries_the_expression_as_a_comment(self):
        self.assertIn("1 \\le |A| \\le 20", self.header)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m unittest tools.tests.test_gen_constraints_header -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `tools/gen_constraints_header.py`**

```python
#!/usr/bin/env python3
"""Generate files/constraints.h from problem.json.

The validator cannot take bounds on the command line — testlib opts are
generator-only (plan.md O-09) — so bounds must be compile-time constants.
Generating them from problem.json is what makes drift impossible rather than
merely discouraged.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from tools.problem_meta import Problem, load

HEADER = """\
// GENERATED by tools/gen_constraints_header.py from problem.json — do not edit.
// Regenerate with:  python3 tools/gen_constraints_header.py <problem-dir>
#pragma once
"""


def identifier(raw: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", raw).strip("_").upper()


def _emit(name: str, value: int) -> str:
    return f"static const long long {name} = {value};"


def render(problem: Problem) -> str:
    lines = [HEADER, ""]

    lines.append("// ---- global bounds " + "-" * 55)
    for c in problem.constraints:
        if c.min is None and c.max is None:
            continue
        lines.append(f"// {c.id}: {c.expr}")
        if c.min is not None:
            lines.append(_emit(f"{identifier(c.id)}_MIN", c.min))
        if c.max is not None:
            lines.append(_emit(f"{identifier(c.id)}_MAX", c.max))
        lines.append("")

    for sub in problem.subtasks:
        lines.append(f"// ---- subtask {sub.id} ({sub.points}%) " + "-" * 40)
        for text in sub.constraints_text:
            lines.append(f"//   {text}")
        for c in problem.constraints:
            if c.min is None and c.max is None:
                continue
            bound = problem.effective_bound(sub.id, c.id)
            prefix = f"{identifier(sub.id)}_{identifier(c.id)}"
            if bound.min is not None:
                lines.append(_emit(f"{prefix}_MIN", bound.min))
            if bound.max is not None:
                lines.append(_emit(f"{prefix}_MAX", bound.max))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: gen_constraints_header.py <problem-dir>", file=sys.stderr)
        return 2
    problem_dir = Path(argv[1])
    problem = load(problem_dir / "problem.json")
    out = problem_dir / "files" / "constraints.h"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(problem), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `python3 -m unittest tools.tests.test_gen_constraints_header -v`
Expected: 7 tests, all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/gen_constraints_header.py tools/tests/test_gen_constraints_header.py
git commit
```
Message: `Generate constraints.h from problem.json so validator bounds cannot drift`

---

### Task 4: `scan_solutions.py`

**Files:**
- Create: `tools/scan_solutions.py`
- Test: `tools/tests/test_scan_solutions.py`

**Interfaces:**
- Consumes: `tools.problem_meta.load`, `Problem`.
- Produces: `parse_block(text) -> dict` (raises `ScanError`); `scan(problem_dir, problem) -> dict` returning the `solutions.json` payload; `main(argv) -> int`. Constants `TAGS`, `VERDICTS`.

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_scan_solutions.py`:

```python
import tempfile
import unittest
from pathlib import Path

from tools.problem_meta import Constraint, Problem, Subtask
from tools.scan_solutions import ScanError, parse_block, scan

MAIN = """\
/**
 * @tag        main
 * @expect     g1=OK g2=OK
 * @algorithm  Aho-Corasick over {A,B} plus a linear solve on the absorbing chain.
 * @complexity O((|A|+|B|)^3)
 */
int main() { return 0; }
"""

GREEDY = """\
/**
 * @tag        wrong-answer
 * @expect     g1=WA g2=WA
 * @algorithm  Compares first occurrence by START index rather than END index.
 * @why-wrong  Diverges from the model exactly when |A| != |B|.
 * @complexity O(|A| + |B|)
 */
int main() { return 0; }
"""

PROBLEM = Problem(
    name="flight", title={}, tags=[], time_ms_published=1000, time_ms_computed=None,
    memory_mb=256, input="stdin", output="stdout",
    checker_kind="stock", checker_name="rcmp6",
    constraints=[Constraint(id="len_a", expr="x", min=1, max=20)],
    subtasks=[Subtask(id="g1", points=40), Subtask(id="g2", points=60)],
    examples=[],
)


class TestParseBlock(unittest.TestCase):
    def test_extracts_every_field(self):
        parsed = parse_block(GREEDY)
        self.assertEqual(parsed["tag"], "wrong-answer")
        self.assertEqual(parsed["expect"], {"g1": "WA", "g2": "WA"})
        self.assertTrue(parsed["algorithm"].startswith("Compares first occurrence"))
        self.assertIn("Diverges", parsed["why_wrong"])
        self.assertEqual(parsed["complexity"], "O(|A| + |B|)")

    def test_why_wrong_is_optional(self):
        self.assertIsNone(parse_block(MAIN)["why_wrong"])

    def test_rejects_missing_tag(self):
        with self.assertRaisesRegex(ScanError, "@tag"):
            parse_block("/**\n * @expect g1=OK\n */\n")

    def test_rejects_unknown_tag(self):
        with self.assertRaisesRegex(ScanError, "sideways"):
            parse_block("/**\n * @tag sideways\n * @expect g1=OK\n"
                        " * @algorithm x\n * @complexity O(1)\n */\n")

    def test_rejects_unknown_verdict(self):
        with self.assertRaisesRegex(ScanError, "MAYBE"):
            parse_block("/**\n * @tag main\n * @expect g1=MAYBE\n"
                        " * @algorithm x\n * @complexity O(1)\n */\n")


class TestScan(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "solutions").mkdir()
        (self.dir / "solutions" / "sol-main.cpp").write_text(MAIN, encoding="utf-8")
        (self.dir / "solutions" / "sol-greedy.cpp").write_text(GREEDY, encoding="utf-8")

    def test_collects_every_solution_sorted_by_filename(self):
        payload = scan(self.dir, PROBLEM)
        self.assertEqual([s["file"] for s in payload["solutions"]],
                         ["sol-greedy.cpp", "sol-main.cpp"])
        self.assertEqual(payload["schema"], 1)

    def test_derives_an_updated_timestamp_for_each_solution(self):
        for entry in scan(self.dir, PROBLEM)["solutions"]:
            self.assertRegex(entry["updated"], r"^\d{4}-\d{2}-\d{2}T")

    def test_rejects_expect_naming_an_unknown_group(self):
        (self.dir / "solutions" / "sol-bad.cpp").write_text(
            MAIN.replace("g2=OK", "g9=OK"), encoding="utf-8")
        with self.assertRaisesRegex(ScanError, "g9"):
            scan(self.dir, PROBLEM)

    def test_rejects_expect_missing_a_group(self):
        (self.dir / "solutions" / "sol-bad.cpp").write_text(
            MAIN.replace(" g2=OK", ""), encoding="utf-8")
        with self.assertRaisesRegex(ScanError, "g2"):
            scan(self.dir, PROBLEM)

    def test_rejects_two_main_solutions(self):
        (self.dir / "solutions" / "sol-other.cpp").write_text(MAIN, encoding="utf-8")
        with self.assertRaisesRegex(ScanError, "exactly one"):
            scan(self.dir, PROBLEM)

    def test_rejects_no_main_solution(self):
        (self.dir / "solutions" / "sol-main.cpp").unlink()
        with self.assertRaisesRegex(ScanError, "exactly one"):
            scan(self.dir, PROBLEM)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m unittest tools.tests.test_scan_solutions -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `tools/scan_solutions.py`**

```python
#!/usr/bin/env python3
"""Scan solution header comments into solutions.json.

Metadata beside the code cannot desynchronize from it, and renaming a file does
not orphan it. solutions.json is therefore a scan product, regenerated on every
run and never hand-edited.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.problem_meta import Problem, load

SCHEMA = 1

TAGS = (
    "main",
    "accepted",
    "wrong-answer",
    "time-limit-exceeded",
    "time-limit-exceeded-or-accepted",
    "memory-limit-exceeded",
    "presentation-error",
    "failed",
)

VERDICTS = ("OK", "WA", "TL", "ML", "PE", "RE")

_FIELD = re.compile(r"^\s*\*?\s*@(?P<key>[a-z-]+)\s+(?P<value>.+?)\s*$")


class ScanError(ValueError):
    """A solution's metadata block is malformed or contradicts problem.json."""


def parse_block(text: str) -> dict:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "*/" in line:
            break
        match = _FIELD.match(line)
        if match:
            fields[match.group("key")] = match.group("value")

    for required in ("tag", "expect", "algorithm", "complexity"):
        if required not in fields:
            raise ScanError(f"metadata block is missing @{required}")

    tag = fields["tag"]
    if tag not in TAGS:
        raise ScanError(f"unknown @tag {tag!r}; known: {TAGS}")

    expect: dict[str, str] = {}
    for token in fields["expect"].split():
        if "=" not in token:
            raise ScanError(f"malformed @expect entry {token!r}, want group=VERDICT")
        group, verdict = token.split("=", 1)
        if verdict not in VERDICTS:
            raise ScanError(f"unknown verdict {verdict!r} in @expect; known: {VERDICTS}")
        expect[group] = verdict

    return {
        "tag": tag,
        "expect": expect,
        "algorithm": fields["algorithm"],
        "why_wrong": fields.get("why-wrong"),
        "complexity": fields["complexity"],
    }


def _updated(path: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", path.name],
            cwd=path.parent, capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return stamp.astimezone().isoformat(timespec="seconds")


def scan(problem_dir: str | Path, problem: Problem) -> dict:
    problem_dir = Path(problem_dir)
    groups = problem.subtask_ids()
    entries = []

    for path in sorted((problem_dir / "solutions").glob("*.cpp")):
        try:
            parsed = parse_block(path.read_text(encoding="utf-8"))
        except ScanError as exc:
            raise ScanError(f"{path.name}: {exc}") from exc

        for group in parsed["expect"]:
            if group not in groups:
                raise ScanError(
                    f"{path.name}: @expect names unknown group {group!r}; "
                    f"problem.json declares {groups}"
                )
        for group in groups:
            if group not in parsed["expect"]:
                raise ScanError(f"{path.name}: @expect is missing group {group!r}")

        entries.append({"file": path.name, "updated": _updated(path), **parsed})

    mains = [e for e in entries if e["tag"] == "main"]
    if len(mains) != 1:
        raise ScanError(f"expected exactly one @tag main, found {len(mains)}")

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "solutions": entries,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: scan_solutions.py <problem-dir>", file=sys.stderr)
        return 2
    problem_dir = Path(argv[1])
    payload = scan(problem_dir, load(problem_dir / "problem.json"))
    out = problem_dir / "solutions.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {out} ({len(payload['solutions'])} solutions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `python3 -m unittest tools.tests.test_scan_solutions -v`
Expected: 12 tests, all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/scan_solutions.py tools/tests/test_scan_solutions.py
git commit
```
Message: `Scan solution header comments into solutions.json`

---

### Task 5: `drift_check.py`

**Files:**
- Create: `tools/drift_check.py`
- Test: `tools/tests/test_drift_check.py`

**Interfaces:**
- Consumes: `tools.problem_meta.load`, `Problem`.
- Produces: `parse_tex(text) -> dict` with keys `time`, `memory`, `input`, `output`, `subtask_points`; `check(problem, tex_text) -> list[str]` returning human-readable mismatches, empty when clean; `main(argv) -> int` exiting 1 on any mismatch.

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_drift_check.py`:

```python
import unittest

from tools.drift_check import check, parse_tex
from tools.problem_meta import Constraint, Problem, Subtask

TEX = r"""
\documentclass[11pt, a4paper, oneside]{article}
\usepackage[vietnamese, color, standalone]{vnolymp}
\begin{document}
\begin{problem}[
  input  = stdin, output = stdout,
  time   = 1, memory = 256,
]{Chuyến bay đầu tiên}
Nội dung.
\begin{subtasks}
  \subtask{40}{$|A| \le 6$ và $|B| \le 6$}
  \subtask{60}{Không có ràng buộc gì thêm}
\end{subtasks}
\end{problem}
\end{document}
"""

PROBLEM = Problem(
    name="flight", title={}, tags=[], time_ms_published=1000, time_ms_computed=740,
    memory_mb=256, input="stdin", output="stdout",
    checker_kind="stock", checker_name="rcmp6",
    constraints=[Constraint(id="len_a", expr="x", min=1, max=20)],
    subtasks=[Subtask(id="g1", points=40), Subtask(id="g2", points=60)],
    examples=[],
)


class TestParseTex(unittest.TestCase):
    def test_reads_the_problem_key_list(self):
        parsed = parse_tex(TEX)
        self.assertEqual(parsed["time"], 1)
        self.assertEqual(parsed["memory"], 256)
        self.assertEqual(parsed["input"], "stdin")
        self.assertEqual(parsed["output"], "stdout")

    def test_reads_subtask_percentages_in_order(self):
        self.assertEqual(parse_tex(TEX)["subtask_points"], [40, 60])


class TestCheck(unittest.TestCase):
    def test_clean_document_reports_nothing(self):
        self.assertEqual(check(PROBLEM, TEX), [])

    def test_detects_time_mismatch(self):
        problems = check(PROBLEM, TEX.replace("time   = 1", "time   = 2"))
        self.assertEqual(len(problems), 1)
        self.assertIn("time", problems[0])

    def test_detects_memory_mismatch(self):
        problems = check(PROBLEM, TEX.replace("memory = 256", "memory = 512"))
        self.assertIn("memory", problems[0])

    def test_detects_subtask_points_mismatch(self):
        problems = check(PROBLEM, TEX.replace(r"\subtask{40}", r"\subtask{30}"))
        self.assertIn("subtask", problems[0].lower())

    def test_detects_subtask_count_mismatch(self):
        stripped = TEX.replace(
            "  \\subtask{60}{Không có ràng buộc gì thêm}\n", "")
        problems = check(PROBLEM, stripped)
        self.assertTrue(problems)

    def test_detects_io_mismatch(self):
        problems = check(PROBLEM, TEX.replace("input  = stdin", "input  = flight.inp"))
        self.assertIn("input", problems[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m unittest tools.tests.test_drift_check -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `tools/drift_check.py`**

```python
#!/usr/bin/env python3
"""Compare problem.json against the vnolymp statement.

The statement is not generated — templating the .tex would fight vnolymp — so
this is the guard that stops the two from disagreeing. Parsing is regex over
two very specific constructs, which is adequate for the vnolymp key list and
the subtasks environment and nothing else.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from tools.problem_meta import Problem, load

_KEYLIST = re.compile(r"\\begin\{problem\}\s*\[(?P<keys>.*?)\]", re.DOTALL)
_SUBTASK = re.compile(r"\\subtask\{(?P<points>\d+)\}")


def parse_tex(text: str) -> dict:
    match = _KEYLIST.search(text)
    keys: dict[str, str] = {}
    if match:
        for pair in match.group("keys").split(","):
            if "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            keys[name.strip()] = value.strip().strip("{}")

    def as_int(name):
        try:
            return int(keys[name])
        except (KeyError, ValueError):
            return None

    return {
        "time": as_int("time"),
        "memory": as_int("memory"),
        "input": keys.get("input"),
        "output": keys.get("output"),
        "subtask_points": [int(m.group("points")) for m in _SUBTASK.finditer(text)],
    }


def check(problem: Problem, tex_text: str) -> list[str]:
    tex = parse_tex(tex_text)
    issues: list[str] = []

    published_s = problem.time_ms_published / 1000
    if tex["time"] is None:
        issues.append("statement: no `time` key in \\begin{problem}")
    elif abs(tex["time"] - published_s) > 1e-9:
        issues.append(
            f"time: problem.json publishes {published_s:g} s, "
            f"statement says {tex['time']:g} s"
        )

    if tex["memory"] != problem.memory_mb:
        issues.append(
            f"memory: problem.json says {problem.memory_mb} MB, "
            f"statement says {tex['memory']} MB"
        )

    if tex["input"] != problem.input:
        issues.append(
            f"input: problem.json says {problem.input!r}, "
            f"statement says {tex['input']!r}"
        )
    if tex["output"] != problem.output:
        issues.append(
            f"output: problem.json says {problem.output!r}, "
            f"statement says {tex['output']!r}"
        )

    expected = [s.points for s in problem.subtasks]
    if tex["subtask_points"] != expected:
        issues.append(
            f"subtask points: problem.json says {expected}, "
            f"statement says {tex['subtask_points']}"
        )

    return issues


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: drift_check.py <problem-dir> <statement.tex>", file=sys.stderr)
        return 2
    problem = load(Path(argv[1]) / "problem.json")
    issues = check(problem, Path(argv[2]).read_text(encoding="utf-8"))
    if not issues:
        print("no drift between problem.json and the statement")
        return 0
    for issue in issues:
        print(f"DRIFT  {issue}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `python3 -m unittest tools.tests.test_drift_check -v`
Expected: 8 tests, all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/drift_check.py tools/tests/test_drift_check.py
git commit
```
Message: `Check problem.json against the statement for drift`

---

### Task 6: `bootstrap_testlib.sh`

**Files:**
- Create: `tools/bootstrap_testlib.sh`

**Interfaces:**
- Consumes: nothing.
- Produces: a cached checkout at `${XDG_CACHE_HOME:-$HOME/.cache}/testlib`, and prints that path on stdout so callers can `TESTLIB="$(bash tools/bootstrap_testlib.sh)"`.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Clone or refresh the qhhoj/testlib checkout the pipeline compiles against, and
# print its path. Reads docs/usage-guide.md and plan.md from here rather than
# paraphrasing the API into a skill file, so the guidance always matches the
# header actually being compiled.
set -euo pipefail

TESTLIB="${XDG_CACHE_HOME:-$HOME/.cache}/testlib"
REPO=https://github.com/qhhoj/testlib.git

if [ ! -d "$TESTLIB" ]; then
    # Clone aside and move into place. Several problems can be prepared at once,
    # and a bare `[ -d ] || git clone` lets the second caller find a directory
    # that exists but is still half-populated, then build against it.
    staging="$(mktemp -d "$TESTLIB.XXXXXX")"
    git clone --depth 1 -q "$REPO" "$staging/testlib"
    mv -T "$staging/testlib" "$TESTLIB" 2>/dev/null || true   # first writer wins
    rm -rf "$staging"
fi
git -C "$TESTLIB" pull --ff-only -q 2>/dev/null || true       # offline, or lost a race

if [ ! -f "$TESTLIB/testlib.h" ]; then
    echo "bootstrap_testlib: $TESTLIB exists but has no testlib.h" >&2
    exit 1
fi

echo "$TESTLIB"
```

- [ ] **Step 2: Make it executable and run it**

```bash
chmod +x tools/bootstrap_testlib.sh
TESTLIB="$(bash tools/bootstrap_testlib.sh)" && echo "TESTLIB=$TESTLIB" && ls "$TESTLIB/testlib.h"
```
Expected: prints a path ending `/testlib`, and `ls` finds `testlib.h`.

- [ ] **Step 3: Verify it compiles a stock checker with the project flags**

```bash
TESTLIB="$(bash tools/bootstrap_testlib.sh)"
g++ -std=c++17 -O2 -Wpedantic -Werror -I"$TESTLIB" "$TESTLIB/checkers/rcmp6.cpp" -o /tmp/rcmp6 && echo BUILD-OK
rm -f /tmp/rcmp6
```
Expected: `BUILD-OK` with no warnings.

- [ ] **Step 4: Verify idempotence**

```bash
bash tools/bootstrap_testlib.sh >/dev/null && bash tools/bootstrap_testlib.sh && echo SECOND-RUN-OK
```
Expected: second run prints the same path, `SECOND-RUN-OK`.

- [ ] **Step 5: Commit**

```bash
git add tools/bootstrap_testlib.sh
git commit
```
Message: `Add the testlib bootstrap with a first-writer-wins race guard`

---

### Task 7: `matrix_core.py` — limits and verdict classification

**Files:**
- Create: `tools/matrix_core.py`
- Test: `tools/tests/test_matrix_core.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `@dataclass Limits(t_main_ms: int, tl_ms: int, kill_ms: int)`; `compute_limits(t_main_per_test: dict[str,int], floor_ms: int = 1000, step_ms: int = 500) -> Limits`; `@dataclass Outcome(verdict: str, banded: bool)`; `classify(time_ms: int, killed: bool, checker_verdict: str, limits: Limits) -> Outcome`. `checker_verdict` is one of `"OK"`, `"WA"`, `"PE"`, `"RE"`, `"FAIL"`.

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_matrix_core.py`:

```python
import unittest

from tools.matrix_core import Limits, classify, compute_limits


class TestComputeLimits(unittest.TestCase):
    def test_floor_binds_for_a_fast_model_solution(self):
        limits = compute_limits({"01": 8, "02": 5})
        self.assertEqual(limits.t_main_ms, 8)
        self.assertEqual(limits.tl_ms, 1000)
        self.assertEqual(limits.kill_ms, 2000)

    def test_uses_the_slowest_test_not_the_mean(self):
        self.assertEqual(compute_limits({"01": 10, "02": 900}).t_main_ms, 900)

    def test_doubles_and_rounds_up_to_the_step(self):
        # 900 -> 1800 -> rounded up to 2000
        limits = compute_limits({"01": 900})
        self.assertEqual(limits.tl_ms, 2000)
        self.assertEqual(limits.kill_ms, 4000)

    def test_spec_worked_example(self):
        # t_main 370 ms: 2x = 740, below the 1000 floor, so TL is 1000.
        limits = compute_limits({"01": 370})
        self.assertEqual(limits.tl_ms, 1000)
        self.assertEqual(limits.kill_ms, 2000)

    def test_rejects_an_empty_timing_table(self):
        with self.assertRaises(ValueError):
            compute_limits({})


LIMITS = Limits(t_main_ms=500, tl_ms=1000, kill_ms=2000)


class TestClassify(unittest.TestCase):
    def test_fast_and_correct_is_ok(self):
        out = classify(300, killed=False, checker_verdict="OK", limits=LIMITS)
        self.assertEqual(out.verdict, "OK")
        self.assertFalse(out.banded)

    def test_fast_and_wrong_is_wa(self):
        self.assertEqual(
            classify(300, killed=False, checker_verdict="WA", limits=LIMITS).verdict,
            "WA")

    def test_killed_is_tl_and_not_banded(self):
        out = classify(2000, killed=True, checker_verdict="OK", limits=LIMITS)
        self.assertEqual(out.verdict, "TL")
        self.assertFalse(out.banded)

    def test_over_the_limit_but_finished_is_banded_tl(self):
        out = classify(1400, killed=False, checker_verdict="OK", limits=LIMITS)
        self.assertEqual(out.verdict, "TL")
        self.assertTrue(out.banded)

    def test_time_beats_a_wrong_answer_when_over_the_limit(self):
        # A solution that is both slow and wrong is reported as TL: the judge
        # would have stopped it before the checker ever ran.
        out = classify(1400, killed=False, checker_verdict="WA", limits=LIMITS)
        self.assertEqual(out.verdict, "TL")

    def test_exactly_at_the_limit_is_accepted(self):
        self.assertEqual(
            classify(1000, killed=False, checker_verdict="OK", limits=LIMITS).verdict,
            "OK")

    def test_checker_fail_surfaces_as_fail_not_wa(self):
        # inf/ans read failures are package bugs, never the solution's fault.
        self.assertEqual(
            classify(10, killed=False, checker_verdict="FAIL", limits=LIMITS).verdict,
            "FAIL")

    def test_presentation_error_is_preserved(self):
        self.assertEqual(
            classify(10, killed=False, checker_verdict="PE", limits=LIMITS).verdict,
            "PE")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m unittest tools.tests.test_matrix_core -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement the limits and classification half of `tools/matrix_core.py`**

```python
"""Pure numeric core of the invocation matrix.

Split from run_matrix.py on purpose: what the limit is, what verdict a runtime
implies, and what counts as a hole are the decisions that must be right, and
they are testable without compiling anything or running a clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_FLOOR_MS = 1000
DEFAULT_STEP_MS = 500


@dataclass(frozen=True)
class Limits:
    t_main_ms: int
    tl_ms: int
    kill_ms: int


def compute_limits(
    t_main_per_test: dict[str, int],
    floor_ms: int = DEFAULT_FLOOR_MS,
    step_ms: int = DEFAULT_STEP_MS,
) -> Limits:
    """TL = max(2 x slowest model run, floor), rounded up to a human number.

    The floor exists because with t_main at 8 ms a 16 ms limit is nonsense:
    process startup alone is ~2 ms and scheduler noise dominates.
    """
    if not t_main_per_test:
        raise ValueError("cannot compute limits without any model-solution timings")
    t_main = max(t_main_per_test.values())
    raw = max(2 * t_main, floor_ms)
    tl = int(math.ceil(raw / step_ms) * step_ms)
    return Limits(t_main_ms=t_main, tl_ms=tl, kill_ms=2 * tl)


@dataclass(frozen=True)
class Outcome:
    verdict: str
    banded: bool


def classify(
    time_ms: int, killed: bool, checker_verdict: str, limits: Limits
) -> Outcome:
    """Turn a runtime plus a checker verdict into a per-test outcome.

    Time is decided before correctness: a judge stops a solution at the limit,
    so the checker never runs on one that exceeded it. `banded` marks the
    [TL, kill] zone, where the result is too close to call on other hardware.
    """
    if killed:
        return Outcome("TL", banded=False)
    if time_ms > limits.tl_ms:
        return Outcome("TL", banded=time_ms <= limits.kill_ms)
    if checker_verdict == "FAIL":
        return Outcome("FAIL", banded=False)
    return Outcome(checker_verdict, banded=False)
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `python3 -m unittest tools.tests.test_matrix_core -v`
Expected: 13 tests, all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/matrix_core.py tools/tests/test_matrix_core.py
git commit
```
Message: `Add the timing model and verdict classification as pure functions`

---

### Task 8: `matrix_core.py` — holes and mismatches

**Files:**
- Modify: `tools/matrix_core.py` (append)
- Modify: `tools/tests/test_matrix_core.py` (append)

**Interfaces:**
- Consumes: `Outcome` from Task 7.
- Produces: `group_verdict(per_test: list[str]) -> str` collapsing a group's per-test verdicts to one; `compare(expected: dict[str, dict[str, str]], actual: dict[str, dict[str, str]]) -> tuple[list[dict], list[dict]]` returning `(holes, mismatches)`. Both outer dicts are keyed by solution filename, inner by group id. A **hole** is `expected in {WA, TL, ML, PE, RE}` while `actual == "OK"`. A **mismatch** is any other difference.

- [ ] **Step 1: Append the failing tests to `tools/tests/test_matrix_core.py`**

```python
from tools.matrix_core import compare, group_verdict


class TestGroupVerdict(unittest.TestCase):
    def test_all_ok_is_ok(self):
        self.assertEqual(group_verdict(["OK", "OK", "OK"]), "OK")

    def test_one_failure_decides_the_group(self):
        self.assertEqual(group_verdict(["OK", "WA", "OK"]), "WA")

    def test_worst_verdict_wins_when_several_differ(self):
        # FAIL is a package bug and must never be masked by a mere WA.
        self.assertEqual(group_verdict(["WA", "FAIL", "TL"]), "FAIL")
        self.assertEqual(group_verdict(["OK", "TL", "WA"]), "TL")

    def test_empty_group_is_an_error(self):
        with self.assertRaises(ValueError):
            group_verdict([])


class TestCompare(unittest.TestCase):
    def test_everything_matching_yields_nothing(self):
        expected = {"sol-main.cpp": {"g1": "OK", "g2": "OK"}}
        holes, mismatches = compare(expected, expected)
        self.assertEqual(holes, [])
        self.assertEqual(mismatches, [])

    def test_a_rejected_solution_that_survived_is_a_hole(self):
        expected = {"sol-greedy.cpp": {"g1": "WA", "g2": "WA"}}
        actual = {"sol-greedy.cpp": {"g1": "OK", "g2": "WA"}}
        holes, mismatches = compare(expected, actual)
        self.assertEqual(len(holes), 1)
        self.assertEqual(holes[0], {"solution": "sol-greedy.cpp", "group": "g1",
                                    "expected": "WA", "actual": "OK"})
        self.assertEqual(mismatches, [])

    def test_an_accepted_solution_that_failed_is_a_mismatch_not_a_hole(self):
        expected = {"sol-conway.cpp": {"g1": "OK"}}
        actual = {"sol-conway.cpp": {"g1": "WA"}}
        holes, mismatches = compare(expected, actual)
        self.assertEqual(holes, [])
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["actual"], "WA")

    def test_wrong_flavour_of_failure_is_a_mismatch(self):
        expected = {"sol-brute.cpp": {"g2": "TL"}}
        actual = {"sol-brute.cpp": {"g2": "WA"}}
        holes, mismatches = compare(expected, actual)
        self.assertEqual(holes, [])
        self.assertEqual(len(mismatches), 1)

    def test_a_group_with_no_result_is_a_mismatch(self):
        expected = {"sol-main.cpp": {"g1": "OK", "g2": "OK"}}
        actual = {"sol-main.cpp": {"g1": "OK"}}
        holes, mismatches = compare(expected, actual)
        self.assertEqual(len(mismatches), 1)
        self.assertIsNone(mismatches[0]["actual"])
```

- [ ] **Step 2: Run and confirm the new tests fail**

Run: `python3 -m unittest tools.tests.test_matrix_core -v`
Expected: `ImportError: cannot import name 'compare'`

- [ ] **Step 3: Append the implementation to `tools/matrix_core.py`**

```python
# Worst-first. FAIL is a package bug and must never be masked by a solution's
# own failure; TL outranks WA because the judge stops before the checker runs.
_SEVERITY = ["FAIL", "TL", "ML", "RE", "PE", "WA", "OK"]

_FAILING = {"WA", "TL", "ML", "PE", "RE"}


def group_verdict(per_test: list[str]) -> str:
    """Collapse a group's per-test verdicts into the one the judge would report."""
    if not per_test:
        raise ValueError("a group must contain at least one test")
    for verdict in _SEVERITY:
        if verdict in per_test:
            return verdict
    raise ValueError(f"unknown verdicts in group: {sorted(set(per_test))}")


def compare(
    expected: dict[str, dict[str, str]],
    actual: dict[str, dict[str, str]],
) -> tuple[list[dict], list[dict]]:
    """Split every disagreement into holes and mismatches.

    A hole is the suite's failure: a solution declared wrong that nothing
    caught. A mismatch is everything else that differed, which is where an
    accepted solution disagreeing with the model shows up.
    """
    holes: list[dict] = []
    mismatches: list[dict] = []

    for solution in sorted(expected):
        for group in expected[solution]:
            want = expected[solution][group]
            got = actual.get(solution, {}).get(group)
            if want == got:
                continue
            record = {
                "solution": solution,
                "group": group,
                "expected": want,
                "actual": got,
            }
            if want in _FAILING and got == "OK":
                holes.append(record)
            else:
                mismatches.append(record)

    return holes, mismatches
```

- [ ] **Step 4: Run tests and confirm they pass**

Run: `python3 -m unittest tools.tests.test_matrix_core -v`
Expected: 22 tests, all PASS

- [ ] **Step 5: Commit**

```bash
git add tools/matrix_core.py tools/tests/test_matrix_core.py
git commit
```
Message: `Separate suite holes from solution mismatches in the matrix core`

---

### Task 9: `run_matrix.py` — the driver

**Files:**
- Create: `tools/run_matrix.py`
- Test: manual, against `tools/tests/fixtures/mini/` built in this task

**Interfaces:**
- Consumes: `problem_meta.load`, `scan_solutions.scan`, `matrix_core.{compute_limits, classify, group_verdict, compare}`, `flags.append`.
- Produces: `run(problem_dir, testlib_dir, runs=3) -> dict` writing `invocation.json`; `main(argv) -> int`. Expects `<problem_dir>/tests/<group>/<name>.in` and writes `.a` answer files beside them.

- [ ] **Step 1: Build the fixture problem**

```bash
mkdir -p tools/tests/fixtures/mini/{solutions,tests/g1,files}
cd tools/tests/fixtures/mini
```

`problem.json`:

```json
{
  "schema": 1,
  "name": "mini",
  "title": {"vi": "Tổng hai số"},
  "tags": ["implementation"],
  "limits": {"time_ms_published": 1000, "memory_mb": 256},
  "io": {"input": "stdin", "output": "stdout"},
  "checker": {"kind": "stock", "name": "ncmp"},
  "constraints": [{"id": "value", "expr": "1 \\le a, b \\le 1000", "min": 1, "max": 1000}],
  "subtasks": [{"id": "g1", "points": 100, "bounds": {}, "constraints_text": ["Không có ràng buộc gì thêm"], "depends_on": []}],
  "examples": []
}
```

`solutions/sol-main.cpp`:

```cpp
/**
 * @tag        main
 * @expect     g1=OK
 * @algorithm  Reads two integers and prints their sum.
 * @complexity O(1)
 */
#include <iostream>
int main() { long long a, b; std::cin >> a >> b; std::cout << a + b << "\n"; }
```

`solutions/sol-wrong.cpp`:

```cpp
/**
 * @tag        wrong-answer
 * @expect     g1=WA
 * @algorithm  Prints the difference instead of the sum.
 * @why-wrong  Wrong operator; every test with a != 0 catches it.
 * @complexity O(1)
 */
#include <iostream>
int main() { long long a, b; std::cin >> a >> b; std::cout << a - b << "\n"; }
```

`tests/g1/01.in`:

```
2 3
```

- [ ] **Step 2: Implement `tools/run_matrix.py`**

```python
#!/usr/bin/env python3
"""Build every solution, run it on every test, and write invocation.json.

Timing policy, from the spec: the model solution is timed as the median of
three runs per test and the limit follows from its slowest test. Adversary
solutions get one run, and only a result landing in the [TL, kill] band is
re-run three times before being reported — three runs of everything triples
the cost of the pipeline for no gain outside the band.
"""

from __future__ import annotations

import json
import os
import platform
import signal
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from tools import flags
from tools.matrix_core import classify, compare, compute_limits, group_verdict
from tools.problem_meta import Problem, load
from tools.scan_solutions import scan

SCHEMA = 1
CXXFLAGS = ["-std=c++17", "-O2"]
CHECKER_EXIT = {0: "OK", 1: "WA", 2: "PE", 3: "FAIL"}


def _compile(source: Path, binary: Path, extra: list[str] | None = None) -> None:
    cmd = ["g++", *CXXFLAGS, *(extra or []), str(source), "-o", str(binary)]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"compile failed: {' '.join(cmd)}\n{done.stderr}")


def _run_once(binary: Path, stdin_path: Path, stdout_path: Path, kill_ms: int):
    """Run one process, returning (elapsed_ms, killed, exit_code, peak_kb)."""
    with open(stdin_path, "rb") as fin, open(stdout_path, "wb") as fout:
        started = time.monotonic()
        proc = subprocess.Popen([str(binary)], stdin=fin, stdout=fout,
                                stderr=subprocess.DEVNULL)
        killed = False
        rusage = None
        status = 0
        while True:
            pid, status, rusage = os.wait4(proc.pid, os.WNOHANG)
            if pid != 0:
                break
            if (time.monotonic() - started) * 1000 >= kill_ms:
                proc.kill()
                os.wait4(proc.pid, 0)
                killed = True
                break
            time.sleep(0.002)
        elapsed_ms = int((time.monotonic() - started) * 1000)

    peak_kb = getattr(rusage, "ru_maxrss", 0) if rusage else 0
    exit_code = os.waitstatus_to_exitcode(status) if not killed else -signal.SIGKILL
    return elapsed_ms, killed, exit_code, peak_kb


def _time_median(binary, stdin_path, stdout_path, kill_ms, runs):
    samples, killed, code, peak = [], False, 0, 0
    for _ in range(runs):
        ms, k, c, p = _run_once(binary, stdin_path, stdout_path, kill_ms)
        samples.append(ms)
        killed, code, peak = killed or k, c, max(peak, p)
    return int(statistics.median(samples)), killed, code, peak


def _check(checker: Path, test_in: Path, out: Path, ans: Path) -> str:
    done = subprocess.run([str(checker), str(test_in), str(out), str(ans)],
                          capture_output=True, text=True)
    return CHECKER_EXIT.get(done.returncode, "FAIL")


def _tests_by_group(problem_dir: Path, problem: Problem) -> dict[str, list[Path]]:
    return {
        sub.id: sorted((problem_dir / "tests" / sub.id).glob("*.in"))
        for sub in problem.subtasks
    }


def run(problem_dir: str | Path, testlib_dir: str | Path, runs: int = 3) -> dict:
    problem_dir, testlib_dir = Path(problem_dir), Path(testlib_dir)
    problem = load(problem_dir / "problem.json")
    manifest = scan(problem_dir, problem)

    build = problem_dir / ".build"
    build.mkdir(exist_ok=True)

    if problem.checker_kind == "stock":
        checker_src = testlib_dir / "checkers" / f"{problem.checker_name}.cpp"
    else:
        checker_src = problem_dir / "files" / problem.checker_name
    checker = build / "checker"
    _compile(checker_src, checker, ["-Wpedantic", "-Werror", f"-I{testlib_dir}"])

    binaries = {}
    for entry in manifest["solutions"]:
        binary = build / Path(entry["file"]).stem
        _compile(problem_dir / "solutions" / entry["file"], binary)
        binaries[entry["file"]] = binary

    main_file = next(e["file"] for e in manifest["solutions"] if e["tag"] == "main")
    tests = _tests_by_group(problem_dir, problem)

    # Pass 1 — the model solution defines both the answers and the limits.
    t_main: dict[str, int] = {}
    for group, paths in tests.items():
        for test in paths:
            answer = test.with_suffix(".a")
            ms, _, code, _ = _time_median(binaries[main_file], test, answer,
                                          kill_ms=60_000, runs=runs)
            if code != 0:
                raise RuntimeError(f"model solution exited {code} on {test}")
            t_main[f"{group}/{test.stem}"] = ms

    limits = compute_limits(t_main)

    # Pass 2 — everything else, one run, band results re-timed.
    results, actual = [], {}
    for entry in manifest["solutions"]:
        name = entry["file"]
        actual[name] = {}
        for group, paths in tests.items():
            per_test = []
            for test in paths:
                out = build / f"{Path(name).stem}.{group}.{test.stem}.out"
                ms, killed, code, peak = _run_once(binaries[name], test, out,
                                                   limits.kill_ms)
                verdict_src = ("RE" if code != 0 and not killed
                               else _check(checker, test, out, test.with_suffix(".a")))
                outcome = classify(ms, killed, verdict_src, limits)

                if outcome.banded:
                    ms, killed, code, peak = _time_median(
                        binaries[name], test, out, limits.kill_ms, runs)
                    outcome = classify(ms, killed, verdict_src, limits)
                    flags.append(
                        problem_dir, phase="validate-solutions", severity="medium",
                        kind="timing-band",
                        what=f"{name} on {group}/{test.stem} ran {ms} ms, "
                             f"between TL {limits.tl_ms} and kill {limits.kill_ms}",
                        assumed="reported as TL, reclassified to "
                                "time-limit-exceeded-or-accepted",
                        changes_if_wrong=f"the expected tag of {name}")

                if peak > problem.memory_mb * 1024:
                    outcome = type(outcome)("ML", outcome.banded)

                per_test.append(outcome.verdict)
                results.append({
                    "solution": name, "group": group, "test": test.stem,
                    "verdict": outcome.verdict, "time_ms": ms,
                    "ratio": round(ms / max(limits.t_main_ms, 1), 2),
                    "peak_kb": peak, "killed": killed, "banded": outcome.banded,
                })
            actual[name][group] = group_verdict(per_test)

    expected = {e["file"]: e["expect"] for e in manifest["solutions"]}
    holes, mismatches = compare(expected, actual)

    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": {
            "cxx": subprocess.run(["g++", "--version"], capture_output=True,
                                  text=True).stdout.splitlines()[0],
            "flags": " ".join(CXXFLAGS),
            "platform": platform.platform(),
        },
        "t_main_ms": {"per_test": t_main, "max": limits.t_main_ms,
                      "runs": runs, "method": "median"},
        "limits": {"tl_ms": limits.tl_ms, "kill_ms": limits.kill_ms},
        "results": results,
        "holes": holes,
        "mismatches": mismatches,
    }
    (problem_dir / "invocation.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: run_matrix.py <problem-dir> <testlib-dir>", file=sys.stderr)
        return 2
    payload = run(argv[1], argv[2])
    print(f"TL {payload['limits']['tl_ms']} ms  "
          f"kill {payload['limits']['kill_ms']} ms  "
          f"holes {len(payload['holes'])}  "
          f"mismatches {len(payload['mismatches'])}")
    for record in payload["holes"]:
        print(f"HOLE      {record['solution']} survived {record['group']} "
              f"(expected {record['expected']})")
    for record in payload["mismatches"]:
        print(f"MISMATCH  {record['solution']} on {record['group']}: "
              f"expected {record['expected']}, got {record['actual']}")
    return 1 if payload["holes"] or payload["mismatches"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 3: Run it against the fixture and confirm a clean matrix**

```bash
cd ~/.claude/skills/competitive-programming
TESTLIB="$(bash tools/bootstrap_testlib.sh)"
python3 -m tools.run_matrix tools/tests/fixtures/mini "$TESTLIB"; echo "exit $?"
```
Expected: `holes 0  mismatches 0`, exit 0. `sol-wrong.cpp` must land on `WA` for `g1`, matching its `@expect`.

- [ ] **Step 4: Prove the hole detector fires**

```bash
cd ~/.claude/skills/competitive-programming
printf '0 0\n' > tools/tests/fixtures/mini/tests/g1/01.in     # a - b == a + b here
TESTLIB="$(bash tools/bootstrap_testlib.sh)"
python3 -m tools.run_matrix tools/tests/fixtures/mini "$TESTLIB"; echo "exit $?"
printf '2 3\n' > tools/tests/fixtures/mini/tests/g1/01.in     # restore
```
Expected: `holes 1`, the line `HOLE  sol-wrong.cpp survived g1 (expected WA)`, exit 1. This is the whole point of the tool: a test that cannot distinguish the wrong solution is reported as a hole rather than passing silently.

- [ ] **Step 5: Clean build artifacts and commit**

```bash
rm -rf tools/tests/fixtures/mini/.build tools/tests/fixtures/mini/invocation.json \
       tools/tests/fixtures/mini/flags.json tools/tests/fixtures/mini/solutions.json
printf '.build/\ninvocation.json\nflags.json\nsolutions.json\n*.a\n' \
  > tools/tests/fixtures/mini/.gitignore
git add tools/run_matrix.py tools/tests/fixtures/mini
git commit
```
Message: `Add the invocation matrix driver with band re-timing`

---

### Task 10: `preparing-tests/SKILL.md`

**Files:**
- Create: `skills/preparing-tests/SKILL.md`

**Interfaces:**
- Consumes: every tool from Tasks 1–9.
- Produces: a skill named `preparing-tests`, matching its directory name as the plugin README requires.

- [ ] **Step 1: Load the skill-authoring skill**

Invoke `superpowers:writing-skills` and follow it. It governs frontmatter, description wording and structure; this task supplies the content.

- [ ] **Step 2: Write the file**

Frontmatter `name` must be exactly `preparing-tests`. The `description` must lead with the artifacts it builds so the router can discriminate it from `validating-solutions`, and must end with the disclaimer sentence, in the style `writing-statements` already uses:

```
Use when writing the generator, validator, or checker for a competitive
programming problem with testlib, generating test data grouped into subtasks,
or choosing sample tests. Triggers on testlib, generator, validator, checker,
registerGen, registerValidation, wcmp/ncmp/rcmp6, test data, subtask groups,
Polygon tests script. This builds the test data; for judging whether that data
is strong enough, and for writing deliberately-wrong solutions, use
competitive-programming:validating-solutions instead.
```

Body sections, in this order:

1. **`## Am I the right skill?`** — the disambiguation table from spec §3, naming `validating-solutions`, `creating-problems`, `writing-statements`, with the contrast line *"Write me a validator" is not ambiguous. "Make my tests better" is.*
2. **Bootstrap** — `TESTLIB="$(bash "$BASE/../../tools/bootstrap_testlib.sh")"`, then *read `$TESTLIB/docs/usage-guide.md` for the API and `$TESTLIB/plan.md` for known defects.* State plainly that no testlib API is reproduced in this file, and why: the guide is versioned against the header being compiled.
3. **The order is the doctrine** — checker, then validator, then generators. Copy the reasoning from spec §9 verbatim, including *why* the checker is first.
4. **Tools, with exact invocations** — `python3 -m tools.gen_constraints_header <dir>`, `python3 -m tools.drift_check <dir> <tex>`. State that the skill must never hand-write `constraints.h`.
5. **testlib traps** — the seven-item list from spec §13, each with its `plan.md` identifier.
6. **TDD on the validator and checker** — invoke `superpowers:test-driven-development`; write a deliberately-illegal input and assert the validator exits nonzero *before* any generator exists.
7. **Generator families** — random, max-size, boundary/degenerate, structured-adversarial, hand-written. Note that writing them is a fan-out and invoke `superpowers:dispatching-parallel-agents`.
8. **Reaching check** — `validator --testOverviewLogFileName` per group; unreached bounds are holes and get a `test-weakness` flag.
9. **Samples** — 2–3, tiny, exercising the interesting rule, produced by the model solution and checker, never hand-computed. Hand back to `writing-statements`.
10. **Done means** — every test validates under its own `--group`, and every declared bound is reached. Invoke `superpowers:verification-before-completion` and show the commands that produce the evidence.

- [ ] **Step 3: Verify the plugin still validates and the skill is visible**

```bash
cd ~/.claude/skills/competitive-programming
claude plugin validate . --strict
grep -c '^name: preparing-tests$' skills/preparing-tests/SKILL.md
```
Expected: validation passes; grep prints `1`.

- [ ] **Step 4: Commit**

```bash
git add skills/preparing-tests/SKILL.md
git commit
```
Message: `Add preparing-tests: validator, checker and generators with testlib`

---

### Task 11: `validating-solutions/SKILL.md`

**Files:**
- Create: `skills/validating-solutions/SKILL.md`

**Interfaces:**
- Consumes: `tools/run_matrix.py`, `tools/scan_solutions.py`, `tools/flags.py`.
- Produces: a skill named `validating-solutions`.

- [ ] **Step 1: Load the skill-authoring skill**

Invoke `superpowers:writing-skills`.

- [ ] **Step 2: Write the file**

Frontmatter `name` exactly `validating-solutions`. Description leads with attack vocabulary so it does not collide with `preparing-tests`:

```
Use when writing deliberately-wrong solutions for a competitive programming
problem, cross-checking a model solution against alternatives, stress testing,
or judging whether a test suite is strong enough. Triggers on wrong solution,
brute force, greedy that fails, stress test, cross-check, are my tests strong,
invocation matrix, expected verdict, TLE margin. This attacks an existing test
suite; to write the generator, validator or checker itself use
competitive-programming:preparing-tests instead.
```

Body sections:

1. **`## Am I the right skill?`** — disambiguation table naming `preparing-tests`, `creating-problems`, `solving-problems`.
2. **The zoo taxonomy** — the nine-row table from spec §10, each row stating the class's job.
3. **Two rules** — each wrong solution wrong in exactly one named way; wrong solutions must be plausible, with the *"would a competent contestant submit this at 2am?"* bar.
4. **The metadata block** — the exact `@tag / @expect / @algorithm / @why-wrong / @complexity` comment format from spec §4, and the instruction never to hand-write `solutions.json`; it comes from `python3 -m tools.scan_solutions <dir>`.
5. **Writing the zoo is a fan-out** — invoke `superpowers:dispatching-parallel-agents`, one agent per solution, each told the single named way its solution must be wrong.
6. **Running the matrix** — `python3 -m tools.run_matrix <dir> "$TESTLIB"`. State that the skill must never re-implement timing; exit 1 means holes or mismatches.
7. **Reading the result** — holes mean the suite is weak, so hand back to `preparing-tests` for a killer test. Mismatches on an `accepted` solution mean the arbiter runs.
8. **The arbiter** — the five-step procedure from spec §10 verbatim, including the hard stop after 3 rounds and the exit to `writing-statements` when the behaviour genuinely is not defined. Invoke `superpowers:systematic-debugging` for the shrink-and-diagnose loop.
9. **Strength is three obligations** — adversarial, reaching, structural — and the claim is always *"no solution in the zoo survives"*, never *"the tests are strong"*.
10. **Done means** — `holes` is empty and every `WA`/`TL` cell names its killing test. Invoke `superpowers:verification-before-completion`.

- [ ] **Step 3: Verify**

```bash
cd ~/.claude/skills/competitive-programming
claude plugin validate . --strict
grep -c '^name: validating-solutions$' skills/validating-solutions/SKILL.md
```
Expected: validation passes; grep prints `1`.

- [ ] **Step 4: Commit**

```bash
git add skills/validating-solutions/SKILL.md
git commit
```
Message: `Add validating-solutions: the adversary zoo and the invocation matrix`

---

### Task 12: Manifest, README, full suite, and the `flight` dogfood

**Files:**
- Modify: `.claude-plugin/plugin.json` (version, description)
- Modify: `README.md` (component table, layout block, checks section)

- [ ] **Step 1: Bump the manifest**

In `.claude-plugin/plugin.json` set `"version": "0.5.0"` and extend `description` to mention test preparation and solution validation.

- [ ] **Step 2: Update the README**

Add two rows to the component table (`preparing-tests`, `validating-solutions`), add `tools/` and the two skill directories to the layout block, and add to the Checks section:

```bash
python3 -m unittest discover -s tools/tests -t . -v    # tools test suite
```

- [ ] **Step 3: Run the whole suite and validate the plugin**

```bash
cd ~/.claude/skills/competitive-programming
python3 -m unittest discover -s tools/tests -t . -v
claude plugin validate . --strict
claude plugin details competitive-programming
```
Expected: every test passes; validation passes; details lists **5 skills**.

- [ ] **Step 4: Dogfood on `flight`**

`flight` at `~/Projects/my_cp_problems/flight` has a statement and nothing else. Drive the two new skills against it by hand and record what happens.

```bash
cd ~/Projects/my_cp_problems/flight
ls                      # flight.tex, flight.pdf — no problem.json, no tests
```

Write `problem.json` from the statement, then:

```bash
CP=~/.claude/skills/competitive-programming
cd "$CP"
python3 -m tools.gen_constraints_header ~/Projects/my_cp_problems/flight
python3 -m tools.drift_check ~/Projects/my_cp_problems/flight \
        ~/Projects/my_cp_problems/flight/flight.tex
```
Expected: `constraints.h` appears with `LEN_A_MAX = 20` and `G1_LEN_A_MAX = 6`; the drift check passes against the published `time = 1` / `memory = 256`.

Then follow `preparing-tests` and `validating-solutions` end to end. **Three specific things must surface, and the dogfood fails if any does not:**

1. The checker decision lands on **`rcmp6`**, not a custom checker — the answer is two reals with 1e-6 tolerance.
2. A `wrong-answer` solution that compares occurrences by **start** index rather than end index is caught, and `invocation.json` names the test that killed it.
3. The `xâu con` wording in the statement's constraints is raised — an assumed definition, ambiguous between *substring* and *subsequence* in Vietnamese, whose unambiguous form is `xâu con liên tiếp`.

Item 3 has no automated owner until Stage 2 builds `reviewing-problems`. Record it as a `statement-ambiguity` flag by hand and note in the Stage 2 plan that it is the acceptance test for the reviewer.

- [ ] **Step 5: Commit and report**

```bash
cd ~/.claude/skills/competitive-programming
git add .claude-plugin/plugin.json README.md
git commit
```
Message: `Bump to 0.5.0 for the test preparation and validation skills`

Report: the full test count, `claude plugin details` output, and which of the three `flight` expectations were met.

---

## Self-review

**Spec coverage.** §3 skill set → Tasks 10, 11, 12. §3 disambiguation → Tasks 10, 11 step 2. §4 directory and the consumer problem → Tasks 1, 3. §4 solution comment blocks and derived timestamps → Task 4. §4 `invocation.json` and holes → Tasks 8, 9. §5 timing → Tasks 7, 9. §6 flag register → Tasks 2, 9. §7 pipeline order → Task 10 section 3. §9 `preparing-tests` → Task 10. §10 `validating-solutions` → Task 11. §13 testlib bootstrap and traps → Tasks 6, 10. §14 verification → Task 12.

**Deferred to Stage 2, by design:** §8 `shaping-problems`, §11 `reviewing-problems`, §12 `creating-problems`, and the `skill-creator` trigger evals — those want all eight descriptions present to be meaningful.

**Known gap, deliberately accepted.** The `xâu con` finding in the `flight` dogfood has no automated owner in Stage 1; `reviewing-problems` is a Stage 2 deliverable. Task 12 records it by hand and hands it forward as the reviewer's acceptance test.

**Type consistency.** `Problem`, `Subtask`, `Constraint`, `Bound` are defined in Task 1 and used unchanged in Tasks 3, 4, 5, 9. `Limits` and `Outcome` are defined in Task 7 and used in Tasks 8, 9. `compare()` returns `(holes, mismatches)` in Task 8 and is unpacked that way in Task 9. `flags.append()`'s keyword signature in Task 2 matches its call in Task 9. `scan()` returns `{"schema", "generated_at", "solutions"}` in Task 4 and Task 9 reads `["solutions"]` and each entry's `["file"]`, `["tag"]`, `["expect"]`.

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
    if not isinstance(data, dict):
        return Phase("matrix", False, "invocation.json top level is not an object")
    try:
        holes = data.get("holes", [])
        mismatches = data.get("mismatches", [])
        if not isinstance(holes, list):
            return Phase("matrix", False, "holes field is not an array")
        if not isinstance(mismatches, list):
            return Phase("matrix", False, "mismatches field is not an array")
    except (TypeError, AttributeError) as exc:
        return Phase("matrix", False, f"invocation.json malformed: {exc}")
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

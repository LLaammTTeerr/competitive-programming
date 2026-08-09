#!/usr/bin/env python3
"""The mechanical half of a problem-package audit.

Everything here is a question a program can answer: does the statement agree
with problem.json, is a phase missing, is a solution file absent from the scan,
did the matrix leave a hole, does files/constraints.h still match what
problem.json renders to right now.

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
from tools.gen_constraints_header import render
from tools.package_status import newest_source_mtime, next_phase, status
from tools.problem_meta import Problem, ProblemMetaError, load
from tools.scan_solutions import ScanError, scan

KINDS = (
    "constraint-drift", "incomplete-package", "orphan-solution",
    "sample-not-reproducible", "matrix-hole", "matrix-mismatch",
    "stale-constraints-header", "stale-matrix",
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


def _matrix(problem_dir: Path, problem: Problem | None) -> list[Finding]:
    path = problem_dir / "invocation.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [Finding("matrix-hole", "low",
                        f"invocation.json unreadable: {exc}", str(path))]
    # Explicit check for dict type: redundant with the try/except below, but provides
    # a clearer message naming the type found. Separates structural validation from
    # operational errors. Kept deliberately for better diagnostics.
    if not isinstance(data, dict):
        return [Finding("matrix-hole", "low",
                        f"invocation.json top level is not an object (got {type(data).__name__})",
                        str(path))]
    try:
        artifact_mtime = path.stat().st_mtime
    except OSError as exc:
        return [Finding("matrix-hole", "low",
                        f"invocation.json unreadable: {exc}", str(path))]
    # The identical staleness claim `package_status._matrix()` makes about
    # the same artifact — via the shared `newest_source_mtime`, not a copy
    # of it, so the two checks cannot silently drift apart (see the task
    # report: leaving this sibling gate without the freshness check
    # `package_status` just got was the exact "fix the instance, not the
    # class" mistake this project keeps re-paying for). Reported instead of
    # the holes/mismatches findings below, not alongside them: those
    # findings describe a package state `invocation.json` no longer speaks
    # for, so surfacing them here would be citing evidence about a
    # different tree as though it were current.
    extra_files: tuple[Path, ...] = ()
    if problem is not None and problem.checker_kind == "custom":
        extra_files = (problem_dir / "files" / problem.checker_name,)
    if newest_source_mtime(problem_dir, extra_files) > artifact_mtime:
        return [Finding(
            "stale-matrix", "high",
            "invocation.json is stale: a solution, test, problem.json, or "
            "the checker changed after it was written — the holes/"
            "mismatches it records describe a package state that no "
            "longer exists; re-run the matrix", str(path))]
    try:
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
    except (TypeError, AttributeError) as exc:
        return [Finding("matrix-hole", "low",
                        f"invocation.json is malformed: {exc}", str(path))]


def _stale_header(problem_dir: Path, problem: Problem | None) -> list[Finding]:
    header = problem_dir / "files" / "constraints.h"
    if not header.exists():
        return []
    if problem is None:
        return []
    try:
        expected = render(problem)
        actual = header.read_text(encoding="utf-8")
        if expected == actual:
            return []
        return [Finding("stale-constraints-header", "high",
                        "constraints.h does not match problem.json; regenerate it "
                        "with `python3 -m tools.gen_constraints_header`", str(header))]
    except ProblemMetaError as exc:
        # `render()` raises this, not just `load()`: two constraint ids that
        # `load` accepts as distinct — `"n"` and `"N"` — collide once
        # `identifier()` uppercases them into the same `N_MIN`. `load` cannot
        # catch that, because the collision is a property of the C++ name the
        # header generator derives, not of the document. Catching it here is
        # what keeps `run()`'s never-raises contract true.
        return [Finding("stale-constraints-header", "low",
                        f"constraints.h cannot be regenerated for comparison: "
                        f"{exc}", str(header))]
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding("stale-constraints-header", "low",
                        f"constraints.h unreadable: {exc}", str(header))]


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
    findings += _matrix(problem_dir, problem)
    findings += _stale_header(problem_dir, problem)
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

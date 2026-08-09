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


# What `invocation.json` is evidence *about*. A matrix result describes a
# specific package state; when any of these is newer than the artifact, the
# artifact has not become wrong, it has become a statement about something
# else — and the gate must not accept it as current. The custom checker (when
# there is one) is included via `_matrix`'s `extra_files`, not listed here,
# because it needs `problem.checker_name` to locate — see `_matrix` below.
#
# mtime is the signal, not a perfect one, and both of its failure directions
# are known:
#
#   * False "stale" (safe): a `git checkout` rewrites every file's mtime
#     without changing content. Costs a re-run; never certifies anything
#     false.
#   * False "fresh" (dangerous — this is a false soundness claim, not an
#     inconvenience): four ways this check can still miss a real edit.
#       1. A *deletion* — removing a test or a solution — used to be
#          invisible, since the old version of this walk only stat'd files.
#          Fixed: directories are stat'd too, both the two top-level ones
#          and every directory `rglob` yields, because removing an entry
#          from a directory updates that directory's own mtime even though
#          no remaining file changed.
#       2. A tool that restores the original mtime on write — `cp -p`,
#          `tar x`, `rsync -a` — changes content without advancing mtime at
#          all. Not detectable by this check; nothing mtime-based can see it.
#       3. A file inside a subdirectory this process cannot read: `rglob`
#          silently skips permission-denied entries rather than raising (a
#          `status()`-never-raises consequence, not a choice made for this
#          check specifically), so content invisible to us cannot bump
#          `newest`.
#       4. A change landing inside the same mtime *tick* as the artifact
#          write, not just the same wall-clock second. Measured on this
#          filesystem: ~4 ms granularity, not 1s — an edit and the
#          `invocation.json` write can round to the identical mtime even
#          though the edit happened after. `>=` is not the fix: pass 1's
#          own `.a` rewrites already share a tick with the final
#          `invocation.json` write on a fast run (see the
#          "Checked against `run_matrix.run()`" note below), so `>=` would
#          flag a normal clean run as stale, which is the failure that
#          makes a gate worthless — see the "equal mtime is not stale"
#          test for why strict `>` is the one that has to stay. The
#          granularity itself is filesystem-dependent (ext4 measured here;
#          other filesystems, or a coarser one under a container overlay,
#          could be wider or narrower). Not reachable by a human editing
#          a file — nobody edits a solution 4 ms after a matrix run
#          finishes — but reachable by a script that runs the matrix and
#          immediately mutates the package in the same process, which is
#          exactly how this gap was found.
#     (2), (3), and (4) are accepted gaps, not fixed here — flagged for a
#     reader deciding how much to trust this gate, not concealed by a
#     comment that only named the safe direction.
#
# `generated_at` inside the payload was considered and rejected as the
# source of truth: it records when the matrix ran, not what it ran against,
# so it cannot detect an edit made afterwards.
#
# Checked against `run_matrix.run()` and confirmed not self-defeating:
# `run()` does write into `tests/` (pass 1 regenerates each `.a` answer file
# from the model solution via `unlink(missing_ok=True)` then `write_bytes`,
# which bumps both the file's own mtime and its parent directory's), but
# every one of those writes happens during pass 1, and `invocation.json`
# itself is written exactly once, as the very last statement in `run()`. So
# immediately after any run — clean or not — every file and directory this
# check walks is already on disk with an equal-or-older mtime than the
# artifact; a same-second write compares equal, not stale (see the strict
# `>` below), and nothing this module writes can trigger its own staleness
# check. Verified empirically, not just by this argument — see the task
# report.
_MATRIX_SOURCES = ("problem.json", "solutions", "tests")


def _mtime_or_zero(path: Path) -> float:
    """`path`'s mtime, or `0.0` if it vanished between being listed and
    being stat'd. `status()` never raises (module docstring) — a file
    legitimately unlinked mid-walk (the exact `unlink`/`write_bytes` cycle
    `run_matrix` itself uses on `.a` files, or simply a concurrent edit)
    must not turn a read-only status check into a crash. Reporting `0.0`
    rather than propagating the race also cannot manufacture a false
    "stale": a vanished entry cannot be newer than anything.
    """
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def newest_source_mtime(problem_dir: Path,
                         extra_files: tuple[Path, ...] = ()) -> float:
    """The newest mtime among everything `invocation.json` is evidence
    about: every name in `_MATRIX_SOURCES`, and any `extra_files` (the
    custom checker, when `_matrix` below determines there is one).

    Public, and shared rather than duplicated: `review_checks._matrix()`
    is a second, independent reader of the same `invocation.json`, making
    the identical staleness claim about the identical files — a copy of
    this function there would be one more place the two checks could
    silently drift apart, which is exactly the failure this project keeps
    re-paying for (see the task report).

    Each `_MATRIX_SOURCES` name is handled generically, not just as
    "a directory": `problem.json` is ordinarily a file, but a hostile
    package can put anything at that path (see `TestStatus`'s hostile-input
    tests elsewhere in this module), so this stats whatever is actually
    there rather than assuming a shape. When it *is* a directory (the
    normal case for `solutions/`/`tests/`), both the directory itself and
    every entry `rglob` yields are stat'd — the directory's own mtime is
    what a deletion updates. Removing a test or a solution touches no
    remaining file at all, so skipping directories would make a deleted
    test invisible to this check and the gate would report "clean" over a
    weakened suite instead of naming the loss.
    """
    newest = 0.0
    for name in _MATRIX_SOURCES:
        path = problem_dir / name
        if path.is_file():
            newest = max(newest, _mtime_or_zero(path))
        elif path.is_dir():
            newest = max(newest, _mtime_or_zero(path))
            for child in path.rglob("*"):
                newest = max(newest, _mtime_or_zero(child))
    for extra in extra_files:
        newest = max(newest, _mtime_or_zero(extra))
    return newest


def _matrix(problem_dir: Path, problem: Problem | None) -> Phase:
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
        artifact_mtime = path.stat().st_mtime
    except OSError as exc:
        return Phase("matrix", False, f"invocation.json unreadable: {exc}")
    # A custom checker decides OK vs WA on every cell of the matrix — as
    # load-bearing as any solution or test, and edited independently of
    # both. `problem.checker_name` is only meaningful when `checker_kind`
    # is "custom" (a stock checker's `checker_name` names a testlib
    # checker this package does not own and cannot edit, so it is not a
    # source of *this* package's evidence going stale). Narrow on purpose:
    # `files/validator.cpp` or `files/gen-*.cpp` are not included, because
    # editing them does not change any recorded verdict until the tests
    # they produce are regenerated — and that regeneration is already
    # caught by the `tests/` walk above. Widening to all of `files/` would
    # add false-staleness for no gain.
    extra_files: tuple[Path, ...] = ()
    if problem is not None and problem.checker_kind == "custom":
        extra_files = (problem_dir / "files" / problem.checker_name,)
    # Before the holes/mismatches verdict, deliberately: a stale artifact
    # reporting zero holes must not read as "clean" — the detail a reader
    # sees has to name the reason they cannot trust the number, not the
    # number itself.
    if newest_source_mtime(problem_dir, extra_files) > artifact_mtime:
        return Phase("matrix", False,
                     "invocation.json is stale: a solution, test, "
                     "problem.json, or the checker changed after it was "
                     "written — re-run the matrix")
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
        _matrix(problem_dir, problem),
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

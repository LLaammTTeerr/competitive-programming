#!/usr/bin/env python3
"""Build every solution, run it on every test, and write invocation.json.

Timing policy, from the spec: the model solution is timed as the median of
three runs per test and the limit follows from its slowest test. Adversary
solutions get one run, and only a result landing in the [TL, kill] band is
re-run three times before being reported — three runs of everything triples
the cost of the pipeline for no gain outside the band.

Process control note: a naive `os.wait4(popen.pid, ...)` on top of
`subprocess.Popen` double-reaps — Popen already reaps its own child on
`.poll()`/`.wait()`/garbage collection, so a second `wait4` races it and can
raise `ChildProcessError` or read garbage rusage. This module owns the child
end-to-end instead: `os.posix_spawn` starts it with the stdio redirected via
POSIX_SPAWN_DUP2 file actions, and the *same* `os.wait4` call that first
observes the child's exit is the one that reaps it. There is exactly one
reaper per child, so there is no double-reap race — but that call's
`ru_maxrss` is *not* the child's own peak RSS: `fork`+`exec` (which is what
`posix_spawn` does under the hood) hands the child a COW copy of the
parent's address space, and `execve` folds that pre-exec mm's high-water
mark — i.e. the *driver's own RSS at spawn time* — into the freshly-exec'd
task's rusage before installing the new address space. `ru_maxrss` is
therefore `max(driver RSS at spawn, child's real peak)`, which floors every
reading at whatever the Python driver itself weighs and grows across a run
as the driver accumulates state. Peak RSS is instead read from the child's
own `/proc/<pid>/status` (`VmHWM`, which lives on the mm and is reset by
`execve`) while it is still alive; `ru_maxrss` is used only as a fallback
for the rare case where that read never lands before the child exits.
"""

from __future__ import annotations

import dataclasses
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

# testlib checker exit codes: 0 ok(), 1 quitf(_wa), 2 quitf(_pe) — which is
# also what _dirt (trailing garbage) and _unexpected_eof surface as, since
# testlib treats both as "the participant's output is malformed" rather than
# a distinct code — and 3 quitf(_fail), the package-bug signal. 7 (_points,
# partial-credit scoring) is deliberately left unmapped: this pipeline only
# uses whole-subtask stock checkers (ncmp et al.), none of which call
# quitp, so a 7 here would mean a checker mismatched to the problem, not a
# real partial-credit result — and should surface as FAIL, the same as any
# other exit code this table doesn't recognise. Defaulting every unmapped
# code to FAIL (never silently to OK/WA) keeps an unexpected checker
# exit from ever being mistaken for a verdict on the *solution*.
CHECKER_EXIT = {0: "OK", 1: "WA", 2: "PE", 3: "FAIL"}

# A checker only reads two or three files already on disk and compares them
# — even a checker doing something unusually heavy (diffing large output
# files) should finish in well under a second. 10s is a deliberately
# generous multiple of that (not tied to the problem's own TL, which bounds
# the *solution*, not the checker) so a merely-slow checker is never
# mistaken for a hung one, while a genuine infinite loop in a custom
# checker (externally-authored data, per R1) still fails in bounded time
# instead of hanging the whole pipeline.
CHECKER_TIMEOUT_S = 10


class MatrixError(RuntimeError):
    """The matrix could not be run: a build, fixture, or environment problem."""


def _compile(source: Path, binary: Path, extra: list[str] | None = None,
             *, context: str) -> None:
    if not source.exists():
        raise MatrixError(f"{context}: source file not found: {source}")
    cmd = ["g++", *CXXFLAGS, *(extra or []), str(source), "-o", str(binary)]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        raise MatrixError(
            f"{context}: compile failed\n$ {' '.join(cmd)}\n{done.stderr}"
        )


_SPIN_WINDOW_MS = 20  # see _run_once: dense polling for a short opening window


def _peak_rss_kb(pid: int) -> int | None:
    """Best-effort read of the child's own peak RSS while it is still alive.

    `VmHWM` lives on the process's mm and is already a running maximum since
    the last `execve` (which resets it), so a single successful read already
    reflects every high-water point observed up to that instant — it does
    not need to land on the actual peak moment, only sometime before the mm
    is torn down at exit. That teardown (`exit_mm`) happens *before* the
    task becomes reapable, i.e. before `os.wait4` can ever observe the exit,
    so this must be attempted on every poll iteration, not once at the end.
    Returns None if the read races the child's exit or is otherwise
    unavailable, so the caller can fall back to `ru_maxrss`.
    """
    try:
        with open(f"/proc/{pid}/status", "r", encoding="ascii", errors="replace") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])  # "VmHWM:\t 12345 kB" -> kB
    except (OSError, ValueError, IndexError):
        return None
    return None


def _run_once(binary: Path, stdin_path: Path, stdout_path: Path, kill_ms: int):
    """Run one process, returning (elapsed_ms, killed, exit_code, peak_kb).

    Spawns and reaps the child itself (see module docstring for why) so the
    single `os.wait4` that observes the exit is the one that reaps it — no
    double reap. `killed` is derived from the reaped wait status rather than
    from which branch of the loop broke it: a child that exits naturally in
    the window between a WNOHANG poll and the deadline check is still reaped
    with its true exit status even if a `kill()` lands on the (already-dead,
    now harmless) zombie, and that must not be reported as killed.

    The poll loop busy-spins (no sleep) for the first `_SPIN_WINDOW_MS` of a
    run, then backs off to a cheap 2ms sleep. A trivial competitive-
    programming solution can start, run, and exit in well under a
    millisecond — far faster than a fixed 2ms poll interval, which measured
    (see task-9-report.md) as often getting zero or one `/proc` samples in
    before the child was already gone, undercounting `VmHWM` by an order of
    magnitude. Spinning tightly for a short opening window catches that
    case; backing off afterward avoids pegging a CPU core for the whole of
    a multi-hundred-millisecond-to-several-second run, where a 2ms poll has
    ample opportunity to observe the same monotonic high-water mark anyway.
    """
    with open(stdin_path, "rb") as fin, \
         open(stdout_path, "wb") as fout, \
         open(os.devnull, "wb") as ferr:
        file_actions = [
            (os.POSIX_SPAWN_DUP2, fin.fileno(), 0),
            (os.POSIX_SPAWN_DUP2, fout.fileno(), 1),
            (os.POSIX_SPAWN_DUP2, ferr.fileno(), 2),
        ]
        started = time.monotonic()
        try:
            pid = os.posix_spawn(str(binary), [str(binary)], os.environ,
                                  file_actions=file_actions)
        except OSError as exc:
            raise MatrixError(f"could not start {binary}: {exc}") from exc

        status = 0
        rusage = None
        peak_kb = 0
        while True:
            hwm = _peak_rss_kb(pid)
            if hwm is not None:
                peak_kb = max(peak_kb, hwm)
            got_pid, status, rusage = os.wait4(pid, os.WNOHANG)
            if got_pid != 0:
                break
            elapsed_so_far_ms = (time.monotonic() - started) * 1000
            if elapsed_so_far_ms >= kill_ms:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                _, status, rusage = os.wait4(pid, 0)
                break
            if elapsed_so_far_ms >= _SPIN_WINDOW_MS:
                time.sleep(0.002)
        elapsed_ms = int((time.monotonic() - started) * 1000)

    if peak_kb == 0 and rusage is not None:
        # The /proc read never landed while the child was alive (a very
        # fast process, or a race with its exit) — fall back to the
        # driver-contaminated but still nonzero figure rather than report 0.
        peak_kb = rusage.ru_maxrss

    killed = os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    exit_code = os.waitstatus_to_exitcode(status)
    return elapsed_ms, killed, exit_code, peak_kb


def _time_median(binary, stdin_path, stdout_path, kill_ms, runs):
    """Median the elapsed time over `runs` runs; a crash on any run wins.

    `killed` and `code` are both sticky: `killed or k` never clears once
    True, and `code or c` never clears once nonzero (0 is falsy, so this
    keeps the first crash it sees rather than letting a later successful
    run silently overwrite it). Without that, a solution that crashes on
    run 1 and happens to succeed on runs 2-3 would pass the `code != 0`
    gate its caller checks — for the model solution specifically, that
    would mean accepting a flaky answer file as jury truth.
    """
    samples, killed, code, peak = [], False, 0, 0
    for _ in range(runs):
        ms, k, c, p = _run_once(binary, stdin_path, stdout_path, kill_ms)
        samples.append(ms)
        killed = killed or k
        code = code or c
        peak = max(peak, p)
    return int(statistics.median(samples)), killed, code, peak


def _check(checker: Path, test_in: Path, out: Path, ans: Path,
           *, timeout_s: float = CHECKER_TIMEOUT_S) -> str:
    try:
        done = subprocess.run([str(checker), str(test_in), str(out), str(ans)],
                              capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        print(f"WARNING: checker {checker} did not finish within {timeout_s}s "
              f"on test {test_in} — reporting FAIL", file=sys.stderr)
        return "FAIL"
    return CHECKER_EXIT.get(done.returncode, "FAIL")


def _tests_by_group(problem_dir: Path, problem: Problem) -> dict[str, list[Path]]:
    """Resolve every subtask's test files, failing loudly on a bad fixture.

    A missing tests/<group>/ directory or an empty one is a package defect,
    not "zero tests to run" — `Path.glob` on a nonexistent directory just
    yields nothing, so left unchecked this would silently produce an empty
    group and only fail much later inside `group_verdict`, far from the
    directory that is actually missing.
    """
    result: dict[str, list[Path]] = {}
    for sub in problem.subtasks:
        group_dir = problem_dir / "tests" / sub.id
        if not group_dir.is_dir():
            raise MatrixError(f"missing tests directory: {group_dir}")
        paths = sorted(group_dir.glob("*.in"))
        if not paths:
            raise MatrixError(f"no .in tests found in {group_dir}")
        result[sub.id] = paths
    return result


def run(problem_dir: str | Path, testlib_dir: str | Path, runs: int = 3) -> dict:
    problem_dir, testlib_dir = Path(problem_dir), Path(testlib_dir)
    problem = load(problem_dir / "problem.json")
    if problem.input != "stdin" or problem.output != "stdout":
        raise MatrixError(
            "file-based IO is not supported by this driver: "
            f"io.input={problem.input!r}, io.output={problem.output!r} "
            "(only io.input='stdin' / io.output='stdout' are handled; "
            "vnolymp-style file-IO problems — e.g. flight.inp/flight.out — "
            "would otherwise feed the model solution empty stdin, discard "
            "its real output, and this driver would report a confident "
            "wrong verdict instead of failing loudly. Supporting file IO "
            "is a later feature, not something to run silently-wrong now.)"
        )
    manifest = scan(problem_dir, problem)

    build = problem_dir / ".build"
    build.mkdir(exist_ok=True)

    if problem.checker_kind == "stock":
        checker_src = testlib_dir / "checkers" / f"{problem.checker_name}.cpp"
    else:
        checker_src = problem_dir / "files" / problem.checker_name
    checker = build / "checker"
    _compile(checker_src, checker, ["-Wpedantic", "-Werror", f"-I{testlib_dir}"],
             context=f"checker ({problem.checker_name})")

    binaries = {}
    for entry in manifest["solutions"]:
        binary = build / Path(entry["file"]).stem
        _compile(problem_dir / "solutions" / entry["file"], binary,
                  context=f"solution {entry['file']}")
        binaries[entry["file"]] = binary

    main_file = next(e["file"] for e in manifest["solutions"] if e["tag"] == "main")
    tests = _tests_by_group(problem_dir, problem)

    # Pass 1 — the model solution defines both the answers and the limits.
    # kill_ms=60_000 here is a hard safety ceiling, not a real limit: the
    # real TL/kill only exist once this pass has finished timing the model
    # solution, so there is no other number to use yet. A genuine infinite
    # loop in the model solution is diagnosed clearly below (it raises,
    # naming the test and whether it was killed) rather than hanging the
    # whole pipeline silently — but it does cost up to 60s of wall time per
    # test until that happens, which is acceptable for a small fixture and
    # a known, bounded cost for a real problem's test count.
    t_main: dict[str, int] = {}
    for group, paths in tests.items():
        for test in paths:
            answer = test.with_suffix(".a")
            ms, killed, code, _ = _time_median(binaries[main_file], test, answer,
                                               kill_ms=60_000, runs=runs)
            if killed:
                raise MatrixError(
                    f"model solution did not finish within 60000 ms on {test} "
                    "(hard safety kill during pass 1, before real limits exist)")
            if code != 0:
                raise MatrixError(f"model solution exited {code} on {test}")
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
                    first_run_ms = ms
                    ms, killed, code, peak = _time_median(
                        binaries[name], test, out, limits.kill_ms, runs)
                    outcome = classify(ms, killed, verdict_src, limits)
                    flags.append(
                        problem_dir, phase="validate-solutions", severity="medium",
                        kind="timing-band",
                        what=f"{name} on {group}/{test.stem} ran {first_run_ms} ms "
                             f"on its first (single) run, between TL {limits.tl_ms} "
                             f"and kill {limits.kill_ms}",
                        assumed=f"re-timed {runs}x for stability; the median came "
                                f"out {ms} ms, and the recorded verdict is "
                                f"{outcome.verdict} — there is no separate "
                                "'banded' verdict, only ever a real one "
                                "(TL if still over the limit, otherwise "
                                "whatever the checker returned)",
                        changes_if_wrong=f"the expected tag of {name}")

                if peak > problem.memory_mb * 1024:  # peak_kb is in KB
                    outcome = dataclasses.replace(outcome, verdict="ML")

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

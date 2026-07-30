#!/usr/bin/env python3
"""Build every solution, run it on every test, and write invocation.json.

Timing policy, from the spec: the model solution is timed as the median of
three runs per test and the limit follows from its slowest test. Adversary
solutions get one run, and only a result landing in the [TL, kill] band is
re-run three times before being reported — three runs of everything triples
the cost of the pipeline for no gain outside the band.

Runner: every solution runs inside the ioi/isolate sandbox (isolate 2.x).
This module previously spawned children itself (`os.posix_spawn` + a
`/proc/<pid>/status` polling loop for peak memory) and that approach had two
proven, opposite defects that no amount of polishing fixed: the `ru_maxrss`
fallback occasionally reported the *driver's* memory (a false-positive ML on
a correct solution), and `VmHWM` polling could only under-report a peak,
never over it (a false-negative ML on a solution engineered just over the
limit). isolate enforces both time and memory *in the kernel* and reports
the outcome in a meta file, so neither defect is possible here: a memory
kill is `cg-oom-killed:1` from the cgroup, not an after-the-fact comparison
against a polled reading, and a time kill is `status:TO` from the sandbox's
own clock, not a wait-loop deadline this process has to race against.

There is no fallback runner. If isolate is missing, or installed but not
usable (unconfigured cgroup delegation, no subuid/subgid range, the
isolate-cg-keeper service not running), `run()` raises `MatrixError` naming
the fix rather than silently reverting to something unsandboxed — see
`open_isolate_box()`.

isolate 2.x box-access model, and the trap it sets: after `--init` the box
directory is owned by the mapped subuid at mode 0700, so files cannot be
copied into it directly. This driver never touches that directory at all —
every run instead bind-mounts host directories we already own straight into
the sandbox (`--dir=<in>=<out>[:rw]`), which is unaffected by that ownership
and is the documented way to get files in and out. The one consequence: the
bind-mounted directory must itself be writable by *any* user (the sandboxed
process runs as a mapped subuid that is neither our uid nor our group), so
`.build/` is chmod'd world-writable for the run — an acceptable trade on a
single-user jury machine, not a multi-tenant one; see the report for this
being called out as a concern rather than silently assumed safe.

Meta-file contract this module parses (all four cases verified against the
isolate 2.6 build on this machine, not read off documentation):

    OK:  no `status` line at all; `exitcode:0`; `max-rss`; `cg-mem`.
    TLE: `status:TO`; `killed:1`; `time`; `message:Time limit exceeded`
         (the message differs for a wall-clock kill, the status does not).
    MLE: `status:SG`; `cg-oom-killed:1`; `cg-mem` pinned at the limit;
         `exitsig:9`; no `exitcode` line.
    RE:  `status:RE`; `exitcode:N`; `message:Exited with error status N`.

Two traps, both handled explicitly in `_run_once`: success emits no
`status` line at all (absence must be read as OK, not as "field missing");
and a memory kill arrives as `status:SG` — indistinguishable from a bare
segfault by the status text alone — so `cg-oom-killed` must be tested
*before* treating an `SG` status as a plain crash, or every OOM misreports
as RE.
"""

from __future__ import annotations

import dataclasses
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from tools import flags
from tools.matrix_core import Limits, Outcome, classify, compare, compute_limits, group_verdict
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

# Pass 1 has no TL/kill yet (they are derived *from* this pass), so it needs
# its own hard safety ceiling — same role the old fixed 60_000 ms kill
# played. The wall-time backstop is a separate, larger number: a model
# solution stuck blocking on I/O rather than burning CPU would never trip
# the CPU cap.
MODEL_SAFETY_CPU_S = 60.0
MODEL_SAFETY_WALL_S = 90.0


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


# ---------------------------------------------------------------------------
# isolate lifecycle: locate the binary, open one box for the whole run(),
# and guarantee its cleanup.
# ---------------------------------------------------------------------------

_ISOLATE_HOME = "https://github.com/ioi/isolate"


@dataclasses.dataclass(frozen=True)
class IsolateHandle:
    """One open isolate sandbox, reused for every run in this invocation.

    A box is expensive to set up relative to how cheap it is to reuse: this
    driver calls `--init` exactly once per `run()` and issues every
    `--run` for every solution/test through the same box id, varying only
    the bind-mounted directories per call (isolate reconstructs the box's
    mount view fresh on each `--run`, so this is safe — verified by
    running two different test groups through one inited box with no
    `--cleanup`/`--init` between them).
    """

    binary: str
    box_id: int
    version: str
    cg: bool
    meta_path: Path


def _isolate_binary_name() -> str:
    """The isolate executable to resolve.

    Reads `$ISOLATE_BIN` so both the test suite and a manual demonstration
    of the refuse-to-run path can point this at a nonexistent binary
    without editing source; defaults to plain "isolate" resolved off PATH.
    """
    return os.environ.get("ISOLATE_BIN", "isolate")


def _select_box_id() -> int:
    """Pick an isolate box id for this `run()` invocation.

    isolate box ids only need to be unique among *concurrently open* boxes
    on the machine (`isolate --box-id`'s own contract) — there is no shared
    allocator to coordinate through, and this tool is not itself run with
    high parallelism. This process's own pid is already unique among
    processes alive at the same instant, so `pid % 65536` (isolate's box-id
    range is 0-65535) gives a box id that only collides with another
    concurrently-running run_matrix invocation whose pid happens to differ
    by an exact multiple of 65536 — vanishingly unlikely at the scale this
    pipeline runs at, and far simpler than a lockfile/allocator.
    """
    return os.getpid() % 65536


def open_isolate_box() -> IsolateHandle:
    """Verify isolate is installed and usable, then open one sandbox.

    Raises `MatrixError` — naming the fix — for two distinct failure
    families rather than letting a bare `FileNotFoundError` or
    `subprocess.CalledProcessError` surface (R1: isolate's own failure
    modes are as much "externally authored" surface as a checker's exit
    code is):

    1. isolate is not on PATH at all.
    2. isolate is on PATH but `--init` fails — the likely case being an
       installed-but-unconfigured sandbox (no cgroup delegation, no
       isolate-cg-keeper service, no subuid/subgid range for the `isolate`
       user). This is diagnosed as a *different* message from case 1 so a
       reader is not sent chasing a reinstall when the real problem is
       configuration.
    """
    name = _isolate_binary_name()
    binary = shutil.which(name)
    if binary is None:
        raise MatrixError(
            f"isolate not found: {name!r} is not an executable on PATH. "
            "This pipeline runs every solution inside the ioi/isolate "
            "sandbox and does not fall back to an unsandboxed runner. "
            f"Install isolate and put it on PATH — {_ISOLATE_HOME}"
        )

    version_done = subprocess.run([binary, "--version"], capture_output=True, text=True)
    version = version_done.stdout.splitlines()[0] if version_done.stdout else "unknown"

    box_id = _select_box_id()
    init = subprocess.run([binary, "--cg", f"--box-id={box_id}", "--init"],
                          capture_output=True, text=True)
    if init.returncode != 0:
        raise MatrixError(
            f"isolate is installed at {binary} but `--init` failed "
            f"(exit {init.returncode}): {(init.stderr or init.stdout).strip()}\n"
            "A missing binary would have failed above with a different "
            "message; this is the installed-but-unconfigured case instead — "
            "isolate needs cgroup v2 delegation, the isolate-cg-keeper "
            "service (isolate.service) enabled and running, and the "
            "'isolate' system user's range registered in /etc/subuid and "
            f"/etc/subgid. See {_ISOLATE_HOME}."
        )

    meta_fd, meta_name = tempfile.mkstemp(prefix="run_matrix_isolate_meta_")
    os.close(meta_fd)
    return IsolateHandle(binary=binary, box_id=box_id, version=version, cg=True,
                         meta_path=Path(meta_name))


def close_isolate_box(handle: IsolateHandle) -> None:
    """Best-effort teardown; never raises.

    Always called from a `finally`, so a cleanup failure here must not mask
    whatever real error (or real result) is already propagating — the
    concern this guards is a leaked box under `/var/local/lib/isolate/`,
    not a crash in the cleanup call itself.
    """
    subprocess.run([handle.binary, "--cg", f"--box-id={handle.box_id}", "--cleanup"],
                    capture_output=True, text=True)
    try:
        handle.meta_path.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Sandboxed execution.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RunResult:
    """One sandboxed execution, already classified from isolate's meta file.

    `oom` and `killed` are mutually exclusive by construction (isolate only
    ever reports one `status`), and `oom` must be checked independently of
    `status` text — a memory kill arrives as `status:SG`, the same status a
    bare segfault gets, and `cg-oom-killed` is the only field that tells
    them apart (see module docstring). `crashed` folds together isolate's
    `RE` status and a genuine non-OOM `SG` (the process died from a signal
    that was not the cgroup's doing, e.g. its own SIGSEGV/SIGABRT) into one
    "this is a runtime error, don't consult the checker" signal, mirroring
    what the old driver did with `code != 0`.

    `cpu_ms` (isolate's `time`) is the primary metric fed to `classify()`
    (judges limit CPU time, and it is far less sensitive to other load on
    this ratio-based model); `wall_ms` (`time-wall`) is carried alongside
    purely so `invocation.json` records both and is never ambiguous about
    which clock produced a reading.
    """

    cpu_ms: int
    wall_ms: int
    killed: bool
    oom: bool
    crashed: bool
    exit_code: int
    peak_kb: int


def _parse_meta(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        meta[key] = value
    return meta


def _run_once(isolate: IsolateHandle, binary: Path, stdin_path: Path,
              stdout_path: Path, cpu_limit_s: float, wall_limit_s: float,
              mem_limit_kb: int) -> RunResult:
    """Run one process inside `isolate`'s sandbox and return its verdict.

    `binary`, `stdin_path`, and `stdout_path` may live in up to three
    distinct directories — pass 1 in particular reads from and writes to
    `tests/<group>/` directly (regenerating the `.a` answer file there),
    while pass 2 reads from `tests/<group>/` but writes into `.build/`
    alongside the binaries. Each distinct parent directory gets its own
    bind mount (isolate supports repeated `--dir=<in>=<out>` rules, verified
    manually); directories that coincide (e.g. binary and stdout both under
    `.build/` in pass 2) are only mounted once. Only the directory holding
    `stdout_path` needs `:rw` — the sandboxed process only ever *creates* a
    file there, never in the binary's or stdin's directory.

    Before running, `stdout_path` is unlinked if it already exists. isolate
    2.x's box-access model hands files it creates to a *mapped subuid*
    (`200000 + box_id`, not our own uid), so a stale file left over from an
    earlier invocation — possibly created under a different box_id, hence a
    different subuid, hence not writable by this run's subuid even under a
    world-writable directory — could otherwise make an ordinary re-run of
    this driver fail with a permission error. Unlinking depends only on the
    *directory's* write permission, which we do own, so this is safe
    regardless of who owns the stale file.
    """
    stdout_path.unlink(missing_ok=True)

    mounts: dict[Path, str] = {}

    def _label(path: Path) -> str:
        resolved = path.resolve()
        if resolved not in mounts:
            mounts[resolved] = f"/host{len(mounts)}"
        return mounts[resolved]

    bin_label = _label(binary.parent)
    stdin_label = _label(stdin_path.parent)
    stdout_label = _label(stdout_path.parent)
    write_dir = stdout_path.parent.resolve()

    cmd = [
        isolate.binary, "--cg", f"--box-id={isolate.box_id}", "--run",
        f"--meta={isolate.meta_path}",
        f"--time={cpu_limit_s:.3f}", f"--wall-time={wall_limit_s:.3f}",
        f"--cg-mem={mem_limit_kb}",
    ]
    for resolved, label in mounts.items():
        opt = ":rw" if resolved == write_dir else ""
        cmd.append(f"--dir={label}={resolved}{opt}")
    cmd += [
        f"--chdir={bin_label}",
        f"--stdin={stdin_label}/{stdin_path.name}",
        f"--stdout={stdout_label}/{stdout_path.name}",
        "--", f"{bin_label}/{binary.name}",
    ]

    subprocess.run(cmd, capture_output=True, text=True)
    # isolate's own process exit code is not the contract here — 0 means OK
    # but 1 covers TO/SG/RE alike, so it cannot distinguish them. The meta
    # file is the actual contract (verified against this exact isolate
    # build; see the module docstring and the task report for pasted
    # output from all four cases).
    try:
        meta_text = isolate.meta_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MatrixError(
            f"isolate produced no readable meta file for {binary} on "
            f"{stdin_path}: {exc}"
        ) from exc
    if not meta_text.strip():
        raise MatrixError(
            f"isolate produced an empty meta file for {binary} on "
            f"{stdin_path} — the sandboxed run did not report any outcome"
        )
    meta = _parse_meta(meta_text)

    status = meta.get("status")  # absent -> OK; see module docstring trap 1
    if status == "XX":
        raise MatrixError(
            f"isolate reported an internal error (status XX) running "
            f"{binary} on {stdin_path}: {meta.get('message', '(no message)')} "
            "— this is isolate's own failure, not a verdict on the solution."
        )

    oom = meta.get("cg-oom-killed") == "1"  # must be tested before treating
    killed = status == "TO"                 # SG as a plain crash (trap 2)
    crashed = (not oom) and status in ("RE", "SG")

    try:
        cpu_ms = int(round(float(meta.get("time", "0")) * 1000))
        wall_ms = int(round(float(meta.get("time-wall", "0")) * 1000))
        peak_kb = int(meta.get("max-rss", "0"))
        exit_code = int(meta.get("exitcode", "0"))
    except ValueError as exc:
        raise MatrixError(
            f"isolate meta file malformed for {binary} on {stdin_path}: "
            f"{meta!r} ({exc})"
        ) from exc

    return RunResult(cpu_ms=cpu_ms, wall_ms=wall_ms, killed=killed, oom=oom,
                      crashed=crashed, exit_code=exit_code, peak_kb=peak_kb)


def _time_median(isolate: IsolateHandle, binary: Path, stdin_path: Path,
                  stdout_path: Path, cpu_limit_s: float, wall_limit_s: float,
                  mem_limit_kb: int, runs: int) -> RunResult:
    """Median the CPU/wall time over `runs` runs; any bad outcome wins.

    `killed`/`oom`/`crashed` are all sticky-OR (never cleared once True) and
    `exit_code` is sticky-first-nonzero — mirroring the old driver's
    reasoning for the model solution specifically: a run that fails once
    and happens to succeed on a later retry must not have that failure
    silently overwritten, or a flaky answer file could pass as jury truth.
    """
    cpu_samples, wall_samples = [], []
    killed = oom = crashed = False
    exit_code = 0
    peak = 0
    for _ in range(runs):
        r = _run_once(isolate, binary, stdin_path, stdout_path,
                      cpu_limit_s, wall_limit_s, mem_limit_kb)
        cpu_samples.append(r.cpu_ms)
        wall_samples.append(r.wall_ms)
        killed = killed or r.killed
        oom = oom or r.oom
        crashed = crashed or r.crashed
        exit_code = exit_code or r.exit_code
        peak = max(peak, r.peak_kb)
    return RunResult(
        cpu_ms=int(statistics.median(cpu_samples)),
        wall_ms=int(statistics.median(wall_samples)),
        killed=killed, oom=oom, crashed=crashed,
        exit_code=exit_code, peak_kb=peak,
    )


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


def _ensure_sandbox_readable(path: Path) -> None:
    """Grant "other" read access to a file the sandbox must open.

    The sandboxed process runs as a mapped subuid that is neither our uid
    nor our group (isolate 2.x's bind-mount model — see module docstring),
    so anything it must read needs the "other" bits regardless of the
    umask a real problem package happened to be created under. This
    matters beyond the checked-in fixture (which already satisfies it by
    luck of the default 022 umask): a stricter umask must not turn into a
    silent, spurious sandbox permission failure.
    """
    os.chmod(path, path.stat().st_mode | 0o004)


def _ensure_sandbox_writable_dir(path: Path) -> None:
    """Make a directory fully open to the sandbox: traverse, read, create.

    `tests/<group>/` is not just read from — pass 1 writes the model
    solution's stdout straight into `<test>.a` there (regenerating the
    answer key), so the sandboxed subuid needs to be able to create files
    in it, the same way `.build/` needs to be world-writable for pass 2's
    outputs (see `run()`). Same trade-off, same acceptance: fine on a
    single-user jury machine, not something to assume safe on a shared one.
    """
    os.chmod(path, path.stat().st_mode | 0o007)


def _classify(r: RunResult, checker: Path, test: Path, out: Path, ans: Path,
              limits: Limits) -> Outcome:
    """Turn one sandboxed execution into an `Outcome`.

    Memory classification is authoritative, not inferred: `cg-oom-killed`
    *is* the ML signal (isolate enforced `--cg-mem` in the kernel), so an
    OOM run short-circuits straight to `Outcome("ML", ...)` without ever
    consulting `classify()` or the checker — there is no comparison against
    a polled peak-RSS reading left to make. A killed (TL) or crashed (RE)
    run likewise skips the checker: "a judge stops a solution at the limit,
    so the checker never runs on one that exceeded it" is already
    `classify()`'s own stated doctrine for the TL case, and it applies just
    as much to a run that never produced valid output to check at all.
    """
    if r.oom:
        return Outcome("ML", banded=False)
    if r.killed:
        verdict_src = ""  # unused: classify() returns TL before consulting it
    elif r.crashed:
        verdict_src = "RE"
    else:
        verdict_src = _check(checker, test, out, ans)
    return classify(r.cpu_ms, r.killed, verdict_src, limits)


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
    # World-writable: the sandboxed process creates its stdout file (and any
    # scratch it likes) here, and it runs as a mapped subuid that is neither
    # our uid nor our group (see module docstring) — 0700/0755 would give it
    # nowhere to write. Acceptable on a single-user jury machine; called out
    # as a concern in the task report rather than assumed safe silently.
    os.chmod(build, 0o777)

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
    for paths in tests.values():
        _ensure_sandbox_writable_dir(paths[0].parent)
        for test in paths:
            _ensure_sandbox_readable(test)

    mem_limit_kb = problem.memory_mb * 1024
    isolate = open_isolate_box()
    try:
        # Pass 1 — the model solution defines both the answers and the
        # limits. The 60s/90s CPU/wall ceiling here is a hard safety cap,
        # not a real limit: the real TL/kill only exist once this pass has
        # finished timing the model solution, so there is no other number
        # to use yet. A genuine infinite loop in the model solution is
        # diagnosed clearly below (it raises, naming the test and why)
        # rather than hanging the whole pipeline silently.
        #
        # t_main is now CPU time (isolate's `time`), not wall time — this
        # is the change instruction 1 calls for, since judges limit CPU
        # time and it is far less sensitive to other load on this box. It
        # changes what every `t_main_ms`/`time_ms`/`ratio` figure in
        # invocation.json means; see the task report.
        t_main: dict[str, int] = {}
        for group, paths in tests.items():
            for test in paths:
                answer = test.with_suffix(".a")
                r = _time_median(isolate, binaries[main_file], test, answer,
                                 MODEL_SAFETY_CPU_S, MODEL_SAFETY_WALL_S,
                                 mem_limit_kb, runs)
                if r.killed:
                    raise MatrixError(
                        f"model solution did not finish within "
                        f"{int(MODEL_SAFETY_CPU_S * 1000)} ms CPU time on "
                        f"{test} (hard safety kill during pass 1, before "
                        "real limits exist)")
                if r.oom:
                    raise MatrixError(
                        f"model solution exceeded the memory limit "
                        f"({problem.memory_mb} MB) on {test}")
                if r.crashed or r.exit_code != 0:
                    raise MatrixError(
                        f"model solution exited {r.exit_code} on {test}")
                t_main[f"{group}/{test.stem}"] = r.cpu_ms

        limits = compute_limits(t_main)

        # Pass 2 — everything else, one run, band results re-timed.
        # `--time` is set to `kill_ms` (not `tl_ms`): that is the value the
        # old driver's own wait loop enforced as its hard kill deadline,
        # and preserving it here is what keeps the [TL, kill] band
        # reachable at all — a solution genuinely running between TL and
        # kill must be allowed to actually finish in that window so
        # `classify()` can band it, not be cut off by isolate at TL first.
        # `--wall-time` is `max(3 * tl_ms, kill_ms)`: the instructed "3x TL"
        # backstop, floored at `kill_ms` so it is never smaller than the
        # CPU cap it backstops (which would happen if a caller ever forces
        # a degenerate tl_ms, e.g. this module's own timing-band test).
        cpu_limit_s = limits.kill_ms / 1000.0
        wall_limit_s = max(3 * limits.tl_ms, limits.kill_ms) / 1000.0

        results, actual = [], {}
        for entry in manifest["solutions"]:
            name = entry["file"]
            actual[name] = {}
            for group, paths in tests.items():
                per_test = []
                for test in paths:
                    out = build / f"{Path(name).stem}.{group}.{test.stem}.out"
                    answer = test.with_suffix(".a")
                    r = _run_once(isolate, binaries[name], test, out,
                                 cpu_limit_s, wall_limit_s, mem_limit_kb)
                    outcome = _classify(r, checker, test, out, answer, limits)

                    if outcome.banded:
                        first_run_ms = r.cpu_ms
                        r = _time_median(isolate, binaries[name], test, out,
                                         cpu_limit_s, wall_limit_s,
                                         mem_limit_kb, runs)
                        outcome = _classify(r, checker, test, out, answer, limits)
                        flags.append(
                            problem_dir, phase="validate-solutions", severity="medium",
                            kind="timing-band",
                            what=f"{name} on {group}/{test.stem} ran {first_run_ms} ms "
                                 f"CPU time on its first (single) run, between TL "
                                 f"{limits.tl_ms} and kill {limits.kill_ms}",
                            assumed=f"re-timed {runs}x for stability; the median came "
                                    f"out {r.cpu_ms} ms, and the recorded verdict is "
                                    f"{outcome.verdict} — there is no separate "
                                    "'banded' verdict, only ever a real one "
                                    "(TL if still over the limit, otherwise "
                                    "whatever the checker returned)",
                            changes_if_wrong=f"the expected tag of {name}")

                    per_test.append(outcome.verdict)
                    results.append({
                        "solution": name, "group": group, "test": test.stem,
                        "verdict": outcome.verdict,
                        "time_ms": r.cpu_ms, "wall_ms": r.wall_ms,
                        "ratio": round(r.cpu_ms / max(limits.t_main_ms, 1), 2),
                        "peak_kb": r.peak_kb, "killed": r.killed, "oom": r.oom,
                        "banded": outcome.banded,
                    })
                actual[name][group] = group_verdict(per_test)
    finally:
        close_isolate_box(isolate)

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
            "runner": "isolate",
            "runner_version": isolate.version,
            "cg": isolate.cg,
        },
        "t_main_ms": {"per_test": t_main, "max": limits.t_main_ms,
                      "runs": runs, "method": "median", "metric": "cpu"},
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

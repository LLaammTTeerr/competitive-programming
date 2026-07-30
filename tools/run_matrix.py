#!/usr/bin/env python3
"""Build every solution, run it on every test, and write invocation.json.

Timing policy, from the spec: the model solution is timed as the median of
three runs per test and the limit follows from its slowest test. Adversary
solutions get one run, and only a result landing in the (TL, kill] band —
strictly over TL, since a run exactly at TL is accepted, up through kill — is
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
the outcome in a meta file: a memory kill is `cg-oom-killed:1` from the
cgroup, not an after-the-fact comparison against a polled reading, and a
time kill is `status:TO` from the sandbox's own clock, not a wait-loop
deadline this process has to race against.

What this module *does* guarantee about accounting, stated precisely
because a stronger claim ("neither defect is possible here") stood in this
docstring for two tasks and was false the whole time — see the staging
paragraph below for the third relocation of the same defect class:

    Memory is bounded by `--cg-mem` and reported by `max-rss`. Output size
    is bounded by `--fsize` (`OUTPUT_LIMIT_KB`) and is *not* reported at
    all. These are two different limits over two different resources, and
    the only thing that keeps them independent is that the file a solution
    writes its stdout to lives on a **disk-backed** filesystem. On tmpfs
    they are the same limit, because tmpfs pages are charged to the writing
    cgroup and are never reclaimable — a solution printing 70 MB under a
    64 MB memory limit is OOM-killed for its *output*, and reported ML on
    2.5% of the limit it was actually given. That is why `_stage_base()`
    refuses to stage on a memory-backed filesystem rather than warning, and
    why `--fsize` is passed explicitly rather than left to the accident of
    where the staging directory happened to land.

There is no fallback runner. If isolate is missing, or installed but not
usable (unconfigured cgroup delegation, no subuid/subgid range, the
isolate-cg-keeper service not running), `run()` raises `MatrixError` naming
the fix rather than silently reverting to something unsandboxed — see
`open_isolate_box()`.

isolate 2.x box-access model, and the trap it sets: after `--init` the box
directory is owned by the mapped subuid at mode 0700, so files cannot be
copied into it directly. This driver never touches that directory at all —
every run instead bind-mounts host directories straight into the sandbox
(`--dir=<in>=<out>[:rw]`), which is unaffected by that ownership and is the
documented way to get files in and out.

Task 9b's own review found and this driver now avoids a second trap in the
same neighbourhood: an *earlier* version of this module bind-mounted real
repository directories (`tests/<group>/`, `.build/`) as the `:rw` target so
the sandboxed process could write its stdout (the regenerated `.a` answer
file, a solution's `.out`) directly into them. That "worked" but was wrong
in a way `git status` cannot see, because both paths are gitignored: the
sandboxed process runs as a mapped subuid that is neither our uid nor our
group, so making a directory writable to it meant granting the repo
directory an `o+w` bit that was never restored, and every file the sandbox
created inside it came back owned by that subuid — not us, not writable or
even `chmod`-able by us afterward. That is permanent, silent damage to the
user's working tree: `chmod -R`, `rsync -p`, `tar --same-owner`, or a
CI rewrite of the checkout would all fail on those files, and — worse —
`tests/<group>/` at `o+rwx` on a shared jury machine means any local
account could substitute test inputs or answer keys for a problem still
under preparation. This driver instead gives every `--run` a *private*
staging directory (`IsolateHandle.stage_dir`, one `mkdtemp` per `run()`,
world-writable — which is harmless there, since it is ours and ephemeral)
as the only `:rw` mount; the binary's and the test input's directories are
mounted read-only. After each run, the
staged output is copied back into the repository with an ordinary
`Path.write_bytes()` call from *this* (unprivileged) process — never
bind-mounted — so every artifact that lands in the user's tree keeps its
normal ownership and the repo directory's own mode is never touched. The
copy always unlinks the destination first (`stdout_dest.unlink(missing_ok=
True)`, relying only on directory-write permission, which this process
already has as the owner), which doubles as a self-heal for a repo already
damaged by the old behaviour: a stale, foreign-owned `.a`/`.out` left over
from a previous run of this driver is simply replaced, not fought with.
`_ensure_dir_traversable()` similarly self-heals the directory-mode half of
that damage — it strips any stray `o+w` bit left on `tests/<group>/` or
`.build/` while granting the `o+x` (traverse) bit these read-only mounts
still need, every time `run()` starts.

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

Task 9c: a fresh box per `--run`, not one box reused for the whole
invocation. The `flight` dogfood found what neither the 9b migration nor
its review did: isolate's cgroup counters are **not reset between `--run`s
in the same box** — reproduced with bare isolate, no involvement from this
module: a memory hog OOMing at 400 MB in box N, followed by
`int main(){return 0;}` in the *same* box N, reports the hog's
`cg-oom-killed:1` for the trivial program too. Since ML outranks WA in
`_SEVERITY` (`matrix_core`), one OOM used to silently overwrite every
later solution's verdict in that run — not merely add a wrong row, replace
correct ones. This is the bug that mattered: `cg-oom-killed` is sticky
across `--run`s in the same box, and this module's classification reads it
directly (see `_run_once`). `cg-mem` is *also* a box-lifetime high-water
mark in the same way — verified directly against the same box (a 200 MB
run followed by a trivial one reported `cg-mem` unchanged) — but this is
not a second consequence for this driver specifically: `peak_kb` is read
from `max-rss`, never from `cg-mem` (see `_run_once`), and `max-rss` is
sourced from `wait4()`/`getrusage()` on the sandboxed *process* rather
than the cgroup, so it resets correctly with every fresh process
regardless of box reuse (also verified directly: same before/after pair,
`max-rss` dropped back down while `cg-mem` stayed pinned). `peak_kb` was
never contaminated, and no `invocation.json` produced before this fix has
an inflated memory column — but `cg-mem` remains unreliable across `--run`s
in a shared box and must not be read that way in the future without this
same per-run isolation. This is the same class of defect the 9b migration
was fixing (memory accounting contaminated by something other than the
process being measured); the live instance of it here had just relocated
from the parent process's address space into the box's cgroup, and it
surfaced as a corrupted verdict rather than a corrupted number. The fix:
`_run_once` now owns a full `--init`/`--run`/`--cleanup` cycle for its own
box id, so no run can ever observe another run's counters — on any field,
whether or not this driver currently reads it. `open_isolate_box()` still
does one probe `--init`/`--cleanup` at startup (to fail fast, before any
compilation, if isolate is missing or unconfigured) but no longer holds a
box open across the whole invocation — see `IsolateHandle.box_id_counter`
for how each call gets its own id.

Where the staging directory lives, and why it is not `/tmp`: the third
relocation of one defect class. The staging directory 9b introduced was a
plain `tempfile.mkdtemp()`, which lands under `$TMPDIR` — `/tmp` — and
`/tmp` is `tmpfs` on this machine and on most modern Linux. `--stdout`
points into that directory while `--cg-mem` caps the same cgroup, and
tmpfs pages are charged to the writing cgroup and are not reclaimable, so
**a solution's own stdout counted against its memory limit**. Reproduced
with bare isolate, no involvement from this module: a 1.6 MB program
writing 70 MB to stdout under a 64 MB limit reported
`max-rss:1668  cg-mem:65536  cg-oom-killed:1  status:SG` — a false ML on a
program using 2.5% of the limit it was given. This is the same class as
the two above (memory accounting contaminated by something other than the
process being measured): it was the parent's `mm` (9), then the box's
cgroup (9c), and then the directory the output was staged in. The fix has
two halves and both are load-bearing:

  * `_stage_base()` picks a **disk-backed** location — by default the
    problem directory's parent (the same filesystem as the work being
    staged), overridable with `$RUN_MATRIX_STAGE_DIR`, never falling back
    to `/tmp`. If the chosen location is memory-backed it raises
    `MatrixError` rather than warning: this driver's standing doctrine is
    that it refuses to run rather than produce a confidently wrong
    verdict, the same call already made for a missing sandbox and for
    file-based IO, and a warning on stderr in the middle of a few hundred
    runs is exactly the thing a caller reads past.

  * `--fsize=OUTPUT_LIMIT_KB` bounds the output explicitly. Until this
    fix, tmpfs *accidentally* capped output at `memory_mb`; moving staging
    to disk removes that accident, and a `while(1) putchar()` solution —
    precisely the kind a deliberately-wrong zoo invites — would otherwise
    write until the disk filled and then have the whole file loaded into
    the driver's RAM by `staged_out.read_bytes()`. Exceeding `--fsize`
    kills the process with SIGXFSZ, which arrives as `status:SG` with no
    `cg-oom-killed`, so it is classified `RE` — the honest verdict for a
    solution whose output ran away, and distinct from the `ML` a real
    memory hog gets.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import os
import platform
import shutil
import stat
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

# Where the per-invocation staging directory is created, and the escape
# hatch for a machine whose problem tree is somewhere unsuitable. Read by
# `_stage_base()`; deliberately not defaulted to `/tmp` under any
# circumstance — see the module docstring for the false-ML that caused.
STAGE_DIR_ENV = "RUN_MATRIX_STAGE_DIR"

# Filesystems whose pages are charged to the writing process's cgroup and
# are not reclaimable — i.e. the ones where a file write is indistinguishable
# from an allocation as far as `--cg-mem` is concerned.
MEMORY_BACKED_FSTYPES = frozenset({"tmpfs", "ramfs", "devtmpfs"})

# `--fsize`: the hard ceiling, in KB, on any single file the sandboxed
# process can create — in practice its stdout, the only file it writes.
#
# 256 MB, chosen deliberately rather than inherited:
#   * It must be far above any legitimate output. The largest plausible
#     answer for a problem this pipeline handles is on the order of 10^6
#     numbers at ~20 bytes each, i.e. tens of MB; 256 MB is an order of
#     magnitude clear of that, so no correct solution is ever truncated
#     into a false WA/RE. A false verdict is the expensive failure here,
#     and it is the one this number is sized against.
#   * It must be low enough that the runaway case stays survivable, because
#     `_run_once` reads the staged file whole into this process's memory
#     (`staged_out.read_bytes()`) before copying it back. 256 MB is a
#     bounded, recoverable read; an unbounded one is not, and neither is a
#     `while(1) putchar()` allowed to fill the user's disk.
#   * 256 MB is also the output cap mainstream judges use (Codeforces),
#     so a solution that trips this one would have tripped a real judge's.
# Note the consequence for `.build/`: a runaway solution can leave a file
# of this size per test until the next run overwrites it. That is the
# deliberate price of not truncating a legitimate answer.
OUTPUT_LIMIT_KB = 256 * 1024


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
    """The isolate environment for one `run()` invocation — no box is held
    open across calls any more (Task 9c).

    A single box reused for every `--run` was the original design, on the
    theory that a box is expensive to set up relative to how cheap it is to
    reuse. That theory was wrong in a way neither the 9b migration nor its
    review caught: isolate's cgroup counters (`cg-mem`, `cg-oom-killed`) are
    **not reset between `--run`s in the same box** — reproduced with bare
    isolate, no involvement from this module (see the module docstring for
    the precise before/after values, and for which of the two actually
    reached this driver's output: `cg-oom-killed` did, `cg-mem` did not,
    because `peak_kb` is read from `max-rss` and never from `cg-mem`). So
    every `--run` now gets a brand-new box id, `--init`ed immediately
    before it and `--cleanup`ed immediately after (see `_run_once`), and
    this handle carries only what is shared safely across that churn:

    `box_id_counter` hands out a fresh id for each call. It starts from
    this process's own pid-derived base (`_select_box_id()` — unique among
    *concurrently running* `run_matrix` invocations, isolate's own
    contract for box ids) and increments by one per call, wrapping at
    isolate's box-id range (0-65535). Advancing rather than reusing the
    same id every time isn't needed for correctness — a fully torn-down
    box (`--cleanup` completed) has no state left to leak into the next
    `--init` at the same id — but it costs nothing and further shrinks an
    already-tiny collision window: a box now exists only for the duration
    of one `--run`, not this whole invocation, so two processes would have
    to land the exact same id at the exact same instant, not merely during
    overlapping lifetimes.

    `stage_dir` is a private `mkdtemp()` directory that is the *only* `:rw`
    mount any `--run` ever uses (unrelated to box identity — a plain host
    directory, shared across every box this invocation opens) — see the
    module docstring for why a real repo directory must never be the write
    target again. It lives for the whole `run()` invocation: created in
    `open_isolate_box()`, removed in `close_isolate_box()`. Its *location*
    is chosen by `_stage_base()` and must be disk-backed, not `/tmp`: on
    tmpfs the bytes a solution writes here are charged to the same cgroup
    `--cg-mem` caps, which is a false ML on any solution with a large
    answer.
    """

    binary: str
    version: str
    meta_path: Path
    stage_dir: Path
    box_id_counter: itertools.count


def _filesystem_type(path: Path) -> str | None:
    """The type of the filesystem `path` lives on, or None if unknowable.

    Reads `/proc/mounts` and picks the longest mount point that is a prefix
    of the resolved path — the same longest-prefix rule the kernel itself
    uses, so a `tmpfs` mounted *inside* a disk-backed tree (or the reverse)
    is resolved correctly rather than by the first line that happens to
    match. Mount points in `/proc/mounts` are octal-escaped; the three
    escapes that occur in practice are decoded.

    Returns None on any platform without `/proc/mounts` rather than
    guessing: an unknown filesystem type is treated as acceptable by
    `_stage_base()`, since refusing to run everywhere `/proc` is absent
    would be a worse failure than the one this detection prevents.
    """
    try:
        raw = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    target = os.path.realpath(path)
    best_len, best_type = -1, None
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        point = (fields[1].replace("\\040", " ").replace("\\011", "\t")
                 .replace("\\012", "\n").replace("\\134", "\\"))
        if target == point or target.startswith(point.rstrip("/") + "/"):
            if len(point) > best_len:
                best_len, best_type = len(point), fields[2]
    return best_type


def _stage_base(problem_dir: str | Path | None) -> Path:
    """Pick the directory the per-invocation staging directory is created in.

    Order: `$RUN_MATRIX_STAGE_DIR` if set, otherwise the problem
    directory's *parent* — same filesystem as the package being staged,
    which is the property that matters — otherwise the current working
    directory (only reachable when a caller opens a box without naming a
    problem, e.g. a unit test driving `_run_once` directly).

    There is no `/tmp` fallback on any path through this function, and that
    is the entire point of it existing: `tempfile.mkdtemp()` with no `dir=`
    lands in `/tmp`, `/tmp` is tmpfs here and on most modern Linux, and a
    file written to tmpfs is charged to the writing cgroup — the same
    cgroup `--cg-mem` caps. See the module docstring for the measured false
    ML that produced.

    Raises `MatrixError` — never warns — when the chosen location is
    unusable or memory-backed. A warning would be the wrong call twice
    over: it scrolls past in the middle of a few hundred sandboxed runs,
    and the failure it precedes is a *wrong verdict on a correct
    solution*, which this driver already refuses to risk elsewhere (a
    missing sandbox, file-based IO) rather than proceed through.
    """
    override = os.environ.get(STAGE_DIR_ENV)
    if override:
        base, source = Path(override), f"${STAGE_DIR_ENV}"
    elif problem_dir is not None:
        base, source = Path(problem_dir).resolve().parent, "the problem directory's parent"
    else:
        base, source = Path.cwd(), "the current working directory"

    if not base.is_dir():
        raise MatrixError(
            f"staging directory base {base} ({source}) is not a directory. "
            f"Set ${STAGE_DIR_ENV} to a writable directory on a disk-backed "
            "filesystem."
        )
    if not os.access(base, os.W_OK | os.X_OK):
        raise MatrixError(
            f"staging directory base {base} ({source}) is not writable by "
            f"this process. Set ${STAGE_DIR_ENV} to a writable directory on "
            "a disk-backed filesystem."
        )

    fstype = _filesystem_type(base)
    if fstype in MEMORY_BACKED_FSTYPES:
        raise MatrixError(
            f"refusing to stage sandbox output on {base} ({source}): it is "
            f"on a {fstype} filesystem, which is memory-backed. Every byte a "
            "solution writes to stdout would be charged against its own "
            "--cg-mem limit and never reclaimed, so a correct solution that "
            "prints a large answer is OOM-killed and reported ML while using "
            "a fraction of the memory it was given (measured: 70 MB of output "
            "at a 64 MB limit reported max-rss:1668 KB, cg-oom-killed:1). "
            f"Set ${STAGE_DIR_ENV} to a directory on a disk-backed "
            "filesystem. This driver does not fall back to /tmp, and does "
            "not run with an accounting defect it can see."
        )
    return base


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

    And even that unlikely collision cannot produce a *wrong verdict*, only
    a loud one: `--init` on a box id that is already open is idempotent (it
    returns 0, reusing/reinitializing the same box) rather than failing, so
    two colliding invocations don't fail here — they fail later, when their
    concurrent `--run`s and `--cleanup`s race on the same box directory.
    The worst case observed for that kind of collision is isolate itself
    reporting an internal error for one side (e.g. "Box not found" /
    `status:XX`), which `_run_once` already turns into a `MatrixError`
    naming isolate's own failure (see its docstring) — never a misreported
    verdict on a solution.
    """
    return os.getpid() % 65536


def _init_box(binary: str, box_id: int) -> None:
    """`isolate --init` for one box id, raising `MatrixError` on failure."""
    init = subprocess.run([binary, "--cg", f"--box-id={box_id}", "--init"],
                          capture_output=True, text=True)
    if init.returncode != 0:
        raise MatrixError(
            f"isolate is installed at {binary} but `--init` failed for box "
            f"{box_id} (exit {init.returncode}): "
            f"{(init.stderr or init.stdout).strip()}\n"
            "A missing binary would have failed with a different message "
            "(see open_isolate_box); this looks instead like an "
            "installed-but-unconfigured sandbox — isolate needs cgroup v2 "
            "delegation, the isolate-cg-keeper service (isolate.service) "
            "enabled and running, and the 'isolate' system user's range "
            f"registered in /etc/subuid and /etc/subgid. See {_ISOLATE_HOME}."
        )


def _cleanup_box(binary: str, box_id: int) -> None:
    """`isolate --cleanup` for one box id; best-effort, never raises.

    Called from a `finally` around every single `--run` (Task 9c: a box is
    now this short-lived, not held for the whole invocation), so a cleanup
    failure here must not mask whatever real error or result is already
    propagating out of that call.
    """
    subprocess.run([binary, "--cg", f"--box-id={box_id}", "--cleanup"],
                    capture_output=True, text=True)


def open_isolate_box(problem_dir: str | Path | None = None) -> IsolateHandle:
    """Verify isolate is installed and usable, then prepare this
    invocation's isolate environment.

    `problem_dir` only decides where the staging directory is created —
    next to the problem package, on the same (disk-backed) filesystem as
    the work being staged. See `_stage_base()` for why it must not be
    `/tmp` and why an unusable location raises rather than warns.

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

    This still does one `--init`/`--cleanup` probe cycle up front — so a
    missing/unconfigured sandbox is diagnosed here, before any compilation
    touches the tree — but does not hold that box open: Task 9c found
    isolate's cgroup counters persist across `--run`s in the same box, so
    every actual sandboxed execution (`_run_once`) now opens and tears down
    its own box instead (see `IsolateHandle.box_id_counter`).
    """
    # Resolved (and validated) before isolate is even probed: a staging
    # location that cannot be used is a refuse-to-run, and refusing early
    # keeps it a true no-op on the tree, exactly as the isolate probe below
    # is (see `run()`).
    stage_base = _stage_base(problem_dir)

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

    probe_box_id = _select_box_id()
    _init_box(binary, probe_box_id)
    # Immediately torn down: this was only a usability probe. Every real
    # sandboxed execution opens and closes its own box (see _run_once).
    _cleanup_box(binary, probe_box_id)

    meta_fd, meta_name = tempfile.mkstemp(prefix="run_matrix_isolate_meta_")
    os.close(meta_fd)

    # The only `:rw` mount any `--run` will ever use (see module docstring:
    # a real repo directory must never be the write target again). Private,
    # ours, and deleted whole in `close_isolate_box` — world-writable is
    # harmless on a directory with that lifetime, and it is unrelated to box
    # identity: every box this invocation opens and closes shares this same
    # plain host directory. `dir=stage_base` is the load-bearing argument:
    # without it `mkdtemp` lands in `/tmp`, which is tmpfs, which charges a
    # solution's stdout against its own memory limit.
    stage_dir = Path(tempfile.mkdtemp(prefix=".run_matrix_stage_", dir=stage_base))
    os.chmod(stage_dir, 0o777)

    return IsolateHandle(binary=binary, version=version,
                         meta_path=Path(meta_name), stage_dir=stage_dir,
                         box_id_counter=itertools.count(probe_box_id))


def close_isolate_box(handle: IsolateHandle) -> None:
    """Best-effort teardown of this invocation's isolate environment; never
    raises.

    No box needs cleaning up here any more (Task 9c): every box `_run_once`
    opens is torn down in its own `finally` before this function is ever
    reached, so there is nothing left to leak at the box level regardless
    of how `run()` exited. This only tears down what *is* shared across
    the whole invocation — the meta-file path and the staging directory —
    and, like the old box cleanup, must not raise and mask whatever real
    error or result is already propagating.
    """
    try:
        handle.meta_path.unlink(missing_ok=True)
    except OSError:
        pass
    # stage_dir may contain files the sandboxed subuid created — deletable
    # regardless of who owns them, because we own the directory itself
    # (verified: see module docstring / task report). ignore_errors so a
    # teardown problem here still cannot mask a real error propagating.
    shutil.rmtree(handle.stage_dir, ignore_errors=True)


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

    `status` (the raw meta field, `""` when absent — i.e. OK) and `message`
    (isolate's own prose, e.g. "Time limit exceeded (wall clock)") are kept
    verbatim rather than boiled down further, specifically so a *diagnostic*
    built from a `RunResult` (a crash report, a kill report) can quote
    isolate's own account of what happened instead of reconstructing it —
    review found two ways reconstructing it from `killed`/`crashed`/
    `exit_code` alone went wrong: a signal death has no `exitcode` line, so
    defaulting to 0 read as "exited 0" (looks like success); and `killed`
    alone can't tell a CPU-time kill from a wall-time kill, which matters
    for pass 1's diagnostic naming the *right* limit it tripped.
    """

    cpu_ms: int
    wall_ms: int
    killed: bool
    oom: bool
    crashed: bool
    exit_code: int
    peak_kb: int
    status: str
    message: str


def _parse_meta(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        meta[key] = value
    return meta


# isolate's default without `--processes` is already a single process — but
# an *inherited* default is not the same as a *chosen* one. A judge that
# limits CPU time and memory almost always limits process/thread count too
# (most stock judges reject a std::thread solution outright), so pinning
# this to 1 explicitly makes "this driver does not sandbox multi-process
# solutions" a documented decision with a name attached, rather than
# something a reader has to know isolate's own default to discover. A
# solution that spawns a second thread now dies (pthread_create fails,
# typically an uncaught exception or abort) and is recorded as RE — a
# real behaviour change from the old posix_spawn driver, which imposed no
# such limit; flagged in the task report rather than left undisclosed.
ISOLATE_PROCESSES = 1


def _run_once(isolate: IsolateHandle, binary: Path, stdin_path: Path,
              stdout_dest: Path, cpu_limit_s: float, wall_limit_s: float,
              mem_limit_kb: int) -> RunResult:
    """Run one process inside `isolate`'s sandbox and return its verdict.

    `binary`'s and `stdin_path`'s directories are mounted **read-only**
    (deduplicated by resolved path when they coincide, e.g. pass 2's
    binary and the checker's binary both under `.build/`) — the sandboxed
    process never needs to write anywhere inside them. The *only* `:rw`
    mount is `isolate.stage_dir`, a private staging directory that lives
    on a disk-backed filesystem for the whole `run()` invocation (see
    `IsolateHandle`); every `--run` writes its stdout there under a fixed
    name, and this function copies the result back to `stdout_dest` itself,
    as this (unprivileged) process, immediately afterward.

    Two limits apply to that write and they are deliberately separate.
    `--cg-mem` caps the solution's *memory*; `--fsize=OUTPUT_LIMIT_KB` caps
    its *output*. They are only separate because `_stage_base()` refuses a
    memory-backed staging location — on tmpfs the output would be charged
    to the same cgroup as the memory, which is the false-ML this driver
    spent three tasks relocating (see module docstring). A solution that
    exceeds `--fsize` dies of SIGXFSZ and arrives here as `status:SG` with
    no `cg-oom-killed`, i.e. classified `crashed`/RE — not ML.

    This is the fix for a real bug an earlier version of this module had:
    bind-mounting a real `tests/<group>/` or `.build/` directory as the
    `:rw` target meant the sandboxed subuid — not us — created the file
    that ended up in the user's working tree, which is permanent,
    `git status`-invisible damage (both paths are gitignored) that
    `chmod -R`/`rsync -p`/`tar --same-owner` all trip over afterward. See
    the module docstring and the task report for the measured before/after.

    The copy-back always unlinks `stdout_dest` first
    (`stdout_dest.unlink(missing_ok=True)` then `write_bytes`), which needs
    only *directory* write permission — something this process already has,
    as the owner — never the target file's own permission bits. That also
    means this call self-heals a `stdout_dest` left over from the old,
    buggy behaviour (foreign-owned, possibly not writable by us at all): it
    is simply replaced, not fought with.

    The staged file itself is unlinked before the sandboxed run (in case a
    previous call left stale content there) and after the copy-back (so
    `isolate.stage_dir` doesn't accumulate one file per call across a whole
    `run()`); both unlinks rely only on `stage_dir`'s own permissions,
    which this process set to 0o777 when it created it.

    Task 9c: every call gets its **own, freshly-`--init`ed box** — one is
    claimed from `isolate.box_id_counter`, `--init`ed before the sandboxed
    execution, and `--cleanup`ed in a `finally` regardless of how this
    function returns or raises. isolate's cgroup counters (`cg-mem`,
    `cg-oom-killed`) persist across `--run`s in the same box — verified
    with bare isolate, no involvement from this module (see module
    docstring for the precise before/after values). Of the two, only
    `cg-oom-killed` reached this driver's output: reusing a box let one
    solution's OOM stick as `oom=True` for every later, memory-innocent
    run in the same box, which is a corrupted *verdict* (ML silently
    overwrote a correct one, since ML outranks WA), not a corrupted
    number — `peak_kb` is read from `max-rss` below, never from `cg-mem`,
    and `max-rss` was independently verified to reset correctly per
    process regardless of box reuse. Still the same class of defect this
    sandbox migration was meant to eliminate (memory-adjacent accounting
    contaminated by something other than the process being measured); a
    box that lives only from just before this one `--run` to just after it
    can never observe another call's counters, on any field.
    """
    box_id = next(isolate.box_id_counter) % 65536
    _init_box(isolate.binary, box_id)
    try:
        mounts: dict[Path, str] = {}

        def _label(path: Path) -> str:
            resolved = path.resolve()
            if resolved not in mounts:
                mounts[resolved] = f"/host{len(mounts)}"
            return mounts[resolved]

        bin_label = _label(binary.parent)
        stdin_label = _label(stdin_path.parent)
        stage_label = _label(isolate.stage_dir)
        stage_dir_resolved = isolate.stage_dir.resolve()

        staged_out = isolate.stage_dir / "run.out"
        staged_out.unlink(missing_ok=True)

        cmd = [
            isolate.binary, "--cg", f"--box-id={box_id}", "--run",
            f"--meta={isolate.meta_path}", f"--processes={ISOLATE_PROCESSES}",
            f"--time={cpu_limit_s:.3f}", f"--wall-time={wall_limit_s:.3f}",
            f"--cg-mem={mem_limit_kb}", f"--fsize={OUTPUT_LIMIT_KB}",
        ]
        for resolved, label in mounts.items():
            opt = ":rw" if resolved == stage_dir_resolved else ""
            cmd.append(f"--dir={label}={resolved}{opt}")
        cmd += [
            f"--chdir={bin_label}",
            f"--stdin={stdin_label}/{stdin_path.name}",
            f"--stdout={stage_label}/{staged_out.name}",
            "--", f"{bin_label}/{binary.name}",
        ]

        subprocess.run(cmd, capture_output=True, text=True)
        # isolate's own process exit code is not the contract here — 0 means
        # OK but 1 covers TO/SG/RE alike, so it cannot distinguish them. The
        # meta file is the actual contract (verified against this exact
        # isolate build; see the module docstring and the task report for
        # pasted output from all four cases).
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

        status = meta.get("status", "")  # absent -> OK; see module docstring trap 1
        if status == "XX":
            raise MatrixError(
                f"isolate reported an internal error (status XX) running "
                f"{binary} on {stdin_path}: {meta.get('message', '(no message)')} "
                "— this is isolate's own failure, not a verdict on the solution."
            )

        oom = meta.get("cg-oom-killed") == "1"  # must be tested before treating
        killed = status == "TO"                 # SG as a plain crash (trap 2)
        crashed = (not oom) and status in ("RE", "SG")
        message = meta.get("message", "")

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

        # Copy the sandboxed output back into the repository as *this*
        # process — never write it through a bind mount again (see
        # docstring above).
        try:
            data = staged_out.read_bytes()
        except FileNotFoundError:
            data = b""
        stdout_dest.unlink(missing_ok=True)
        stdout_dest.write_bytes(data)
        staged_out.unlink(missing_ok=True)

        return RunResult(cpu_ms=cpu_ms, wall_ms=wall_ms, killed=killed, oom=oom,
                          crashed=crashed, exit_code=exit_code, peak_kb=peak_kb,
                          status=status, message=message)
    finally:
        _cleanup_box(isolate.binary, box_id)


def _time_median(isolate: IsolateHandle, binary: Path, stdin_path: Path,
                  stdout_dest: Path, cpu_limit_s: float, wall_limit_s: float,
                  mem_limit_kb: int, runs: int) -> RunResult:
    """Median the CPU/wall time over `runs` runs; any bad outcome wins.

    `killed`/`oom`/`crashed` are all sticky-OR (never cleared once True) and
    `exit_code`/`status`/`message` are sticky-first-nonempty — mirroring the
    old driver's reasoning for the model solution specifically: a run that
    fails once and happens to succeed on a later retry must not have that
    failure silently overwritten, or a flaky answer file could pass as jury
    truth, and the diagnostic for that failure must survive to be reported
    even though it happened on an earlier iteration than the last one.
    """
    cpu_samples, wall_samples = [], []
    killed = oom = crashed = False
    exit_code = 0
    status = message = ""
    peak = 0
    for _ in range(runs):
        r = _run_once(isolate, binary, stdin_path, stdout_dest,
                      cpu_limit_s, wall_limit_s, mem_limit_kb)
        cpu_samples.append(r.cpu_ms)
        wall_samples.append(r.wall_ms)
        killed = killed or r.killed
        oom = oom or r.oom
        crashed = crashed or r.crashed
        exit_code = exit_code or r.exit_code
        status = status or r.status
        message = message or r.message
        peak = max(peak, r.peak_kb)
    return RunResult(
        cpu_ms=int(statistics.median(cpu_samples)),
        wall_ms=int(statistics.median(wall_samples)),
        killed=killed, oom=oom, crashed=crashed,
        exit_code=exit_code, peak_kb=peak,
        status=status, message=message,
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


def _git_rev(path: str | Path) -> str | None:
    """The git revision checked out at `path`, or None if it isn't a checkout.

    Used to pin the testlib revision into `invocation.json`: the checker is
    compiled against `$TESTLIB/testlib.h` and `bootstrap_testlib.sh` pulls
    on every invocation, so an artifact that records only "isolate 2.6" is
    not enough to reproduce the run that produced it.
    """
    try:
        done = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


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
    silent, spurious sandbox permission failure. Never grants write — every
    directory this driver hands to the sandbox is now read-only (see
    `_ensure_dir_traversable` and the module docstring); the only `:rw`
    mount is the private staging directory in `IsolateHandle`.
    """
    os.chmod(path, path.stat().st_mode | 0o004)


def _ensure_sandbox_executable(path: Path) -> None:
    """Grant "other" read+execute on a compiled binary the sandbox must run.

    Defensive, for the same reason as `_ensure_sandbox_readable`: a
    stricter umask than this machine's could otherwise produce a binary
    without the "other" bits g++'s default output happens to carry, and
    that must be a granted permission, not a silent, spurious exec failure.
    """
    os.chmod(path, path.stat().st_mode | 0o005)


def _ensure_dir_traversable(path: Path) -> None:
    """Grant "other" traverse (search) access to a directory the sandbox
    reads through — and, just as importantly, strip any stray "other"
    write bit already sitting on it.

    Every directory this driver bind-mounts is read-only now (see the
    module docstring): the sandboxed subuid only ever needs to look up a
    file by exact name inside it (`os.execve`/`open` by path), which is
    what the directory's own *execute* bit controls on Linux — not its
    read bit (that only gates directory *listing*, e.g. `ls`), and
    certainly not its write bit, which this driver never has a reason to
    grant to a real repository directory again.

    The `& ~stat.S_IWOTH` half of this is a deliberate self-heal, not just
    a guard: an earlier version of this module *did* grant that bit (to
    bind-mount `tests/<group>/` and `.build/` read-write, so the sandboxed
    process could write its own stdout there) and never restored it,
    leaving real problem directories at `o+w` permanently. Every `run()`
    from here on strips that bit back off its own accord, so a problem
    directory that was damaged by the old behaviour heals the next time
    this tool touches it — no separate migration step required.
    """
    mode = path.stat().st_mode
    healed = (mode | stat.S_IXOTH) & ~stat.S_IWOTH
    if healed != mode:
        path.chmod(healed)


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
    # Task 9b review, aggravating detail: an earlier version of this
    # function only discovered whether isolate was even usable *after*
    # already compiling every solution and touching the tree — so a
    # refuse-to-run (isolate missing or unconfigured) still left `.build/`
    # and its binaries behind, on a path that was never going to reach the
    # sandbox at all. Opening the box first means a refusal here is a true
    # no-op on the tree: nothing is compiled, nothing is chmod'd, nothing
    # is created. (`--init`/`--cleanup` themselves only touch
    # `/var/local/lib/isolate/`, never this problem's directory.)
    isolate = open_isolate_box(problem_dir)
    try:
        manifest = scan(problem_dir, problem)

        build = problem_dir / ".build"
        build.mkdir(exist_ok=True)
        # Read-only from the sandbox's perspective — it only ever needs to
        # look up and exec a binary here by name, never write.
        # `_ensure_dir_traversable` also self-heals a `.build/` left `o+w`
        # by an earlier version of this module that bind-mounted it
        # read-write (see module docstring); this driver never grants that
        # bit to a real repo directory again.
        _ensure_dir_traversable(build)

        if problem.checker_kind == "stock":
            checker_src = testlib_dir / "checkers" / f"{problem.checker_name}.cpp"
        else:
            checker_src = problem_dir / "files" / problem.checker_name
        checker = build / "checker"
        _compile(checker_src, checker, ["-Wpedantic", "-Werror", f"-I{testlib_dir}"],
                 context=f"checker ({problem.checker_name})")
        # The checker itself is never sandboxed (`_check` runs it directly,
        # as this process) — no permission grant needed. The reason is that
        # a checker is *jury-authored* code, not a submission: it is part of
        # the package the setter is building, it must read the test input
        # and the jury's own answer file, and nothing about it is under a
        # contestant's control. The sandbox exists to contain untrusted,
        # possibly-adversarial submissions and to *measure* them; a checker
        # is neither untrusted nor measured. It is still bounded in time by
        # CHECKER_TIMEOUT_S, which is the one failure mode a jury-authored
        # checker realistically has (an infinite loop in a hand-written one).

        binaries = {}
        for entry in manifest["solutions"]:
            binary = build / Path(entry["file"]).stem
            _compile(problem_dir / "solutions" / entry["file"], binary,
                      context=f"solution {entry['file']}")
            _ensure_sandbox_executable(binary)
            binaries[entry["file"]] = binary

        main_file = next(e["file"] for e in manifest["solutions"] if e["tag"] == "main")
        tests = _tests_by_group(problem_dir, problem)
        for paths in tests.values():
            # Read-only for the same reason as `.build/` above: pass 1's
            # regenerated `.a` answer file is no longer written through
            # this bind mount (see `_run_once` and the module docstring) —
            # it is copied back by this process afterward, so the
            # directory itself never needs an `o+w` bit, and this call
            # self-heals one left by the earlier, buggy version of this
            # module.
            _ensure_dir_traversable(paths[0].parent)
            for test in paths:
                _ensure_sandbox_readable(test)

        mem_limit_kb = problem.memory_mb * 1024

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
                    # isolate's own `status:TO` fires for either a CPU-time
                    # kill or a wall-time kill, and this pass has two
                    # different safety ceilings for them — the message
                    # text is what tells them apart ("Time limit exceeded"
                    # vs "Time limit exceeded (wall clock)", verified
                    # against a real sleep()-bound run; see the task
                    # report), so it, not a hardcoded guess, picks which
                    # limit to name here.
                    if "wall clock" in r.message.lower():
                        kind, limit_ms = "wall-clock", int(MODEL_SAFETY_WALL_S * 1000)
                    else:
                        kind, limit_ms = "CPU", int(MODEL_SAFETY_CPU_S * 1000)
                    raise MatrixError(
                        f"model solution did not finish within {limit_ms} ms "
                        f"{kind} time on {test} (hard safety kill during "
                        "pass 1, before real limits exist; isolate reported: "
                        f"{r.message or '(no message)'})")
                if r.oom:
                    raise MatrixError(
                        f"model solution exceeded the memory limit "
                        f"({problem.memory_mb} MB) on {test}")
                if r.crashed or r.exit_code != 0:
                    # A signal death (status SG, a real segfault/abort, not
                    # an OOM — that's handled above) carries no `exitcode`
                    # line at all, so defaulting it to 0 and reporting
                    # "exited 0" would read as a bug in this check rather
                    # than a crashing model solution. Quote isolate's own
                    # status/message instead of reconstructing one.
                    detail = f"status {r.status or 'RE'}"
                    if r.message:
                        detail += f", {r.message}"
                    elif r.status != "SG":
                        detail += f", exitcode {r.exit_code}"
                    raise MatrixError(
                        f"model solution crashed on {test} ({detail}) — a "
                        "solution that exits abnormally cannot define the "
                        "jury's expected timing or answers")
                t_main[f"{group}/{test.stem}"] = r.cpu_ms

        limits = compute_limits(t_main)

        # Pass 2 — everything else, one run, band results re-timed.
        # `--time` is set to `kill_ms` (not `tl_ms`): that is the value the
        # old driver's own wait loop enforced as its hard kill deadline,
        # and preserving it here is what keeps the (TL, kill] band
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
            # A declaration, not a measurement. This driver passes `--cg` to
            # every isolate invocation unconditionally (`_init_box`,
            # `_run_once`, `_cleanup_box`), so what this field records is
            # what was *requested*; nothing here probes the kernel to
            # confirm cgroup accounting was actually honoured. The previous
            # name (`cg`) read as an observation of the machine and was
            # hardcoded `True` — renamed rather than deleted, because a
            # reader of an old invocation.json still needs to know which
            # mode the runner asked for.
            "cg_requested": True,
            # Pins the testlib revision the checker in this run was
            # compiled against. `bootstrap_testlib.sh` runs `git pull` on
            # every invocation, so without this the artifact certifying
            # "no solution survives" could not be reproduced against the
            # header that produced it.
            "testlib": _git_rev(testlib_dir),
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
    """Exit codes are a contract `validating-solutions` reads directly:

        0 — every solution's @expect was met.
        1 — the matrix ran and found holes and/or mismatches. This is a
            *result*, printed to stdout: the signal to keep reading.
        2 — the matrix could not be run at all (usage error, or any
            `MatrixError`: a compile failure, a missing tests directory,
            the file-IO guard, an unusable sandbox or staging location).
            A message on stderr, nothing on stdout.

    Before this, an uncaught `MatrixError` surfaced as a traceback and
    exited 1 as well, so an agent told "exit 1 means holes or mismatches"
    would read a crash as a finding — a compile failure reported as
    "the suite has a hole".
    """
    if len(argv) != 3:
        print("usage: run_matrix.py <problem-dir> <testlib-dir>", file=sys.stderr)
        return 2
    try:
        payload = run(argv[1], argv[2])
    except MatrixError as exc:
        print(f"run_matrix: {exc}", file=sys.stderr)
        return 2
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

# Parallel Invocation Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `run_matrix` safe to run concurrently with itself and internally parallel, turning the pipeline's longest serial stage (24s–253s per package, ~1160s across the eight real packages) into a ~2.3x faster stage that still cannot produce a wrong timing verdict.

**Architecture:** Three separate defects are fixed in order, and only the third is about speed. (1) Box ids are leased from a per-user, cross-process `flock` pool instead of derived from `pid`, which is what makes two concurrent invocations collide today. (2) `_run_once` stops sharing one meta file and one staging directory across the whole invocation and owns per-run copies, which is what makes it reentrant. (3) Pass 2 runs on a bounded thread pool sized to the same lease pool, so the lease pool doubles as this user's CPU admission control; pass 1 stays serial because it defines TL and costs only 1–6% of the wall clock. Timing stays trustworthy because CPU-time contention is **one-sided** — it can only inflate a measurement — so only results measured in the narrow band `(TL, 1.5·TL]` are ambiguous and get re-timed serially. Measured on the eight real packages: 18 results out of 5508 land in that band.

**Tech Stack:** Python 3.10+ stdlib only (no venv, no third-party imports — hard project constraint). `ioi/isolate` 2.6 as the sandbox. `concurrent.futures.ThreadPoolExecutor` (threads, not processes: every unit of work is a `subprocess.run`, which releases the GIL, and the workers must share one `IsolateHandle`).

## Global Constraints

- **stdlib only.** No third-party imports in `tools/`. No `requirements.txt`, no venv.
- **Never modify anything under `~/Projects/my_cp_problems/`.** Compile and stage to temp paths only. Clean up isolate boxes you create.
- **R1 (standing):** externally-authored data must never surface a bare stdlib exception. Raise the module's own error type (`MatrixError`, `BoxPoolError`).
- **Evidence standard (standing):** a claim in a docstring or a skill is a testable assertion. If you write "X is guaranteed", there must be a test that fails when X stops being true. This project shipped four docstrings asserting things the code did not do — including the two this plan deletes.
- **Verification standard (standing):** an error path you have not triggered is not handled. Do not report a claim as verified because you read the code.
- **`_SEVERITY` ordering is load-bearing** and does not change in this plan.
- **The `holes` definition does not change.** It is the pipeline's one non-circular claim.
- **No verdict may become less trustworthy than it is today.** Parallelism is only permitted where a measurement is provably unaffected or is re-measured serially. A speedup that costs a verdict is a rejected change.
- **`python3 -m unittest discover -s tools/tests -t .` must pass** at the end of every task. After Task 2 it must also pass when two copies are run concurrently — that is the acceptance test for the whole plan.

---

## Root Cause (verified, not inferred)

Everything below was reproduced on this machine against isolate 2.6 (`/usr/local/bin/isolate`, git `cf03a90`), `nproc` = 8, `/etc/subuid` grants `isolate:200000:65536` so box ids 0–65535 all `--init` cleanly.

### Cause A — box ids are derived from `pid`, and Task 9c turned one id into hundreds

`_select_box_id()` (`run_matrix.py:449-473`) returns `os.getpid() % 65536`, and `IsolateHandle.box_id_counter` (`:341`) is `itertools.count(that)`. Task 9c made every `_run_once` claim the *next* id, so an invocation with pid `P` occupies the whole range `[P, P+K)`, where `K` is its total number of sandboxed runs. `K` is large in practice:

| package | solutions | tests | boxes consumed (`K`) |
|---|---|---|---|
| xorcount | 8 | 24 | 264 |
| flight | 9 | 25 | 300 |
| goldenseed | 13 | 45 | 720 |
| stray | 10 | 74 | 962 |
| ledger | 10 | 89 | 1157 |
| corridor | 9 | 92 | 1104 |
| procession | 12 | 71 | 1065 |
| lantern | 13 | 112 | 1792 |

Concurrently launched processes get near-adjacent pids — measured, 8 concurrent spawns produced pids `[1413, 1415, 1417, 1420, 1422, 1425, 1426, 1427]`, a spread of **14**. Two concurrent invocations therefore overlap on essentially their entire box range.

The docstring's safety argument is stale in two separate ways, and both must be deleted rather than softened:

1. *"only collides with another concurrently-running run_matrix invocation whose pid happens to differ by an exact multiple of 65536 — vanishingly unlikely"* — true of the pre-9c design, which used **one** box per invocation. With an incrementing counter the collision condition is `|P_A − P_B| < K`, which is near-certain.
2. *"`--init` on a box id that is already open is idempotent (it returns 0, reusing/reinitializing the same box) rather than failing"* — **false when the box is live.** Measured:

```
$ isolate --cg --box-id=100 --init      # while another process's --run holds box 100
This box is currently in use by another process
rc=2
```

Two failure windows, both reproduced:

- **W1 — lock contention.** The neighbour's `--init` or `--run` hits a box whose isolate lock (`lock_root = /run/isolate/locks`) is held. `rc=2`. `_init_box` (`:476-492`) turns *any* nonzero rc into a `MatrixError` that blames **cgroup v2 delegation, the isolate-cg-keeper service, and `/etc/subuid`** — a confident, wrong diagnosis pointing at the install. This is the message that "cost three agents a false diagnosis" (`docs/superpowers/specs/2026-07-31-stage-3-scope.md:116`).
- **W2 — cleanup steal.** The neighbour's `--cleanup` lands between our `--init` and our `--run`:

```
$ isolate --cg --box-id=200 --init      # A
$ isolate --cg --box-id=200 --init      # B, rc=0 — the box is idle, so this one IS idempotent
$ isolate --cg --box-id=200 --cleanup   # B, rc=0 — B has just destroyed A's box
$ isolate --cg --box-id=200 --run --meta=metaC -- /bin/true   # A
Box not found, did you run `isolate --cg --init'?
rc=2
```

**W2 cannot be fixed by retrying** — another process destroyed our box — which is why the fix is a lease, not a retry loop.

Neither window can produce a wrong verdict, and this was verified rather than assumed: isolate **overwrites** the `--meta` file on both failures, so the previous run's numbers cannot be read as this run's.

```
$ printf 'time:0.111\nexitcode:0\n' > metaStale
$ isolate --cg --box-id=333 --run --meta=metaStale -- /bin/true
$ cat metaStale
status:XX
message:Box not found, did you run `isolate --cg --init'?
```

`_run_once` already raises on `status:XX` (`:1052-1057`). So Cause A is a **loud, misdiagnosed failure**, exactly as `2026-07-31-stage-3-scope.md` recorded. It stays that way; this plan removes it.

### Cause B — one `IsolateHandle` shares mutable state across every run

Even with box ids fixed, a single invocation cannot run two sandboxed executions at once. Two hard blockers, both on state that is per-invocation and must be per-run:

- **`meta_path` (`:341`, created at `:561-562`).** One `mkstemp` file for the whole invocation. Every `--run` writes it (`:1016`) and `_run_once` reads it straight back (`:1038`). Two concurrent runs and one reads the other's meta — a **silent wrong verdict**, the one outcome this driver's whole design refuses.
- **`stage_dir` (`:572`).** One directory, and `_clear_stage_dir` (`:702-748`) wipes it at the top of *every* `_run_once` (`:995`). Two concurrent runs and one deletes the other's staged input and output mid-flight.

Cause B is why the stage is slow: 264–1792 sandboxed runs, strictly one at a time.

| package | pass 1 (serial floor) | pass 2 (serial floor) | total |
|---|---|---|---|
| xorcount | 0.5s | 23.9s | 24.4s |
| flight | 0.1s | 31.3s | 31.4s |
| stray | 2.4s | 73.3s | 75.7s |
| procession | 2.2s | 140.3s | 142.5s |
| goldenseed | 8.6s | 186.2s | 194.9s |
| ledger | 7.8s | 190.2s | 198.0s |
| corridor | 13.8s | 225.5s | 239.3s |
| lantern | 10.7s | 242.6s | 253.3s |
| **total** | **46.1s** | **1113.3s** | **1159.6s** |

isolate's own per-box overhead is not the cost: one full `--init`/`--run`/`--cleanup` cycle measures **6.0 ms**, a `--run` alone **2.2 ms**. The cost is the solutions themselves.

**Pass 1 is 1–6% of the wall clock.** That is the single most important number in this plan: keeping pass 1 serial preserves the derivation of TL bit-for-bit and costs almost nothing.

### The constraint that makes "just add a thread pool" wrong

The pipeline's product is *timing verdicts*. `compute_limits` sets `tl_ms = max(2·max(t_main), 1000)` rounded to 500 ms and `kill_ms = 2·tl_ms` (`matrix_core.py:24-39`); `classify` compares `cpu_ms` against `tl_ms` (`:48-65`). CPU time inflates under contention. Measured on this box, isolate-sandboxed, median of the concurrent cohort against a serial baseline:

| workers | CPU-bound inflation | memory-bound inflation |
|---|---|---|
| 1 (baseline) | 1.00x | 1.00x |
| 2 | 1.08x | 1.04x |
| 3 | 1.10x | 1.04x |
| 4 | 1.15x | 1.21x |
| 6 | 1.18x | 1.48x |
| 8 | 1.27x | 1.65x (1.92x in a second run) |

Naive 8-way parallelism inflates memory-bound CPU time up to ~1.9x. Applied to pass 1 it would nearly double TL and let genuinely-TLE solutions pass — manufacturing holes. Applied to pass 2 it would manufacture false TLs.

### Why this is nonetheless safe — contention is one-sided

isolate measures the sandboxed process's *own* CPU time. Interference from other boxes (LLC pressure, memory bandwidth, SMT sharing) can only **add** to that number; nothing about a neighbouring box can make a process consume less CPU than it would alone. So for a measurement `T` taken under a contention bound `F`, the true serial time lies in `[T/F, T]`, and:

- `T ≤ tl_ms` ⟹ true `≤ T ≤ tl_ms` ⟹ genuinely not TL. **Safe, no re-measurement.**
- `T > F·tl_ms` ⟹ true `≥ T/F > tl_ms` ⟹ genuinely TL. **Safe, no re-measurement.**
- `tl_ms < T ≤ F·tl_ms` ⟹ **ambiguous, re-time serially.**
- `killed` (kernel kill at `--time=kill_ms = 2·tl_ms`) ⟹ true `≥ 2·tl_ms/F > tl_ms` for any `F < 2` ⟹ genuinely TL. **Safe, no re-measurement.** This is why `F < 2` is a hard assertion and not a tuning knob: at `F ≥ 2` every killed run becomes ambiguous and the whole scheme collapses.

Memory verdicts are unaffected in the first place: each box has its own cgroup and its own `--cg-mem`, so `cg-oom-killed` and `max-rss` do not see other boxes at all.

The band is narrow, so the serial tail is cheap. Simulated against the recorded results of all eight packages (5508 results total), 4 workers, serial pass 1, serial 3x re-time of the ambiguous band:

| bound `F` | ambiguous results | projected total | speedup |
|---|---|---|---|
| 1.25 | 13 / 5508 | 431s | 2.69x |
| **1.50** | **18 / 5508** | **512s** | **2.26x** |
| 1.75 | 27 / 5508 | 612s | 1.90x |

`F = 1.5` is the chosen default: it covers the measured 4-worker inflation (1.15–1.21x) with real headroom, sits well below the `F < 2` wall, and costs 18 re-timings across every package this project has.

**The rejected alternative, recorded so it is not re-proposed:** "run everything in parallel, then serially re-time everything the parallel pass called TL." TL results are 2–13% of results but **43–88% of the wall clock** (corridor: 83 TL results = 166s of 225s), because each burns the full `kill_ms`. That rule yields ~1.3x, not 2.3x. The one-sided argument above is what makes the difference, by proving killed runs need no re-measurement.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/box_pool.py` | per-user, cross-process isolate box-id leases | **new** |
| `tools/tests/test_box_pool.py` | lease semantics, including cross-process | **new** |
| `tools/matrix_core.py` | pure timing/verdict model | add `needs_serial_retime()`; no signature changes to `classify`/`compute_limits` |
| `tools/run_matrix.py` | the sandboxed driver | lease box ids; per-run meta + staging; parallel pass 2; provenance |
| `tools/tests/test_matrix_core.py` | | cover `needs_serial_retime` |
| `tools/tests/test_run_matrix.py` | | reentrancy, concurrency, parallel-pass tests |
| `README.md` | | replace the "run it alone" warning |
| `skills/validating-solutions/SKILL.md` | | document the worker knobs and the re-timing band |
| `docs/superpowers/specs/2026-07-31-stage-3-scope.md` | | close the carried-forward parallel-safety item |

**Why `compute_limits()` and `classify()` are untouched.** Pass 1 stays serial, so `compute_limits` sees exactly the inputs it sees today. `classify` already returns `banded` for `(TL, kill]`; the new band is a *different, wider* question ("was this measurement taken under contention near the limit") asked by a *new* function. Widening `classify`'s existing band would conflate the two and change serial-mode behaviour. Do not touch either signature.

---

### Task 1: The box-id lease pool

`_select_box_id()` must be replaced by a real allocator before anything else can be parallel. This task builds it standalone, with no `run_matrix` changes, so it can be tested on its own.

The pool is deliberately **cross-process, not per-invocation** (and, per the ruling above, per-user): it is simultaneously the box-id allocator (fixing Cause A) and the CPU admission-control token pool (bounding `F` when several invocations run at once). Sizing it to `nproc // 2` means three concurrent invocations share four leases rather than running twelve boxes and blowing past the contention bound.

**Files:**
- Create: `tools/box_pool.py`
- Test: `tools/tests/test_box_pool.py`

> **SUPERSEDED IN PART — read this before the code blocks below.** Task 1
> shipped (`55c0358`, fixes `3a16a27`) under a human ruling that overrides
> this section: **the pool is per-user, not machine-wide-multi-user.** The
> lock directory defaults to `/run/user/<uid>/run_matrix-boxes`, falling
> back to `/tmp/run_matrix-boxes-<uid>`; there is no `0o1777` chmod and no
> world-writable anything; lock files are `0o600`; and `pool_size()`
> rejects a value above 65536. The docstrings say per-user and state the
> consequence: two *different users* running `run_matrix` on one machine
> can still collide on isolate box ids, and isolate's own lock catches that
> loudly. The "`/tmp` is the right default, do not fix this" note in the
> code block below applied to the multi-user design and no longer governs —
> the tmpfs *reasoning* in it is still correct and still shipped. Read
> `tools/box_pool.py` for what actually exists; later tasks depend on that,
> not on this section.

**Interfaces:**
- Produces:
  - `class BoxPoolError(RuntimeError)`
  - `pool_size() -> int` — lease count, from `$RUN_MATRIX_BOX_POOL` else `max(1, (os.cpu_count() or 2) // 2)`, rejecting anything above 65536
  - `lock_dir() -> Path` — from `$RUN_MATRIX_BOX_LOCK_DIR` else the per-user default
  - `lease(*, timeout_s: float = 3600.0) -> ContextManager[int]` — yields an isolate box id held exclusively for the `with` body
- Consumed by: Task 2 (`run_matrix._run_once`, `run_matrix.open_isolate_box`)

- [ ] **Step 1: Write the failing tests**

Create `tools/tests/test_box_pool.py`:

```python
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from tools import box_pool


class BoxPoolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="box_pool_test_"))
        self._env = {}
        self._set("RUN_MATRIX_BOX_LOCK_DIR", str(self.tmp))
        self._set("RUN_MATRIX_BOX_POOL", "2")

    def tearDown(self):
        for key, old in self._env.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def _set(self, key, value):
        self._env.setdefault(key, os.environ.get(key))
        os.environ[key] = value

    def test_pool_size_reads_the_environment_override(self):
        self._set("RUN_MATRIX_BOX_POOL", "5")
        self.assertEqual(box_pool.pool_size(), 5)

    def test_pool_size_defaults_to_half_the_cpus_and_is_at_least_one(self):
        os.environ.pop("RUN_MATRIX_BOX_POOL", None)
        self.assertGreaterEqual(box_pool.pool_size(), 1)

    def test_pool_size_rejects_a_nonsense_override(self):
        self._set("RUN_MATRIX_BOX_POOL", "0")
        with self.assertRaises(box_pool.BoxPoolError):
            box_pool.pool_size()

    def test_lease_yields_an_id_inside_the_pool(self):
        with box_pool.lease() as box_id:
            self.assertIn(box_id, range(2))

    def test_two_concurrent_leases_never_return_the_same_id(self):
        with box_pool.lease() as a, box_pool.lease() as b:
            self.assertNotEqual(a, b)

    def test_lease_is_released_on_exit_and_the_id_is_reusable(self):
        with box_pool.lease() as a:
            first = a
        with box_pool.lease() as b:
            self.assertEqual(first, b)

    def test_lease_is_released_when_the_body_raises(self):
        with self.assertRaises(ValueError):
            with box_pool.lease():
                raise ValueError("boom")
        with box_pool.lease() as a, box_pool.lease() as b:
            self.assertEqual({a, b}, {0, 1})

    def test_exhausted_pool_raises_rather_than_hanging_forever(self):
        with box_pool.lease(), box_pool.lease():
            with self.assertRaises(box_pool.BoxPoolError) as ctx:
                with box_pool.lease(timeout_s=0.5):
                    self.fail("a third lease was granted from a pool of two")
        self.assertIn("RUN_MATRIX_BOX_POOL", str(ctx.exception))

    def test_a_waiting_lease_is_granted_once_a_holder_releases(self):
        granted = []

        def waiter():
            with box_pool.lease(timeout_s=30.0) as box_id:
                granted.append(box_id)

        with box_pool.lease() as first:
            inner = box_pool.lease()
            inner.__enter__()                 # pool of two is now exhausted
            thread = threading.Thread(target=waiter)
            thread.start()
            thread.join(timeout=1.0)
            self.assertTrue(thread.is_alive(), "waiter should still be blocked")
            inner.__exit__(None, None, None)  # release the second lease
            thread.join(timeout=30.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(granted), 1)
        self.assertNotEqual(granted[0], first)

    def test_a_lease_held_by_another_process_is_not_handed_out_here(self):
        # A separate process, not a thread: flock is per open file description,
        # and the whole point of this pool is cross-invocation exclusion.
        script = (
            "import os,sys,time\n"
            "sys.path.insert(0, %r)\n"
            "from tools import box_pool\n"
            "with box_pool.lease() as b:\n"
            "    print(b, flush=True)\n"
            "    time.sleep(30)\n"
        ) % str(Path(__file__).resolve().parents[2])
        child = subprocess.Popen([sys.executable, "-c", script],
                                 stdout=subprocess.PIPE, text=True,
                                 env={**os.environ})
        try:
            theirs = int(child.stdout.readline().strip())
            with box_pool.lease() as ours:
                self.assertNotEqual(ours, theirs)
        finally:
            child.kill()
            child.wait(timeout=10)

    def test_a_lease_is_released_when_its_holder_process_dies(self):
        script = (
            "import sys,time\n"
            "sys.path.insert(0, %r)\n"
            "from tools import box_pool\n"
            "with box_pool.lease() as b:\n"
            "    print(b, flush=True)\n"
            "    time.sleep(30)\n"
        ) % str(Path(__file__).resolve().parents[2])
        child = subprocess.Popen([sys.executable, "-c", script],
                                 stdout=subprocess.PIPE, text=True)
        theirs = int(child.stdout.readline().strip())
        child.kill()
        child.wait(timeout=10)
        with box_pool.lease() as a, box_pool.lease() as b:
            self.assertIn(theirs, {a, b})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tools.tests.test_box_pool -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.box_pool'`

- [ ] **Step 3: Implement `tools/box_pool.py`**

```python
"""Machine-wide lease allocator for isolate box ids.

Why a lease and not a smarter derivation of the id: `run_matrix` used to
take `os.getpid() % 65536` and hand out consecutive ids from there, one per
sandboxed run. A real package makes 264-1792 of those runs, and two
concurrently launched processes get pids about two apart (measured: eight
concurrent spawns spanned 14), so two invocations overlapped on nearly
every id they used. The two failure windows that produced were reproduced
against isolate 2.6 and neither is fixable by a retry:

  * The neighbour's `--init`/`--run` hits a live box and isolate answers
    "This box is currently in use by another process" (rc=2), which
    `_init_box` misreported as an unconfigured cgroup/subuid install.
  * The neighbour's `--cleanup` lands between our `--init` and our `--run`
    and isolate answers "Box not found". *Another process destroyed our
    box* — retrying cannot help, only exclusive ownership can.

So a lease: `flock(LOCK_EX|LOCK_NB)` on one lock file per id, held for the
whole `--init`/`--run`/`--cleanup` cycle. `flock` is advisory and lives on
the open file description, so the kernel releases it when the holder closes
the fd *or dies*, including `kill -9` — there is no stale-lease cleanup to
write, and none should be added. This is the same mechanism `tools/flags.py`
already uses for its register, deliberately, so the project has one locking
idiom rather than two.

The pool is also this pipeline's CPU admission control, and that is not a
side effect — it is the second reason it is machine-wide rather than
per-process. `run_matrix` sizes its worker pool to `pool_size()`, so three
concurrent invocations share `pool_size()` leases instead of running three
times that many boxes. That bound is load-bearing for verdict correctness:
CPU time inflates under contention (measured on an 8-thread box: 1.15-1.21x
at 4 concurrent boxes, up to 1.92x at 8), and `run_matrix`'s ambiguity band
is only valid below a bounded inflation factor.

The lock directory holds zero-byte files and is *not* where anything
sandboxed writes, so the tmpfs-charges-the-cgroup rule that keeps
`run_matrix`'s staging directory off `/tmp` does not apply here and `/tmp`
is the right default: it is the one path that is machine-wide, writable by
every user who could run isolate, and cleared on boot. Do not "fix" this to
match `_stage_base()`.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

POOL_ENV = "RUN_MATRIX_BOX_POOL"
LOCK_DIR_ENV = "RUN_MATRIX_BOX_LOCK_DIR"
DEFAULT_LOCK_DIR = "/tmp/run_matrix-boxes"

# How long to sleep between full sweeps of the pool when every id is taken.
# Short enough that a released lease is picked up promptly, long enough that
# a blocked worker is not spinning on `flock` several thousand times a second.
_POLL_INTERVAL_S = 0.05


class BoxPoolError(RuntimeError):
    """A box id could not be leased."""


def pool_size() -> int:
    """How many isolate boxes may be open on this machine at once.

    Defaults to half the CPUs because this number is a contention bound, not
    a throughput target: `run_matrix`'s timing verdicts are only sound while
    CPU-time inflation stays under its ambiguity band, and inflation climbs
    sharply once every hardware thread is busy.
    """
    raw = os.environ.get(POOL_ENV)
    if raw is None:
        return max(1, (os.cpu_count() or 2) // 2)
    try:
        value = int(raw)
    except ValueError as exc:
        raise BoxPoolError(
            f"${POOL_ENV} must be a positive integer, got {raw!r}"
        ) from exc
    if value < 1:
        raise BoxPoolError(
            f"${POOL_ENV} must be at least 1, got {value}"
        )
    return value


def lock_dir() -> Path:
    """The directory holding one lock file per box id, created if absent.

    Mode 0o1777 (sticky, world-writable) for the same reason `/tmp` has it:
    the pool must be shared by every user who can run isolate, and the sticky
    bit stops one user unlinking another's lock file.
    """
    path = Path(os.environ.get(LOCK_DIR_ENV, DEFAULT_LOCK_DIR))
    try:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o1777)
    except OSError as exc:
        if not path.is_dir():
            raise BoxPoolError(
                f"cannot create the box-lease directory {path}: {exc}. Set "
                f"${LOCK_DIR_ENV} to a writable directory."
            ) from exc
    return path


def _try_claim(directory: Path, box_id: int) -> int | None:
    """Open and `flock` one id's lock file, returning the fd or None.

    Returns None only for "someone else holds it" (EWOULDBLOCK/EACCES); any
    other OSError is a real problem with the lock directory and propagates as
    `BoxPoolError` rather than silently shrinking the pool.
    """
    path = directory / f"box-{box_id}.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o666)
    except OSError as exc:
        raise BoxPoolError(
            f"cannot open the box-lease file {path}: {exc}"
        ) from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
            return None
        raise BoxPoolError(
            f"cannot lock the box-lease file {path}: {exc}"
        ) from exc
    return fd


@contextmanager
def lease(*, timeout_s: float = 3600.0) -> Iterator[int]:
    """Hold one isolate box id exclusively for the duration of the block.

    Sweeps the pool from a pid-derived offset so concurrent invocations do
    not all probe id 0 first, and blocks (polling, not spinning) until an id
    frees up or `timeout_s` elapses. The timeout exists so a wedged holder
    surfaces as a named error instead of an invocation that hangs forever;
    the default is deliberately long, because legitimately waiting behind
    another package's matrix is normal, not a fault.
    """
    directory = lock_dir()
    size = pool_size()
    start_at = os.getpid() % size
    deadline = time.monotonic() + timeout_s
    while True:
        for offset in range(size):
            box_id = (start_at + offset) % size
            fd = _try_claim(directory, box_id)
            if fd is not None:
                try:
                    yield box_id
                finally:
                    # Closing the fd releases the flock; doing it in one place
                    # means process death and normal exit take the same path.
                    os.close(fd)
                return
        if time.monotonic() >= deadline:
            raise BoxPoolError(
                f"no isolate box id became free within {timeout_s:.0f}s: all "
                f"{size} leases in {directory} are held. Another run_matrix "
                f"invocation is still running, or a holder is wedged. Raise "
                f"${POOL_ENV} only if this machine has the cores to keep CPU "
                "timing trustworthy."
            )
        time.sleep(_POLL_INTERVAL_S)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tools.tests.test_box_pool -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add tools/box_pool.py tools/tests/test_box_pool.py
git commit -m "feat: machine-wide flock lease pool for isolate box ids"
```

---

### Task 2: Lease box ids in run_matrix, and stop misdiagnosing collisions

This task fixes Cause A end to end: the allocator replaces `pid`-derived ids, and `_init_box` stops blaming the install for a collision. No parallelism yet — after this task `run_matrix` is still fully serial, but two copies of it can run at the same time without interfering. That is what makes the test suite runnable concurrently, which is the prerequisite for everything after.

**Files:**
- Modify: `tools/run_matrix.py` — delete `_select_box_id` (`:449-473`), rewrite `_init_box` (`:476-492`), drop `box_id_counter` from `IsolateHandle` (`:294-341`), rework `open_isolate_box` (`:506-577`) and `_run_once`'s box lifecycle (`:940-941`, `:1121-1122`)
- Test: `tools/tests/test_run_matrix.py`

**Interfaces:**
- Consumes: `box_pool.lease`, `box_pool.pool_size`, `box_pool.BoxPoolError` from Task 1
- Produces: `_run_once` acquires its own box lease internally; `IsolateHandle` no longer carries `box_id_counter`; `open_isolate_box(problem_dir)` keeps its signature

- [ ] **Step 1: Write the failing tests**

Add to `tools/tests/test_run_matrix.py`:

> **Note for the implementer:** `test_run_matrix.py` imports only
> `from tools.matrix_core import Limits` today (`:55`); Task 5's tests also
> need `from tools import matrix_core`. Add it now so later tasks don't
> churn the import block.
>
> **Note for the implementer:** `test_run_matrix.py` offers two bases, and
> picking the wrong one is expensive. `TestRunMatrixFixture` (`:174`) copies
> the whole `mini` package into a scratch tree and provides `self.tmp`,
> `self.problem_dir` and `self.testlib_dir` — use it **only** when the test
> actually drives a full `run()` over a problem package. For a test that
> needs no package (it compiles its own throwaway binary, or drives
> `_run_once` directly), subclass the **light mixin** instead: it carries
> only `self.tmp` and the `g++`/`isolate` skip guard. Task 2 got this wrong
> and paid for it — `BoxLeasingTest` inherited ~50 unrelated tests to gain
> 3, taking the suite from 289 to 342 and adding ~108s, doubled again by
> the two-concurrent-suites acceptance run. Task 2's fix round introduces
> the mixin; reuse it, do not re-derive it.
>
> Binaries are built with the **module-level** `_compile(src_text, out_path,
> tmp_dir)` helper (`:140`) — there is no `self._compile`.

```python
class BoxLeasingTest(TestRunMatrixFixture):
    def test_isolate_handle_has_no_pid_derived_counter(self):
        # The pid-derived counter is the Cause-A defect itself. Its absence
        # is the invariant, so it is asserted rather than assumed.
        self.assertFalse(hasattr(run_matrix, "_select_box_id"))
        self.assertNotIn("box_id_counter",
                         run_matrix.IsolateHandle.__dataclass_fields__)

    def test_init_box_names_the_collision_instead_of_the_install(self):
        # isolate answers "This box is currently in use by another process"
        # (rc=2) when the id is live. The old message blamed cgroup
        # delegation, subuid ranges and isolate-cg-keeper — a confident wrong
        # diagnosis that has already cost three agents an afternoon.
        fake = self._fake_isolate(
            rc=2, message="This box is currently in use by another process")
        with self.assertRaises(run_matrix.MatrixError) as ctx:
            run_matrix._init_box(fake, 7)
        message = str(ctx.exception)
        self.assertIn("in use", message)
        self.assertIn("box 7", message)
        self.assertNotIn("subuid", message)
        self.assertNotIn("cg-keeper", message)

    def test_init_box_still_names_the_install_for_a_real_config_failure(self):
        fake = self._fake_isolate(rc=1, message="Cannot initialize control group")
        with self.assertRaises(run_matrix.MatrixError) as ctx:
            run_matrix._init_box(fake, 7)
        self.assertIn("subuid", str(ctx.exception))

    def _fake_isolate(self, *, rc: int, message: str) -> str:
        script = self.tmp / f"fake_isolate_{rc}_{abs(hash(message)) % 9999}"
        script.write_text(f"#!/bin/sh\necho '{message}' >&2\nexit {rc}\n",
                          encoding="utf-8")
        script.chmod(0o755)
        return str(script)

```

The two `_init_box` tests call the helper as
`run_matrix._init_box(self._fake_isolate(rc=2, message="This box is currently "
"in use by another process"), 7)` and
`run_matrix._init_box(self._fake_isolate(rc=1, message="Cannot initialize "
"control group"), 7)` respectively.

> **Note for the implementer:** `test_two_concurrent_run_once_calls_never_share_a_box` belongs to **Task 3**, not this task — do not add it here. Two threads sharing one `IsolateHandle` still share a meta file and a staging directory until Task 3, so its outcome at this point is a race: it fails when the clobbering happens to be observable and passes when it doesn't (two ~6 ms trivial runs frequently serialize, and a clobbered stdout in stdin mode lands in the harmless `FileNotFoundError → data=b""` branch). An `@unittest.expectedFailure` on a test that passes by luck reports **unexpected success**, which fails the suite — a flaky gate on the very task whose acceptance criterion is "two concurrent suites both pass". Task 2's acceptance is Step 5's two-concurrent-suites run, which is the property Task 2 actually fixes: separate processes already have separate handles, so only the box ids were colliding.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tools.tests.test_run_matrix.BoxLeasingTest -v`
Expected: FAIL — `_select_box_id` still exists; `_init_box`'s message still contains "subuid" for the rc=2 case.

- [ ] **Step 3: Implement the change**

Delete `_select_box_id` entirely. Replace `_init_box` with:

```python
# isolate's own words when an id is already claimed. Matched as a substring
# because it is the only signal that separates "another invocation is using
# this box" from "this install is broken", and the two need opposite advice.
_ISOLATE_BOX_BUSY = "currently in use by another process"


def _init_box(binary: str, box_id: int) -> None:
    """`isolate --init` for one box id, raising `MatrixError` on failure.

    Two failures with opposite fixes, so they get two messages. A busy box
    means a *lease* was violated — either something else on this machine
    uses isolate directly, or `$RUN_MATRIX_BOX_POOL` was raised past what
    the lock directory coordinates. The old code folded this into the
    install-is-broken message and sent three agents chasing a cgroup
    misconfiguration that was never there.
    """
    init = subprocess.run([binary, "--cg", f"--box-id={box_id}", "--init"],
                          capture_output=True, text=True)
    if init.returncode == 0:
        return
    detail = (init.stderr or init.stdout).strip()
    if _ISOLATE_BOX_BUSY in detail:
        raise MatrixError(
            f"isolate box {box_id} is already in use by another process "
            f"({detail}). This driver leases every box id through "
            f"{box_pool.lock_dir()} before touching it, and that lease pool "
            "is per-user — so the cause is something the pool cannot see: "
            "another user running run_matrix on this machine, another tool "
            "using isolate directly, or a stale run started before the "
            "lease pool existed. It is not an install problem: nothing "
            "about cgroups, subuid ranges or isolate-cg-keeper needs "
            "changing."
        )
    raise MatrixError(
        f"isolate is installed at {binary} but `--init` failed for box "
        f"{box_id} (exit {init.returncode}): {detail}\n"
        "A missing binary would have failed with a different message "
        "(see open_isolate_box); this looks instead like an "
        "installed-but-unconfigured sandbox — isolate needs cgroup v2 "
        "delegation, the isolate-cg-keeper service (isolate.service) "
        "enabled and running, and the 'isolate' system user's range "
        f"registered in /etc/subuid and /etc/subgid. See {_ISOLATE_HOME}."
    )
```

Add `from tools import box_pool` to the imports. Remove `box_id_counter` from `IsolateHandle` and its docstring paragraph, replacing that paragraph with a pointer to `box_pool`. In `open_isolate_box`, replace the `probe_box_id = _select_box_id()` block with:

```python
    # A usability probe, so a missing or unconfigured sandbox is diagnosed
    # before any compilation touches the tree. It leases an id like every
    # other box: probing an id another invocation is using is the exact
    # collision this pool exists to prevent.
    with box_pool.lease() as probe_box_id:
        _init_box(binary, probe_box_id)
        _cleanup_box(binary, probe_box_id)
```

and drop `box_id_counter=itertools.count(probe_box_id)` from the returned handle (and the now-unused `import itertools`).

In `_run_once`, replace `box_id = next(isolate.box_id_counter) % 65536` / `_init_box(...)` / `finally: _cleanup_box(...)` with a lease that wraps the whole cycle:

```python
    with box_pool.lease() as box_id:
        _init_box(isolate.binary, box_id)
        try:
            ...  # the existing body, unchanged
        finally:
            _cleanup_box(isolate.binary, box_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tools.tests.test_run_matrix -v`
Expected: PASS, no expected failures and no skips.

- [ ] **Step 5: Verify the acceptance property directly**

Run two full suites at once — the thing that was impossible before:

```bash
python3 -m unittest discover -s tools/tests -t . > /tmp/a.log 2>&1 &
python3 -m unittest discover -s tools/tests -t . > /tmp/b.log 2>&1 &
wait; tail -3 /tmp/a.log /tmp/b.log
```

Expected: both end in `OK`. Before this task they produced spurious `MatrixError`s.

- [ ] **Step 6: Commit**

```bash
git add tools/run_matrix.py tools/tests/test_run_matrix.py
git commit -m "fix: lease isolate box ids instead of deriving them from pid"
```

---

### Task 3: Make `_run_once` reentrant

Cause B. Each sandboxed run gets its own meta file and its own staging directory, so two runs in one process cannot see each other's state. Still no parallelism — this only removes the blockers.

Two placement rules are load-bearing and must not be simplified:

1. **The meta file stays outside every `--dir` mount.** It is the driver's only account of what happened; a solution that could open it could rewrite its own verdict. It lives in a `meta_dir` that is never mounted, never in `stage_root`.
2. **The per-run staging directory is removed after the run, not before the next one.** The old `_clear_stage_dir` cleared at the top of the *next* run, so a failure to clean up was reported against an innocent run. Per-run directories attribute it to the run that made the mess. The contamination `_clear_stage_dir` existed to prevent is gone by construction: a directory created fresh for one run cannot hold another run's files.

**Files:**
- Modify: `tools/run_matrix.py` — `IsolateHandle` (`:294-341`), `open_isolate_box` (`:561-577`), `close_isolate_box` (`:580-611`), `_clear_stage_dir` → `_remove_run_dir` (`:702-748`), `_run_once` (`:940-1122`)
- Test: `tools/tests/test_run_matrix.py`

**Interfaces:**
- Consumes: `box_pool.lease` (Task 2)
- Produces: `IsolateHandle(binary, version, meta_dir, stage_root)` — `meta_path` and `stage_dir` are gone; `_run_once` is safe to call from multiple threads sharing one handle

- [ ] **Step 1: Write the failing tests**

```python
class ReentrancyTest(TestRunMatrixFixture):
    def setUp(self):
        super().setUp()
        os.chmod(self.tmp, 0o777)
        self.stdin_path = self.tmp / "in.txt"
        self.stdin_path.write_text("\n", encoding="utf-8")

    def test_handle_exposes_roots_not_single_files(self):
        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            self.assertTrue(isolate.meta_dir.is_dir())
            self.assertTrue(isolate.stage_root.is_dir())
            self.assertFalse(hasattr(isolate, "meta_path"))
            self.assertFalse(hasattr(isolate, "stage_dir"))
        finally:
            run_matrix.close_isolate_box(isolate)

    def test_meta_dir_is_never_inside_the_sandbox_writable_root(self):
        # A solution that could write its own meta file could write its own
        # verdict. This is the invariant that forbids the obvious tidy-up of
        # putting the meta file next to the staged output.
        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            self.assertNotIn(isolate.stage_root.resolve(),
                             isolate.meta_dir.resolve().parents)
            self.assertNotEqual(isolate.stage_root.resolve(),
                                isolate.meta_dir.resolve())
        finally:
            run_matrix.close_isolate_box(isolate)

    def test_concurrent_runs_report_their_own_times_not_each_others(self):
        # The shared-meta defect in its purest form: a fast and a slow run at
        # once. With one meta file the fast run could read the slow run's
        # numbers, or vice versa.
        import concurrent.futures
        fast = _compile("int main(){ return 0; }\n",
                        self.tmp / "fast", self.tmp)
        slow = _compile("int main(){ volatile long s=0;"
                        " for(long i=0;i<400000000L;i++) s+=i; return 0; }\n",
                        self.tmp / "slow", self.tmp)
        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                f_fast = pool.submit(run_matrix._run_once, isolate, fast,
                                     self.stdin_path, self.tmp / "fast.out",
                                     cpu_limit_s=30.0, wall_limit_s=60.0,
                                     mem_limit_kb=256 * 1024)
                f_slow = pool.submit(run_matrix._run_once, isolate, slow,
                                     self.stdin_path, self.tmp / "slow.out",
                                     cpu_limit_s=30.0, wall_limit_s=60.0,
                                     mem_limit_kb=256 * 1024)
                r_fast, r_slow = f_fast.result(), f_slow.result()
        finally:
            run_matrix.close_isolate_box(isolate)
        self.assertLess(r_fast.cpu_ms, 200, r_fast)
        self.assertGreater(r_slow.cpu_ms, 200, r_slow)

    def test_concurrent_runs_do_not_read_each_others_output(self):
        import concurrent.futures
        a = _compile('#include <cstdio>\nint main(){ puts("AAA"); }\n',
                     self.tmp / "aaa", self.tmp)
        b = _compile('#include <cstdio>\nint main(){ puts("BBB"); }\n',
                     self.tmp / "bbb", self.tmp)
        out_a, out_b = self.tmp / "a.out", self.tmp / "b.out"
        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                fs = [pool.submit(run_matrix._run_once, isolate, binary,
                                  self.stdin_path, dest, cpu_limit_s=30.0,
                                  wall_limit_s=60.0, mem_limit_kb=256 * 1024)
                      for binary, dest in ((a, out_a), (b, out_b))]
                [f.result() for f in fs]
        finally:
            run_matrix.close_isolate_box(isolate)
        self.assertEqual(out_a.read_text().strip(), "AAA")
        self.assertEqual(out_b.read_text().strip(), "BBB")

    def test_two_concurrent_run_once_calls_never_share_a_box(self):
        # The end-to-end Cause-A regression test: run the same binary from two
        # threads and assert both produced a real verdict. Before the lease
        # pool this raced on box ids and one side raised MatrixError.
        import concurrent.futures
        binary = _compile("int main(){ return 0; }\n",
                          self.tmp / "trivial", self.tmp)
        os.chmod(self.tmp, 0o777)
        stdin_path = self.tmp / "in.txt"
        stdin_path.write_text("\n", encoding="utf-8")

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(run_matrix._run_once, isolate, binary,
                                       stdin_path, self.tmp / f"out{i}",
                                       cpu_limit_s=5.0, wall_limit_s=10.0,
                                       mem_limit_kb=256 * 1024)
                           for i in range(2)]
                results = [f.result() for f in futures]
        finally:
            run_matrix.close_isolate_box(isolate)
        for r in results:
            self.assertFalse(r.crashed, r)
            self.assertFalse(r.killed, r)

    def test_run_directory_is_removed_after_a_successful_run(self):
        binary = _compile("int main(){ return 0; }\n",
                          self.tmp / "trivial", self.tmp)
        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            run_matrix._run_once(isolate, binary, self.stdin_path,
                                 self.tmp / "o.out", cpu_limit_s=5.0,
                                 wall_limit_s=10.0, mem_limit_kb=256 * 1024)
            self.assertEqual(list(isolate.stage_root.iterdir()), [])
        finally:
            run_matrix.close_isolate_box(isolate)

    def test_a_solutions_stray_file_cannot_reach_the_next_run(self):
        # The Task 6 dogfood defect: a solution writing an unexpected
        # filename used to leave it behind, owned by that box's subuid, and
        # the next run got EACCES and was reported RE. A fresh directory per
        # run makes that unreachable rather than merely cleaned up.
        litterer = _compile('#include <cstdio>\n'
                            'int main(){ FILE*f=fopen("stray.txt","w");'
                            ' fputs("x",f); fclose(f); return 0; }\n',
                            self.tmp / "litterer", self.tmp)
        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            first = run_matrix._run_once(
                isolate, litterer, self.stdin_path, self.tmp / "1.out",
                cpu_limit_s=5.0, wall_limit_s=10.0, mem_limit_kb=256 * 1024,
                io_input="t.inp", io_output="t.out")
            second = run_matrix._run_once(
                isolate, litterer, self.stdin_path, self.tmp / "2.out",
                cpu_limit_s=5.0, wall_limit_s=10.0, mem_limit_kb=256 * 1024,
                io_input="t.inp", io_output="t.out")
        finally:
            run_matrix.close_isolate_box(isolate)
        # Both runs wrote the wrong filename, so both must report the same
        # thing. Before per-run directories the first was NO_OUTPUT and the
        # second RE, because the leftover file was owned by a subuid the
        # second box could not write through.
        self.assertTrue(first.no_output, first)
        self.assertTrue(second.no_output, second)
        self.assertFalse(second.crashed, second)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tools.tests.test_run_matrix.ReentrancyTest -v`
Expected: FAIL — `IsolateHandle` has no `meta_dir`; the concurrent tests raise or report crossed numbers.

- [ ] **Step 3: Implement the change**

Replace the `IsolateHandle` fields:

```python
@dataclasses.dataclass(frozen=True)
class IsolateHandle:
    """The isolate environment shared by one `run()` invocation.

    Everything per-*run* now lives under a per-run directory that
    `_run_once` creates and removes, because a single meta file and a single
    staging directory shared across runs are exactly what stopped this
    driver from ever running two solutions at once: two concurrent `--run`s
    would have written the same meta file (one reads the other's verdict —
    silent and wrong) and cleared the same staging directory out from under
    each other.

    `meta_dir` is deliberately NOT under `stage_root` and is never passed to
    `--dir`. The meta file is the driver's only account of what happened; a
    solution able to open it could write its own verdict.

    `stage_root` is the disk-backed parent of every per-run staging
    directory. Disk-backed, never `/tmp`: on tmpfs the bytes a solution
    writes to its output are charged to the same cgroup `--cg-mem` caps,
    which is a false ML on any solution with a large answer. See
    `_stage_base()`.

    Box ids are not a field here at all — `_run_once` leases one per run from
    `tools.box_pool`, which is cross-process and therefore also excludes
    *other* invocations by this user, something no per-handle counter
    could do.
    """

    binary: str
    version: str
    meta_dir: Path
    stage_root: Path
```

In `open_isolate_box`, replace the `mkstemp`/`mkdtemp` block:

```python
    meta_dir = Path(tempfile.mkdtemp(prefix=".run_matrix_meta_", dir=stage_base))
    stage_root = Path(tempfile.mkdtemp(prefix=".run_matrix_stage_", dir=stage_base))
    os.chmod(stage_root, 0o777)
    return IsolateHandle(binary=binary, version=version,
                         meta_dir=meta_dir, stage_root=stage_root)
```

In `close_isolate_box`, remove both trees, keeping the existing "say so on stderr, never raise" behaviour for a directory that cannot be removed:

```python
    for path in (handle.meta_dir, handle.stage_root):
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            print(f"WARNING: could not remove {path} — it holds something "
                  f"created inside the sandbox that this user cannot delete. "
                  f"Remove it as root: sudo rm -rf {path}", file=sys.stderr)
```

Replace `_clear_stage_dir` with:

```python
def _remove_run_dir(run_dir: Path) -> None:
    """Delete one run's private staging directory.

    Called from `_run_once`'s `finally`, so a run cleans up after itself
    rather than clearing the *previous* run's litter on the way in — which
    is how the old `_clear_stage_dir` worked and why a cleanup failure used
    to be reported against an innocent run.

    This process can unlink files it does not own, because unlinking is
    governed by the *directory's* permissions and this driver created the
    directory. The one case that fails is a foreign-owned *subdirectory*
    with contents, and it raises rather than being swallowed: a staging
    directory this driver cannot guarantee it emptied is one whose disk
    usage grows without bound across a matrix, and silence is how the old
    `ignore_errors=True` left users with directories they could not explain.
    """
    try:
        shutil.rmtree(run_dir)
    except OSError as exc:
        raise MatrixError(
            f"could not remove the sandbox staging directory {run_dir}: "
            f"{exc} — the solution left a directory this process cannot "
            "delete. Remove it as root before running the matrix again."
        ) from exc
```

In `_run_once`, inside the lease, create the per-run directories and point everything at them:

```python
    with box_pool.lease() as box_id:
        _init_box(isolate.binary, box_id)
        run_dir = Path(tempfile.mkdtemp(prefix="run_", dir=isolate.stage_root))
        os.chmod(run_dir, 0o777)
        meta_path = isolate.meta_dir / f"meta_{box_id}_{run_dir.name}"
        try:
            ...  # body, with `isolate.stage_dir` -> `run_dir`,
                 # `isolate.meta_path` -> `meta_path`, and the
                 # `_clear_stage_dir(...)` call deleted (a fresh directory
                 # is empty by construction)
        finally:
            meta_path.unlink(missing_ok=True)
            _cleanup_box(isolate.binary, box_id)
            _remove_run_dir(run_dir)
```

- [ ] **Step 4: Confirm the concurrency test is genuinely load-bearing**

`test_two_concurrent_run_once_calls_never_share_a_box` lives in this task because it only passes deterministically once `_run_once` is reentrant. Prove it is not passing by luck: temporarily revert `_run_once` to the single shared `meta_path`/`stage_dir` (stash the change, or point both runs at one meta file), confirm the test fails, then restore. Record the observed failure in your report — a concurrency test that has never been seen to fail has not been shown to test anything.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tools.tests.test_run_matrix -v`
Expected: PASS, no expected failures remaining.

- [ ] **Step 6: Commit**

```bash
git add tools/run_matrix.py tools/tests/test_run_matrix.py
git commit -m "fix: per-run meta file and staging directory make _run_once reentrant"
```

---

### Task 4: The ambiguity rule

The pure decision function, in `matrix_core` with the rest of the timing model, tested without running anything. It exists separately from Task 5 because it is the part that must be *right*, and it is cheap to get a fresh reviewer's gate on it alone.

**Files:**
- Modify: `tools/matrix_core.py`
- Test: `tools/tests/test_matrix_core.py`

**Interfaces:**
- Produces: `CONTENTION_BOUND: float`, `needs_serial_retime(time_ms: int, killed: bool, limits: Limits, bound: float = CONTENTION_BOUND) -> bool`
- Consumed by: Task 5 (`run_matrix._run_pass2`)

- [ ] **Step 1: Write the failing tests**

Extend the file's existing import line (`:3`) to
`from tools.matrix_core import Limits, classify, compute_limits, needs_serial_retime`
and add `from tools import matrix_core` for the constant.

```python
class NeedsSerialRetimeTest(unittest.TestCase):
    def setUp(self):
        self.limits = Limits(t_main_ms=500, tl_ms=1000, kill_ms=2000)

    def test_comfortably_under_the_limit_is_never_ambiguous(self):
        # Contention only inflates, so a measurement already under TL was
        # under TL serially too.
        self.assertFalse(needs_serial_retime(400, False, self.limits))

    def test_exactly_at_the_limit_is_not_ambiguous(self):
        self.assertFalse(needs_serial_retime(1000, False, self.limits))

    def test_just_over_the_limit_is_ambiguous(self):
        self.assertTrue(needs_serial_retime(1001, False, self.limits))

    def test_the_top_of_the_band_is_ambiguous(self):
        self.assertTrue(needs_serial_retime(1500, False, self.limits))

    def test_past_the_band_is_not_ambiguous(self):
        # 1501/1.5 = 1000.7 > TL, so it was over the limit serially too.
        self.assertFalse(needs_serial_retime(1501, False, self.limits))

    def test_a_kernel_kill_is_never_ambiguous(self):
        # Killed at kill_ms = 2*TL; even at the bound, 2*TL/1.5 = 1.33*TL.
        self.assertFalse(needs_serial_retime(2000, True, self.limits))

    def test_a_bound_of_one_makes_nothing_ambiguous(self):
        # bound=1.0 is serial mode: measurements are exact.
        self.assertFalse(needs_serial_retime(1500, False, self.limits, bound=1.0))

    def test_a_bound_at_or_past_two_is_rejected(self):
        # kill_ms is always 2*tl_ms, so at bound >= 2 a kernel kill stops
        # implying a genuine TL and the whole scheme is unsound.
        with self.assertRaises(ValueError) as ctx:
            needs_serial_retime(1500, False, self.limits, bound=2.0)
        self.assertIn("kill", str(ctx.exception))

    def test_a_bound_below_one_is_rejected(self):
        with self.assertRaises(ValueError):
            needs_serial_retime(1500, False, self.limits, bound=0.9)

    def test_the_default_bound_is_under_two(self):
        self.assertLess(matrix_core.CONTENTION_BOUND, 2.0)
        self.assertGreaterEqual(matrix_core.CONTENTION_BOUND, 1.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tools.tests.test_matrix_core.NeedsSerialRetimeTest -v`
Expected: FAIL — `ImportError: cannot import name 'needs_serial_retime'`

- [ ] **Step 3: Implement the change**

Append to `tools/matrix_core.py`:

```python
# How much a CPU-time measurement may be inflated by other sandboxes running
# on the same machine. Measured under isolate on an 8-thread box, median of
# the concurrent cohort against a serial baseline:
#
#   workers   2      3      4      6      8
#   CPU-bound 1.08x  1.10x  1.15x  1.18x  1.27x
#   mem-bound 1.04x  1.04x  1.21x  1.48x  1.65x (1.92x in a second run)
#
# 1.5 covers the 4-worker figures with real headroom. It must stay strictly
# below 2.0 and that is not a style preference: `kill_ms` is always
# `2 * tl_ms`, so a kernel kill implies a genuine over-limit run only while
# `kill_ms / bound > tl_ms`. At bound >= 2 every killed run becomes
# ambiguous, the serial tail swallows the whole speedup, and the argument
# this function rests on stops holding.
CONTENTION_BOUND = 1.5


def needs_serial_retime(
    time_ms: int, killed: bool, limits: Limits, bound: float = CONTENTION_BOUND
) -> bool:
    """Was this measurement taken close enough to TL that contention could
    have decided it?

    Contention is **one-sided**: isolate reports the sandboxed process's own
    CPU time, and a neighbouring box can only add to it — nothing another
    sandbox does makes a process consume less CPU than it would alone. So a
    measurement `T` taken under a contention bound `F` implies a true serial
    time in `[T/F, T]`, and only one interval is undecidable:

        T <= tl_ms      -> true <= T <= tl_ms   -> genuinely not TL
        T > F * tl_ms   -> true >= T/F > tl_ms  -> genuinely TL
        otherwise       -> undecidable, re-time serially

    `killed` short-circuits to False because isolate kills at `kill_ms`,
    which `compute_limits` fixes at `2 * tl_ms`: a killed run's true time is
    at least `2 * tl_ms / bound`, which exceeds `tl_ms` for every legal
    bound. That single fact is what makes this scheme worth anything — TL
    results are a small share of a matrix but the large majority of its
    wall clock, and re-timing them all serially would give back the speedup.

    This is deliberately NOT `classify`'s `banded` flag. That one marks
    `(TL, kill]` — "too close to call on other hardware", a statement about
    the *problem*, reported to the setter. This one marks "too close to call
    on this hardware right now", a statement about the *measurement*,
    resolved by re-measuring. Conflating them would change serial-mode
    behaviour.
    """
    if bound < 1.0:
        raise ValueError(f"contention bound must be at least 1.0, got {bound}")
    if bound >= 2.0:
        raise ValueError(
            f"contention bound must be below 2.0, got {bound}: kill_ms is "
            "2 * tl_ms, so at this bound a kernel kill no longer implies a "
            "genuine over-limit run"
        )
    if killed:
        return False
    return limits.tl_ms < time_ms <= bound * limits.tl_ms
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tools.tests.test_matrix_core -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/matrix_core.py tools/tests/test_matrix_core.py
git commit -m "feat: one-sided contention rule for which timings need re-measuring"
```

---

### Task 5: Run pass 2 on a worker pool

The payoff. Pass 1 stays exactly as it is — serial, defining `t_main` and therefore TL under no contention at all. Pass 2 fans out to `box_pool.pool_size()` workers, then re-times the ambiguous band serially, with every worker idle.

**Files:**
- Modify: `tools/run_matrix.py` — extract the pass-2 body from `run()` (`:1500-1546`) into `_run_pass2`, add provenance to the payload (`:1553-1586`)
- Test: `tools/tests/test_run_matrix.py`

**Interfaces:**
- Consumes: `matrix_core.needs_serial_retime`, `matrix_core.CONTENTION_BOUND` (Task 4); `box_pool.pool_size` (Task 1)
- Produces: `invocation.json` gains `machine.workers`, `machine.contention_bound`, and a per-result `retimed_serially` boolean

- [ ] **Step 1: Write the failing tests**

```python
class ParallelPassTest(TestRunMatrixFixture):
    def tearDown(self):
        os.environ.pop("RUN_MATRIX_BOX_POOL", None)
        super().tearDown()

    def test_invocation_json_records_the_worker_count_and_bound(self):
        payload = run_matrix.run(self.problem_dir, self.testlib_dir)
        self.assertIn("workers", payload["machine"])
        self.assertGreaterEqual(payload["machine"]["workers"], 1)
        self.assertEqual(payload["machine"]["contention_bound"],
                         matrix_core.CONTENTION_BOUND)

    def test_every_result_declares_whether_it_was_retimed_serially(self):
        payload = run_matrix.run(self.problem_dir, self.testlib_dir)
        for record in payload["results"]:
            self.assertIn("retimed_serially", record)
            self.assertIsInstance(record["retimed_serially"], bool)

    def test_one_worker_produces_the_same_verdicts_as_many(self):
        # The property that matters: parallelism must not change a verdict.
        os.environ["RUN_MATRIX_BOX_POOL"] = "1"
        serial = run_matrix.run(self.problem_dir, self.testlib_dir)
        os.environ["RUN_MATRIX_BOX_POOL"] = "4"
        parallel = run_matrix.run(self.problem_dir, self.testlib_dir)

        def verdicts(payload):
            return {(r["solution"], r["group"], r["test"]): r["verdict"]
                    for r in payload["results"]}

        self.assertEqual(verdicts(serial), verdicts(parallel))
        self.assertEqual(serial["holes"], parallel["holes"])
        self.assertEqual(serial["mismatches"], parallel["mismatches"])

    def test_pass_one_is_never_run_concurrently(self):
        # t_main defines TL. Running it under contention inflates TL and lets
        # genuinely-TLE solutions through, which manufactures holes. Asserted
        # behaviourally — by watching how many runs are actually in flight —
        # rather than by scraping the source for "ThreadPoolExecutor", so a
        # refactor that keeps the property passes and one that loses it fails.
        os.environ["RUN_MATRIX_BOX_POOL"] = "4"
        real_run_once = run_matrix._run_once
        lock = threading.Lock()
        state = {"live": 0, "peak_pass1": 0, "peak_pass2": 0}
        limits_known = threading.Event()

        def watched(*args, **kwargs):
            with lock:
                state["live"] += 1
                key = "peak_pass2" if limits_known.is_set() else "peak_pass1"
                state[key] = max(state[key], state["live"])
            try:
                return real_run_once(*args, **kwargs)
            finally:
                with lock:
                    state["live"] -= 1

        real_compute = run_matrix.compute_limits

        def marking(*args, **kwargs):
            # Pass 1 ends exactly here: compute_limits is what consumes it.
            result = real_compute(*args, **kwargs)
            limits_known.set()
            return result

        with mock.patch.object(run_matrix, "_run_once", watched), \
             mock.patch.object(run_matrix, "compute_limits", marking):
            run_matrix.run(self.problem_dir, self.testlib_dir)

        self.assertEqual(state["peak_pass1"], 1,
                         "pass 1 must measure the model solution alone")
        self.assertGreater(state["peak_pass2"], 1,
                           "pass 2 did not actually run in parallel")

    def test_a_retimed_result_is_flagged_with_the_worker_count(self):
        # The band is unreachable on the `mini` fixture — two trivial
        # solutions, TL pinned to the 1000 ms floor, so nothing can land in
        # (1000, 2000]. Rather than assert inside a loop that never runs
        # (a test that asserts nothing), the near-TL measurement is
        # fabricated by stubbing the runner.
        os.environ["RUN_MATRIX_BOX_POOL"] = "4"
        real_run_once = run_matrix._run_once
        seen = {"pass2": False}

        def near_tl(*args, **kwargs):
            r = real_run_once(*args, **kwargs)
            if seen["pass2"]:
                return dataclasses.replace(r, cpu_ms=1200)  # TL < 1200 <= 1.5*TL
            return r

        real_compute = run_matrix.compute_limits

        def marking(*args, **kwargs):
            result = real_compute(*args, **kwargs)
            seen["pass2"] = True
            return result

        with mock.patch.object(run_matrix, "_run_once", near_tl), \
             mock.patch.object(run_matrix, "compute_limits", marking):
            payload = run_matrix.run(self.problem_dir, self.testlib_dir)

        self.assertTrue(any(r["retimed_serially"] for r in payload["results"]))
        register = json.loads(
            (self.problem_dir / "flags.json").read_text(encoding="utf-8"))
        banded = [f for f in register["flags"] if f["kind"] == "timing-band"]
        self.assertTrue(banded, "a near-TL measurement produced no flag")
        self.assertTrue(any("worker" in f["assumed"] or "worker" in f["what"]
                            for f in banded))

    def test_a_matrix_error_in_one_worker_surfaces_from_run(self):
        # A worker's MatrixError must propagate out of the pool, not be
        # swallowed into a verdict. Forced by making the *staged output* of
        # every run unreadable, which is the real MatrixError path in
        # `_run_once` (a solution that umask(077)s its own output file).
        os.environ["RUN_MATRIX_BOX_POOL"] = "4"
        real_run_once = run_matrix._run_once
        calls = []

        def exploding(*args, **kwargs):
            calls.append(1)
            if len(calls) > 3:
                raise run_matrix.MatrixError("synthetic worker failure")
            return real_run_once(*args, **kwargs)

        with mock.patch.object(run_matrix, "_run_once", exploding):
            with self.assertRaises(run_matrix.MatrixError) as ctx:
                run_matrix.run(self.problem_dir, self.testlib_dir)
        self.assertIn("synthetic worker failure", str(ctx.exception))
```

> **Note for the implementer:** `mock` is already imported in this file
> (`:52`); `threading` and `dataclasses` are not — add them. The exploding
> patch has to survive pass 1 — hence the `len(calls) > 3` guard — because a
> failure raised during pass 1 would prove nothing about the worker pool,
> which only exists in pass 2.
>
> Two of these tests patch `run_matrix.compute_limits` purely as a
> *marker* for where pass 1 ends (they call through to the real one and
> change nothing), so `run()` must reference it as a module global —
> `compute_limits(...)`, which is how it is imported today (`:198`). Do not
> "tidy" that into a local alias.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tools.tests.test_run_matrix.ParallelPassTest -v`
Expected: FAIL — `KeyError: 'workers'`; `test_pass_one_is_not_parallelised` passes trivially at this point and must keep passing.

- [ ] **Step 3: Implement the change**

Add to the imports: `import concurrent.futures`, `from tools import box_pool`, and extend the `matrix_core` import with `CONTENTION_BOUND, needs_serial_retime`.

Extract pass 2 into its own function:

```python
def _run_pass2(isolate, problem, problem_dir, manifest, binaries, checker,
               tests, limits, mem_limit_kb, runs, workers):
    """Run every solution on every test, on `workers` sandboxes at once.

    Only pass 2 is parallel. Pass 1 stays serial in `run()` because it
    measures `t_main`, from which `compute_limits` derives TL: timing the
    model solution under contention inflates TL, and an inflated TL lets
    genuinely-too-slow solutions pass, which manufactures holes — the one
    claim this pipeline makes that has to be true. Pass 1 is also 1-6% of
    the wall clock on every real package measured, so serialising it costs
    almost nothing.

    Two phases. The first fans out; the second re-times, **serially and with
    every worker idle**, only those results `needs_serial_retime` calls
    undecidable. That set is tiny in practice — 18 of 5508 results across
    the eight packages this was measured on — because contention is
    one-sided and a kernel kill therefore still implies a genuine TL (see
    `matrix_core.needs_serial_retime`).

    Threads, not processes: every unit of work is a `subprocess.run` on
    isolate, which releases the GIL, and the workers share one
    `IsolateHandle`. Each `_run_once` leases its own box id and creates its
    own staging directory, so no state is shared between them; the shared
    handle carries only the two roots those live under.

    A `MatrixError` raised in any worker propagates out of `.result()` and
    aborts the matrix. That is deliberate: every `MatrixError` in this
    driver means "this run cannot be judged", and turning one into a verdict
    is precisely the confidently-wrong outcome the whole module refuses.
    """
    cpu_limit_s = limits.kill_ms / 1000.0
    wall_limit_s = max(3 * limits.tl_ms, limits.kill_ms) / 1000.0
    work = [(entry["file"], group, test)
            for entry in manifest["solutions"]
            for group, paths in tests.items()
            for test in paths]

    def one(item):
        name, group, test = item
        out = problem_dir / ".build" / f"{Path(name).stem}.{group}.{test.stem}.out"
        r = _run_once(isolate, binaries[name], test, out,
                      cpu_limit_s, wall_limit_s, mem_limit_kb,
                      io_input=problem.input, io_output=problem.output)
        return item, out, r

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        measured = list(pool.map(one, work))

    results, actual = [], {}
    for (name, group, test), out, r in measured:
        answer = test.with_suffix(".a")
        retimed = needs_serial_retime(r.cpu_ms, r.killed, limits) if workers > 1 else False
        if retimed:
            first_run_ms = r.cpu_ms
            r = _time_median(isolate, binaries[name], test, out,
                             cpu_limit_s, wall_limit_s, mem_limit_kb, runs,
                             io_input=problem.input, io_output=problem.output)
            flags.append(
                problem_dir, phase="validate-solutions", severity="low",
                kind="timing-band",
                what=f"{name} on {group}/{test.stem} measured {first_run_ms} ms "
                     f"CPU time with {workers} sandboxes running, close enough "
                     f"to TL {limits.tl_ms} that contention could have decided it",
                assumed=f"re-timed {runs}x serially with every worker idle; the "
                        f"median came out {r.cpu_ms} ms",
                changes_if_wrong=f"the expected tag of {name}")
        outcome = _classify(r, checker, test, out, answer, limits)
        if outcome.banded:
            first_run_ms = r.cpu_ms
            r = _time_median(isolate, binaries[name], test, out,
                             cpu_limit_s, wall_limit_s, mem_limit_kb, runs,
                             io_input=problem.input, io_output=problem.output)
            outcome = _classify(r, checker, test, out, answer, limits)
            flags.append(
                problem_dir, phase="validate-solutions", severity="medium",
                kind="timing-band",
                what=f"{name} on {group}/{test.stem} ran {first_run_ms} ms CPU "
                     f"time, between TL {limits.tl_ms} and kill {limits.kill_ms} "
                     f"({workers} worker(s))",
                assumed=f"re-timed {runs}x for stability; the median came out "
                        f"{r.cpu_ms} ms, and the recorded verdict is "
                        f"{outcome.verdict} — there is no separate 'banded' "
                        "verdict, only ever a real one (TL if still over the "
                        "limit, otherwise whatever the checker returned)",
                changes_if_wrong=f"the expected tag of {name}")
        actual.setdefault(name, {}).setdefault(group, []).append(outcome.verdict)
        results.append({
            "solution": name, "group": group, "test": test.stem,
            "verdict": outcome.verdict,
            "time_ms": r.cpu_ms, "wall_ms": r.wall_ms,
            "ratio": round(r.cpu_ms / max(limits.t_main_ms, 1), 2),
            "peak_kb": r.peak_kb, "killed": r.killed, "oom": r.oom,
            "banded": outcome.banded, "retimed_serially": retimed,
        })
    collapsed = {name: {group: group_verdict(v) for group, v in groups.items()}
                 for name, groups in actual.items()}
    return results, collapsed
```

> **Note for the implementer:** the ordering above is not incidental. The serial re-time happens **before** `_classify`, because `needs_serial_retime` asks about the raw measurement while `classify`'s `banded` asks about the settled verdict. Reversing them would classify on a number already known to be untrustworthy. Also note `retimed` is forced False at `workers == 1`: with one sandbox there is no contention to correct for, which is what makes `test_one_worker_produces_the_same_verdicts_as_many` a real comparison rather than a tautology.

In `run()`, replace the pass-2 block (`:1500-1546`) with:

```python
        workers = box_pool.pool_size()
        results, actual = _run_pass2(isolate, problem, problem_dir, manifest,
                                     binaries, checker, tests, limits,
                                     mem_limit_kb, runs, workers)
```

and add to the payload's `machine` dict:

```python
            # How many sandboxes were running at once, and the inflation
            # bound the ambiguity rule assumed. Both are provenance, not
            # settings: a reader asking whether a recorded 1040 ms is
            # trustworthy needs to know it was measured with three other
            # boxes live.
            "workers": workers,
            "contention_bound": CONTENTION_BOUND,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tools.tests.test_run_matrix -v`
Expected: PASS

- [ ] **Step 5: Verify the speedup on a real package**

The plan's whole justification is a wall-clock number, so measure it rather than assert it. Copy a package out of `~/Projects/my_cp_problems/` first — that tree is never modified in place.

```bash
cp -r ~/Projects/my_cp_problems/goldenseed /tmp/gs-serial
cp -r ~/Projects/my_cp_problems/goldenseed /tmp/gs-par
RUN_MATRIX_BOX_POOL=1 time python3 -m tools.run_matrix /tmp/gs-serial "$TESTLIB"
RUN_MATRIX_BOX_POOL=4 time python3 -m tools.run_matrix /tmp/gs-par "$TESTLIB"
python3 - <<'EOF'
import json
a = json.load(open("/tmp/gs-serial/invocation.json"))
b = json.load(open("/tmp/gs-par/invocation.json"))
key = lambda p: {(r["solution"], r["group"], r["test"]): r["verdict"] for r in p["results"]}
assert key(a) == key(b), "PARALLELISM CHANGED A VERDICT — stop and investigate"
assert a["limits"] == b["limits"], "TL differed between serial and parallel"
print("verdicts identical;", sum(r["retimed_serially"] for r in b["results"]), "re-timed serially")
EOF
```

Expected: identical verdicts and limits, a handful (0–5) re-timed, and the parallel run roughly 2.5–3x faster (serial baseline for `goldenseed` is ~195s).

- [ ] **Step 6: Commit**

```bash
git add tools/run_matrix.py tools/tests/test_run_matrix.py
git commit -m "feat: run pass 2 on a bounded worker pool, re-timing only ambiguous results"
```

---

### Task 6: Retire the "run it alone" contract

The warning in `README.md` and the constraint repeated in the plan documents are now false, and a stale safety warning is worse than none — it trains readers to serialise work that no longer needs it.

**Files:**
- Modify: `README.md:168-171`
- Modify: `skills/validating-solutions/SKILL.md` (near the `run_matrix` invocation at `:294`)
- Modify: `docs/superpowers/specs/2026-07-31-stage-3-scope.md:116-118`
- Test: `tools/tests/test_skill_docs.py`

**Interfaces:**
- Consumes: the env var names from Task 1 (`RUN_MATRIX_BOX_POOL`, `RUN_MATRIX_BOX_LOCK_DIR`) and the provenance fields from Task 5

- [ ] **Step 1: Write the failing test**

Add to `tools/tests/test_skill_docs.py`:

```python
def test_readme_no_longer_claims_the_tools_are_serial_only(self):
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    self.assertNotIn("not parallel-safe", readme)
    self.assertIn("RUN_MATRIX_BOX_POOL", readme)

def test_validating_solutions_documents_the_worker_knob(self):
    skill = (REPO / "skills" / "validating-solutions" / "SKILL.md").read_text(
        encoding="utf-8")
    self.assertIn("RUN_MATRIX_BOX_POOL", skill)
    self.assertIn("retimed_serially", skill)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tools.tests.test_skill_docs -v`
Expected: FAIL — README still contains "not parallel-safe".

- [ ] **Step 3: Rewrite the README section**

Replace `README.md:168-171` with:

```markdown
**The tools suite is parallel-safe.** `run_matrix.py` leases every isolate
box id from a per-user `flock` pool (`/run/user/<uid>/run_matrix-boxes`,
falling back to `/tmp/run_matrix-boxes-<uid>`, overridable with
`$RUN_MATRIX_BOX_LOCK_DIR`), so several invocations — or several
`dispatching-parallel-agents` subagents, or two copies of the test suite —
can run at once without colliding. It also runs pass 2 on that same pool, so
the pool size is simultaneously the box allocator and this user's CPU
admission control.

The pool is per-user, and that bound is worth knowing: two *different* users
running `run_matrix` on the same machine can still land on the same isolate
box id. That collision is caught loudly by isolate's own lock — the driver
names it and stops, rather than reporting a wrong verdict — but it is not
prevented.

`$RUN_MATRIX_BOX_POOL` sets the pool size; it defaults to half the CPUs. That
default is a correctness bound, not a throughput setting: CPU time inflates
under contention (measured on an 8-thread box, 1.15–1.21x at 4 concurrent
sandboxes and up to 1.92x at 8), and the driver's ambiguity rule is only
sound while inflation stays below 2x. Raise it only on a machine with the
cores to match, and set it to `1` for a fully quiesced authoritative run.

Pass 1 — the model solution's timings, from which TL is derived — is always
serial regardless of the pool size.
```

- [ ] **Step 4: Add the operator note to the skill**

After the `python3 -m tools.run_matrix "$PROBLEM" "$TESTLIB"` block in `skills/validating-solutions/SKILL.md`:

```markdown
The matrix runs several sandboxes at once (half this machine's CPUs by
default; `RUN_MATRIX_BOX_POOL=N` to change it, `RUN_MATRIX_BOX_POOL=1` for a
fully quiesced run). Running it in parallel with another package's matrix is
safe — box ids are leased through a per-user, cross-process pool.

Timing stays trustworthy because contention can only make a run look
*slower*, never faster. A result measured close enough to TL that contention
could have decided it is re-timed serially, with every other sandbox idle,
and marked `"retimed_serially": true` in `invocation.json`;
`machine.workers` records how many sandboxes were live. The model solution's
own timings — the ones TL is derived from — are always measured serially.
```

- [ ] **Step 5: Close the carried-forward item**

In `docs/superpowers/specs/2026-07-31-stage-3-scope.md`, replace the "The test suite is not parallel-safe with itself" bullet with:

```markdown
- ~~**The test suite is not parallel-safe with itself.**~~ **Resolved**
  2026-08-09 by `docs/superpowers/plans/2026-08-09-parallel-invocation-matrix.md`:
  box ids are leased from a per-user, cross-process `flock` pool instead of
  derived from `pid`, `_run_once` owns its meta file and staging directory, and pass 2 runs
  on the lease pool.
```

- [ ] **Step 6: Run the full suite**

Run: `python3 -m unittest discover -s tools/tests -t . -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add README.md skills/validating-solutions/SKILL.md \
        docs/superpowers/specs/2026-07-31-stage-3-scope.md \
        tools/tests/test_skill_docs.py
git commit -m "docs: the tools suite is parallel-safe; document the worker pool"
```

---

## Known limitations, stated rather than hidden

- **The serial re-time is quiesced within the invocation, not across the machine.** If another `run_matrix` holds leases while this one re-times its ambiguous band, the re-timing is itself mildly contended. Acquiring the whole pool would fix it and would deadlock two invocations doing the same, so it is not done. The `timing-band` flag names the worker count, and `RUN_MATRIX_BOX_POOL=1` gives a fully quiesced authoritative run. A setter shipping a problem with a tight TL should do the final matrix that way.
- **`CHECKER_TIMEOUT_S` (10s) is unchanged and checkers run unsandboxed, outside the lease pool.** A heavy custom checker on a loaded machine has less headroom than it did serially. 10s is still ~10x any plausible checker, so this is recorded rather than acted on; if it ever fires spuriously, the fix is to run checkers inside the pool, not to raise the constant.
- **`CONTENTION_BOUND` is a measured constant, not calibrated per machine.** The measurements behind 1.5 come from one 8-thread box. On very different hardware — many-core with shared memory bandwidth, or an oversubscribed VM — the true bound could be higher, and the failure mode is a genuinely-TL result recorded as OK. If that is ever suspected, the check is a `RUN_MATRIX_BOX_POOL=1` re-run compared against the parallel one, exactly as Task 5 Step 5 does. A runtime calibration probe is the obvious follow-up and is deliberately out of scope here.
- **`review_checks.run()` still triggers `scan()` three times**, one `git log` per solution each. Untouched, still cosmetic, still carried forward.

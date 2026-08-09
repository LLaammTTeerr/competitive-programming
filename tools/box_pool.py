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

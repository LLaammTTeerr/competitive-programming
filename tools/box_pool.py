"""Per-user lease allocator for isolate box ids.

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
write, and none should be added. This is the same *primitive* `tools/flags.py`
already uses for its register — `flock` on a file, deliberately, so the
project reasons about one locking mechanism rather than two — but not the
same *mode*: `flags.py` takes a blocking `LOCK_EX` and waits for the lock;
this module takes `LOCK_EX | LOCK_NB` and polls in a loop instead (see
`lease` below), because a lease has other ids to try before it is worth
waiting on any one of them.

The pool is also this pipeline's CPU admission control, and that is not a
side effect — it is the second reason it exists as a shared pool rather
than a per-process counter. `run_matrix` sizes its worker pool to
`pool_size()`, so all of one user's concurrent invocations share
`pool_size()` leases instead of each running that many boxes on top of the
others. That bound is load-bearing for verdict correctness: CPU time
inflates under contention (measured on an 8-thread box: 1.15-1.21x at 4
concurrent boxes, up to 1.92x at 8), and `run_matrix`'s ambiguity band is
only valid below a bounded inflation factor.

The lock directory holds zero-byte files and is *not* where anything
sandboxed writes, so the tmpfs-charges-the-cgroup rule that keeps
`run_matrix`'s staging directory off `/tmp` does not apply here — these
locks are allowed to live on tmpfs. What the directory *is* is per-user, not
machine-wide: it defaults to the caller's systemd-managed per-user runtime
directory (`/run/user/<uid>/run_matrix-boxes`), falling back to a
uid-suffixed directory under `/tmp` (`/tmp/run_matrix-boxes-<uid>`) on
machines without one. Building a pool that several different users could
share safely would need a lock directory writable, and *trusted*, by all of
them; this module does not attempt that, and the consequence is real,
not hidden: two different users running `run_matrix` on the same machine at
the same time can still pick the same isolate box id, because each has
their own lock directory and neither can see the other's leases. When that
happens, isolate's own "This box is currently in use by another process"
check (rc=2) catches it — loudly, as a named failure, which is strictly
better than the silent collisions the pid-derived scheme produced, but it
is a live failure mode, not a guarantee this module closes. Do not "fix"
this to a single shared directory to close that gap; that is a deliberate,
documented trade-off, and do not "fix" the lock directory choice to match
`_stage_base()` either — the tmpfs reasoning above is why it doesn't need
to.
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

# isolate box ids run 0-65535 on this machine's isolate 2.6; a pool bigger
# than that would eventually hand out an id isolate itself will refuse.
MAX_POOL_SIZE = 65536

# The basename of the lock directory, whether it lands under /run/user/<uid>
# or under /tmp.
_LOCK_DIR_NAME = "run_matrix-boxes"

# How long to sleep between full sweeps of the pool when every id is taken.
# Short enough that a released lease is picked up promptly, long enough that
# a blocked worker is not spinning on `flock` several thousand times a second.
_POLL_INTERVAL_S = 0.05


class BoxPoolError(RuntimeError):
    """A box id could not be leased."""


def pool_size() -> int:
    """How many isolate boxes this user's `run_matrix` invocations may hold
    open at once.

    Per-user, not machine-wide (see the module docstring): a different user
    running `run_matrix` on the same machine draws from their own lock
    directory and is invisible to this bound.

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
    if value > MAX_POOL_SIZE:
        raise BoxPoolError(
            f"${POOL_ENV} must be at most {MAX_POOL_SIZE} (isolate box ids "
            f"run 0-{MAX_POOL_SIZE - 1} on this machine), got {value}"
        )
    return value


def _default_lock_dir() -> Path:
    """Where lock files live when $RUN_MATRIX_BOX_LOCK_DIR is unset.

    Per-user, not machine-wide: prefers the caller's systemd-managed
    per-user runtime directory (mode 0700, owned by the user, wiped at
    logout) and falls back to a uid-suffixed directory under `/tmp` when
    that isn't available (no systemd, or `/run/user/<uid>` doesn't exist).
    See the module docstring for what "per-user" implies for two different
    users racing on the same machine.
    """
    uid = os.getuid()
    runtime_dir = Path(f"/run/user/{uid}")
    if runtime_dir.is_dir() and os.access(runtime_dir, os.W_OK):
        return runtime_dir / _LOCK_DIR_NAME
    return Path(f"/tmp/{_LOCK_DIR_NAME}-{uid}")


def lock_dir() -> Path:
    """The directory holding one lock file per box id, created if absent.

    Per-user (see `_default_lock_dir`): not chmod'd to be shared with other
    users, because it isn't meant to be — a lock directory one user's
    `run_matrix` writes into is not a directory another user should be able
    to write into too.
    """
    raw = os.environ.get(LOCK_DIR_ENV)
    path = Path(raw) if raw else _default_lock_dir()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if not path.is_dir():
            raise BoxPoolError(
                f"cannot create the box-lease directory {path}: {exc}. Set "
                f"${LOCK_DIR_ENV} to a writable directory."
            ) from exc
    return path


def _try_claim(directory: Path, box_id: int) -> int | None:
    """Open and `flock` one id's lock file, returning the fd or None.

    Mode 0o600: the directory is per-user (see `lock_dir`), so there is no
    reason for any other user to be able to read or write these files.

    Returns None only for "someone else holds it" (EWOULDBLOCK/EACCES); any
    other OSError is a real problem with the lock directory and propagates as
    `BoxPoolError` rather than silently shrinking the pool.
    """
    path = directory / f"box-{box_id}.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
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

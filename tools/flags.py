"""The flag register: every autonomous judgement call the pipeline makes.

Flags do not stop the pipeline. `changes_if_wrong` is mandatory because it is
what prices an interruption before the reader decides to make one.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
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


@contextmanager
def _lock(path: Path):
    """Hold an exclusive advisory lock for the whole read-modify-write.

    `append()` used to read the register, add one record, and write the
    result back with no mutual exclusion, through a *fixed* temp filename
    shared by every writer (`flags.json.tmp`). Two processes doing 40
    appends each produced `FileNotFoundError: 'flags.json.tmp' ->
    'flags.json'` — one process's `os.replace` consuming the other's
    half-written temp file — and 51 of 80 records surviving. A register
    that exists to make autonomous judgement calls durable cannot drop 36%
    of them, and both skills that write to it instruct
    `superpowers:dispatching-parallel-agents`.

    A separate lock file, not `flags.json` itself: the data file is
    replaced by `os.replace`, so a lock held on it would be a lock on an
    unlinked inode the moment the first writer finished. `flock` is
    advisory and per-open-file-description, released by `os.close` (and by
    process death, including a kill -9, which is why no stale-lock cleanup
    is needed).
    """
    lock_path = path.with_name(path.name + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _write_atomically(path: Path, text: str) -> None:
    """Replace `path` with `text` via a *uniquely named* temp file.

    `mkstemp` in the destination's own directory: unique per writer (the
    fixed `flags.json.tmp` was the other half of the concurrency bug) and
    on the same filesystem, which `os.replace` requires to be atomic.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                     prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates at 0600; the register is an ordinary readable
        # artifact of the run, like invocation.json beside it.
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read(problem_dir: str | Path) -> list[dict]:
    path = _path(problem_dir)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FlagError(f"{path}: cannot be read: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # R1: this file is written by this module but read after arbitrary
        # interruptions (and is small enough that a human edits it), so a
        # truncated or hand-mangled register must arrive as a FlagError
        # naming the file, not a bare JSONDecodeError from json's internals.
        raise FlagError(f"{path}: corrupted flags.json, not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FlagError(f"flags.json top-level must be dict, got {type(data).__name__}")
    flags = data.get("flags", [])
    if not isinstance(flags, list):
        raise FlagError(f"flags.json 'flags' field must be list, got {type(flags).__name__}")
    # Validate each record has required fields
    for flag in flags:
        if not isinstance(flag, dict):
            raise FlagError(f"flag record must be dict, got {type(flag).__name__}")
        if "id" not in flag:
            raise FlagError("corrupted flags.json: flag record missing 'id' field")
        # `append` calls `.startswith` on every id to number the next one, so
        # a non-string id was an AttributeError from inside the numbering
        # rather than a message about the record that has it.
        if not isinstance(flag["id"], str):
            raise FlagError(
                f"corrupted flags.json: flag record 'id' is "
                f"{flag['id']!r} ({type(flag['id']).__name__}), expected a string")
    return flags


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
    path = _path(problem_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Everything from here to os.replace is one critical section. Read,
    # number, and write must be atomic with respect to other appenders:
    # both skills that use this register instruct
    # `superpowers:dispatching-parallel-agents`, so concurrent appends are
    # the normal case, not an exotic one.
    with _lock(path):
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
        _write_atomically(path, json.dumps(payload, indent=2,
                                           ensure_ascii=False) + "\n")
    return record

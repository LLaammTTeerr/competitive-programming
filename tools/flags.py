"""The flag register: every autonomous judgement call the pipeline makes.

Flags do not stop the pipeline. `changes_if_wrong` is mandatory because it is
what prices an interruption before the reader decides to make one.
"""

from __future__ import annotations

import json
import os
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


def read(problem_dir: str | Path) -> list[dict]:
    path = _path(problem_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
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
    path = _path(problem_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return record

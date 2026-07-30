#!/usr/bin/env python3
"""Scan solution header comments into solutions.json.

Metadata beside the code cannot desynchronize from it, and renaming a file does
not orphan it. solutions.json is therefore a scan product, regenerated on every
run and never hand-edited.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tools.problem_meta import Problem, load

SCHEMA = 1

TAGS = (
    "main",
    "accepted",
    "wrong-answer",
    "time-limit-exceeded",
    "time-limit-exceeded-or-accepted",
    "memory-limit-exceeded",
    "presentation-error",
    "failed",
)

VERDICTS = ("OK", "WA", "TL", "ML", "PE", "RE")

_FIELD = re.compile(r"^\s*\*?\s*@(?P<key>[a-z-]+)\s+(?P<value>.+?)\s*$")


class ScanError(ValueError):
    """A solution's metadata block is malformed or contradicts problem.json."""


def parse_block(text: str) -> dict:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "*/" in line:
            break
        match = _FIELD.match(line)
        if match:
            fields[match.group("key")] = match.group("value")

    for required in ("tag", "expect", "algorithm", "complexity"):
        if required not in fields:
            raise ScanError(f"metadata block is missing @{required}")

    tag = fields["tag"]
    if tag not in TAGS:
        raise ScanError(f"unknown @tag {tag!r}; known: {TAGS}")

    expect: dict[str, str] = {}
    for token in fields["expect"].split():
        if "=" not in token:
            raise ScanError(f"malformed @expect entry {token!r}, want group=VERDICT")
        group, verdict = token.split("=", 1)
        if verdict not in VERDICTS:
            raise ScanError(f"unknown verdict {verdict!r} in @expect; known: {VERDICTS}")
        expect[group] = verdict

    return {
        "tag": tag,
        "expect": expect,
        "algorithm": fields["algorithm"],
        "why_wrong": fields.get("why-wrong"),
        "complexity": fields["complexity"],
    }


def _updated(path: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", path.name],
            cwd=path.parent, capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return stamp.astimezone().isoformat(timespec="seconds")


def scan(problem_dir: str | Path, problem: Problem) -> dict:
    problem_dir = Path(problem_dir)
    groups = problem.subtask_ids()
    entries = []

    for path in sorted((problem_dir / "solutions").glob("*.cpp")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ScanError(f"{path.name}: {exc}") from exc
        try:
            parsed = parse_block(text)
        except ScanError as exc:
            raise ScanError(f"{path.name}: {exc}") from exc

        for group in parsed["expect"]:
            if group not in groups:
                raise ScanError(
                    f"{path.name}: @expect names unknown group {group!r}; "
                    f"problem.json declares {groups}"
                )
        for group in groups:
            if group not in parsed["expect"]:
                raise ScanError(f"{path.name}: @expect is missing group {group!r}")

        entries.append({"file": path.name, "updated": _updated(path), **parsed})

    mains = [e for e in entries if e["tag"] == "main"]
    if len(mains) != 1:
        raise ScanError(f"expected exactly one @tag main, found {len(mains)}")

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "solutions": entries,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: scan_solutions.py <problem-dir>", file=sys.stderr)
        return 2
    problem_dir = Path(argv[1])
    payload = scan(problem_dir, load(problem_dir / "problem.json"))
    out = problem_dir / "solutions.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {out} ({len(payload['solutions'])} solutions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

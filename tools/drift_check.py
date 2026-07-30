#!/usr/bin/env python3
"""Compare problem.json against the vnolymp statement.

The statement is not generated — templating the .tex would fight vnolymp — so
this is the guard that stops the two from disagreeing. Parsing is regex over
two very specific constructs, which is adequate for the vnolymp key list and
the subtasks environment and nothing else.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from tools.problem_meta import Problem, load

_KEYLIST = re.compile(r"\\begin\{problem\}\s*\[(?P<keys>.*?)\]", re.DOTALL)
_SUBTASK = re.compile(r"\\subtask\{(?P<points>\d+)\}")


class DriftCheckError(ValueError):
    """Statement file is malformed, unreadable, or inconsistent with problem.json."""


def parse_tex(text: str) -> dict:
    match = _KEYLIST.search(text)
    keys: dict[str, str] = {}
    if match:
        for pair in match.group("keys").split(","):
            if "=" not in pair:
                continue
            name, value = pair.split("=", 1)
            keys[name.strip()] = value.strip().strip("{}")

    def as_int(name):
        try:
            return int(keys[name])
        except (KeyError, ValueError):
            return None

    return {
        "time": as_int("time"),
        "memory": as_int("memory"),
        "input": keys.get("input"),
        "output": keys.get("output"),
        "subtask_points": [int(m.group("points")) for m in _SUBTASK.finditer(text)],
    }


def check(problem: Problem, tex_text: str) -> list[str]:
    tex = parse_tex(tex_text)
    issues: list[str] = []

    published_s = problem.time_ms_published / 1000
    if tex["time"] is None:
        issues.append("statement: no `time` key in \\begin{problem}")
    elif abs(tex["time"] - published_s) > 1e-9:
        issues.append(
            f"time: problem.json publishes {published_s:g} s, "
            f"statement says {tex['time']:g} s"
        )

    if tex["memory"] != problem.memory_mb:
        issues.append(
            f"memory: problem.json says {problem.memory_mb} MB, "
            f"statement says {tex['memory']} MB"
        )

    if tex["input"] != problem.input:
        issues.append(
            f"input: problem.json says {problem.input!r}, "
            f"statement says {tex['input']!r}"
        )
    if tex["output"] != problem.output:
        issues.append(
            f"output: problem.json says {problem.output!r}, "
            f"statement says {tex['output']!r}"
        )

    expected = [s.points for s in problem.subtasks]
    if tex["subtask_points"] != expected:
        issues.append(
            f"subtask points: problem.json says {expected}, "
            f"statement says {tex['subtask_points']}"
        )

    return issues


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: drift_check.py <problem-dir> <statement.tex>", file=sys.stderr)
        return 2
    problem = load(Path(argv[1]) / "problem.json")
    try:
        tex_text = Path(argv[2]).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DriftCheckError(f"statement file not found: {argv[2]}") from exc
    except UnicodeDecodeError as exc:
        raise DriftCheckError(f"statement file is not valid UTF-8: {argv[2]}") from exc
    issues = check(problem, tex_text)
    if not issues:
        print("no drift between problem.json and the statement")
        return 0
    for issue in issues:
        print(f"DRIFT  {issue}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

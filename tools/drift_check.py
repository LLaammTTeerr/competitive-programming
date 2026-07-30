#!/usr/bin/env python3
"""Compare problem.json against the vnolymp statement.

The statement is not generated — templating the .tex would fight vnolymp — so
this is the guard that stops the two from disagreeing. Parsing is brace-aware
and comment-aware for robustness against well-formed LaTeX statements.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from tools.problem_meta import Problem, load

_SUBTASK = re.compile(r"\\subtask\{(?P<points>\d+)\}")


class DriftCheckError(ValueError):
    """Statement file is malformed, unreadable, or inconsistent with problem.json."""


def _strip_comments(text: str) -> str:
    """Remove LaTeX comments (% to EOL) but preserve escaped percents (\\%)."""
    result = []
    i = 0
    while i < len(text):
        if i + 1 < len(text) and text[i] == '\\' and text[i + 1] == '%':
            # Escaped percent - keep both characters
            result.append('\\%')
            i += 2
        elif text[i] == '%':
            # Unescaped percent - skip to EOL
            while i < len(text) and text[i] != '\n':
                i += 1
            # Keep the newline if present
            if i < len(text):
                result.append('\n')
                i += 1
        else:
            result.append(text[i])
            i += 1
    return ''.join(result)


def _extract_subtasks_body(text: str) -> str:
    """Extract the content between \\begin{subtasks} and \\end{subtasks}."""
    begin_idx = text.find(r'\begin{subtasks}')
    if begin_idx == -1:
        return ""
    end_idx = text.find(r'\end{subtasks}', begin_idx)
    if end_idx == -1:
        return text[begin_idx + len(r'\begin{subtasks}'):]
    return text[begin_idx + len(r'\begin{subtasks}'):end_idx]


def _parse_keylist_braceaware(text: str) -> dict[str, str]:
    """Parse the vnolymp problem key list with brace-aware scanning.

    Handles keys like origin = {Đề chọn [Vòng 2]} correctly by tracking
    brace depth and only splitting on commas at depth 0.
    """
    # Find \begin{problem}[
    start = text.find(r'\begin{problem}[')
    if start == -1:
        return {}

    i = start + len(r'\begin{problem}[')
    depth = 0
    keylist_text = []

    # Scan forward until we find ] at depth 0
    while i < len(text):
        ch = text[i]
        if ch == '{':
            depth += 1
            keylist_text.append(ch)
        elif ch == '}':
            depth -= 1
            keylist_text.append(ch)
        elif ch == ']' and depth == 0:
            # End of key list
            break
        else:
            keylist_text.append(ch)
        i += 1

    # Parse the keylist, splitting on commas at depth 0
    keys: dict[str, str] = {}
    keylist = ''.join(keylist_text)

    depth = 0
    pairs = []
    current_pair = []

    for ch in keylist:
        if ch == '{':
            depth += 1
            current_pair.append(ch)
        elif ch == '}':
            depth -= 1
            current_pair.append(ch)
        elif ch == ',' and depth == 0:
            pairs.append(''.join(current_pair))
            current_pair = []
        else:
            current_pair.append(ch)

    if current_pair:
        pairs.append(''.join(current_pair))

    for pair in pairs:
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        keys[name.strip()] = value.strip().strip("{}")

    return keys


def parse_tex(text: str) -> dict:
    # Strip comments first
    text_no_comments = _strip_comments(text)

    # Parse key list with brace awareness
    keys = _parse_keylist_braceaware(text_no_comments)

    def as_int(name):
        try:
            return int(keys[name])
        except (KeyError, ValueError):
            return None

    # Extract subtasks body and find subtask points only within it
    subtasks_body = _extract_subtasks_body(text_no_comments)
    subtask_points = [int(m.group("points")) for m in _SUBTASK.finditer(subtasks_body)]

    return {
        "time": as_int("time"),
        "memory": as_int("memory"),
        "input": keys.get("input"),
        "output": keys.get("output"),
        "subtask_points": subtask_points,
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
    except (OSError, UnicodeDecodeError) as exc:
        raise DriftCheckError(f"statement file error: {exc}") from exc
    issues = check(problem, tex_text)
    if not issues:
        print("no drift between problem.json and the statement")
        return 0
    for issue in issues:
        print(f"DRIFT  {issue}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

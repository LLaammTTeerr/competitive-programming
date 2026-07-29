"""Normalising submission records from both the API and the status pages."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

# Verdicts that mean the judge is still working on the submission.
PENDING_VERDICTS = {
    "TESTING",
    "SUBMITTED",
    "IN QUEUE",
    "RUNNING",
    "PENDING",
    "",
}

_API_VERDICTS = {
    "OK": "Accepted",
    "FAILED": "Failed",
    "PARTIAL": "Partial",
    "COMPILATION_ERROR": "Compilation error",
    "RUNTIME_ERROR": "Runtime error",
    "WRONG_ANSWER": "Wrong answer",
    "PRESENTATION_ERROR": "Presentation error",
    "TIME_LIMIT_EXCEEDED": "Time limit exceeded",
    "MEMORY_LIMIT_EXCEEDED": "Memory limit exceeded",
    "IDLENESS_LIMIT_EXCEEDED": "Idleness limit exceeded",
    "SECURITY_VIOLATED": "Security violated",
    "CRASHED": "Crashed",
    "INPUT_PREPARATION_CRASHED": "Input preparation crashed",
    "CHALLENGED": "Hacked",
    "SKIPPED": "Skipped",
    "TESTING": "Testing",
    "REJECTED": "Rejected",
}


_PROBLEM_HREF = re.compile(
    # Group 1 captures the contest base path, including the /group/<groupId>
    # prefix that private group contests carry, so sibling URLs can reuse it.
    r"((?:/group/[^/]+)?/(?:contest|gym)/(\d+))/problem/([A-Za-z]\d*)"
    r"|/problemset/problem/(\d+)/([A-Za-z]\d*)"
)


def is_pending(verdict: str | None) -> bool:
    if not verdict:
        return True
    return verdict.strip().upper() in PENDING_VERDICTS


def from_api(entry: dict[str, Any]) -> dict[str, Any]:
    problem = entry.get("problem", {}) or {}
    raw_verdict = entry.get("verdict")
    verdict = _API_VERDICTS.get(raw_verdict, raw_verdict) if raw_verdict else None
    passed = entry.get("passedTestCount")

    # Codeforces reports the count of passed tests; the failing one is next.
    if verdict and verdict not in ("Accepted", "Testing") and passed is not None:
        verdict_detail = f"{verdict} on test {passed + 1}"
    else:
        verdict_detail = verdict or "In queue"

    memory = entry.get("memoryConsumedBytes")
    return {
        "submission_id": entry.get("id"),
        "contest_id": entry.get("contestId"),
        "problem_index": problem.get("index"),
        "problem_name": problem.get("name"),
        "language": entry.get("programmingLanguage"),
        "verdict": verdict_detail,
        "raw_verdict": raw_verdict,
        "passed_test_count": passed,
        "time_ms": entry.get("timeConsumedMillis"),
        "memory_kb": round(memory / 1024) if isinstance(memory, int) else None,
        "testset": entry.get("testset"),
        "created_at": entry.get("creationTimeSeconds"),
        "pending": is_pending(raw_verdict),
        "url": (
            f"https://codeforces.com/contest/{entry['contestId']}"
            f"/submission/{entry['id']}"
            if entry.get("contestId") and entry.get("id")
            else None
        ),
    }


def _cell_text(cell: Tag | None) -> str:
    return cell.get_text(" ", strip=True) if cell else ""


def parse_status_table(html: str) -> list[dict[str, Any]]:
    """Parse a ``/contest/<id>/my`` or ``/submissions/<handle>`` page.

    The website is the only source that works during a running contest without
    an API key, so this is the fallback path for live verdicts.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []

    for row in soup.find_all("tr"):
        submission_id = row.get("data-submission-id")
        if not submission_id:
            continue
        cells = row.find_all("td")
        if not cells:
            continue

        verdict_span = row.find("span", class_=re.compile(r"^verdict-"))
        verdict_cell = row.find("td", class_=re.compile(r"status-cell"))
        verdict = _cell_text(verdict_span) or _cell_text(verdict_cell)

        problem_index = problem_name = None
        contest_id = None
        contest_base_path = ""
        for link in row.find_all("a", href=True):
            # Anchored so that /contest/<id>/submission/<n> cannot match.
            match = _PROBLEM_HREF.fullmatch(link["href"].split("?")[0].rstrip("/"))
            if match:
                # Groups 1-3 are the contest form, 4/5 the problemset form.
                contest_base_path = match.group(1) or ""
                raw_contest = match.group(2) or match.group(4)
                contest_id = int(raw_contest)
                problem_index = match.group(3) or match.group(5)
                text = link.get_text(" ", strip=True)
                problem_name = text.split("-", 1)[1].strip() if "-" in text else text
                break

        # Prefer the row's own submission link: on a group page it carries the
        # /group/<id> prefix that a contest-only path would drop.
        submission_href = ""
        for link in row.find_all("a", href=True):
            href = link["href"].split("?")[0].rstrip("/")
            if href.endswith(f"/submission/{submission_id}"):
                submission_href = href
                break

        time_ms = _cell_text(row.find("td", class_=re.compile("time-consumed-cell")))
        memory = _cell_text(row.find("td", class_=re.compile("memory-consumed-cell")))

        # The language column is the one right before the verdict column.
        # Compare by identity: bs4 tag equality is structural, so `in`/`index`
        # would happily match a different cell with the same markup.
        language = ""
        if verdict_cell is not None:
            position = next(
                (i for i, cell in enumerate(cells) if cell is verdict_cell), -1
            )
            if position > 0:
                language = _cell_text(cells[position - 1])

        rows.append(
            {
                "submission_id": int(submission_id),
                "contest_id": contest_id,
                "problem_index": problem_index,
                "problem_name": problem_name,
                "language": language or None,
                "verdict": verdict or "In queue",
                "raw_verdict": verdict or None,
                "time_ms": _to_int(time_ms),
                "memory_kb": _to_int(memory),
                "pending": _web_pending(verdict, verdict_span),
                # A just-created submission has no link of its own yet, so fall
                # back to the problem link's base path rather than assuming
                # /contest/<id> — that would 404 for a group contest.
                "url": (
                    f"https://codeforces.com{submission_href}"
                    if submission_href
                    else (
                        f"https://codeforces.com"
                        f"{contest_base_path or f'/contest/{contest_id}'}"
                        f"/submission/{submission_id}"
                        if contest_id
                        else None
                    )
                ),
            }
        )
    return rows


def _web_pending(verdict: str, span: Tag | None) -> bool:
    if span is not None:
        classes = span.get("class") or []
        if "verdict-waiting" in classes:
            return True
        if any(c in classes for c in ("verdict-accepted", "verdict-rejected")):
            return False
    lowered = (verdict or "").lower()
    return (not lowered) or any(
        marker in lowered
        for marker in ("in queue", "running", "testing", "pending", "submitted")
    )


def _to_int(text: str) -> int | None:
    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else None

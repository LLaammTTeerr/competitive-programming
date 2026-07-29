"""MCP server exposing Codeforces contest browsing, statements and submitting."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .api import CodeforcesApi
from .config import BASE_URL, Config, contest_base
from .session import CodeforcesError, CodeforcesSession
from .statement import parse_contest_problem_list, parse_statement
from .submissions import from_api, parse_status_table
from .submit import fetch_languages, submit_solution

mcp = FastMCP("codeforces")

config = Config.from_env()
session = CodeforcesSession(config)
api = CodeforcesApi(config)


def _fail(error: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(error)}


def _problem_url(contest_id: int, index: str, gym: bool, group_id: str = "") -> str:
    base = contest_base(contest_id, gym, group_id)
    return f"{BASE_URL}{base}/problem/{index.upper()}"


# --------------------------------------------------------------------- tools


@mcp.tool()
async def cf_whoami() -> dict[str, Any]:
    """Report which Codeforces account this server is configured to use.

    Call this first when a submit or personal-submission tool fails, to check
    whether credentials are configured and the login actually works.
    """
    status: dict[str, Any] = {
        "ok": True,
        "auth_method": "cookie"
        if config.has_cookie
        else ("password" if config.has_password else None),
        "api_key_configured": config.has_api_key,
        "configured_handle": config.handle or None,
        "default_language": config.default_language,
    }
    if not config.has_credentials:
        status["logged_in"] = False
        status["hint"] = (
            "No credentials configured. Reading contests, problems and public "
            "submissions works without them; submitting does not. To enable it, "
            "sign in at codeforces.com in a browser, copy the JSESSIONID cookie, "
            "and set CODEFORCES_COOKIE=JSESSIONID=<value> for this server."
        )
        return status
    try:
        status["logged_in_handle"] = await session.ensure_login()
        status["logged_in"] = True
    except CodeforcesError as error:
        status["logged_in"] = False
        status["error"] = str(error)
    return status


@mcp.tool()
async def cf_list_contest_problems(
    contest_id: int, gym: bool = False, group_id: str = ""
) -> dict[str, Any]:
    """List every problem in a Codeforces contest.

    Returns the contest metadata (name, phase, duration) and each problem's
    index, name, rating, tags and points. Set `gym` for gym contests.

    For a private group contest, pass `group_id` — the code from the URL
    https://codeforces.com/group/<group_id>/contest/<contest_id>. These are
    invisible to the public API, so the listing is scraped from the contest
    page and requires being signed in as a member of the group.

    Use this to discover which problems exist before fetching statements.
    """
    try:
        if not gym and not group_id:
            try:
                data = await api.contest_problems(contest_id)
                problems = [
                    {
                        "index": p.get("index"),
                        "name": p.get("name"),
                        "rating": p.get("rating"),
                        "points": p.get("points"),
                        "tags": p.get("tags", []),
                        "url": _problem_url(contest_id, p.get("index", ""), gym),
                    }
                    for p in data["problems"]
                ]
                if problems:
                    return {
                        "ok": True,
                        "source": "api",
                        "contest": data["contest"],
                        "problem_count": len(problems),
                        "problems": problems,
                    }
            except CodeforcesError:
                pass  # Running/unlisted contests: fall through to the page.

        # Gyms, group contests and running contests are only visible on the page.
        html = await session.get_text(contest_base(contest_id, gym, group_id))
        problems = parse_contest_problem_list(html)
        if not problems:
            where = f"group {group_id} contest {contest_id}" if group_id else (
                f"contest {contest_id}"
            )
            raise CodeforcesError(
                f"No problems found for {where}. It may not exist, may not have "
                "started, or may require registration/login."
                + (
                    " Group contests are private: you must be signed in as a "
                    "member of the group."
                    if group_id
                    else ""
                )
            )
        for problem in problems:
            if not problem.get("url"):
                problem["url"] = _problem_url(
                    contest_id, problem["index"], gym, group_id
                )
        return {
            "ok": True,
            "source": "web",
            "contest": {"id": contest_id, "group_id": group_id or None},
            "problem_count": len(problems),
            "problems": problems,
        }
    except Exception as error:
        return _fail(error)


@mcp.tool()
async def cf_get_problem_statement(
    contest_id: int, index: str, gym: bool = False, group_id: str = ""
) -> dict[str, Any]:
    """Read one problem's full statement, limits and sample tests.

    `index` is the problem letter, e.g. "A" or "C1". Returns the statement as
    Markdown plus the sample inputs/outputs as separate strings so they can be
    fed straight into a local test run.

    Pass `group_id` for a problem in a private group contest; see
    `cf_list_contest_problems` for where to find it.
    """
    try:
        url = f"{contest_base(contest_id, gym, group_id)}/problem/{index.upper()}"
        html = await session.get_text(url, params={"locale": "en"})
        statement = parse_statement(
            html,
            contest_id,
            index.upper(),
            f"{BASE_URL}{url}",
        )
        result = statement.to_dict()
        result["ok"] = True
        return result
    except Exception as error:
        return _fail(error)


@mcp.tool()
async def cf_list_languages(
    contest_id: int, gym: bool = False, group_id: str = ""
) -> dict[str, Any]:
    """List the language ids accepted for a contest's submit form.

    Requires credentials. Use this when a submission is rejected for an unknown
    language, or to pick the exact compiler version to submit with.
    """
    try:
        languages = await fetch_languages(session, contest_id, gym, group_id)
        if not languages:
            raise CodeforcesError(
                "The submit page did not contain a language list. You may not be "
                "registered for this contest."
            )
        return {
            "ok": True,
            "count": len(languages),
            "languages": [
                {"id": i, "name": name} for i, name in sorted(languages.items())
            ],
        }
    except Exception as error:
        return _fail(error)


@mcp.tool()
async def cf_submit_solution(
    contest_id: int,
    index: str,
    source_code: str = "",
    source_file: str = "",
    language: str = "",
    gym: bool = False,
    group_id: str = "",
    wait_for_verdict: bool = True,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Submit a solution to a contest problem. Requires credentials.

    Provide the code either inline via `source_code` or as a path via
    `source_file`. `language` accepts a Codeforces programTypeId ("89") or a
    name fragment ("GNU G++23", "Python 3"); it defaults to the server's
    configured language. With `wait_for_verdict` the call polls until the judge
    finishes and returns the final verdict.

    This performs a real submission against the account's contest history.
    """
    try:
        if source_code and source_file:
            raise CodeforcesError(
                "Pass either source_code or source_file, not both."
            )
        if source_file:
            path = Path(source_file).expanduser()
            if not path.is_file():
                raise CodeforcesError(f"Source file not found: {path}")
            source_code = path.read_text(encoding="utf-8")
        if not source_code.strip():
            raise CodeforcesError("The source code is empty.")

        submission = await submit_solution(
            session,
            contest_id,
            index,
            source_code,
            language or config.default_language,
            gym=gym,
            group_id=group_id,
        )

        if wait_for_verdict and submission.get("pending"):
            submission = await _poll_verdict(
                submission["submission_id"],
                contest_id,
                gym=gym,
                group_id=group_id,
                timeout_seconds=timeout_seconds,
                fallback=submission,
            )

        return {"ok": True, "submitted": True, **submission}
    except Exception as error:
        return _fail(error)


@mcp.tool()
async def cf_get_submission_status(
    contest_id: int = 0,
    submission_id: int = 0,
    handle: str = "",
    count: int = 10,
    gym: bool = False,
    group_id: str = "",
) -> dict[str, Any]:
    """Look up submission verdicts.

    With `contest_id` it reads your submissions for that contest (works during a
    running contest). With `submission_id` it returns just that one. With
    `handle` it reads that user's recent submissions via the public API.
    Otherwise it uses the configured account's recent submissions.
    """
    try:
        rows = await _fetch_submissions(contest_id, handle, count, gym, group_id)
        if submission_id:
            match = [r for r in rows if r.get("submission_id") == submission_id]
            if not match:
                raise CodeforcesError(
                    f"Submission {submission_id} not found in the last {count} "
                    "submissions. Try a larger count or pass its contest_id."
                )
            return {"ok": True, **match[0]}
        return {"ok": True, "count": len(rows), "submissions": rows}
    except Exception as error:
        return _fail(error)


@mcp.tool()
async def cf_wait_for_verdict(
    submission_id: int,
    contest_id: int = 0,
    timeout_seconds: int = 120,
    gym: bool = False,
    group_id: str = "",
) -> dict[str, Any]:
    """Poll a submission until the judge finishes, then return its verdict.

    Use after `cf_submit_solution` was called with `wait_for_verdict=false`, or
    to re-check a submission that was still "In queue".
    """
    try:
        result = await _poll_verdict(
            submission_id,
            contest_id,
            gym=gym,
            group_id=group_id,
            timeout_seconds=timeout_seconds,
        )
        return {"ok": True, **result}
    except Exception as error:
        return _fail(error)


# ------------------------------------------------------------------ internals


async def _fetch_submissions(
    contest_id: int, handle: str, count: int, gym: bool, group_id: str = ""
) -> list[dict[str, Any]]:
    """Read submissions, preferring the source that works in the current phase."""
    count = max(1, min(count, 100))

    if contest_id:
        # The status page is authoritative during a running contest, where the
        # API refuses to serve contest.status without an API key.
        try:
            await session.ensure_login()
            html = await session.get_text(
                f"{contest_base(contest_id, gym, group_id)}/my"
            )
            rows = parse_status_table(html)
            if rows or group_id:
                # For a group contest the status page is the only source there
                # is, so an empty page means "no submissions yet" — falling
                # through to the API would report the contest as nonexistent.
                return rows[:count]
        except CodeforcesError:
            if group_id:
                raise

        target = handle or config.handle
        if target:
            entries = await api.contest_status(contest_id, target, count=count)
            return [from_api(entry) for entry in entries]

    target = handle or config.handle
    if not target:
        raise CodeforcesError(
            "No handle available. Pass `handle`, or configure "
            "CODEFORCES_HANDLE for the server."
        )
    entries = await api.user_status(target, count=count)
    rows = [from_api(entry) for entry in entries]
    if contest_id:
        rows = [r for r in rows if r.get("contest_id") == contest_id]
    return rows


async def _poll_verdict(
    submission_id: int,
    contest_id: int,
    *,
    gym: bool = False,
    group_id: str = "",
    timeout_seconds: int = 120,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Poll until the submission leaves the judging queue or time runs out."""
    deadline = time.monotonic() + max(5, timeout_seconds)
    delay = 2.0
    latest = fallback or {"submission_id": submission_id, "pending": True}

    while True:
        try:
            rows = await _fetch_submissions(contest_id, "", 25, gym, group_id)
            match = [r for r in rows if r.get("submission_id") == submission_id]
            if match:
                latest = match[0]
                if not latest.get("pending"):
                    latest["timed_out"] = False
                    return latest
        except CodeforcesError as error:
            latest.setdefault("poll_warning", str(error))

        if time.monotonic() >= deadline:
            latest["timed_out"] = True
            latest["hint"] = (
                "Still judging when the timeout elapsed. Call "
                "cf_wait_for_verdict again to keep waiting."
            )
            return latest

        await asyncio.sleep(delay)
        delay = min(delay * 1.4, 10.0)  # Back off; judging can take a while.


def run() -> None:
    mcp.run()

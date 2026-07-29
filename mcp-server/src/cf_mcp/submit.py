"""Submitting a solution through the Codeforces web form.

There is no API method for submitting, so this drives the same form a browser
would: fetch the submit page for its csrf_token and language list, POST the
source, then confirm the submission actually landed.
"""

from __future__ import annotations

import asyncio
import difflib
import re
from typing import Any

from bs4 import BeautifulSoup

from .config import BASE_URL, contest_base
from .session import CodeforcesError, CodeforcesSession
from .submissions import parse_status_table

def submit_url(contest_id: int, gym: bool = False, group_id: str = "") -> str:
    return f"{contest_base(contest_id, gym, group_id)}/submit"


def parse_languages(html: str) -> dict[str, str]:
    """Read the ``programTypeId`` dropdown from the submit page."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", attrs={"name": "programTypeId"})
    if select is None:
        return {}
    languages = {}
    for option in select.find_all("option"):
        value = option.get("value")
        if value:
            languages[str(value)] = option.get_text(strip=True)
    return languages


def resolve_language(query: str, languages: dict[str, str]) -> str:
    """Map a language id or (partial) name onto a ``programTypeId``."""
    query = (query or "").strip()
    if not query:
        raise CodeforcesError("No language specified.")
    if query.isdigit():
        if languages and query not in languages:
            raise CodeforcesError(
                f"Language id {query} is not offered for this contest. "
                f"Available: {_describe(languages)}"
            )
        return query
    if not languages:
        raise CodeforcesError(
            "Could not read the language list from the submit page, so the "
            f"name {query!r} cannot be resolved. Pass a numeric programTypeId."
        )

    lowered = query.lower()
    exact = [i for i, name in languages.items() if name.lower() == lowered]
    if exact:
        return exact[0]

    # Prefer the newest matching entry: Codeforces lists ids in ascending age.
    contains = [i for i, name in languages.items() if lowered in name.lower()]
    if contains:
        return max(contains, key=lambda i: int(i) if i.isdigit() else 0)

    close = difflib.get_close_matches(
        lowered, [name.lower() for name in languages.values()], n=1, cutoff=0.6
    )
    if close:
        for language_id, name in languages.items():
            if name.lower() == close[0]:
                return language_id

    raise CodeforcesError(
        f"No language matching {query!r}. Available: {_describe(languages)}"
    )


def _describe(languages: dict[str, str]) -> str:
    return ", ".join(f"{i}={name}" for i, name in sorted(languages.items()))


async def fetch_languages(
    session: CodeforcesSession,
    contest_id: int,
    gym: bool = False,
    group_id: str = "",
) -> dict[str, str]:
    await session.ensure_login()
    html = await session.get_text(submit_url(contest_id, gym, group_id))
    return parse_languages(html)


def _form_errors(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    errors = []
    for span in soup.find_all("span", class_=re.compile(r"\berror\b")):
        text = span.get_text(" ", strip=True)
        if text:
            errors.append(text)
    return errors


async def submit_solution(
    session: CodeforcesSession,
    contest_id: int,
    index: str,
    source: str,
    language: str,
    *,
    gym: bool = False,
    group_id: str = "",
) -> dict[str, Any]:
    """Submit ``source`` and return the resulting submission record."""
    await session.ensure_login()
    url = submit_url(contest_id, gym, group_id)
    html, csrf = await session.csrf_for(url)

    languages = parse_languages(html)
    program_type_id = resolve_language(language, languages)

    if "submittedProblemIndex" not in html and "submittedProblemCode" not in html:
        raise CodeforcesError(
            f"The submit form is not available for contest {contest_id}. "
            "You may need to register for the contest first, or the contest "
            "may not accept submissions right now."
        )

    # Remember the newest existing submission so we can tell a fresh one apart
    # from a leftover of an earlier attempt.
    previous_id = await _latest_submission_id(
        session, contest_id, index, gym=gym, group_id=group_id
    )

    response = await session.post(
        url,
        params={"csrf_token": csrf},
        data={
            "csrf_token": csrf,
            "ftaa": session.ftaa,
            "bfaa": session.bfaa,
            "action": "submitSolutionFormSubmitted",
            "submittedProblemIndex": index.upper(),
            "programTypeId": program_type_id,
            "source": source,
            "tabSize": "4",
            "sourceCodeConfirmed": "true",
        },
        headers={"Referer": f"{BASE_URL}{url}"},
    )

    # Codeforces re-renders the form with an inline error span on failure, and
    # redirects to the status page on success.
    errors = _form_errors(response.text)
    if errors:
        raise CodeforcesError("Codeforces rejected the submission: " + "; ".join(errors))

    # A submission only counts if it is strictly newer than what was there
    # before; otherwise a silently-dropped POST would look like a success.
    submission = await _find_new_submission(
        session,
        contest_id,
        index,
        previous_id,
        gym=gym,
        group_id=group_id,
        first_page=response.text,
    )
    if submission is None:
        raise CodeforcesError(
            "The submission was sent but no new entry appeared on your status "
            "page, so it was probably not accepted. Check "
            f"{BASE_URL}{contest_base(contest_id, gym, group_id)}/my"
        )
    submission["language_used"] = languages.get(program_type_id, program_type_id)
    return submission


def _rows_for(html: str, index: str) -> list[dict[str, Any]]:
    return [
        row
        for row in parse_status_table(html)
        if (row.get("problem_index") or "").upper() == index.upper()
    ]


async def _latest_submission_id(
    session: CodeforcesSession,
    contest_id: int,
    index: str,
    *,
    gym: bool = False,
    group_id: str = "",
) -> int:
    """Highest existing submission id for this problem, or 0 if there is none."""
    try:
        html = await session.get_text(
            f"{contest_base(contest_id, gym, group_id)}/my"
        )
    except CodeforcesError:
        return 0
    rows = _rows_for(html, index)
    return max((row["submission_id"] for row in rows), default=0)


async def _find_new_submission(
    session: CodeforcesSession,
    contest_id: int,
    index: str,
    previous_id: int,
    *,
    gym: bool = False,
    group_id: str = "",
    first_page: str | None = None,
    retries: int = 4,
) -> dict[str, Any] | None:
    """Wait for a submission newer than ``previous_id`` to show up."""
    my_url = f"{contest_base(contest_id, gym, group_id)}/my"
    for attempt in range(retries):
        if attempt == 0 and first_page:
            rows = _rows_for(first_page, index)
        else:
            rows = _rows_for(await session.get_text(my_url), index)

        fresh = [row for row in rows if row["submission_id"] > previous_id]
        if fresh:
            return max(fresh, key=lambda row: row["submission_id"])
        if attempt < retries - 1:
            await asyncio.sleep(1.5)
    return None

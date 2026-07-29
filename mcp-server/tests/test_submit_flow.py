"""Exercise the submit flow against a fake Codeforces, without network access."""

from __future__ import annotations

import pytest

from cf_mcp.session import CodeforcesError
from cf_mcp.submit import submit_solution

SUBMIT_PAGE = """
<html><body>
<form action="" method="post">
  <input type="hidden" name="csrf_token" value="cafebabe"/>
  <select name="programTypeId">
    <option value="54">GNU G++17 7.3.0</option>
    <option value="89">GNU G++23 14.2 (64 bit, msys2)</option>
  </select>
  <input name="submittedProblemIndex"/>
  <textarea name="source"></textarea>
</form>
</body></html>
"""


def status_page(entries):
    rows = "".join(
        f"""
        <tr data-submission-id="{sid}">
          <td class="id-cell"><a href="/contest/100/submission/{sid}">{sid}</a></td>
          <td><span class="format-time">now</span></td>
          <td class="status-party-cell"><a href="/profile/me">me</a></td>
          <td><a href="/contest/100/problem/{index}">{index} - Problem</a></td>
          <td>GNU G++23 14.2 (64 bit, msys2)</td>
          <td class="status-cell"><span class="{cls}">{verdict}</span></td>
          <td class="time-consumed-cell">15 ms</td>
          <td class="memory-consumed-cell">200 KB</td>
        </tr>"""
        for sid, index, verdict, cls in entries
    )
    return f'<table class="status-frame-datatable">{rows}</table>'


class FakeSession:
    """Stands in for CodeforcesSession, recording what the submitter sends."""

    def __init__(self, status_sequence, post_response=SUBMIT_PAGE):
        self.ftaa = "f" * 18
        self.bfaa = "b" * 32
        self.status_sequence = list(status_sequence)
        self.post_response = post_response
        self.posts = []
        self.logged_in = False

    async def ensure_login(self):
        self.logged_in = True
        return "me"

    async def csrf_for(self, url):
        return SUBMIT_PAGE, "cafebabe"

    async def get_text(self, url, **kwargs):
        if url.endswith("/my"):
            if len(self.status_sequence) > 1:
                return self.status_sequence.pop(0)
            return self.status_sequence[0]
        return SUBMIT_PAGE

    async def post(self, url, **kwargs):
        self.posts.append(kwargs)

        class Response:
            text = self.post_response
            url = "https://codeforces.com/contest/100/my"

        return Response()


async def test_submit_returns_the_new_submission():
    before = status_page([(500, "A", "Accepted", "verdict-accepted")])
    after = status_page(
        [
            (501, "A", "In queue", "verdict-waiting"),
            (500, "A", "Accepted", "verdict-accepted"),
        ]
    )
    session = FakeSession([before, after], post_response="<html>redirected</html>")

    result = await submit_solution(session, 100, "A", "int main(){}", "GNU G++23")

    assert session.logged_in
    assert result["submission_id"] == 501  # the new one, not the pre-existing 500
    assert result["pending"] is True
    assert result["language_used"] == "GNU G++23 14.2 (64 bit, msys2)"

    sent = session.posts[0]["data"]
    assert sent["programTypeId"] == "89"
    assert sent["submittedProblemIndex"] == "A"
    assert sent["source"] == "int main(){}"
    assert sent["csrf_token"] == "cafebabe"
    assert sent["action"] == "submitSolutionFormSubmitted"


async def test_submit_surfaces_the_duplicate_code_error():
    page = status_page([(500, "A", "Accepted", "verdict-accepted")])
    duplicate = (
        '<form><span class="error for__source">'
        "You have submitted exactly the same code before</span></form>"
    )
    session = FakeSession([page], post_response=duplicate)

    with pytest.raises(CodeforcesError, match="exactly the same code before"):
        await submit_solution(session, 100, "A", "int main(){}", "89")


async def test_submit_fails_when_no_new_submission_appears():
    page = status_page([(500, "A", "Accepted", "verdict-accepted")])
    session = FakeSession([page], post_response="<html>nothing happened</html>")

    with pytest.raises(CodeforcesError, match="no new entry appeared"):
        await submit_solution(session, 100, "A", "int main(){}", "89")


async def test_submit_rejects_an_unavailable_form():
    session = FakeSession([status_page([])])
    session.csrf_for = lambda url: _form_without_index()

    with pytest.raises(CodeforcesError, match="submit form is not available"):
        await submit_solution(session, 100, "A", "code", "89")


async def _form_without_index():
    return '<form><input name="csrf_token" value="x"/></form>', "x"


async def test_submit_rejects_an_unknown_language():
    page = status_page([])
    session = FakeSession([page])

    with pytest.raises(CodeforcesError, match="No language matching"):
        await submit_solution(session, 100, "A", "code", "Brainfuck")

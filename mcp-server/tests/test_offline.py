"""Unit tests that do not touch the network."""

from __future__ import annotations

import pytest

from cf_mcp.aes import decrypt_block, decrypt_cbc, _expand_key
from cf_mcp.config import contest_base, parse_cookie_string
from cf_mcp.session import CodeforcesSession, compute_tta
from cf_mcp.statement import parse_contest_problem_list, parse_statement
from cf_mcp.submissions import from_api, is_pending, parse_status_table
from cf_mcp.submit import parse_languages, resolve_language, submit_url
from cf_mcp.session import CodeforcesError


# --------------------------------------------------------------------- crypto


def test_aes_matches_fips197_vector():
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    ciphertext = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    plain = decrypt_block(ciphertext, _expand_key(key))
    assert plain.hex() == "00112233445566778899aabbccddeeff"


def test_aes_cbc_matches_sp800_38a_vector():
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    iv = bytes.fromhex("000102030405060708090A0B0C0D0E0F")
    ciphertext = bytes.fromhex("7649abac8119b246cee98e9b12e9197d")
    assert decrypt_cbc(key, iv, ciphertext).hex() == "6bc1bee22e409f96e93d7e117393172a"


def test_tta_is_deterministic_and_in_range():
    value = compute_tta("abcdefghij12345678")
    assert value == compute_tta("abcdefghij12345678")
    assert 0 <= value < 1009


# --------------------------------------------------------------------- config


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ABC123", {"JSESSIONID": "ABC123"}),
        ("JSESSIONID=ABC", {"JSESSIONID": "ABC"}),
        (
            "JSESSIONID=ABC; cf_clearance=xyz",
            {"JSESSIONID": "ABC", "cf_clearance": "xyz"},
        ),
        ("  JSESSIONID=ABC;  ", {"JSESSIONID": "ABC"}),
        ("", {}),
    ],
)
def test_parse_cookie_string(raw, expected):
    assert parse_cookie_string(raw) == expected


# ------------------------------------------------------------------- statement

STATEMENT_HTML = """
<div class="problem-statement">
  <div class="header">
    <div class="title">B. Sample Problem</div>
    <div class="time-limit"><div class="property-title">time limit per test</div>2 seconds</div>
    <div class="memory-limit"><div class="property-title">memory limit per test</div>256 megabytes</div>
    <div class="input-file input-standard"><div class="property-title">input</div>standard input</div>
    <div class="output-file output-standard"><div class="property-title">output</div>standard output</div>
  </div>
  <div><p>Given $$$n$$$, print it.</p><ul><li>first</li><li>second</li></ul></div>
  <div class="input-specification"><div class="section-title">Input</div><p>One integer $$$n$$$.</p></div>
  <div class="output-specification"><div class="section-title">Output</div><p>Print $$$n$$$.</p></div>
  <div class="sample-tests"><div class="section-title">Example</div>
    <div class="sample-test">
      <div class="input"><div class="title">Input</div><pre>
<div class="test-example-line test-example-line-0">2</div><div class="test-example-line test-example-line-1">5</div></pre></div>
      <div class="output"><div class="title">Output</div><pre>
5
</pre></div>
    </div>
  </div>
  <div class="note"><div class="section-title">Note</div><p>Nothing to add.</p></div>
</div>
"""


def test_parse_statement_extracts_metadata_and_samples():
    statement = parse_statement(STATEMENT_HTML, 42, "B", "https://example/42/B")
    assert statement.name == "Sample Problem"
    assert statement.time_limit == "2 seconds"
    assert statement.memory_limit == "256 megabytes"
    assert statement.input_file == "standard input"
    assert len(statement.samples) == 1
    assert statement.samples[0].input == "2\n5"
    assert statement.samples[0].output == "5"


def test_parse_statement_normalises_math_and_lists():
    statement = parse_statement(STATEMENT_HTML, 42, "B", "https://example/42/B")
    assert "$n$" in statement.legend
    assert "$$$" not in statement.legend
    assert "- first" in statement.legend
    markdown = statement.to_markdown()
    assert markdown.startswith("# B. Sample Problem")
    assert "## Input" in markdown and "## Note" in markdown


def test_parse_statement_rejects_a_page_without_a_statement():
    with pytest.raises(ValueError):
        parse_statement("<html><body>nope</body></html>", 1, "A", "u")


def test_parse_contest_problem_list():
    html = """
    <table class="problems">
      <tr><th>#</th><th>Name</th></tr>
      <tr><td class="id"><a href="/contest/5/problem/A">A</a></td>
          <td><a href="/contest/5/problem/A">First</a>
              <div class="notice">1 s, 256 MB</div></td>
          <td><a href="/contest/5/status/A">&nbsp;x120</a></td></tr>
    </table>
    """
    problems = parse_contest_problem_list(html)
    assert len(problems) == 1
    assert problems[0]["index"] == "A"
    assert problems[0]["name"] == "First"
    assert problems[0]["solved_count"] == 120


def test_parse_contest_problem_list_with_unclosed_rows():
    """Codeforces emits <tr> without </tr>, which makes the parser nest rows.

    Each row must still report its own solved count, not a later row's.
    """
    html = """
    <table class="problems">
      <tr><th>#</th><th>Name</th></tr>
      <tr><td class="id"><a href="/gym/9/problem/A">A</a></td>
          <td><a href="/gym/9/problem/A">First</a><div class="notice">0.3 s, 1024 MB</div></td>
          <td class="act"><a href="/gym/9/submit/A">submit</a></td>
          <td><a href="/gym/9/status/A">&nbsp;x2622</a></td>
      <tr><td class="id"><a href="/gym/9/problem/B">B</a></td>
          <td><a href="/gym/9/problem/B">Second</a><div class="notice">0.6 s, 1024 MB</div></td>
          <td class="act"><a href="/gym/9/submit/B">submit</a></td>
          <td><a href="/gym/9/status/B">&nbsp;x413</a></td>
    </table>
    """
    problems = parse_contest_problem_list(html)
    assert [p["index"] for p in problems] == ["A", "B"]
    assert [p["solved_count"] for p in problems] == [2622, 413]
    assert problems[0]["limits"] == "0.3 s, 1024 MB"


# ----------------------------------------------------------------- submissions


def test_from_api_reports_the_failing_test_number():
    row = from_api(
        {
            "id": 7,
            "contestId": 1900,
            "problem": {"index": "A", "name": "X"},
            "verdict": "WRONG_ANSWER",
            "passedTestCount": 3,
            "timeConsumedMillis": 30,
            "memoryConsumedBytes": 2048,
            "programmingLanguage": "GNU G++23",
        }
    )
    assert row["verdict"] == "Wrong answer on test 4"
    assert row["memory_kb"] == 2
    assert row["pending"] is False
    assert row["url"].endswith("/contest/1900/submission/7")


def test_from_api_marks_queued_submissions_pending():
    row = from_api({"id": 8, "contestId": 1, "problem": {}, "verdict": None})
    assert row["pending"] is True
    assert row["verdict"] == "In queue"


def test_from_api_accepted_has_no_test_suffix():
    row = from_api(
        {
            "id": 9,
            "contestId": 1,
            "problem": {"index": "A"},
            "verdict": "OK",
            "passedTestCount": 40,
        }
    )
    assert row["verdict"] == "Accepted"


@pytest.mark.parametrize(
    "verdict,pending",
    [("OK", False), (None, True), ("TESTING", True), ("WRONG_ANSWER", False)],
)
def test_is_pending(verdict, pending):
    assert is_pending(verdict) is pending


STATUS_HTML = """
<table class="status-frame-datatable">
<tr data-submission-id="123">
  <td class="id-cell"><a href="/contest/1900/submission/123">123</a></td>
  <td><span class="format-time">Nov/26/2023</span></td>
  <td class="status-party-cell"><a href="/profile/someone">someone</a></td>
  <td><a href="/contest/1900/problem/A">A - Cover in Water</a></td>
  <td>GNU G++23 14.2</td>
  <td class="status-cell status-small"><span class="verdict-rejected">Wrong answer on test 2</span></td>
  <td class="time-consumed-cell">30 ms</td>
  <td class="memory-consumed-cell">100 KB</td>
</tr>
<tr data-submission-id="124">
  <td class="id-cell"><a href="/contest/1900/submission/124">124</a></td>
  <td><span class="format-time">Nov/26/2023</span></td>
  <td class="status-party-cell"><a href="/profile/someone">someone</a></td>
  <td><a href="/contest/1900/problem/B">B - Laura</a></td>
  <td>Python 3.8</td>
  <td class="status-cell status-small"><span class="verdict-waiting">In queue</span></td>
  <td class="time-consumed-cell">0 ms</td>
  <td class="memory-consumed-cell">0 KB</td>
</tr>
</table>
"""


def test_parse_status_table_ignores_the_submission_link():
    """The row links to both the submission and the problem; only one is a problem."""
    rows = parse_status_table(STATUS_HTML)
    assert rows[0]["problem_index"] == "A"  # not "s" from /submission/123
    assert rows[0]["contest_id"] == 1900


def test_parse_status_table():
    rows = parse_status_table(STATUS_HTML)
    assert len(rows) == 2

    first = rows[0]
    assert first["submission_id"] == 123
    assert first["contest_id"] == 1900
    assert first["problem_index"] == "A"
    assert first["problem_name"] == "Cover in Water"
    assert first["verdict"] == "Wrong answer on test 2"
    assert first["language"] == "GNU G++23 14.2"
    assert first["time_ms"] == 30
    assert first["memory_kb"] == 100
    assert first["pending"] is False

    assert rows[1]["pending"] is True


# --------------------------------------------------------------------- submit

SUBMIT_HTML = """
<form><input name="csrf_token" value="deadbeef"/>
<select name="programTypeId">
  <option value="54">GNU G++17 7.3.0</option>
  <option value="89">GNU G++23 14.2 (64 bit, msys2)</option>
  <option value="31">Python 3.8.10</option>
</select>
<input name="submittedProblemIndex"/></form>
"""


def test_parse_languages():
    languages = parse_languages(SUBMIT_HTML)
    assert languages["89"] == "GNU G++23 14.2 (64 bit, msys2)"
    assert len(languages) == 3


def test_resolve_language_by_id_name_and_fragment():
    languages = parse_languages(SUBMIT_HTML)
    assert resolve_language("89", languages) == "89"
    assert resolve_language("GNU G++23", languages) == "89"
    assert resolve_language("python 3", languages) == "31"
    assert resolve_language("GNU G++17 7.3.0", languages) == "54"


def test_resolve_language_rejects_unknown():
    languages = parse_languages(SUBMIT_HTML)
    with pytest.raises(CodeforcesError):
        resolve_language("COBOL", languages)
    with pytest.raises(CodeforcesError):
        resolve_language("999", languages)


def test_csrf_extraction():
    assert CodeforcesSession.extract_csrf(SUBMIT_HTML) == "deadbeef"
    meta = '<meta name="X-Csrf-Token" content="abc123"/>'
    assert CodeforcesSession.extract_csrf(meta) == "abc123"
    assert CodeforcesSession.extract_csrf("<html></html>") is None


def test_logged_in_handle_detection():
    logged_out = '<div class="lang-chooser"><a href="/enter">Enter</a></div>'
    assert CodeforcesSession.logged_in_handle(logged_out) is None

    logged_in = (
        '<div class="lang-chooser"><div>'
        '<a href="/profile/tourist">tourist</a>\n | \n'
        '<a href="/settings">Settings</a> | <a href="/logout?x=1">Logout</a>'
        "</div></div>"
    )
    assert CodeforcesSession.logged_in_handle(logged_in) == "tourist"

    # Codeforces now prefixes the logout link with a per-session token.
    token_prefixed = logged_in.replace(
        'href="/logout?x=1"', 'href="/b5b31668c5f716d13f6d683b38d8d0f3/logout"'
    )
    assert CodeforcesSession.logged_in_handle(token_prefixed) == "tourist"


def test_contest_base_paths():
    assert contest_base(1873) == "/contest/1873"
    assert contest_base(1873, gym=True) == "/gym/1873"
    assert contest_base(705790, group_id="434yrzK1nB") == (
        "/group/434yrzK1nB/contest/705790"
    )
    # A group contest is never also a gym contest; the group path wins.
    assert contest_base(705790, gym=True, group_id="434yrzK1nB") == (
        "/group/434yrzK1nB/contest/705790"
    )


def test_submit_url_follows_contest_base():
    assert submit_url(1873) == "/contest/1873/submit"
    assert submit_url(1873, gym=True) == "/gym/1873/submit"
    assert submit_url(705790, group_id="434yrzK1nB") == (
        "/group/434yrzK1nB/contest/705790/submit"
    )


def test_parse_contest_problem_list_keeps_group_urls():
    """Group pages link problems by their full group path; keep it verbatim."""
    html = (
        '<table class="problems">'
        "<tr><th>#</th><th>Name</th></tr>"
        '<tr><td class="id">A</td><td>'
        '<a href="/group/434yrzK1nB/contest/705790/problem/A">Test</a>'
        '<div class="notice">courses.inp / courses.out 1 s, 512 MB</div>'
        '</td><td><a href="/group/434yrzK1nB/contest/705790/status/A">x5</a></td>'
        "</tr></table>"
    )
    problems = parse_contest_problem_list(html)
    assert len(problems) == 1
    assert problems[0]["index"] == "A"
    assert problems[0]["url"] == (
        "https://codeforces.com/group/434yrzK1nB/contest/705790/problem/A"
    )
    assert problems[0]["solved_count"] == 5
    assert "courses.inp" in problems[0]["limits"]


def test_status_table_reads_group_contest_problem_links():
    """Group status pages prefix problem hrefs with /group/<id>.

    `_rows_for` filters submissions by problem_index, so a miss here makes a
    successful group submission look like it never landed.
    """
    html = (
        '<table class="status-frame-datatable">'
        "<tr><th>#</th></tr>"
        '<tr data-submission-id="383774426">'
        '<td><a href="/group/434yrzK1nB/contest/705790/submission/383774426">'
        "383774426</a></td>"
        '<td><a href="/group/434yrzK1nB/contest/705790/problem/B">B - Test</a></td>'
        '<td class="status-cell"><span class="verdict-accepted">Accepted</span></td>'
        "</tr></table>"
    )
    rows = parse_status_table(html)
    assert len(rows) == 1
    assert rows[0]["problem_index"] == "B"
    assert rows[0]["contest_id"] == 705790
    assert rows[0]["submission_id"] == 383774426
    # The URL must keep the group prefix, or it 404s for a private contest.
    assert rows[0]["url"] == (
        "https://codeforces.com/group/434yrzK1nB/contest/705790"
        "/submission/383774426"
    )


def test_status_row_without_submission_link_keeps_group_path():
    """A just-submitted row has no link of its own; the URL must still be
    rebuilt from the group path, not a bare /contest/<id>."""
    html = (
        '<table class="status-frame-datatable">'
        '<tr data-submission-id="383810912">'
        "<td>383810912</td>"
        '<td><a href="/group/434yrzK1nB/contest/705790/problem/C">C - X</a></td>'
        '<td class="status-cell"><span class="verdict-waiting">In queue</span></td>'
        "</tr></table>"
    )
    rows = parse_status_table(html)
    assert rows[0]["url"] == (
        "https://codeforces.com/group/434yrzK1nB/contest/705790"
        "/submission/383810912"
    )
    assert rows[0]["problem_index"] == "C"


def test_status_row_plain_contest_url_unchanged():
    html = (
        '<table class="status-frame-datatable">'
        '<tr data-submission-id="55">'
        "<td>55</td>"
        '<td><a href="/contest/1873/problem/A">A - Y</a></td>'
        '<td class="status-cell"><span class="verdict-accepted">Accepted</span></td>'
        "</tr></table>"
    )
    rows = parse_status_table(html)
    assert rows[0]["url"] == "https://codeforces.com/contest/1873/submission/55"
    assert rows[0]["contest_id"] == 1873

# cf-mcp — a Codeforces MCP server

Gives an MCP client (Claude Code, Claude Desktop, …) four things:

1. **Get all problems from a contest** — `cf_list_contest_problems`
2. **Read a problem statement** — `cf_get_problem_statement`
3. **Submit a solution** — `cf_submit_solution`
4. **Read submission status** — `cf_get_submission_status` / `cf_wait_for_verdict`

Codeforces only offers a read-only public API, and it covers none of the
submitting or statement text. So this server uses the API where it exists
(contest metadata, problem lists, verdicts) and drives the website for the rest
(statements, submitting, live-contest status), including the anti-bot `RCPC`
challenge and the `csrf_token` handling that requires.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Configure

**Reading contests, statements and public submissions needs no credentials.**
Submitting and reading your own submissions does.

### Authentication: use a session cookie, not a password

Codeforces puts `/enter` behind a Cloudflare browser challenge, so scripted
password login cannot work from a plain HTTP client — verified against the live
site, which answers `403 "Just a moment..."` no matter how browser-like the
request headers are. Every other endpoint (`/contest/…/submit`,
`/contest/…/my`, statements) is *not* challenged, so an existing session cookie
is all that is needed.

To get one:

1. Sign in at <https://codeforces.com> in your browser.
2. Open DevTools → **Application** (Chrome) or **Storage** (Firefox) → Cookies →
   `https://codeforces.com`.
3. Copy the value of **`JSESSIONID`**.
4. Set `CODEFORCES_COOKIE=JSESSIONID=<that value>`.

The cookie is long-lived if you ticked "remember me", but it does expire —
when it does, `cf_whoami` reports `logged_in: false` and you repeat the steps.

| Variable | Required for | Notes |
| --- | --- | --- |
| `CODEFORCES_COOKIE` | submitting, own submissions | `JSESSIONID=<value>`; a bare value works too |
| `CODEFORCES_HANDLE` | recommended | your handle; used for `user.status` lookups |
| `CODEFORCES_PASSWORD` | optional | best-effort login, normally blocked by Cloudflare |
| `CODEFORCES_API_KEY` | private/running-contest API reads | from <https://codeforces.com/settings/api> |
| `CODEFORCES_API_SECRET` | as above | |
| `CF_MCP_DEFAULT_LANGUAGE` | optional | default `GNU G++23` |
| `CF_MCP_STATE_DIR` | optional | cookie cache, default `~/.cache/cf-mcp` |

The session is cached (mode `0600`) under the state dir, so the server is not
re-authenticating on every call.

### Register with Claude Code

```bash
claude mcp add codeforces \
  --env CODEFORCES_HANDLE=your_handle \
  --env CODEFORCES_COOKIE=JSESSIONID=your_cookie_value \
  -- /home/lam_n/Projects/CF_Solver/.venv/bin/python -m cf_mcp
```

Or in `claude_desktop_config.json` / `.mcp.json`:

```json
{
  "mcpServers": {
    "codeforces": {
      "command": "/home/lam_n/Projects/CF_Solver/.venv/bin/python",
      "args": ["-m", "cf_mcp"],
      "env": {
        "CODEFORCES_HANDLE": "your_handle",
        "CODEFORCES_COOKIE": "JSESSIONID=your_cookie_value"
      }
    }
  }
}
```

## Tools

### `cf_list_contest_problems(contest_id, gym=False, group_id="")`
Contest metadata plus every problem's index, name, rating, tags and points.
Uses the standings API for public contests, and falls back to scraping the
contest page for gyms, group contests and contests that are still running.

### `cf_get_problem_statement(contest_id, index, gym=False, group_id="")`
Full statement as Markdown (math normalised from `$$$x$$$` to `$x$`), time and
memory limits, and every sample test as a separate `{input, output}` pair ready
to pipe into a local run. Also returns `sections` — the statement's titled
blocks (Input, Output, Interaction, Scoring, Note…) in page order — and
`interactive`, true when the problem talks to the judge instead of reading a
fixed input; when it is, flush after every write and treat the sample as a
dialogue transcript, not a runnable test file.

### `cf_list_languages(contest_id, gym=False, group_id="")`
The exact `programTypeId` values that contest's submit form offers. Language
ids change over time, so this reads them live rather than trusting a table.

### `cf_submit_solution(contest_id, index, source_code|source_file, language, gym=False, group_id="", wait_for_verdict=True)`
Submits, then polls until judged. `language` takes an id (`"89"`) or a name
fragment (`"GNU G++23"`, `"Python 3"`). Real submissions against your account.

### `cf_get_submission_status(contest_id=, submission_id=, handle=, count=10, group_id="")`
Verdict, failing test number, time and memory. Reads `/contest/<id>/my` when a
contest is given (works mid-contest), otherwise the public `user.status` API.

### `cf_wait_for_verdict(submission_id, contest_id=, timeout_seconds=120, group_id="")`
Polls a pending submission with backoff until the judge finishes.

Every tool returns `{"ok": false, "error": "..."}` rather than raising, so the
model can read the failure and correct itself.

### Private group contests

Contests inside a group live at
`https://codeforces.com/group/<group_id>/contest/<contest_id>` and are invisible
to the public API — `contest.standings` reports nothing for them regardless of
credentials. Pass the group code from that URL as `group_id` to any tool above
and it scrapes the group pages instead:

```
cf_list_contest_problems(705790, group_id="434yrzK1nB")
cf_get_problem_statement(705790, "A", group_id="434yrzK1nB")
```

This requires being signed in as a member of the group, so `CODEFORCES_COOKIE`
must be set even for reads that are anonymous on the public site. `group_id`
takes precedence over `gym`.

## Typical agent loop

```
cf_list_contest_problems(2000)          → pick problem C
cf_get_problem_statement(2000, "C")     → statement + samples to test against
… write and test a solution locally …
cf_submit_solution(2000, "C", source_file="sol.cpp", language="GNU G++23")
                                        → submits, polls, returns the verdict
```

## Tests

```bash
.venv/bin/python -m pytest -q
```

56 tests, no network required: AES against the NIST vectors, statement and
status-table parsing, language resolution, and the whole submit flow against a
fake Codeforces.

## Implementation notes

Things that are non-obvious about Codeforces and are handled here:

- **Group contests bypass the API entirely.** Every `group_id` call is a page
  scrape against the signed-in session, so it breaks if Codeforces changes its
  markup — unlike the API paths, which are contractual.
- **Standings API is picky.** `contest.standings` only serves non-gym contests
  to anonymous requests carrying *no* extra parameters, so the problem list is
  fetched with a bare query and falls back to scraping for gyms.
- **Unclosed `<tr>`.** Contest tables emit `<tr>` with no `</tr>`, so an HTML
  parser nests every row inside the previous one. Row cells are read with
  `recursive=False` or each problem reports the *last* row's solved count.
- **Two sample-test markups.** Newer problems wrap each sample line in a
  `<div class="test-example-line">`; older ones use plain text in the `<pre>`.
- **Verdicts need the failing test number.** The API reports `passedTestCount`,
  so "Wrong answer" becomes "Wrong answer on test 4".
- **Submission confirmation.** The newest submission id is recorded *before*
  POSTing, and the result must be strictly newer — otherwise a silently dropped
  submission would look like a success.
- Submitting identical source twice is rejected by Codeforces ("You have
  submitted exactly the same code before"); that error is passed through.
- Polling backs off from 2s to 10s, to be considerate to the judge.

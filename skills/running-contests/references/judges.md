# Judge registry

Per-judge notes for [running-contests](../SKILL.md): how a judge's MCP binds to
the four capabilities, and the quirks worth knowing before you submit anything.

**The loaded tool schema always wins over this file.** These entries are a
starting point and a place to record quirks — they are not authoritative about a
server's current parameters. Discover the real schema with `ToolSearch`, per
[the capability contract](../SKILL.md#judge-interface--the-capability-contract).

---

## Codeforces

**MCP server:** `codeforces` — bundled with this plugin, tools prefixed `cf_`.
**Domains:** `codeforces.com`, including `/gym/…` and
`/group/<group_id>/contest/<contest_id>`.

| Capability | Tool |
|---|---|
| list-problems | `cf_list_contest_problems(contest_id, gym, group_id)` |
| get-statement | `cf_get_problem_statement(contest_id, index, gym, group_id)` |
| submit | `cf_submit_solution(contest_id, index, source_code or source_file, language, gym, group_id, wait_for_verdict)` |
| poll-verdict | `cf_wait_for_verdict(submission_id, contest_id, …)`, or `cf_get_submission_status(…)` for a one-off check |

Quirks:

- **Contest kinds.** A regular round needs only `contest_id`. A gym contest
  needs `gym=True`. A private group contest needs `group_id` — the code in
  `codeforces.com/group/<group_id>/contest/<contest_id>` — and an account that
  belongs to the group.
- **Languages** are numeric `programTypeId`s, but the submit tool also accepts a
  name fragment such as `"GNU G++23"`. Prefer the fragment. When a submission is
  rejected for an unknown language, call `cf_list_languages(contest_id)` for the
  ids this contest actually offers. These ids are Codeforces-specific.
- **Verdicts** come back already normalised to readable strings — `Accepted`,
  `Wrong answer on test 4`, `Time limit exceeded on test 12`, `Partial` — with
  the raw API value in `raw_verdict` and a `pending` flag while judging.
- **Scoring** on regular rounds is the ICPC penalty model: rank by problems
  solved, ties broken by time plus a fixed charge per rejected attempt, counted
  over solved problems only. Some rounds use points that decay with time; read
  the contest page when the distinction matters.
- **Interactive problems** carry an `Interaction` section, and
  `cf_get_problem_statement` returns `interactive: true` for them. See
  [Interactive problems](../SKILL.md#interactive-problems).
- **Credentials.** Reading is anonymous; submitting needs `CODEFORCES_HANDLE`
  and `CODEFORCES_COOKIE`. When a submit fails, call `cf_whoami()` first — it
  reports whether credentials are configured and whether the login works.

---

## Judge not listed

No entry means no recorded quirks — not that the judge is unsupported. Run the
discovery procedure anyway: if an MCP for that judge is installed, `ToolSearch`
finds its tools and you bind them the same way. If nothing turns up, use
[degraded mode](../SKILL.md#when-no-mcp-covers-this-judge).

When you learn something durable about a new judge — its scoring rule, its
language ids, a parameter that isn't obvious — add an entry with the template
below.

## Entry template

```markdown
## <Judge name>

**MCP server:** `<server name>` — <where it comes from>.
**Domains:** `<domain>`, <any contest URL shapes>.

| Capability | Tool |
|---|---|
| list-problems | `<tool(args)>` |
| get-statement | `<tool(args)>` |
| submit | `<tool(args)>` |
| poll-verdict | `<tool(args)>` |

Quirks:

- **Scoring.** <how rank and penalty actually work here>
- **Languages.** <how the submit tool names C++>
- **Verdicts.** <the strings this judge returns>
- **Credentials.** <what must be configured to submit>
```

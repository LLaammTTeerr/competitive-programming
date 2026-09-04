---
name: uploading-to-polygon
description: >
  Use ONLY when the user explicitly asks to upload, push, ship or re-sync a
  finished problem package to Codeforces Polygon — upload this to polygon,
  push the package to polygon, sync it to polygon, put it on polygon. Drives
  the plugin's own bundled `polygon` MCP server (tools `polygon_*`): create
  the problem, set limits, write the statement, push validator, generators
  and checker, upload every solution with its expected verdict, save the
  generator script and the samples, wire subtasks into groups and points,
  commit, and grant the coordinators read access. It is the one opt-in step
  of the setting pipeline and never runs on its own — not at the end of
  competitive-programming:creating-problems, not after a review. It uploads
  a package that is already finished and never regenerates, repairs or
  re-reviews one.
---

# Uploading to Polygon

Ship a finished package to [Polygon](https://polygon.codeforces.com) through
this plugin's **own** bundled MCP server. The upload mirrors what
`problem.json` and the files on disk already say, and a package that is not
finished goes back to a sibling skill rather than being patched up on the way
out. **The one file this skill writes is `polygon.json`** — the record of
which Polygon problem the package owns. It writes nothing else, and nothing
in it edits `problem.json`, the statement, the tests or the solutions.

**This skill runs only when asked for.** Every other setting skill is part of
a pipeline that reaches an end; this one starts after that end, publishes to
an account that owns real problems, and is not something to do helpfully.

## Am I the right skill?

| If it's really about | Use |
|---|---|
| Finishing the package first — any phase still incomplete | `competitive-programming:creating-problems` |
| Auditing a package that has not been signed off yet | `competitive-programming:reviewing-problems` |
| The statement prose itself, in the `.tex` | `competitive-programming:writing-statements` |
| Test data, groups, the generator families | `competitive-programming:preparing-tests` |
| Publishing a package the user has explicitly asked to upload | this skill |

## Bootstrap

`$BASE` is not an environment variable the harness sets — it is not exported
into a shell, only into MCP config. What you actually have is the line **"Base
directory for this skill" printed in this skill's own invocation preamble.
Substitute that literal path for `BASE` below:

```bash
BASE="<the path from this skill's own 'Base directory for this skill' line>"
PLUGIN_ROOT="$BASE/../.."
PROBLEM="<absolute path to the problem directory you are uploading>"
TESTLIB="$(bash "$PLUGIN_ROOT/tools/bootstrap_testlib.sh")"
cd "$PLUGIN_ROOT"
PREFS="$(python3 -m tools.preferences)"
```

`$PREFS` is the effective `preferences.toml` as JSON — the standing answers
to the questions this pipeline would otherwise put to a human on every
problem. Read it before asking anything it already answers, and treat a
value of `"ask"` as the file declining to decide: that one is genuinely
open, so ask it. Anything said in this conversation still wins over the
file, for this problem only.

The keys this skill reads: `polygon.statement_language` (which language the
statement goes up as), `polygon.notify_on_commit` (whether the commit emails
the problem's other authors), `polygon.grant_codeforces_read` (whether to
hand the `codeforces` login read access at the end).

Every `python3 -m tools.*` command below is a module inside `tools/`, only
importable with `PLUGIN_ROOT` as the working directory — `cd` there first, or
every invocation fails with `ModuleNotFoundError` before it does anything.
**The working directory stays `$PLUGIN_ROOT` for everything below**, and
`$PROBLEM` is passed as an argument, never `cd`'d into.

## Secrets never reach you

The server reads its credentials from its own environment and signs every
request itself. **Never** read a config file for them, print them, ask the
user to paste them into the conversation, or reimplement the signature. If a
tool reports the credentials are missing, stop and point the user at
[`mcp-server/README.md`](../../mcp-server/README.md) — that is the whole of
your setup advice.

## Bind the tools before you call one

The server's tools are not in your catalogue until you load them: call
`ToolSearch` with a `select:` list of the names each phase needs, and **read
the loaded schema**, which always wins over anything written down.
[`references/polygon-tools.md`](references/polygon-tools.md) lists all
thirty-five with the API method each wraps and the failure shape they share;
it is a map, not an authority.

Never retry an identical request, and never invent a tool the server does not
have. If the server is not connected, say so and stop: there is no degraded
mode here, because a half-uploaded problem is worse than none.

## Phase 0 — preflight, and the one blocking gate

**Both preconditions, run fresh, in this conversation.** Not remembered from
earlier in the session:

```bash
python3 -m tools.package_status "$PROBLEM" "$TESTLIB"
python3 -m tools.review_checks "$PROBLEM" "$PROBLEM/<name>.tex" "$TESTLIB"
```

`tools.package_status` must print `complete` — every phase `[x]`, no `next:`
line — and `tools.review_checks` must exit 0. Either one short of that and
you **stop**: send the package back to `creating-problems` or
`reviewing-problems`. Upload is not a way to finish a package, and a Polygon
problem built from one that drifted carries the drift into a contest.
**REQUIRED:** invoke `superpowers:verification-before-completion` and show
both commands' output and exit codes.

Then read `problem.json`, the single source of truth for every number below.

**Already on Polygon?** Read the package's Polygon record:

```bash
python3 -c "import sys;from tools.polygon_ref import load;print(load(sys.argv[1]))" "$PROBLEM"
```

`None` means the package has never been uploaded — go on to Phase 1. Anything
else means it has, and you ask, and do not proceed until answered:
**re-sync** the problem the record names — uploading only the files whose
mtime is newer than its `committed_at`, the RFC 3339 timestamp of the last
revision this skill committed, then committing again — or **stop**. There is
no third answer. On a re-sync, **skip Phase 1 entirely**: the problem already
exists, and `problem_id` for every phase below is the record's `id`. **Never
create a second Polygon problem for a package that already has one**: no
tidying afterwards undoes the id the user's collaborators have already
bookmarked. A record that fails to load is a `PolygonRefError` naming the
field — report it and stop; do not guess around it.

The record is `polygon.json`, beside `problem.json` rather than inside it,
and that placement is load-bearing. `problem.json` is matrix evidence: the
two gates above compare it against `invocation.json` and call the matrix
stale when it is newer. A Polygon id written into `problem.json` would fail
the gate this phase has just passed, on every run after the first, over a
package nothing had changed. `polygon.json` is not walked by either gate, so
writing it costs nothing.

## Phase 1 — create, and record where it went

1. `polygon_whoami()` — proves the key, the secret and the clock.
2. `polygon_problems_list(name=<problem.json name>)`. A live problem with
   that name and no `polygon.json` in the package means someone else already
   created it, or a previous run failed after create and before recording.
   **Stop and report the id** — do not adopt it silently and do not create a
   second.
3. `polygon_problem_create(name=<problem.json name>)`. The Polygon name is
   `problem.json`'s `name`, the ASCII slug; the human title is the
   statement's `name` in Phase 3, and they are not the same thing.
4. **Record it, immediately.** `problem.create` returns `id` and `owner` and
   **no address**, so ask the user for the problem's URL from their browser
   and write all three to `$PROBLEM/polygon.json`:

```bash
python3 -c "import sys;from tools.polygon_ref import PolygonRef,save;save(sys.argv[1],PolygonRef(int(sys.argv[2]),sys.argv[3],sys.argv[4]))" \
  "$PROBLEM" 123456 "<owner, from the create result>" "<url, from the user>"
```

`owner` is whatever the create result says — never a name from this skill,
this repository, or a previous problem. Write it before anything else goes
up: a create that is not recorded is the state Phase 1 step 2 has to stop
on next time. `committed_at` stays unset until Phase 8; the module refuses
anything it could not read back, so a `PolygonRefError` here means the
values are wrong, not the file.

## Phase 2 — limits

`polygon_problem_update_info(problem_id, time_limit_ms=<limits.time_ms_published>,
memory_limit_mb=<limits.memory_mb>)`. The published time limit, not
`time_ms_computed` — the statement's promise is what contestants are judged
against.

For `io.input == "stdin"`, **leave `input_file` and `output_file` unset**: a
new Polygon problem is stdin/stdout already, an empty argument means "leave
it alone", and passing the literal string would create a file named `stdin`.
For file IO, pass `io.input` and `io.output` verbatim.

## Phase 3 — statement

`polygon_save_statement(problem_id, lang=<polygon.statement_language>, …)`,
with the text taken from the package's `.tex`, in that language. Polygon's
markup, not the vnolymp macros: `$$$x$$$` for inline math, `$$…$$` for
display math — never `\[…\]`.

| package | Polygon field |
|---|---|
| the title in the statement's language | `name` |
| story and task | `legend` |
| `\InputFile` | `input` |
| `\OutputFile` | `output` |
| the subtask table, `format == "oi"` only | `scoring` |
| `\Explanation` | `notes` |

Samples do **not** go in `legend` or `notes`; they arrive in Phase 6 as tests
marked for the statement. For `format == "icpc"`, leave `scoring` out
entirely. Figures the statement includes go up with
`polygon_save_statement_resource`.

## Phase 4 — checker, validator, generators

`polygon_save_file` takes `path=`, resolved under `POLYGON_MCP_ROOT`, and a
`path=` outside that root is refused by design. The server reads the root from
the environment of the shell that **launched Claude Code**, so if it is unset
the fix is to export it there and restart — exporting it in some other
terminal mid-session changes nothing, because the server process is already
running without it. Pass `content=` inline only for something genuinely small
— a few KB — never as a way around the guard.

1. **Checker.** `checker.kind == "stock"` → `polygon_set_checker(problem_id,
   "std::<checker.name>.cpp")`; the package spells stock names bare (`ncmp`,
   `wcmp`, `rcmp6`) and Polygon spells them `std::ncmp.cpp`. `custom` →
   `polygon_save_file(file_type="source", name=<checker.name>, path=…)`
   first, then `polygon_set_checker` with that same name.
2. **`files/constraints.h`** as `file_type="resource"` — the generated header
   the validator includes. A resource file is placed beside the sources at
   compile time, which is exactly what `#include "constraints.h"` needs.
   Upload it **before** the validator so that compile finds it, and never
   edit the package's own `files/validator.cpp` to work around it.
3. **Validator.** `polygon_save_file(file_type="source",
   name="validator.cpp", path=…)`, then
   `polygon_set_validator(problem_id, "validator.cpp")`.
4. **Generators.** Every `files/gen-*.cpp` as `file_type="source"` under its
   own name. Nothing binds them; the script names them. `testlib.h` is
   Polygon's own — do not upload it.

## Phase 5 — solutions, with the tags they were measured at

**The model solution goes up first, before any test.** Polygon computes every
test's answer by running the `MA` solution, so `tests/*/*.a` is never
uploaded — those are local evidence, and uploading one would stand a second,
unchecked answer beside the one Polygon derives.

Then every other `solutions/*.cpp`, one
`polygon_save_solution(problem_id, name=<basename>, tag=…, path=…)` apiece,
with the Polygon tag its own `@tag` metadata block maps to:

| `@tag` | Polygon |
|---|---|
| `main` | `MA` |
| `accepted` | `OK` |
| `wrong-answer` | `WA` |
| `time-limit-exceeded` | `TL` |
| `time-limit-exceeded-or-accepted` | `TO` |
| `memory-limit-exceeded` | `ML` |
| `presentation-error` | `PE` |
| `failed` | `RJ` |

The mapping is total over the package's tag set (`scan_solutions.TAGS`) —
never invent a tag, and never promote a measured verdict. A solution that is
correct but only just fits the limit is `TO`, not `OK`: a verified build runs
every solution and fails when `OK` times out. Exactly one solution carries
`MA`; `tools.review_checks` has already guaranteed that.

## Phase 6 — tests, then samples last

**Tests go up as the package's generator script, not as uploaded files.**
Each line is the exact `argv` that produced the corresponding
`tests/<group>/NN.in` — the generators are pure functions of their command
line, so the same invocation reproduces the same bytes forever.

**If the exact argv is not recoverable, STOP.** Say plainly that the suite
has to be regenerated with its commands recorded and then re-reviewed, and
end the run. Do not guess an invocation, and do not regenerate anything here:
a generator run inside this skill produces test data nothing has validated,
reviewed, or run the matrix against.

1. Count the samples, `S`. Their indices are `1..S`, so every script line
   ends `> S+1`, `> S+2`, … — explicit numbers, never `> $`, and no `#`
   comment lines, which Polygon's script parser rejects.
2. `polygon_save_script(problem_id, "tests", source=<the whole script>)`. It
   replaces the script entirely; there is no appending.
3. **Samples last**, as manual tests at `1..S`:
   `polygon_save_test(problem_id, "tests", test_index=i, path=<the .in>,
   use_in_statements=true)`. Leave `output_for_statements` unset — the shown
   answer is then the one Polygon computes from `MA`, which is the point of
   Phase 5's ordering. Samples carry no group and no points.
4. Read back with `polygon_tests(problem_id, no_inputs=true)`: indices `1..S`
   marked `useInStatements`, one test per script line above them.

## Phase 7 — groups and points, `format == "oi"` only

For `format == "icpc"`, skip this phase: groups and points stay disabled and
the problem is scored all-or-nothing.

For `format == "oi"`:

1. `polygon_enable_groups(problem_id, "tests", true)` and
   `polygon_enable_points(problem_id, true)`. Both come first — a test
   cannot carry a group or points until they are on.
2. **One group per subtask, named with the subtask's own id** (`g1`, `g2`, …
   from `problem.json`). Polygon hands the group name to the validator, so a
   group renamed to `1`, `2`, … is only safe if that validator accepts the
   bare-number spelling too — and when it does not, the package build fails
   with the validator's own `FAIL unknown group` and nothing else explains
   why. The subtask id is the spelling every part of the package agrees on;
   keep it.
3. Give each test its group and its points in the same
   `polygon_save_test(problem_id, "tests", test_index=…, test_group=…,
   test_points=…)` call — both together, with no `test_input`, so the script
   line is left alone. A group comes into existence by a test naming it, and
   `subtasks[].points` is split across that group's tests to sum **exactly**
   to the subtask's points.
4. Then the policies:
   `polygon_save_test_group(problem_id, "tests", group=<subtask id>,
   points_policy="COMPLETE_GROUP", dependencies=<subtasks[].depends_on>)` —
   only after the tests exist, because it edits a group rather than
   creating one.
5. Read back with `polygon_test_groups` and `polygon_tests` before
   committing: every group present, dependencies as `problem.json` declares
   them, points summing to 100 across the ladder.

## Phase 8 — commit

`polygon_commit(problem_id, minor_changes=<not polygon.notify_on_commit>,
message="<problem name>: uploaded from competitive-programming")`. Note the
inversion: `notify_on_commit = false` means `minor_changes = true`, which is
how Polygon commits without mailing the problem's other authors.

**Read `committed`, not `ok`.** `ok: true` only means the call went through:
`committed: false` with the message "No changes" means nothing was saved, and
`conflict_occurred: true` means the working copy fell behind — then
`polygon_update_working_copy` and commit again.

After a commit that really happened — and only then — stamp the record. The
next re-sync compares file mtimes against `committed_at`, so a timestamp
written for a commit that did not happen skips files that had in fact
changed:

```bash
python3 -c "import sys;from dataclasses import replace;from tools.polygon_ref import load,save;save(sys.argv[1],replace(load(sys.argv[1]),committed_at=sys.argv[2]))" \
  "$PROBLEM" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

Then `polygon_build_package(problem_id, verify=true)` and poll
`polygon_packages` until `state` leaves `PENDING`/`RUNNING`. `verify=true` is
what makes the Phase 5 tags mean something — it runs every solution on every
test and checks each claim holds. A `FAILED` package's `comment` says why;
report it rather than committing again over the top.

## Phase 9 — access

When `polygon.grant_codeforces_read` is true:
`polygon_set_access(problem_id, "codeforces", "READ")` — this is what makes
the problem importable into a Codeforces contest. It takes effect
immediately and needs no commit.

Report exactly what came back; `polygon_accesses(problem_id)` confirms it.
The method needs **direct** WRITE or OWNER access on the problem — access
held through a user group is not enough — so a refusal here is about who the
key belongs to, not about the package. Say that and stop; do not describe a
sequence of clicks in a web UI you cannot see. When the preference is false,
say the step was skipped and which preference skipped it.

## Done

- [ ] Both preconditions run fresh in this conversation: `tools.package_status`
      printed `complete`, `tools.review_checks` exited 0
- [ ] `$PROBLEM/polygon.json` carries the id and owner the server reported
      and the URL the user gave, and `polygon_ref.load` reads it back
- [ ] Limits, statement, checker, validator, generators and every solution
      uploaded, each solution tagged from its own `@tag`, exactly one `MA`
- [ ] Tests are the package's script with recoverable argv; samples are
      indices `1..S`, marked for the statement, with no uploaded answers
- [ ] Groups and points enabled iff `format == "oi"`, one group per subtask
      id, points summing to 100
- [ ] `polygon_commit` reported `committed: true`; `committed_at` recorded in
      `polygon.json`; the verified build reached `READY`
- [ ] The access step reported: granted, or skipped with the preference that
      skipped it, or refused with the reason

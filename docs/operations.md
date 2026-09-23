# Operations reference

The details behind the short [README](../README.md): how the sandbox, IO modes,
preferences, parallel runs and testlib cache behave, plus the files the
pipeline leaves in a problem repository.

## Codeforces and Polygon credentials

Codeforces guards its login with a Cloudflare challenge, so the server
authenticates with a session cookie rather than a password. Sign in at
codeforces.com, then DevTools → Application → Cookies → copy `JSESSIONID`.
`.mcp.json` reads every credential via `${…}`, so **no secret is ever stored in
this repo**.

Polygon has a real API, so no cookie is involved: generate a key pair at
Polygon → Settings → API keys. `POLYGON_MCP_ROOT` is the one directory the
Polygon server may read a file from when a tool is called with `path=` instead
of inline content; leave it unset and every path is refused, which is the safe
default.

Every other variable either server reads — Codeforces API key, default
language, state dir; Polygon base URL, timeout, pacing — is documented in
[`mcp-server/README.md`](../mcp-server/README.md), which owns those tables;
`mcp-server/.env.example` mirrors them as a fill-in template.

If you previously registered a `codeforces` server by hand in `~/.claude.json`,
remove that entry — the plugin now provides it, and two definitions of the same
server name will collide.

## The isolate sandbox

`tools/run_matrix.py` runs every *solution* sandboxed under
[`ioi/isolate`](https://github.com/ioi/isolate), never a bare `fork`/`exec`,
and refuses to start rather than falling back to something unsandboxed.
Generators, validators and checkers are not sandboxed; nothing in `tools/`
executes a generator at all. This is a one-time machine setup:

```bash
sudo apt install build-essential pkg-config libcap-dev libseccomp-dev libsystemd-dev
git clone https://github.com/ioi/isolate.git && cd isolate
make && sudo make install

sudo useradd -r isolate   # if it doesn't already exist
echo "isolate:200000:65536" | sudo tee -a /etc/subuid /etc/subgid
sudo systemctl enable --now isolate.service
```

Verify with `isolate --version`; if `--init` still fails, the likely cause is a
missing subuid/subgid range or `isolate.service` not running — both above.

## IO modes

A problem's `problem.json` sets `io.input` / `io.output` either to the
sentinels `"stdin"` / `"stdout"` or to a pair of bare filenames (`flight.inp` /
`flight.out`, the shape most VOI-style packages use); anything else — a path
separator, a dot-segment, the two names being equal — is refused at load. In
file-IO mode `run_matrix.py` stages the test into the sandbox's one writable
mount under `io.input`, `--chdir`s there, and reads the answer back from
`io.output`. Generators and validators are unaffected: they are stdin/stdout
testlib tools in both modes. The checker is unaffected too — testlib checkers
already take three file paths (`checker <input> <output> <answer>`). The one
new outcome is the verdict `NO_OUTPUT`: a solution that exits cleanly and never
creates `io.output`, almost always because it wrote the wrong filename. Like
`FAIL`, it is discovered by the harness and can never be declared in a
solution's `@expect`.

## Preferences

The judgement calls the setting pipeline would otherwise ask about on every
problem — OI or ICPC, who proposes the subtask ladder, how many files a test
group gets, how many stress rounds — have standing answers in
`preferences.toml`. Six of the seven setting skills read it before asking
anything it already answers — writing-statements has no Bootstrap block and
does not read the file; a value of `"ask"` means the file declines to decide
and the question is put to you.

One file is used **whole**, with no layering: `$CP_PREFERENCES` if set (an
explicit path, and an error if it does not load), else
`$XDG_CONFIG_HOME/competitive-programming/preferences.toml` (default
`~/.config/…`), else the shipped file. So a copy you put in your config
directory has to keep every key. `tools/preferences.py` is the only parser — an
unknown section or key, a wrong type, or a value outside the closed set is an
error naming the file, the `section.key` and what was allowed, rather than a
silent default. `python3 -m tools.preferences` prints the effective config.

## Parallel runs

`run_matrix.py` leases every isolate box id from a per-user `flock` pool
(`/run/user/<uid>/run_matrix-boxes`, falling back to
`/tmp/run_matrix-boxes-<uid>`, overridable with `$RUN_MATRIX_BOX_LOCK_DIR`), so
several invocations — or several `dispatching-parallel-agents` subagents, or two
copies of the test suite — can run at once without colliding. That guarantee is
about correctness — no two of this user's invocations can land on the same box
or clobber each other's staged output — not about timing isolation: a sibling
invocation's sandboxes still compete for the same CPUs while yours run. Pass 2
also runs on that same pool, so the pool size is simultaneously the box
allocator and this user's CPU admission control. Measured, not projected:
`goldenseed` (13 solutions, 42 graded tests, 546 results) ran in 182.4s serial
vs. 65.4s at 4 workers — 2.79x — with verdicts, holes, mismatches, and TL/kill
limits identical between the two runs, and 1 of 546 results re-timed serially.

The pool is per-user: two *different* users running `run_matrix` on the same
machine can still land on the same isolate box id. That collision is caught
loudly by isolate's own lock — the driver names it and stops, rather than
reporting a wrong verdict — but it is not prevented.

`$RUN_MATRIX_BOX_POOL` sets the pool size; it defaults to half the CPUs. That
default is a correctness bound, not a throughput setting: CPU time inflates
under contention (measured on an 8-thread box, 1.15–1.21x at 4 concurrent
sandboxes and up to 1.92x at 8), and the driver's ambiguity rule is only sound
while inflation stays below 2x. `pool_size()` accepts any value up to isolate's
own box-id ceiling with no check against the core count, so raising it past
`nproc` is an operator hazard — nothing bounds wall-time inflation the way
`CONTENTION_BOUND` bounds CPU time. The same is true of memory: each sandbox's
cgroup is capped via `--cg-mem` at the problem's `memory_mb` plus a fixed 256 MB
output allowance (on cgroup v2 a solution's dirty output pages are charged to
its cgroup until written back; ML itself is judged from the child's peak RSS
against `memory_mb`), so the driver's peak footprint is
`workers × (memory_mb + 256 MB)`, unchecked against physical RAM. Set it to `1`
for a fully quiesced authoritative run *provided this is the only `run_matrix`
invocation on the machine* — a sibling at `RUN_MATRIX_BOX_POOL=4` will still
sweep the other lease ids.

Pass 1 — the model solution's timings, from which TL is derived — is always
serial within one invocation. A sibling invocation can still inflate the
measured `t_main`, but that is the safe direction to be wrong in: an inflated
TL lets a too-slow solution pass, and `compare()` records `@expect TL` met by an
`OK` result as a **hole** in `invocation.json`, tripping exit code 1. It is a
false alarm worth double-checking, not a silent failure.

## Test suite and testlib cache

The tools suite **fails** rather than skips when `g++`, `isolate`, or the
testlib cache is missing: `run_matrix.py` has no fallback runner, so skipping
would print a green `OK` over a driver that never executed. Set
`CP_ALLOW_SANDBOX_SKIP=1` to opt back into skipping them.

The testlib cache is populated by `tools/bootstrap_testlib.sh`, which every
skill's Bootstrap block and the tools suite shell out to. It clones or refreshes
`qhhoj/testlib` into `$XDG_CACHE_HOME/testlib` (`~/.cache/testlib` if unset) and
prints the path; set `CP_TESTLIB` to an existing directory containing
`testlib.h` to skip that entirely — no network, no `git` needed.
`python3 -m tools.bootstrap_testlib` is the portable entry point; the `.sh` is a
thin `cd`-then-`exec` wrapper kept for existing callers.

Each check command names its own working directory: the tools suite imports
`tools.*` and only resolves from the repository root (after a `cd mcp-server`
it fails with `ImportError: Start directory is not importable`).

## Files the pipeline leaves in a problem repository

**`flags.json.lock` — gitignore it.** `tools/flags.py` takes an advisory `flock`
on a separate lock file beside every package's `flags.json`, so concurrent
writers don't race each other's read-modify-write. It is never unlinked:
`flags.json` itself is replaced with `os.replace` on every write, so a lock held
on it would be a lock on an unlinked inode, and `flock` is released by
`os.close` regardless. It is therefore a permanent byproduct; this repo itself
never creates one, since no problem package lives here.

**`polygon.json` — commit it.** `uploading-to-polygon` records which Polygon
problem a package owns — id, owner, URL and the timestamp of the last revision
it committed, via `tools/polygon_ref.py`. It is the only record of which
Polygon problem a package is, and losing it makes the next upload look like a
first one. It deliberately is *not* a key in `problem.json`: that file is matrix
evidence (`tools/package_status.py` walks it to decide whether
`invocation.json` has gone stale), so writing into it would fail the very gates
the upload skill must pass first.

## Maintainer notes

**Skill discovery.** Claude Code discovers personal skills at exactly
`~/.claude/skills/<skill>/SKILL.md` — one level; a skill at
`~/.claude/skills/<category>/<skill>/SKILL.md` returns `Unknown skill`.
Grouping works here only because this folder is a **plugin**: the
`.claude-plugin/plugin.json` makes `skills/*` visible and supplies the
`competitive-programming:` namespace. To add a skill, create
`skills/<new-skill>/SKILL.md` with frontmatter whose `name:` matches the
directory. Do not nest deeper, and do not remove the manifest.

**The `mcp` pin.** `pyproject.toml` requires `mcp>=1.2,<2`. Both servers use
`mcp.server.fastmcp`, which 2.0 removed — an unpinned `>=1.2.0` resolves to 2.0
and fails at import. Keep the upper bound until they are ported.

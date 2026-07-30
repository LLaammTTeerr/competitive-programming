# competitive-programming

Claude Code plugin for competitive programming: five skills — two for solving
(one problem, one whole contest), three for setting one (test data, solution
validation, statement) — plus the bundled Codeforces MCP server. This repository
is also a **marketplace**, so it can be used in place or installed on another
machine.

| Component | Invoked as | What it does |
|---|---|---|
| Skill `solving-problems` | `competitive-programming:solving-problems` | Algorithm design and C++ for one problem on a stdin/stdout judge — constraints → complexity budget → design → edge cases → clean implementation, with stress testing against a brute-force oracle |
| Skill `running-contests` | `competitive-programming:running-contests` | Drives a whole contest on any judge: binds to whatever judge MCP is installed, pulls the problem set, orders it, delegates each problem to `solving-problems`, submits, reads verdicts, and keeps going until every problem is solved |
| Skill `preparing-tests` | `competitive-programming:preparing-tests` | Builds the test-data contract for a problem being set: checker, validator, generators (random / max-size / boundary / structured-adversarial / hand-written), and sample selection, driven by testlib and `tools/gen_constraints_header.py` / `tools/drift_check.py` |
| Skill `validating-solutions` | `competitive-programming:validating-solutions` | Attacks a problem's test suite with a zoo of deliberately-wrong solutions plus alternative and exhaustive-arbiter `accepted` solutions, runs the invocation matrix (`tools/run_matrix.py`) under `ioi/isolate`, and reports holes and mismatches |
| Skill `writing-statements` | `competitive-programming:writing-statements` | Authors, translates, and reviews problem statements for the vnolymp LaTeX template — the Vietnamese statement package for problems prepared on Polygon |
| MCP server `codeforces` | tools `cf_*` | Browse contest problems, read statements, submit solutions, poll verdicts |

## Layout

```
competitive-programming/
├── .claude-plugin/
│   ├── plugin.json           # plugin manifest ("skills": ["./skills"])
│   └── marketplace.json      # lets this repo be installed as a marketplace
├── .mcp.json                 # registers the bundled codeforces server
├── skills/
│   ├── solving-problems/SKILL.md  (+ references/black-magic.md)
│   ├── running-contests/SKILL.md   (+ references/judges.md)
│   ├── preparing-tests/SKILL.md
│   ├── validating-solutions/SKILL.md
│   └── writing-statements/SKILL.md
├── tools/                    # Python pipeline the two test-authoring skills drive
│   ├── problem_meta.py  flags.py  gen_constraints_header.py  drift_check.py
│   ├── scan_solutions.py  matrix_core.py  run_matrix.py  bootstrap_testlib.sh
│   └── tests/                # unittest suite, see Checks below
└── mcp-server/               # the Codeforces MCP server (Python, package cf-mcp)
    ├── pyproject.toml  uv.lock
    ├── src/cf_mcp/
    └── tests/
```

## Setup

**Prerequisite:** [`uv`](https://docs.astral.sh/uv/) — the server is launched with
`uvx`, which builds it from `mcp-server/` and resolves dependencies on its own, so
there is no virtualenv to manage:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Credentials.** Codeforces guards its login with a Cloudflare challenge, so the
server authenticates with a session cookie rather than a password. Sign in at
codeforces.com, then DevTools → Application → Cookies → copy `JSESSIONID`. Export
both variables in the shell that launches Claude Code (`.mcp.json` reads them via
`${…}`, so **no secret is ever stored in this repo**):

```bash
export CODEFORCES_HANDLE=your_handle
export CODEFORCES_COOKIE=JSESSIONID=your_cookie_value
```

Everything else the server understands is documented in `mcp-server/.env.example`.

**Prerequisite:** [`ioi/isolate`](https://github.com/ioi/isolate) —
`tools/run_matrix.py` runs every *solution* sandboxed under isolate, never a bare
`fork`/`exec`, and refuses to start rather than falling back to something
unsandboxed. Generators, validators and checkers are not sandboxed; nothing in
`tools/` executes a generator at all. This is a one-time machine setup, not a
per-problem one:

```bash
sudo apt install build-essential pkg-config libcap-dev libseccomp-dev libsystemd-dev
git clone https://github.com/ioi/isolate.git && cd isolate
make && sudo make install
```

Then create the system user isolate expects, register its subuid/subgid range, and
start the cgroup keeper daemon:

```bash
sudo useradd -r isolate   # if it doesn't already exist
echo "isolate:200000:65536" | sudo tee -a /etc/subuid /etc/subgid
sudo systemctl enable --now isolate.service
```

Verify with `isolate --version`; if `--init` still fails, the likely cause is a
missing subuid/subgid range or `isolate.service` not running — both above.

## Installing

**Same machine** — clone into `~/.claude/skills/`. Anything there with a
`.claude-plugin/plugin.json` auto-loads as `<name>@skills-dir`; no install step:

```bash
git clone <repo-url> ~/.claude/skills/competitive-programming
# then, in Claude Code:  /reload-plugins
```

**Elsewhere** — install it as a marketplace:

```
/plugin marketplace add <repo-url>
/plugin install competitive-programming@competitive-programming
```

If you previously registered a `codeforces` server by hand in `~/.claude.json`,
remove that entry — the plugin now provides it, and two definitions of the same
server name will collide.

## How skill discovery works here (read before adding skills)

Claude Code discovers personal skills at exactly **`~/.claude/skills/<skill>/SKILL.md`**
— one level. A bare subfolder is *not* scanned: a skill at
`~/.claude/skills/<category>/<skill>/SKILL.md` returns `Unknown skill`.

Grouping into a folder works only because that folder is a **plugin**: the
`.claude-plugin/plugin.json` here is what makes `skills/*` visible, and it is
also what supplies the `competitive-programming:` namespace.

To add a skill, create `skills/<new-skill>/SKILL.md` with frontmatter whose `name:`
matches the directory. Do not nest deeper, and do not remove the manifest.

## Checks

Each line names its own working directory: the tools suite imports `tools.*`
and only resolves from the repository root, and the previous version of this
block put it after a `cd mcp-server`, where it fails with `ImportError: Start
directory is not importable`.

```bash
cd <this repo>
claude plugin validate . --strict                 # manifests
claude plugin details competitive-programming     # inventory: 5 skills, 1 MCP server

python3 -m unittest discover -s tools/tests -t . -v    # tools suite (repo root)
(cd mcp-server && uv run --extra dev pytest -q)        # server suite (subshell)

# end-to-end: the server should answer an MCP handshake
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}' \
  | uvx --from ./mcp-server cf-mcp
```

The tools suite **fails** rather than skips when `g++`, `isolate`, or the
testlib cache is missing: `run_matrix.py` is the one module with no fallback
runner, so gating its tests on the presence of that same dependency meant a
fresh clone printed a green `OK` over a driver it had never executed. Set
`CP_ALLOW_SANDBOX_SKIP=1` to opt back into skipping them.

After editing a skill or `.mcp.json`, run `/reload-plugins` (or start a new session).

> **Note on the `mcp` pin.** `pyproject.toml` requires `mcp>=1.2,<2`. The server uses
> `mcp.server.fastmcp`, which 2.0 removed — an unpinned `>=1.2.0` resolves to 2.0 and
> fails at import. Keep the upper bound until the server is ported.

## Author

LamTer <lamtercqh@gmail.com>

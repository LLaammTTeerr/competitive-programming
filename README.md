# competitive-programming

A Claude Code plugin for competitive programming: eleven skills for solving and
setting problems, plus MCP servers for Codeforces and Polygon.

- [What's inside](#whats-inside)
- [Install](#install)
- [Setup](#setup)
- [Layout](#layout)
- [Checks](#checks)
- [More detail](#more-detail)

## What's inside

**Solving**

| Skill | Use it to |
|---|---|
| `competitive-programming:solving-problems` | Design and implement one problem in C++, with stress testing |
| `competitive-programming:running-contests` | Work through a whole contest on any judge: fetch, solve, submit, repeat |

**Setting**

| Skill | Use it to |
|---|---|
| `competitive-programming:creating-problems` | Take an idea all the way to a Polygon-ready package (drives the five below) |
| `competitive-programming:shaping-problems` | Pick difficulty, constraints and a subtask ladder |
| `competitive-programming:preparing-tests` | Write the generator, validator and checker; build the tests |
| `competitive-programming:validating-solutions` | Attack the tests with deliberately-wrong solutions |
| `competitive-programming:writing-statements` | Write or translate a Vietnamese vnolymp LaTeX statement |
| `competitive-programming:reviewing-problems` | Audit a finished package before it ships |
| `competitive-programming:uploading-to-polygon` | Upload a finished package to Polygon (only when asked) |
| `competitive-programming:writing-editorials` | Write an HTML editorial (only when asked) |
| `competitive-programming:calculating-difficulties` | Estimate a finished problem's Codeforces rating (only when asked) |

**MCP servers** (11 skills, 2 MCP servers in total)

| Server | Tools | Use it to |
|---|---|---|
| MCP server `codeforces` | `cf_*` | Read problems, submit, poll verdicts |
| MCP server `polygon` | `polygon_*` | Upload tests, solutions and statements, then commit and build |

## Install

On this machine, clone into `~/.claude/skills/` and run `/reload-plugins`:

```bash
git clone <repo-url> ~/.claude/skills/competitive-programming
```

Elsewhere, install it as a marketplace:

```
/plugin marketplace add <repo-url>
/plugin install competitive-programming@competitive-programming
```

See `CHANGELOG.md` for what changed.

## Setup

1. **Install [`uv`](https://docs.astral.sh/uv/).** Both servers run through `uvx`;
   there is no virtualenv to manage.

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Export credentials** in the shell that launches Claude Code. Nothing
   secret is stored in the repo.

   ```bash
   export CODEFORCES_HANDLE=your_handle
   export CODEFORCES_COOKIE=JSESSIONID=your_cookie_value   # from browser DevTools
   export POLYGON_API_KEY=your_key                          # Polygon → Settings → API keys
   export POLYGON_API_SECRET=your_secret
   export POLYGON_MCP_ROOT=/path/to/the/problem/you/are/uploading
   ```

3. **Install [`ioi/isolate`](https://github.com/ioi/isolate)** if you set
   problems: `tools/run_matrix.py` runs solutions only inside it. The steps are
   in [docs/operations.md](docs/operations.md#the-isolate-sandbox).

4. **Optional: edit `preferences.toml`** for standing answers (OI or ICPC,
   stress rounds…). You can override it with `$CP_PREFERENCES` or
   `$XDG_CONFIG_HOME/competitive-programming/preferences.toml`.
   `python3 -m tools.preferences` shows the settings in effect.

Good to know:

- **File IO works as well as stdin/stdout.** Set `io.input` / `io.output` in
  `problem.json`. Generators and validators are unaffected. Checkers still take
  three file paths.
- **Parallel runs are safe.** Tune them with `$RUN_MATRIX_BOX_POOL` and
  `$RUN_MATRIX_BOX_LOCK_DIR`.
- **testlib is cached automatically.** Set `CP_TESTLIB` to use an existing copy
  instead (the entry point is `python3 -m tools.bootstrap_testlib`).

## Layout

```
competitive-programming/
├── .claude-plugin/           # plugin.json + marketplace.json
├── .mcp.json                 # registers the codeforces and polygon servers
├── preferences.toml
├── docs/operations.md        # the long-form details
├── skills/
│   ├── solving-problems/SKILL.md      running-contests/SKILL.md
│   ├── creating-problems/SKILL.md     shaping-problems/SKILL.md
│   ├── preparing-tests/SKILL.md       validating-solutions/SKILL.md
│   ├── writing-statements/SKILL.md    reviewing-problems/SKILL.md
│   ├── uploading-to-polygon/SKILL.md  writing-editorials/SKILL.md
│   └── calculating-difficulties/SKILL.md
├── tools/                    # Python pipeline the setting skills drive
│   ├── problem_meta.py  flags.py  gen_constraints_header.py  drift_check.py
│   ├── scan_solutions.py  matrix_core.py  run_matrix.py  box_pool.py
│   ├── package_status.py  review_checks.py  preferences.py  polygon_ref.py
│   ├── cf_statement_lint.py  recover_test_argv.py
│   ├── bootstrap_testlib.py  bootstrap_testlib.sh
│   └── tests/
└── mcp-server/               # both servers: src/cf_mcp, src/polygon_mcp
```

## Checks

Run from the repository root:

```bash
claude plugin validate . --strict
claude plugin details competitive-programming          # expect: 11 skills, 2 MCP servers
python3 -m unittest discover -s tools/tests -t . -v
(cd mcp-server && uv run --extra dev pytest -q)

# each server should answer an MCP handshake
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}' \
  | uvx --from ./mcp-server cf-mcp
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}' \
  | uvx --from ./mcp-server polygon-mcp
```

After you edit a skill or `.mcp.json`, run `/reload-plugins`.

## More detail

- [docs/operations.md](docs/operations.md) covers sandbox setup, IO modes, how
  preferences are looked up, parallel-run limits, the testlib cache, and which
  generated files to commit (`polygon.json`) or gitignore (`flags.json.lock`).
- [mcp-server/README.md](mcp-server/README.md) lists every server variable and tool.

## Author

LamTer <lamtercqh@gmail.com> · MIT license (see `LICENSE`; `NOTICE` credits the editorial theme).

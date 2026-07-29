# competitive-programming

Claude Code plugin for competitive programming: two skills plus the Codeforces MCP
server they drive. This repository is also a **marketplace**, so it can be used in
place or installed on another machine.

| Component | Invoked as | What it does |
|---|---|---|
| Skill `solving-problems` | `competitive-programming:solving-problems` | Algorithm design and C++ for one problem on a stdin/stdout judge — constraints → complexity budget → design → edge cases → clean implementation, with stress testing against a brute-force oracle |
| Skill `running-contests` | `competitive-programming:running-contests` | Drives a whole contest on any judge: binds to whatever judge MCP is installed, pulls the problem set, orders it, delegates each problem to `solving-problems`, submits, reads verdicts, and keeps going until every problem is solved |
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
│   └── running-contests/SKILL.md   (+ references/judges.md)
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

```bash
claude plugin validate . --strict                 # manifests
claude plugin details competitive-programming     # inventory: 2 skills, 1 MCP server

cd mcp-server && uv run --extra dev pytest -q     # server test suite

# end-to-end: the server should answer an MCP handshake
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}' \
  | uvx --from ./mcp-server cf-mcp
```

After editing a skill or `.mcp.json`, run `/reload-plugins` (or start a new session).

> **Note on the `mcp` pin.** `pyproject.toml` requires `mcp>=1.2,<2`. The server uses
> `mcp.server.fastmcp`, which 2.0 removed — an unpinned `>=1.2.0` resolves to 2.0 and
> fails at import. Keep the upper bound until the server is ported.

## Author

LamTer <lamtercqh@gmail.com>

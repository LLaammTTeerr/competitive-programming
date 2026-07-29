# competitive-programming

Claude Code skills for competitive programming — one skill for solving a single
problem, one for driving an entire contest. This repository is both a **plugin**
and a **marketplace**, so it can be used in place or installed on another machine.

| Skill | Invoked as | What it does |
|---|---|---|
| `solving-problems` | `competitive-programming:solving-problems` | Algorithm design and C++ for one problem on a stdin/stdout judge — constraints → complexity budget → design → edge cases → clean implementation, with stress testing against a brute-force oracle |
| `running-contests` | `competitive-programming:running-contests` | Drives a whole contest: pulls the problem set, orders it, delegates each problem to `solving-problems`, submits through the Codeforces MCP, reads verdicts, and keeps going until every problem is solved |

## Layout

```
competitive-programming/
├── .claude-plugin/
│   ├── plugin.json           # the plugin manifest ("skills": ["./skills"])
│   └── marketplace.json      # lets this repo be installed as a marketplace
└── skills/
    ├── solving-problems/SKILL.md
    │   └── references/black-magic.md
    └── running-contests/SKILL.md
```

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

## How skill discovery works here (read before adding skills)

Claude Code discovers personal skills at exactly **`~/.claude/skills/<skill>/SKILL.md`**
— one level. A bare subfolder is *not* scanned: a skill at
`~/.claude/skills/<category>/<skill>/SKILL.md` returns `Unknown skill`.

Grouping into a folder works only because that folder is a **plugin**: the
`.claude-plugin/plugin.json` here is what makes `skills/*` visible, and it is
also what supplies the `competitive-programming:` namespace.

So: to add a skill, create `skills/<new-skill>/SKILL.md` with frontmatter whose
`name:` matches the directory. Do not nest deeper, and do not remove the manifest.

## Checks

```bash
claude plugin validate . --strict                 # manifests
claude plugin details competitive-programming     # component inventory + token cost
```

After editing any skill, run `/reload-plugins` (or start a new session) to pick
up the change.

## Author

LamTer <lamtercqh@gmail.com>

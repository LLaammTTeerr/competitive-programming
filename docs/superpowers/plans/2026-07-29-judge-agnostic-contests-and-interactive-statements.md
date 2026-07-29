# Judge-Agnostic Contests + Interactive Statements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `running-contests` drive a contest on any judge by binding to whatever judge MCP is installed, and stop the Codeforces MCP's statement parser from discarding the Interaction section.

**Architecture:** Two independent changes. The parser fix replaces `parse_statement`'s fixed-field model with a single ordered walk of the statement's top-level divs, so any titled section survives in document order. The skill change replaces hardcoded `cf_*` references with a four-capability contract bound at runtime via `tool_search`, backed by a `references/judges.md` registry and a degraded manual mode.

**Tech Stack:** Python 3 + BeautifulSoup (`html.parser`) + `mcp.server.fastmcp`, tested with pytest under `uv`. Skills are Markdown with YAML frontmatter.

## Global Constraints

- Server tests run as `cd mcp-server && uv run --extra dev pytest -q`.
- `pyproject.toml` pins `mcp>=1.2,<2`; do not change it (the server uses `mcp.server.fastmcp`, removed in 2.0).
- Existing `to_dict` keys must keep their current names and shapes — additive changes only.
- Concrete judge tool names (`cf_*`) may appear in `skills/running-contests/references/judges.md` and in the MCP server, nowhere else in the skill.
- Plugin version moves 0.2.0 → 0.3.0 in **both** `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`; the two must stay identical.
- After editing a skill file, `/reload-plugins` is needed for a running session to see it. Note it; don't try to run it from a script.
- Task order matters: Tasks 1–2 (parser) land before Task 4, whose skill text tells the reader the statement tool returns `interactive: true`.

---

### Task 1: Parse statement sections in document order

Recovers every titled section Codeforces puts in a class-less top-level div — Interaction, Scoring, and anything else — instead of keeping only the first one as the legend.

**Files:**
- Modify: `mcp-server/src/cf_mcp/statement.py:17-87` (dataclasses + `to_markdown` + `to_dict`), `:180-188` (`_section` → `_body`), `:202-266` (`parse_statement`)
- Test: `mcp-server/tests/test_offline.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Section(title: str, body: str)` dataclass; `Statement.sections: list[Section]`; `Statement.samples_index: int | None`; `Statement.to_dict()` gains a `"sections": [{"title": str, "body": str}]` key. Task 2 adds `Statement.interactive` on top of these.

- [ ] **Step 1: Write the failing tests**

Add these fixtures and tests to `mcp-server/tests/test_offline.py`, directly after the existing `test_parse_statement_rejects_a_page_without_a_statement` (around line 111). `STATEMENT_HTML` already exists at line ~62 — do not redefine it.

```python
# Mirrors contest 2206 problem A: an interactive problem has no input or output
# specification at all, only a class-less <div> titled "Interaction".
INTERACTIVE_STATEMENT_HTML = """
<div class="problem-statement">
  <div class="header">
    <div class="title">A. Compare Suffixes</div>
    <div class="time-limit"><div class="property-title">time limit per test</div>2 seconds</div>
    <div class="memory-limit"><div class="property-title">memory limit per test</div>1024 megabytes</div>
    <div class="input-file input-standard"><div class="property-title">input</div>standard input</div>
    <div class="output-file output-standard"><div class="property-title">output</div>standard output</div>
  </div>
  <div><p>The judge hides a string $$$S$$$ of length $$$n$$$.</p></div>
  <div><div class="section-title">Interaction</div><p>Print <span class="tex-font-style-tt">query i j</span> to compare two suffixes. You may ask at most $$$10^5$$$ queries. Flush after every line.</p></div>
  <div class="sample-tests"><div class="section-title">Example</div>
    <div class="sample-test">
      <div class="input"><div class="title">Input</div><pre>
4
first
</pre></div>
      <div class="output"><div class="title">Output</div><pre>
query 2 1
</pre></div>
    </div>
  </div>
  <div class="note"><div class="section-title">Note</div><p>Sample interaction.</p></div>
</div>
"""


# A subtask problem puts its scoring rules in the same kind of class-less div.
SUBTASK_STATEMENT_HTML = """
<div class="problem-statement">
  <div class="header">
    <div class="title">C. Subtasks</div>
  </div>
  <div><p>Solve it.</p></div>
  <div class="input-specification"><div class="section-title">Input</div><p>One integer $$$n$$$.</p></div>
  <div class="output-specification"><div class="section-title">Output</div><p>Print $$$n$$$.</p></div>
  <div><div class="section-title">Scoring</div><p>Subtask 1 ($$$n \\le 10$$$): 30 points.</p></div>
  <div class="note"><div class="section-title">Note</div><p>Nothing to add.</p></div>
</div>
"""


def test_parse_statement_keeps_a_class_less_titled_section():
    statement = parse_statement(
        INTERACTIVE_STATEMENT_HTML, 2206, "A", "https://example/2206/A"
    )
    titles = [section.title for section in statement.sections]
    assert titles == ["Interaction", "Note"]
    interaction = statement.sections[0].body
    assert "query i j" in interaction
    assert "$10^5$ queries" in interaction
    assert "Flush after every line." in interaction


def test_class_less_titled_section_reaches_the_markdown():
    statement = parse_statement(
        INTERACTIVE_STATEMENT_HTML, 2206, "A", "https://example/2206/A"
    )
    markdown = statement.to_markdown()
    assert "## Interaction" in markdown
    assert "Flush after every line." in markdown


def test_parse_statement_keeps_an_unknown_titled_section():
    statement = parse_statement(
        SUBTASK_STATEMENT_HTML, 1, "C", "https://example/1/C"
    )
    titles = [section.title for section in statement.sections]
    assert titles == ["Input", "Output", "Scoring", "Note"]
    assert "30 points" in statement.to_markdown()


def test_sections_render_in_page_order_around_the_samples():
    statement = parse_statement(STATEMENT_HTML, 42, "B", "https://example/42/B")
    markdown = statement.to_markdown()
    positions = [
        markdown.index("## Input"),
        markdown.index("## Output"),
        markdown.index("## Example"),
        markdown.index("## Note"),
    ]
    assert positions == sorted(positions)


def test_to_dict_exposes_sections():
    statement = parse_statement(
        SUBTASK_STATEMENT_HTML, 1, "C", "https://example/1/C"
    )
    scoring = statement.to_dict()["sections"][2]
    assert scoring["title"] == "Scoring"
    assert scoring["body"].startswith("Subtask 1")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-server && uv run --extra dev pytest tests/test_offline.py -q -k "section or class_less"`
Expected: FAIL — `AttributeError: 'Statement' object has no attribute 'sections'`.

- [ ] **Step 3: Add the `Section` dataclass and the new `Statement` fields**

In `mcp-server/src/cf_mcp/statement.py`, add after the `Sample` dataclass:

```python
@dataclass
class Section:
    """A titled block of the statement — Input, Interaction, Scoring, Note…"""

    title: str
    body: str
```

Then in `Statement`, add two fields after `samples`:

```python
    sections: list[Section] = field(default_factory=list)
    # Where the sample block sat among the sections, so rendering can put it back.
    samples_index: int | None = None
```

Keep `legend`, `input_spec`, `output_spec` and `note` exactly as they are — they stay populated, and `test_parse_statement_normalises_math_and_lists` reads `legend`.

- [ ] **Step 4: Render sections in document order**

Replace `Statement.to_markdown` (currently `statement.py:39-73`) with:

```python
    def to_markdown(self) -> str:
        parts = [f"# {self.index}. {self.name}", ""]
        meta = []
        if self.time_limit:
            meta.append(f"- **Time limit:** {self.time_limit}")
        if self.memory_limit:
            meta.append(f"- **Memory limit:** {self.memory_limit}")
        meta.append(f"- **Input:** {self.input_file}")
        meta.append(f"- **Output:** {self.output_file}")
        meta.append(f"- **URL:** {self.url}")
        parts += meta + ["", self.legend.strip()]

        split = (
            len(self.sections) if self.samples_index is None else self.samples_index
        )
        parts += self._section_lines(self.sections[:split])
        parts += self._sample_lines()
        parts += self._section_lines(self.sections[split:])
        return "\n".join(parts).strip() + "\n"

    def _section_lines(self, sections: list[Section]) -> list[str]:
        lines: list[str] = []
        for section in sections:
            body = section.body.strip()
            if not body:
                continue
            lines += ["", f"## {section.title}", "", body]
        return lines

    def _sample_lines(self) -> list[str]:
        lines: list[str] = []
        for i, sample in enumerate(self.samples, 1):
            label = f"## Example {i}" if len(self.samples) > 1 else "## Example"
            lines += [
                "",
                label,
                "",
                "Input:",
                "```",
                sample.input,
                "```",
                "",
                "Output:",
                "```",
                sample.output,
                "```",
            ]
        return lines
```

And add `sections` to `to_dict`, after the `samples` key:

```python
            "sections": [
                {"title": s.title, "body": s.body} for s in self.sections
            ],
```

- [ ] **Step 5: Replace `_section` with a class-agnostic `_body`, and add `_titled`**

Delete `_section` (`statement.py:180-188`) and put these in its place:

```python
def _titled(node: Tag) -> str:
    """The section's heading text, or "" when the div carries no heading."""
    title = node.find("div", class_="section-title")
    return title.get_text(" ", strip=True) if title else ""


def _body(node: Tag) -> str:
    """Render a section's contents as Markdown, minus its heading."""
    clone = _soup(str(node)).find("div")
    title = clone.find("div", class_="section-title")
    if title:
        title.decompose()
    return _clean(_children_text(clone))
```

- [ ] **Step 6: Rewrite `parse_statement`'s body as one ordered walk**

Add this table above `parse_statement`:

```python
# Statement divs whose class names the section; the fallback title is used when
# the page omits the heading.
_NAMED_SECTIONS = {
    "input-specification": ("input_spec", "Input"),
    "output-specification": ("output_spec", "Output"),
    "note": ("note", "Note"),
}
```

Then replace everything in `parse_statement` from the `statement = Statement(...)` construction (`statement.py:222-264`) down to `return statement` with:

```python
    statement = Statement(
        contest_id=contest_id,
        index=index,
        name=name,
        url=url,
        time_limit=_property(header, "time-limit") if header else "",
        memory_limit=_property(header, "memory-limit") if header else "",
        input_file=_property(header, "input-file", "standard input")
        if header
        else "standard input",
        output_file=_property(header, "output-file", "standard output")
        if header
        else "standard output",
    )

    for child in root.find_all("div", recursive=False):
        if child is header:
            continue
        classes = child.get("class") or []

        if "sample-tests" in classes:
            statement.samples_index = len(statement.sections)
            statement.samples.extend(_parse_samples(child))
            continue

        named = next((c for c in classes if c in _NAMED_SECTIONS), None)
        if named:
            attribute, fallback_title = _NAMED_SECTIONS[named]
            body = _body(child)
            setattr(statement, attribute, body)
            statement.sections.append(Section(_titled(child) or fallback_title, body))
            continue

        if classes:
            continue  # A decorated div that is not statement prose.

        # Class-less divs are either the legend or a section Codeforces did not
        # give a class — Interaction, Scoring. Only the titled ones are sections.
        title = _titled(child)
        if title:
            statement.sections.append(Section(title, _body(child)))
            continue
        prose = _clean(_children_text(child))
        if not prose:
            continue
        statement.legend = f"{statement.legend}\n\n{prose}" if statement.legend else prose

    return statement
```

Then extract the existing sample loop into a helper, placed next to `_body`:

```python
def _parse_samples(samples_root: Tag) -> list[Sample]:
    samples: list[Sample] = []
    for test in samples_root.find_all("div", class_="sample-test"):
        inputs = [
            _pre_text(div.find("pre"))
            for div in test.find_all("div", class_="input")
            if div.find("pre")
        ]
        outputs = [
            _pre_text(div.find("pre"))
            for div in test.find_all("div", class_="output")
            if div.find("pre")
        ]
        for i, sample_input in enumerate(inputs):
            samples.append(Sample(sample_input, outputs[i] if i < len(outputs) else ""))
    return samples
```

Leave the `root is None` check, the `header`/`name` extraction (`statement.py:205-220`), `parse_contest_problem_list`, and every other helper untouched.

- [ ] **Step 7: Run the whole suite**

Run: `cd mcp-server && uv run --extra dev pytest -q`
Expected: PASS, including the pre-existing `test_parse_statement_extracts_metadata_and_samples` and `test_parse_statement_normalises_math_and_lists` — they are the regression guard that ordinary statements still parse identically.

- [ ] **Step 8: Commit**

```bash
git add mcp-server/src/cf_mcp/statement.py mcp-server/tests/test_offline.py
git commit -m "fix: keep every titled statement section, in page order

Codeforces puts Interaction and Scoring in class-less top-level divs, the
same shape as the legend. The parser kept the first one and dropped the
rest, so interactive problems lost their whole protocol section."
```

---

### Task 2: Flag interactive problems

Marks a statement as interactive so the contest loop knows to flush and knows the sample is a transcript rather than a runnable test file.

**Files:**
- Modify: `mcp-server/src/cf_mcp/statement.py` (`Statement` fields, `to_markdown`, `to_dict`, end of `parse_statement`), `mcp-server/src/cf_mcp/server.py:147-159` (docstring)
- Test: `mcp-server/tests/test_offline.py`

**Interfaces:**
- Consumes: `Section`, `Statement.sections`, `INTERACTIVE_STATEMENT_HTML` and `SUBTASK_STATEMENT_HTML` from Task 1.
- Produces: `Statement.interactive: bool`; `to_dict()` gains `"interactive": bool`.

- [ ] **Step 1: Write the failing tests**

Append to `mcp-server/tests/test_offline.py`, after the Task 1 statement tests:

```python
def test_interaction_section_marks_the_problem_interactive():
    statement = parse_statement(
        INTERACTIVE_STATEMENT_HTML, 2206, "A", "https://example/2206/A"
    )
    assert statement.interactive is True
    assert statement.to_dict()["interactive"] is True
    assert "transcript" in statement.to_markdown()


def test_ordinary_statement_is_not_interactive():
    statement = parse_statement(STATEMENT_HTML, 42, "B", "https://example/42/B")
    assert statement.interactive is False
    assert statement.to_dict()["interactive"] is False
    assert "transcript" not in statement.to_markdown()


def test_legend_wording_alone_marks_the_problem_interactive():
    html = (
        '<div class="problem-statement">'
        '<div class="header"><div class="title">A. Talk</div></div>'
        "<div><p>This is an interactive problem. Ask the judge.</p></div>"
        "</div>"
    )
    assert parse_statement(html, 1, "A", "u").interactive is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp-server && uv run --extra dev pytest tests/test_offline.py -q -k interactive`
Expected: FAIL — `AttributeError: 'Statement' object has no attribute 'interactive'`.

- [ ] **Step 3: Add the field and detect it**

In `Statement`, add after `samples_index`:

```python
    interactive: bool = False
```

At the end of `parse_statement`, immediately before `return statement`:

```python
    statement.interactive = any(
        section.title.strip().lower().startswith("interaction")
        for section in statement.sections
    ) or "interactive problem" in statement.legend.lower()
```

- [ ] **Step 4: Surface it in the rendered statement**

In `to_markdown`, after the `- **URL:** …` line is appended to `meta`:

```python
        if self.interactive:
            meta.append(
                "- **Interactive:** yes — flush after every write. The example "
                "below is a dialogue transcript, not a runnable test file."
            )
```

In `to_dict`, add alongside `sections`:

```python
            "interactive": self.interactive,
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mcp-server && uv run --extra dev pytest -q`
Expected: PASS, whole suite.

- [ ] **Step 6: Document the new keys on the MCP tool**

In `mcp-server/src/cf_mcp/server.py`, replace the `cf_get_problem_statement` docstring body (currently lines 151-158) with:

```python
    """Read one problem's full statement, limits and sample tests.

    `index` is the problem letter, e.g. "A" or "C1". Returns the statement as
    Markdown plus the sample inputs/outputs as separate strings so they can be
    fed straight into a local test run, `sections` as the statement's titled
    blocks in page order (Input, Output, Interaction, Scoring, Note…), and
    `interactive` — when true, the problem talks to the judge, so flush after
    every write and treat the sample as a dialogue transcript rather than a
    test file.

    Pass `group_id` for a problem in a private group contest; see
    `cf_list_contest_problems` for where to find it.
    """
```

- [ ] **Step 7: Verify against the real page that triggered this**

```bash
cd mcp-server && uv run python - <<'PY'
import sys, urllib.request
sys.path.insert(0, "src")
from cf_mcp.statement import parse_statement

request = urllib.request.Request(
    "https://codeforces.com/contest/2206/problem/A?locale=en",
    headers={"User-Agent": "Mozilla/5.0"},
)
html = urllib.request.urlopen(request).read().decode("utf-8")
statement = parse_statement(html, 2206, "A", "https://codeforces.com/contest/2206/problem/A")
print("interactive:", statement.interactive)
print("sections:", [s.title for s in statement.sections])
print(statement.to_markdown())
PY
```

Expected: `interactive: True`, `sections: ['Interaction', 'Note']`, and the printed Markdown contains the query format, the query budget, and the flush requirement — none of which appear today.

If Codeforces answers with a Cloudflare interstitial ("Just a moment…") the fetch failed, not the parser: retry, or call `cf_get_problem_statement(2206, "A")` through the MCP, which carries the session cookie, and check the same three things in its `markdown`.

Also confirm no regression on an ordinary problem: fetch `contest/2206/problem/B` the same way and check its Markdown still has `## Input`, `## Output`, `## Example`, `## Note` in that order and `interactive: False`.

- [ ] **Step 8: Commit**

```bash
git add mcp-server/src/cf_mcp/statement.py mcp-server/src/cf_mcp/server.py mcp-server/tests/test_offline.py
git commit -m "feat: flag interactive problems in the statement payload"
```

---

### Task 3: Bind the contest skill to any judge

Replaces every hardcoded Codeforces reference in the contest loop with a four-capability contract discovered at runtime, plus the registry that records per-judge quirks and the fallback for judges with no MCP.

**Files:**
- Modify: `skills/running-contests/SKILL.md`
- Create: `skills/running-contests/references/judges.md`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the anchors `#judge-interface--the-capability-contract` and `#when-no-mcp-covers-this-judge`, which Task 4 and `judges.md` link to; the capability names **list-problems**, **get-statement**, **submit**, **poll-verdict** used throughout the skill.

- [ ] **Step 1: Rewrite the frontmatter description**

Replace the whole `description:` block (`SKILL.md:3-13`) with:

```yaml
description: >
  Orchestrate solving an entire competitive programming contest end to end on
  any judge — Codeforces, AtCoder, CodeChef, Kattis, DMOJ, oj.uz, a gym or a
  virtual round — binding at runtime to whatever judge MCP is installed (fetch
  the problem list, fetch statements, submit, poll verdicts) and delegating the
  algorithm design and C++ to the competitive-programming:solving-problems
  skill. Use this whenever the user wants to work through a whole contest or
  problem set rather than a single problem — phrasings like "solve this
  contest", "grind contest 1998", "do the whole round", "solve problems A–F",
  "run through this contest and submit until AC", or any mention of ICPC-style
  or IOI-style contest mode. Trigger even if the user only gives a contest ID
  or URL and says "go". For a single isolated problem with no contest loop and
  no auto-submission, use competitive-programming:solving-problems directly
  instead.
```

Leave `name: running-contests` alone — it must keep matching the directory.

- [ ] **Step 2: Rewrite the title and intro**

Replace `SKILL.md:16-26` (from `# Codeforces Contest Orchestrator` through `on, when to submit, how to read the result, and what to do next*.`) with:

```markdown
# Contest Orchestrator

Drive a full contest on any competitive programming judge: pull the problems,
solve them one at a time, submit, read the verdict, and iterate to Accepted
before moving to the next — delegating the actual thinking and C++ to the
**competitive-programming:solving-problems** skill and using a **judge MCP** for
everything that touches the judge.

This skill is the *loop and the judge interface*. It does not re-implement
algorithm design — solving-problems already does that well. Keep the division clean:
solving-problems decides *what code to write*; this skill decides *what problem to work
on, when to submit, how to read the result, and what to do next*.
```

- [ ] **Step 3: Replace "Before you start" with the three-part setup and the capability contract**

Replace `SKILL.md:28-43` — the whole `## Before you start — establish the run` section, including the paragraph beginning "Then **discover the MCP tools at runtime**" — with:

```markdown
## Before you start — establish the run

Settle these three things (ask only for what the user hasn't already given):

1. **Which contest, on which judge.** A contest ID or URL. Infer the judge from
   the URL's domain — codeforces.com, atcoder.jp, codechef.com, open.kattis.com,
   dmoj.ca, oj.uz. Ask only when it is genuinely ambiguous, such as a bare
   number with no judge named.
2. **Which mode** — `ICPC` or `IOI`. They change submission strategy (see
   [Modes](#modes)). If the user hasn't said, ask which one.
3. **Which judge interface** — bind the four capabilities below to real tools
   before you open a single problem.

## Judge interface — the capability contract

This skill never hardcodes a judge's tool names. It needs four **capabilities**,
and binds each one to whatever tool the installed MCP actually provides:

| Capability | What it must give you | Used at |
|---|---|---|
| **list-problems** | the contest's problem indices and names; ideally solve counts, points or difficulty | [Ordering](#ordering--easiest-first) |
| **get-statement** | one problem's full statement, limits and samples | loop step 1 |
| **submit** | send source code and a language for one problem | loop step 4 |
| **poll-verdict** | a submission's verdict or score | loop step 5 |

Bind them once, before the first problem:

1. **Read `references/judges.md`** for the judge the user named. An entry there
   gives you the server, the expected bindings, and the judge's quirks — scoring
   rule, language ids, contest URL shapes.
2. **Discover the tools at runtime.** Call `tool_search` with the judge name
   plus capability words ("codeforces contest problems", "atcoder submit",
   "submission verdict") to load the real tool definitions, and read their
   actual parameter names. MCPs vary and a registry entry can go stale — **the
   loaded schema always wins over anything written down.** Never guess a schema.
3. **Bind each capability to one concrete tool** and write the binding down.
4. **State the binding in your first status update**, so the user can correct a
   mis-binding before any submission happens.
5. **If a capability has no tool**, go to
   [When no MCP covers this judge](#when-no-mcp-covers-this-judge). Don't
   improvise a tool name and don't abandon the run.

After this step, reason in capabilities. Concrete tool names live in your
binding and in `references/judges.md` — not in the loop.

## When no MCP covers this judge

A missing MCP moves the judge I/O to the user; it does not end the contest. Say
plainly which capabilities you could not bind, then **offer** this mode — don't
slide into it silently.

| Missing capability | What you do instead |
|---|---|
| **list-problems** | Read the problem list off the contest page with WebFetch, or ask the user for it. |
| **get-statement** | Fetch the problem URL with WebFetch, or ask the user to paste the statement. |
| **submit** | Hand over the final source file path and the exact language to select, and ask the user to submit it. |
| **poll-verdict** | Ask the user to report the verdict verbatim — including the failing test number or the per-subtask scores, which you need in order to debug. |

**Check a fetched statement before you solve it.** It is usable only if it
carries the constraints, the limits, and the samples. If WebFetch returns a
truncated page, a JavaScript shell, or a login wall, stop and ask for a paste.
Solving a partial statement burns a full cycle and produces confidently wrong
code.

Everything else here is unchanged in degraded mode — the ordering, the
per-problem loop, the verification bar for the mode, the stuck triggers, the
progress reporting. Only the judge I/O is manual.
```

- [ ] **Step 4: Generalise the remaining Codeforces-specific passages**

Five edits in `SKILL.md`, each a literal replacement:

1. In `## Ordering — easiest first`, replace the sentence beginning "If the MCP exposes solve counts" and the one after it with:

```markdown
If the **list-problems** capability exposes solve counts, points or difficulty,
order by that (most-solved, or lowest points/difficulty, first). If it doesn't,
fall back to problem-index order (A, B, C… or 1, 2, 3…), which on most judges is
already roughly easy-to-hard. State the order you chose in your first status
update so the user can override.
```

2. In `## What you are optimizing`, insert this immediately after the section heading, before "Get this right":

```markdown
The rule below is the **ICPC/Codeforces penalty model**, the most common one. If
your judge scores differently — AtCoder's points per problem with penalties only
separating equal scores, an IOI-style subtask total — read that judge's actual
rule (`references/judges.md`, or the contest page) and re-derive from it. Two
consequences survive every scoring system in use, so treat them as fixed: **a
solve beats no solve**, and **an attempt on a problem you have not solved costs
almost nothing.**
```

3. In `## The per-problem loop`, replace steps 1, 4 and 5's opening sentences:

```markdown
1. **Fetch the statement** via the **get-statement** capability. Read it fully —
   constraints, time/memory limits, and all samples.
```

```markdown
4. **Submit** via the **submit** capability. Pick the C++ language from the ids
   that tool actually offers — discover them, don't assume a numbering. A
   judge's language ids mean nothing on another judge.
```

```markdown
5. **Poll the verdict** via the **poll-verdict** capability. Submissions judge
   asynchronously. Poll until the verdict leaves "In queue"/"Running"/"Testing",
   at a reasonable interval (a few seconds between checks); don't hammer it, and
   don't assume an immediate result.
```

4. Under `### Verdict handling`, insert this line directly above the table:

```markdown
Judges spell verdicts differently — `AC`/`OK`/`Accepted`, `WA`/`Wrong answer`,
`TLE`, `MLE`, `RE`, `CE`, `ILE`/`Idleness limit exceeded`. Match on **meaning**,
not on the exact string. A verdict that maps to no row is surprising: report it
rather than guessing.
```

5. In `## Guardrails`, replace the first bullet with:

```markdown
- **One contest, one judge, the user's.** Only operate on the contest the user
  named, on the judge they named. Don't fetch or submit anywhere else.
```

- [ ] **Step 5: Show the binding in the progress format**

In `## Progress reporting`, replace the two fenced status blocks' first lines so the judge and binding are visible:

```
Codeforces 1998 · ICPC mode · order by solves · judge MCP: codeforces
```

```
Codeforces 1998 · IOI mode · order by index · judge MCP: codeforces
```

- [ ] **Step 6: Write the judge registry**

Create `skills/running-contests/references/judges.md`:

````markdown
# Judge registry

Per-judge notes for [running-contests](../SKILL.md): how a judge's MCP binds to
the four capabilities, and the quirks worth knowing before you submit anything.

**The loaded tool schema always wins over this file.** These entries are a
starting point and a place to record quirks — they are not authoritative about a
server's current parameters. Discover the real schema with `tool_search`, per
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
discovery procedure anyway: if an MCP for that judge is installed, `tool_search`
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
````

Do **not** add speculative AtCoder or CodeChef entries. Inventing tool names for
servers that don't exist yet produces a registry that contradicts the real
server when it lands.

- [ ] **Step 7: Verify the skill still loads and no tool names leaked**

```bash
claude plugin validate . --strict
claude plugin details competitive-programming
grep -rn "cf_" skills/ | grep -v "references/judges.md"   # expect: no output
grep -rn "Codeforces MCP\|the MCP\b" skills/running-contests/SKILL.md  # expect: no output
grep -n "Codeforces" skills/running-contests/SKILL.md
```

Expected: validation passes; the inventory still shows 2 skills and 1 MCP server; the first two greps print nothing; the last shows Codeforces only as one judge among several (the description, the domain list, the ICPC penalty-model note) and never as the assumed judge.

- [ ] **Step 8: Commit**

```bash
git add skills/running-contests/SKILL.md skills/running-contests/references/judges.md
git commit -m "feat: drive contests on any judge via a capability contract

Bind list-problems/get-statement/submit/poll-verdict to whatever judge MCP
is installed, record per-judge quirks in a registry, and fall back to a
human-in-the-loop mode when no MCP covers the judge."
```

---

### Task 4: Teach the loop about interactive problems

**Files:**
- Modify: `skills/running-contests/SKILL.md`

**Interfaces:**
- Consumes: `Statement.interactive` from Task 2 (the section tells the reader the Codeforces statement tool returns `interactive: true`); the `#when-no-mcp-covers-this-judge` anchor from Task 3.
- Produces: the anchor `#interactive-problems`, which `references/judges.md` links to.

- [ ] **Step 1: Add the section**

Insert into `skills/running-contests/SKILL.md` between `### Verdict handling` and `## When a problem won't fall`:

```markdown
## Interactive problems

Some problems talk to the judge instead of reading a fixed input. The statement
gives it away: an **Interaction** section, a query format, a query budget, and
usually no output specification. A judge MCP may flag it too — the Codeforces
server returns `interactive: true`.

They break three assumptions the normal loop makes:

- **Flush after every write.** Use `cout << … << endl;` or an explicit
  `cout.flush()` after each query. Buffered output deadlocks against the judge
  and scores Idleness Limit Exceeded — the fast-I/O habit of avoiding `endl` is
  exactly wrong here.
- **The sample is a transcript, not a test file.** Its two blocks are the two
  sides of a dialogue. Piping the sample input into your program and diffing the
  output proves nothing; don't report that as verification.
- **Stress testing needs a mock interactor**, not a brute-force oracle: a
  program that holds a hidden instance, answers queries by the statement's rule,
  counts them against the budget, and checks your final answer. Write that when
  an interactive problem needs stress testing, and drive your solution through a
  pipe.

Read the query budget as a constraint like any other — it usually names the
intended algorithm (about n log n queries → sorting or binary search; about 2n →
a linear scan; about log n → binary search on the answer).
```

- [ ] **Step 2: Point the Idleness verdict row at it**

In the verdict table, replace the `Idleness Limit Exceeded` row's response cell with:

```markdown
Flush after each write — see [Interactive problems](#interactive-problems). If the problem isn't interactive, you are not reading input to end of stream.
```

- [ ] **Step 3: Verify**

```bash
claude plugin validate . --strict
grep -n "interactive-problems" skills/running-contests/SKILL.md skills/running-contests/references/judges.md
```

Expected: validation passes; the grep shows the anchor defined in `SKILL.md` and linked from both the verdict row and `judges.md` (the `judges.md` link was written in Task 3, so it now resolves).

- [ ] **Step 4: Commit**

```bash
git add skills/running-contests/SKILL.md
git commit -m "docs: handle interactive problems in the contest loop"
```

---

### Task 5: Update the plugin's own description of itself

**Files:**
- Modify: `README.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

**Interfaces:**
- Consumes: the finished skill from Tasks 3–4.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Update the README skill table and layout**

In `README.md`, replace the `running-contests` row with:

```markdown
| Skill `running-contests` | `competitive-programming:running-contests` | Drives a whole contest on any judge: binds to whatever judge MCP is installed, pulls the problem set, orders it, delegates each problem to `solving-problems`, submits, reads verdicts, and keeps going until every problem is solved |
```

And in the Layout tree, replace the `running-contests` line with:

```
│   └── running-contests/SKILL.md   (+ references/judges.md)
```

- [ ] **Step 2: Update both manifests**

In `.claude-plugin/plugin.json` and the plugin entry in `.claude-plugin/marketplace.json`, set both `version` fields to `"0.3.0"` and both `description` fields to the same string:

```
Competitive programming: single-problem solving, full-contest orchestration on any judge, and the bundled Codeforces MCP server
```

- [ ] **Step 3: Verify**

```bash
claude plugin validate . --strict
claude plugin details competitive-programming
grep -n '"version"' .claude-plugin/plugin.json .claude-plugin/marketplace.json
```

Expected: validation passes; details reports 2 skills and 1 MCP server with the new description; both versions read `0.3.0`.

- [ ] **Step 4: Commit**

```bash
git add README.md .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "docs: describe the contest skill as judge-agnostic, bump to 0.3.0"
```

---

## Final verification

- [ ] `cd mcp-server && uv run --extra dev pytest -q` — whole suite passes.
- [ ] `claude plugin validate . --strict` — passes.
- [ ] `grep -rn "cf_" skills/ | grep -v references/judges.md` — no output.
- [ ] `cf_get_problem_statement(2206, "A")` through the reloaded MCP returns `interactive: true` and a `markdown` containing the query format, the query budget, and the flush requirement.
- [ ] A normal problem's Markdown is unchanged in shape: `## Input`, `## Output`, `## Example`, `## Note`, in that order.
- [ ] Tell the user to run `/reload-plugins` (or restart the session) before using the updated skill and server.

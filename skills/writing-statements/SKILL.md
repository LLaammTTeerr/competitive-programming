---
name: writing-statements
description: >
  Use when authoring, translating, or reviewing a competitive-programming
  problem statement for the vnolymp LaTeX template — the Vietnamese
  statement package for problems prepared on Polygon. Triggers on requests
  to write a statement from a problem idea or notes, translate an English
  or Codeforces-style statement into Vietnamese, fix up the statement a
  Polygon package export generated, assemble several problems into a
  contest booklet, or check an existing .tex statement for errors. Also
  triggers on mentions of vnolymp, olymp.sty, \exmpfile, subtasks tables,
  "đề bài", "statement tiếng Việt", or a problem directory containing
  statement.tex plus .in/.out sample files. This is the problem-setter
  side; for solving a problem use competitive-programming:solving-problems
  instead.
---

# Writing vnolymp statements

The template is well documented and its reference — `docs/AUTHORING.md` in
the template repo — is the authority on syntax. Read it; don't work from
memory. This skill covers what that reference does not: how to build from a
problem directory outside the template checkout, what "done" means, and the
conventions that keep twenty statements in a booklet looking like one
document.

## Get the template

The package is not on CTAN. Clone it shallow (908K) and cache it, so a
second problem costs nothing:

```bash
VNOLYMP="${XDG_CACHE_HOME:-$HOME/.cache}/vnolymp"
REPO=https://github.com/LLaammTTeerr/vietnamese-polygon-statement-latex.git

if [ ! -d "$VNOLYMP" ]; then
    # Clone aside and move into place, rather than cloning straight to the
    # cache path. Statements get written one per problem, so several copies
    # of this skill can run at once; a bare `[ -d ] || git clone` lets the
    # second one find a directory that exists but is still half-populated,
    # and build against an incomplete checkout.
    staging="$(mktemp -d "$VNOLYMP.XXXXXX")"
    git clone --depth 1 -q "$REPO" "$staging/vnolymp"
    mv -T "$staging/vnolymp" "$VNOLYMP" 2>/dev/null || true  # first writer wins
    rm -rf "$staging"
fi
git -C "$VNOLYMP" pull --ff-only -q 2>/dev/null || true   # offline, or lost a race
```

The clone brings `docs/AUTHORING.md` and `samples/` with it. Read
`AUTHORING.md` from the cache — it is the version that matches the `.sty`
you are about to compile, which a copy pasted into a skill never is.
`samples/kitchen-sink/kitchen-sink.tex` is the widest worked example;
`samples/minimal/minimal.tex` is the smallest.

## Build

```bash
cd <problem dir>
export TEXINPUTS=".:$VNOLYMP:"
latexmk -lualatex -interaction=nonstopmode <problem>.tex
```

**Keep `.` first in `TEXINPUTS`.** It makes every file in the checkout
visible to your build, and the checkout has a `problem.tex` of its own — the
name Polygon requires — plus, in checkouts from before mid-2026, a
`statement.tex` and `contest.tex`. Without the leading `.`, a file of yours
sharing one of those names can lose the lookup, and the engine compiles a
document you never wrote and reports

```
! LaTeX Error: Environment problem undefined.
```

at a line inside someone else's file. Nothing in the message names the
cause, so it costs a long detour the first time.

When you are **creating** the statement, name it after the problem —
`chiaqua.tex` — which sidesteps the collision entirely and reads better in
a directory listing. When you are **reviewing** a file the author already
has, leave its name alone even if it is `statement.tex`: `.` first already
resolves the ambiguity in their favour, and renaming someone's file is a
larger change than a review was asked to make. Mention the hazard instead
and let them decide.

Use `latexmk`, not bare `lualatex`. The footer's page total, the cover's
overview table, and the "Bài N." numbering all come from the `.aux` file
written by the previous run, so the document needs two passes and a single
pass produces `??` and an empty table **with no error**. `latexmk` runs the
passes for you; a hand-written `lualatex && lualatex` is one edit away from
becoming a single pass.

## Done means the PDF is right, not that the build exited 0

The package compiles happily while producing a document with missing
glyphs, a subtask table that doesn't add up, or text overflowing the page.
Check the log and the text:

```bash
grep -iE 'missing character|undefined control sequence|overfull|underfull' <problem>.log
grep -iE 'subtask|vnolymp' <problem>.log     # the package's own warnings
pdftotext -layout <problem>.pdf - | head -40
```

All three matter for a reason:

- **Missing character** means a Vietnamese diacritic silently vanished from
  the PDF. The text still looks present in your `.tex`.
- Subtask percentages that don't sum to 100 are a **warning, not an
  error** — deliberately, so work-in-progress compiles. Nothing else will
  ever tell you.
- The `pdftotext` pass is where you confirm the limits panel reads `1 giây`
  / `256 MB` and the headings came out in the right language.

Report what you checked. "It builds" is not a result; "PDF, 2 pages, log
clean, panel reads 1 giây / 256 MB" is.

## Statement shape

Follow this order. It is what the template's own samples do, and a booklet
whose problems agree on it reads as one paper:

1. **Story and task**, straight after `\begin{problem}`, no heading. Close
   it with a `\textbf{Yêu cầu:}` line stating precisely what to compute.
2. `\InputFile` — an `itemize` describing the lines, structure only.
3. `\OutputFile` — what to print, including the degenerate case.
4. `\Constraints` — the numeric bounds, as an `itemize`. Hoist them out of
   the input description even when the source statement buried them there;
   a reader checking whether their `long long` is wide enough should not
   have to read prose to find out.
5. `subtasks` environment. It emits its own "Chấm điểm" heading.
6. `\Examples` with `\exmpfile` — only when the sample files exist; see
   below.
7. `\Explanation` walking through the first sample, when there is one. Use
   `\Explanation` ("Giải thích"), not `\Note` ("Chú ý"), when the content
   explains a sample — reserve `\Note` for a genuine aside.

Keep `\begin{problem}`'s key list to bare numbers for `time` and `memory`;
the package owns the units. Everything else about the key list is in
`AUTHORING.md` §2.

Use `standalone` for a single problem and `booklet` with `\contest{}` plus
`\vnolympcover` for several. When the source gives no contest name, date,
or location, `standalone` is the honest choice — a cover page with three
blanks on it is worse than no cover page.

## Sample data belongs to whatever produces the tests

Sample tests live in files and come in through `\exmpfile`; inline data is
impossible, not merely discouraged, and `AUTHORING.md` §5 explains why.

**Wire up sample files; do not author them.** Test data is the test
generator's output, checked by the checker and the model solution. A sample
invented while writing prose has none of that behind it — and a wrong
expected output is the most expensive error a statement can carry, because
it looks authoritative, contradicts the real tests, and contestants find it
before the setter does.

- **Tests already exist** (a Polygon export, or generated tests in the
  problem directory) — reference them with `\exmpfile`, and read them so the
  Input and Output sections actually describe the format they're in.
- **No tests yet** — leave the `\Examples` block out and say so. A statement
  whose `\exmpfile` points at files that don't exist does not compile, which
  would forfeit the whole verification pass below over data that isn't yours
  to write. Note in the report exactly what to add once the tests land:

  ```latex
  \Examples
  \begin{example}
  \exmpfile{ex1.in}{ex1.out}%
  \end{example}
  ```

  Then hand off to test generation. Statements and tests converge from two
  directions; this skill owns the prose and the build, not the data.

## Surface the ambiguities you find

Writing a statement precisely is how underspecified problems get caught.
When the notes and the required output disagree, that is a finding, not an
obstacle to route around: a problem whose notes say "print 0 if no valid
segment exists" while the empty segment trivially sums to 0 has a real bug,
and the statement cannot be made correct without a decision.

Make the minimum assumption needed to write a coherent statement, then
report it explicitly and name what changes if the author decides otherwise.
Silently resolving it produces a statement that reads fine and describes a
different problem than the tests.

## Reference

Everything about syntax lives in `$VNOLYMP/docs/AUTHORING.md`: package
options and the two-pass rule (§1), the `problem` key list and numbering
(§2), section commands (§3), subtasks (§4), sample tests and figures (§5),
editorials (§6), deliberate surprises (§7), and migrating legacy statements
(§8). Read the section you need rather than guessing — the package's
failure modes are mostly silent, which is exactly when guessing costs most.

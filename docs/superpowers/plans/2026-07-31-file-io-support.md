# File-Based IO Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the invocation matrix run VOI/vnolymp-style problems that read `<name>.inp` and write `<name>.out`, replacing the hard refusal at `run_matrix.py:1007` with a proven path.

**Architecture:** The driver already speaks in paths everywhere except one function. `_run_once()` mounts the binary's directory read-only, mounts one private `:rw` staging directory, and wires `--stdin`/`--stdout`. File IO changes three things inside that function: the test input is *copied into* the staging directory under the problem's input filename, `--chdir` points at the staging directory instead of the read-only binary directory, and the output is read back from `stage_dir/<io.output>` instead of the staged stdout. Nothing downstream changes, because everything downstream already receives a path to an output file. A new `NO_OUTPUT` verdict covers the case a stdin/stdout problem cannot have: the process exits cleanly and never creates its output file.

**Tech Stack:** Python 3.10+ stdlib only (no venv, no third-party imports — this is a hard project constraint). `ioi/isolate` 2.6 as the sandbox. `qhhoj/testlib` 0.9.52 for checkers.

## Global Constraints

- **stdlib only.** No third-party imports in `tools/`. No `requirements.txt`, no venv.
- **`python3 -m unittest discover -s tools/tests -t .` must be run ALONE.** `run_matrix` derives isolate box ids from `pid`; a concurrent run collides and produces spurious failures that have already misled three agents.
- **Never modify anything under `~/Projects/my_cp_problems/`.** Compile and stage to temp paths only. Clean up isolate boxes you create.
- **R1 (standing):** externally-authored data must never surface a bare stdlib exception. Raise the module's own error type (`ProblemMetaError`, `MatrixError`).
- **Evidence standard (standing):** a claim in a docstring or a skill is a testable assertion. If you write "X is guaranteed", there must be a test that fails when X stops being true. This project shipped four docstrings asserting things the code did not do; two were the controller's own words transcribed into source.
- **Verification standard (standing):** an error path you have not triggered is not handled. A command you have not run from a foreign working directory is not runnable. Do not report a claim as verified because you read the code.
- **`_SEVERITY` ordering is load-bearing.** `FAIL` must never be masked by a solution's own failure. `NO_OUTPUT` joins it in that category.
- **The `holes` definition does not change.** It is the pipeline's one non-circular claim: a hole is a solution declared wrong that no test killed.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `tools/problem_meta.py` | source of truth for `problem.json` | validate `io.input`/`io.output` shape at load |
| `tools/matrix_core.py` | pure timing/verdict model | add `NO_OUTPUT` to `_SEVERITY` |
| `tools/run_matrix.py` | the sandboxed driver | file-IO wiring in `_run_once`; drop the refusal in `run()` |
| `tools/drift_check.py` | statement vs `problem.json` | cover the vnolymp `input =` / `output =` keys |
| `tools/tests/test_*.py` | | one test file per module above |

**Why `classify()` is not in this table.** Passing `checker_verdict="NO_OUTPUT"` flows through its existing passthrough (`matrix_core.py:65`), and it decides time *before* correctness (`:59-62`), so a timed-out run can never be misreported as NO_OUTPUT. Adding the entry to `_SEVERITY` is necessary and sufficient. Do not change `classify()`'s signature.

---

### Task 1: Validate the io filenames

`problem_meta.py:359-360` reads `io.get("input", "stdin")` and `io.get("output", "stdout")` as unvalidated free strings. Stage 2's `_string()` sweep did not reach them. These values reach a `--dir` mount and a filename join, so a path separator or a `..` segment is a real escape.

**Files:**
- Modify: `tools/problem_meta.py:359-360`
- Test: `tools/tests/test_problem_meta.py`

**Interfaces:**
- Consumes: the existing `_string(value, *, where)` helper added in Stage 2 (commit `5742d08`) and `ProblemMetaError`.
- Produces: `Problem.input` / `Problem.output` guaranteed to be either the exact literals `"stdin"`/`"stdout"` or a bare filename with no separator and no dot-segment.

- [ ] **Step 1: Write the failing tests**

```python
def test_io_input_rejects_path_separator(self):
    with self.assertRaises(ProblemMetaError) as ctx:
        self._load_with_io({"input": "sub/dir.inp", "output": "x.out"})
    self.assertIn("io.input", str(ctx.exception))

def test_io_output_rejects_dot_segment(self):
    with self.assertRaises(ProblemMetaError) as ctx:
        self._load_with_io({"input": "x.inp", "output": "../escape.out"})
    self.assertIn("io.output", str(ctx.exception))

def test_io_rejects_non_string(self):
    with self.assertRaises(ProblemMetaError):
        self._load_with_io({"input": 5, "output": "x.out"})

def test_io_rejects_empty_string(self):
    with self.assertRaises(ProblemMetaError):
        self._load_with_io({"input": "", "output": "x.out"})

def test_io_accepts_stdin_stdout_and_bare_filenames(self):
    p = self._load_with_io({"input": "stdin", "output": "stdout"})
    self.assertEqual((p.input, p.output), ("stdin", "stdout"))
    p = self._load_with_io({"input": "flight.inp", "output": "flight.out"})
    self.assertEqual((p.input, p.output), ("flight.inp", "flight.out"))
```

Add the `_load_with_io` helper to the test class if one does not already exist: it deep-copies the `mini` fixture's `problem.json`, replaces its `io` object, writes it to a temp dir, and returns `load(...)`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd /home/lamter/.claude/skills/competitive-programming && python3 -m unittest tools.tests.test_problem_meta -v`
Expected: the four rejection tests FAIL (no exception raised); the acceptance test passes.

- [ ] **Step 3: Implement**

In `problem_meta.py`, add beside the other helpers:

```python
def _io_name(value: object, *, where: str, literal: str) -> str:
    """Validate an `io.input`/`io.output` value.

    Either the exact sentinel (`stdin`/`stdout`) or a bare filename. The
    value reaches an isolate `--dir` mount and a filename join, so a
    separator or a dot-segment is an escape, not a style problem.
    """
    name = _string(value, where=where)
    if name == literal:
        return name
    if not name:
        raise ProblemMetaError(f"{where} must not be empty")
    if "/" in name or "\\" in name or "\0" in name:
        raise ProblemMetaError(
            f"{where} must be a bare filename with no path separator, got {name!r}"
        )
    if name in (".", "..") or name.startswith("../") or name.startswith("./"):
        raise ProblemMetaError(f"{where} must not contain a path segment, got {name!r}")
    return name
```

Then change lines 359-360 to:

```python
        input=_io_name(io.get("input", "stdin"), where="io.input", literal="stdin"),
        output=_io_name(io.get("output", "stdout"), where="io.output", literal="stdout"),
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m unittest tools.tests.test_problem_meta -v`
Expected: PASS, and no other test regresses.

- [ ] **Step 5: Commit**

```bash
git add tools/problem_meta.py tools/tests/test_problem_meta.py
git commit -m "Validate io.input/io.output as bare filenames"
```

---

### Task 2: The NO_OUTPUT verdict

**Files:**
- Modify: `tools/matrix_core.py:68-72`
- Test: `tools/tests/test_matrix_core.py`

**Interfaces:**
- Produces: `"NO_OUTPUT"` is a legal verdict string for `group_verdict()` and `compare()`. It ranks second, immediately after `FAIL`.
- **Not** added to `_FAILING`, and **not** added to `scan_solutions.VERDICTS`. `NO_OUTPUT` parallels `FAIL` exactly: the harness discovers it, a solution never declares it. `_FAILING` drives the hole rule ("declared to fail but got OK"), and no author can declare NO_OUTPUT, so membership there would be meaningless.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_output_ranks_just_below_fail(self):
    self.assertEqual(group_verdict(["OK", "NO_OUTPUT", "WA"]), "NO_OUTPUT")
    self.assertEqual(group_verdict(["FAIL", "NO_OUTPUT"]), "FAIL")

def test_no_output_outranks_every_solution_verdict(self):
    for weaker in ("TL", "ML", "RE", "PE", "WA", "OK"):
        self.assertEqual(group_verdict([weaker, "NO_OUTPUT"]), "NO_OUTPUT", weaker)

def test_no_output_is_not_declarable(self):
    from tools.scan_solutions import VERDICTS
    self.assertNotIn("NO_OUTPUT", VERDICTS)

def test_classify_passes_no_output_through_but_time_wins(self):
    limits = Limits(tl_ms=1000, kill_ms=2000)
    self.assertEqual(classify(10, False, "NO_OUTPUT", limits).verdict, "NO_OUTPUT")
    # A run that exceeded the limit is TL, never NO_OUTPUT — time is decided first.
    self.assertEqual(classify(1500, False, "NO_OUTPUT", limits).verdict, "TL")
    self.assertEqual(classify(10, True, "NO_OUTPUT", limits).verdict, "TL")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tools.tests.test_matrix_core -v`
Expected: the `group_verdict` tests FAIL with `ValueError: unknown verdicts in group`.

- [ ] **Step 3: Implement**

In `matrix_core.py`, replace the `_SEVERITY` block and its comment:

```python
# Worst-first. FAIL is a package bug and must never be masked by a solution's
# own failure; NO_OUTPUT is the same category — the harness could not evaluate
# the run at all (the process exited cleanly and never wrote its output file,
# usually a wrong filename rather than a wrong algorithm), so it must not be
# masked either. TL outranks WA because the judge stops before the checker runs.
_SEVERITY = ["FAIL", "NO_OUTPUT", "TL", "ML", "RE", "PE", "WA", "OK"]

# Verdicts an author can DECLARE for a solution. NO_OUTPUT and FAIL are
# absent by design: both are discovered by the harness, never declared.
_FAILING = {"WA", "TL", "ML", "PE", "RE"}
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m unittest tools.tests.test_matrix_core -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/matrix_core.py tools/tests/test_matrix_core.py
git commit -m "Add the NO_OUTPUT verdict, ranked next to FAIL"
```

---

### Task 3: File-IO wiring in `_run_once`

This is the task that carries the real risk. Read the whole of `_run_once` (`run_matrix.py:673-830`) and its docstring before changing anything.

**Files:**
- Modify: `tools/run_matrix.py:673-830`
- Test: `tools/tests/test_run_matrix.py`

**Interfaces:**
- Consumes: `IsolateHandle` (fields `binary`, `meta_path`, `stage_dir`), `RunResult`.
- Produces: `_run_once(isolate, binary, stdin_path, stdout_dest, cpu_limit_s, wall_limit_s, mem_limit_kb, *, io_input="stdin", io_output="stdout") -> RunResult`. The two new keyword-only parameters default to the sentinels, so every existing call site keeps its current behaviour unchanged. `RunResult` gains one field: `no_output: bool = False`.

**Three things that must be true, each earned by a bug this project already shipped:**

1. **The staging directory must stay disk-backed.** `_stage_base()` already refuses a memory-backed location, because on tmpfs the solution's own output is charged to its own `--cg-mem` — the false-ML this driver spent three tasks relocating. Do not add a second writable mount, and do not move the input staging anywhere else.
2. **Stale output must be deleted before every run.** `_time_median()` calls `_run_once` three times. The existing code already does `staged_out.unlink(missing_ok=True)`; the `io_output` file needs exactly the same treatment. Without it, run N reads run N-1's output, or worse, solution B reads solution A's. This is the same contamination shape as the three memory bugs.
3. **`--chdir` currently points at a read-only mount.** `cmd` sets `--chdir={bin_label}`, and `bin_label` is mounted without `:rw`. A file-IO solution chdir'd there cannot create its output file at all. It must become `{stage_label}` in the file-IO path.

- [ ] **Step 1: Write the failing tests**

```python
def test_file_io_solution_reads_inp_and_writes_out(self):
    """A solution that only touches files — never stdin/stdout — is run correctly."""
    src = self.tmp / "fileio.cpp"
    src.write_text(
        '#include <cstdio>\n'
        'int main(){FILE*fi=fopen("t.inp","r");if(!fi)return 3;'
        'int a,b;fscanf(fi,"%d %d",&a,&b);fclose(fi);'
        'FILE*fo=fopen("t.out","w");fprintf(fo,"%d\\n",a+b);fclose(fo);return 0;}\n'
    )
    binary = self._compile(src)
    test_in = self.tmp / "01.in"
    test_in.write_text("2 3\n")
    dest = self.tmp / "01.produced"
    with _isolate_handle() as h:
        r = _run_once(h, binary, test_in, dest, 2.0, 4.0, 262144,
                      io_input="t.inp", io_output="t.out")
    self.assertFalse(r.crashed, "solution should not have crashed")
    self.assertFalse(r.no_output)
    self.assertEqual(dest.read_text().strip(), "5")

def test_missing_output_file_is_reported_not_crashed(self):
    """Exits 0, writes nothing — the case a stdin/stdout problem cannot have."""
    src = self.tmp / "silent.cpp"
    src.write_text("int main(){return 0;}\n")
    binary = self._compile(src)
    test_in = self.tmp / "01.in"
    test_in.write_text("2 3\n")
    dest = self.tmp / "01.produced"
    with _isolate_handle() as h:
        r = _run_once(h, binary, test_in, dest, 2.0, 4.0, 262144,
                      io_input="t.inp", io_output="t.out")
    self.assertFalse(r.crashed, "a clean exit is not a crash")
    self.assertTrue(r.no_output, "absent output file must be reported")

def test_output_file_does_not_leak_between_runs(self):
    """Run 1 writes; run 2 writes nothing. Run 2 must NOT see run 1's output."""
    writer = self._compile_source(
        '#include <cstdio>\nint main(){FILE*f=fopen("t.out","w");'
        'fprintf(f,"first\\n");fclose(f);return 0;}\n', "writer.cpp")
    silent = self._compile_source("int main(){return 0;}\n", "silent2.cpp")
    test_in = self.tmp / "01.in"
    test_in.write_text("x\n")
    d1, d2 = self.tmp / "a.produced", self.tmp / "b.produced"
    with _isolate_handle() as h:
        _run_once(h, writer, test_in, d1, 2.0, 4.0, 262144,
                  io_input="t.inp", io_output="t.out")
        r2 = _run_once(h, silent, test_in, d2, 2.0, 4.0, 262144,
                       io_input="t.inp", io_output="t.out")
    self.assertEqual(d1.read_text().strip(), "first")
    self.assertTrue(r2.no_output, "run 2 must not inherit run 1's output file")

def test_large_output_file_is_not_charged_to_memory(self):
    """Risk 1: the tmpfs bug, a fourth time. A big .out must not read as ML."""
    src = self._compile_source(
        '#include <cstdio>\nint main(){FILE*f=fopen("t.out","w");'
        'for(long i=0;i<400000;i++)fprintf(f,"0123456789\\n");fclose(f);return 0;}\n',
        "big.cpp")
    test_in = self.tmp / "01.in"
    test_in.write_text("x\n")
    dest = self.tmp / "big.produced"
    with _isolate_handle() as h:
        r = _run_once(h, src, test_in, dest, 10.0, 20.0, 65536,
                      io_input="t.inp", io_output="t.out")
    self.assertFalse(r.oom, "a large output file must not be charged to --cg-mem")

def test_stdin_mode_is_unchanged(self):
    """The default path must behave exactly as before."""
    src = self._compile_source(
        "#include <cstdio>\nint main(){int a,b;scanf(\"%d %d\",&a,&b);"
        "printf(\"%d\\n\",a+b);return 0;}\n", "stdio.cpp")
    test_in = self.tmp / "01.in"
    test_in.write_text("7 8\n")
    dest = self.tmp / "s.produced"
    with _isolate_handle() as h:
        r = _run_once(h, src, test_in, dest, 2.0, 4.0, 262144)
    self.assertFalse(r.crashed)
    self.assertFalse(r.no_output)
    self.assertEqual(dest.read_text().strip(), "15")
```

Match the existing helpers in `test_run_matrix.py` for compiling and for obtaining an `IsolateHandle` — do not invent new ones if equivalents exist; reuse them and adapt these tests' names to match.

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tools.tests.test_run_matrix -v`
Expected: the five new tests FAIL with `TypeError: _run_once() got an unexpected keyword argument 'io_input'`, except `test_stdin_mode_is_unchanged`, which passes already.

- [ ] **Step 3: Implement**

Add the field to `RunResult`:

```python
    no_output: bool = False
```

Document it in the class docstring beside `oom`/`killed`/`crashed`: *"`no_output` means the process exited without being killed and never created the problem's output file. Only reachable in file-IO mode — a stdin/stdout run always has a stdout file. It is not a crash: the exit status was clean."*

Change the signature:

```python
def _run_once(isolate: IsolateHandle, binary: Path, stdin_path: Path,
              stdout_dest: Path, cpu_limit_s: float, wall_limit_s: float,
              mem_limit_kb: int, *, io_input: str = "stdin",
              io_output: str = "stdout") -> RunResult:
```

Inside the `try:` block, after `stage_label` is computed and before `cmd` is built:

```python
        file_io = io_input != "stdin" or io_output != "stdout"

        staged_out = isolate.stage_dir / "run.out"
        staged_out.unlink(missing_ok=True)

        # In file-IO mode the solution reads and writes real files in its cwd,
        # which must be the ONE `:rw` mount. Both are unlinked first: a stale
        # file from an earlier run (`_time_median` calls this three times, and
        # every solution reuses the handle) would otherwise be read as this
        # run's output.
        staged_in = staged_result = None
        if file_io:
            staged_in = isolate.stage_dir / io_input
            staged_result = isolate.stage_dir / io_output
            staged_in.unlink(missing_ok=True)
            staged_result.unlink(missing_ok=True)
            shutil.copyfile(stdin_path, staged_in)
```

Then in `cmd`, replace the `--chdir`/`--stdin` lines:

```python
        cmd += [
            f"--chdir={stage_label if file_io else bin_label}",
            f"--stdin={stage_label}/{staged_in.name}" if file_io
            else f"--stdin={stdin_label}/{stdin_path.name}",
            f"--stdout={stage_label}/{staged_out.name}",
            "--", f"{bin_label}/{binary.name}",
        ]
```

Keep `--stdout` pointed at `run.out` in **both** modes: a file-IO solution that also prints debug output writes it there, where it is discarded, and `--fsize` still caps it.

In file-IO mode `--stdin` is pointed at the staged copy rather than the original, so a solution that reads stdin *as well as* the file still sees the test data, and `stdin_label` may go unused — that is fine, the mount is harmless.

At the copy-back point (replacing the existing `stdout_dest.unlink(...)` / `write_bytes(data)`):

```python
        source = staged_result if file_io else staged_out
        if file_io and not source.exists():
            return replace(result, no_output=True)
        data = source.read_bytes()
        stdout_dest.unlink(missing_ok=True)
        stdout_dest.write_bytes(data)
```

Adapt the surrounding names to the code actually there — `result` above stands for whatever `RunResult` the existing code has built by that point. Add `import shutil` and `from dataclasses import replace` if absent.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m unittest tools.tests.test_run_matrix -v`
Expected: PASS, all five. Then run the FULL suite alone and confirm no regression.

- [ ] **Step 5: Commit**

```bash
git add tools/run_matrix.py tools/tests/test_run_matrix.py
git commit -m "Wire file-based IO through _run_once"
```

---

### Task 4: Drop the refusal and thread io through `run()`

**Files:**
- Modify: `tools/run_matrix.py:1003-1016` (the refusal), plus the `_run_once`/`_time_median` call sites and `_classify`
- Test: `tools/tests/test_run_matrix.py`

**Interfaces:**
- Consumes: Task 1's validated `problem.input`/`problem.output`, Task 2's `NO_OUTPUT`, Task 3's `no_output` field.
- Produces: `run()` accepts a file-IO problem end to end and writes a normal `invocation.json`.

- [ ] **Step 1: Write the failing test**

```python
def test_run_accepts_a_file_io_problem(self):
    """The refusal is gone and a file-IO package produces a real matrix."""
    pkg = self._make_file_io_package()   # io.input="t.inp", io.output="t.out"
    result = run(pkg, self.testlib, runs=1)
    self.assertEqual(result["holes"], [])
    self.assertEqual(result["mismatches"], [])

def test_solution_that_never_writes_output_is_NO_OUTPUT(self):
    pkg = self._make_file_io_package(extra_solution=("silent.cpp", "wrong-answer",
                                                     "int main(){return 0;}\n"))
    result = run(pkg, self.testlib, runs=1)
    verdicts = {row["solution"]: row["verdict"] for row in result["rows"]}
    self.assertEqual(verdicts["silent.cpp"], "NO_OUTPUT")
```

Adapt the row/field names to `invocation.json`'s actual schema — read one before writing this test.

- [ ] **Step 2: Run to verify it fails**

Expected: `MatrixError: file-based IO is not supported by this driver`.

- [ ] **Step 3: Implement**

Delete the `if problem.input != "stdin" or problem.output != "stdout": raise MatrixError(...)` block at `:1006-1016`. Thread `io_input=problem.input, io_output=problem.output` through every `_run_once` and `_time_median` call site. In `_classify`, before consulting the checker, add:

```python
    if r.no_output:
        return "NO_OUTPUT"
```

placed beside the existing `crashed` short-circuit, so the checker is never handed a nonexistent file. Order matters: `killed`/`crashed` are checked first, exactly as now — a solution that segfaulted is RE, not NO_OUTPUT.

- [ ] **Step 4: Run to verify it passes**

Run the full suite alone.

- [ ] **Step 5: Commit**

```bash
git add tools/run_matrix.py tools/tests/test_run_matrix.py
git commit -m "Accept file-based IO problems in run()"
```

---

### Task 5: Drift-check the io keys

The statement's vnolymp `input =` / `output =` keys must agree with `problem.json`. This is the same class of drift `drift_check` already guards for bounds — a statement promising `flight.inp` while `problem.json` says `stdin` sends every solution to a NO_OUTPUT verdict with no explanation.

**Files:**
- Modify: `tools/drift_check.py`
- Test: `tools/tests/test_drift_check.py`

**Interfaces:**
- Consumes: `parse_tex(tex_text)`, `check(problem, tex_text)`, the existing brace-aware keylist scanner.
- Produces: `check()` reports a drift entry when the `.tex` `input`/`output` keys disagree with `problem.input`/`problem.output`.

- [ ] **Step 1: Write the failing tests**

```python
def test_io_drift_is_reported(self):
    tex = self._tex(input_key="stdin", output_key="stdout")
    problem = self._problem(io_input="t.inp", io_output="t.out")
    drift = check(problem, tex)
    self.assertTrue(any("input" in d for d in drift), drift)

def test_matching_io_is_not_reported(self):
    tex = self._tex(input_key="t.inp", output_key="t.out")
    problem = self._problem(io_input="t.inp", io_output="t.out")
    self.assertEqual([d for d in check(problem, tex) if "input" in d or "output" in d], [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m unittest tools.tests.test_drift_check -v`

- [ ] **Step 3: Implement**

Extend `check()` to compare the parsed `input`/`output` keys against `problem.input`/`problem.output`, using the same message shape the existing bound-drift entries use. Follow the existing code's comment-stripping and brace-awareness — do not add a second parser.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add tools/drift_check.py tools/tests/test_drift_check.py
git commit -m "Drift-check the statement's io keys against problem.json"
```

---

### Task 6: Dogfood on a real file-IO problem, then document

**The definition of done for the whole plan.** A file-IO problem — **not** `flight`, which is stdin/stdout and must stay that way — driven end to end to `holes: 0`.

**Files:**
- Create: a scratch file-IO package under a temp path (NOT under `~/Projects/my_cp_problems/`)
- Modify: `skills/preparing-tests/SKILL.md`, `skills/validating-solutions/SKILL.md`, `README.md`
- Test: `tools/tests/test_skill_docs.py`

- [ ] **Step 1: Build a small file-IO package**

Reuse `xorcount`'s shape if convenient. It needs: `problem.json` with `io.input`/`io.output` set, a statement, a model solution, a validator, one generator, at least two subtask groups, and a zoo containing at least one `wrong-answer` solution **and** one solution that writes to the wrong filename (to realize NO_OUTPUT for real).

- [ ] **Step 2: Drive it through the pipeline**

Run the model solution, generators, validator, then `python3 -m tools.run_matrix <pkg> <testlib>`.
Expected: `holes: []`, `mismatches: []`, at least one row with verdict `NO_OUTPUT`, and every declared bound attained.

- [ ] **Step 3: Prove the three risks closed, by running**

Paste the evidence into the report, not a summary of it:
1. the large-output run is not reported ML,
2. the wrong-filename solution is `NO_OUTPUT` and not `WA`,
3. `problem.json` with `io.input: "../x"` is rejected at load.

- [ ] **Step 4: Update the skills**

`preparing-tests` and `validating-solutions` both document stdin/stdout assumptions in prose. Update them to describe both modes, and state plainly that generators and validators are unaffected (they are stdin/stdout testlib tools; `run_matrix` never invokes them) while the checker already takes three file paths. Remove the README's "file-based IO is rejected" line and replace it with what is now true.

Add a `test_skill_docs.py` case pinning whatever command text you add, in the style of the existing recipe-equality test.

- [ ] **Step 5: Full verification and commit**

```bash
python3 -m unittest discover -s tools/tests -t .    # ALONE
claude plugin validate . --strict
git add -A && git commit -m "Dogfood file IO end to end and document both modes"
```

---

## Self-Review

**Spec coverage.** Scope item 1's four parts map to tasks: the `_run_once` change → Task 3; risk 1 (memory) → Task 3 Step 1 test 4 and Task 6 Step 3; risk 2 (missing output verdict) → Tasks 2 and 4; risk 3 (unvalidated io strings) → Task 1. The two "also in scope" bullets map to Tasks 5 and 6. Scope item 2 (`writing-statements` routing) is deliberately **excluded** — the user scoped this run to file IO only.

**Placeholders.** Three steps intentionally say "adapt to the code actually there" (Task 3 Step 3's copy-back, Task 4 Step 1's row schema, Task 3 Step 1's compile helpers) rather than inventing names. That is a real instruction to read the surrounding code, not a TBD — the names exist and the implementer must match them.

**Type consistency.** `_run_once`'s new params are `io_input`/`io_output` (str) in Tasks 3 and 4; `RunResult.no_output` (bool) is produced in Task 3 and consumed in Task 4's `_classify`; `"NO_OUTPUT"` is the verdict string in Tasks 2 and 4. `_io_name` is Task 1 only.

**One known gap.** Task 6 leaves the scratch package in a temp path, so it is not committed and the end-to-end run is not reproducible from the repo. Making it a permanent fixture would be a second dogfood package in the tree; that call belongs to the human, not this plan.

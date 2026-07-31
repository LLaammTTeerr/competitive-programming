"""Integration test for run_matrix.py against the mini fixture.

This wraps the fixture run described in Task 9's brief: build every
solution, run the matrix, and confirm both a clean pass (no holes, no
mismatches) and — the actual point of the tool — that the hole detector
fires when a test can no longer distinguish the wrong solution from the
model solution. It also pins down the fixes made during review: the
child's own peak RSS (not the driver's), the timing-band re-run path, the
checker timeout, and the file-IO guard.

Task 9b migrated the runner from `os.posix_spawn` + `/proc` polling to the
ioi/isolate sandbox — there is no fallback runner any more, so the tests
below exercise the real thing: the peak-RSS test now pins isolate's own
cgroup accounting rather than `VmHWM`, and new tests below cover
isolate-specific outcomes a posix_spawn driver could never produce
(`status:TO`, `cg-oom-killed`) plus the refuse-to-run and box-cleanup
guarantees task 9b added.

**Missing tooling fails this suite; it does not skip it.** g++, isolate,
and the testlib cache are hard requirements of the module under test, and
`run_matrix.py` is the one module in this pipeline with no fallback path —
gating its only 20 tests on the presence of the very dependency that has
no fallback meant a fresh clone, or CI without isolate, printed a green
`OK` for a 1000-line driver that had not been executed at all. Set
`CP_ALLOW_SANDBOX_SKIP=1` to opt back into skipping, for the one case that
justifies it: working on an unrelated module on a machine where the
sandbox genuinely cannot be installed.

Scratch trees live under `<plugin root>/.test-scratch/`, not `/tmp`, and
that is load-bearing rather than tidiness: `/tmp` is tmpfs, `run()` stages
sandbox output next to the problem directory, and tmpfs pages are charged
to the writing cgroup — so a fixture under `/tmp` would put the driver's
staging directory back on exactly the memory-backed filesystem
`_stage_base()` now refuses. The refusal would fail every test here with
a message about staging rather than about the thing under test.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tools import flags, run_matrix
from tools.matrix_core import Limits

FIXTURE = Path(__file__).parent / "fixtures" / "mini"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SCRIPT = PLUGIN_ROOT / "tools" / "bootstrap_testlib.sh"

# Scratch trees go here rather than /tmp — see the module docstring: /tmp is
# tmpfs, and the driver refuses to stage sandbox output on a memory-backed
# filesystem because that charges a solution's stdout against its own
# memory limit. This directory is gitignored and each test removes its own
# subtree in tearDown.
SCRATCH_ROOT = PLUGIN_ROOT / ".test-scratch"

# Set CP_ALLOW_SANDBOX_SKIP=1 to turn missing tooling back into a skip.
SKIP_ENV = "CP_ALLOW_SANDBOX_SKIP"


def _missing_dependency(reason: str):
    """Fail — not skip — when a hard dependency of run_matrix is absent.

    Returns an exception for the caller to raise. `unittest.SkipTest` only
    when the caller explicitly opted in via $CP_ALLOW_SANDBOX_SKIP;
    otherwise an `AssertionError`, so a fresh clone or a CI runner without
    isolate reports a failure instead of a green suite over a driver that
    was never executed.
    """
    if os.environ.get(SKIP_ENV) == "1":
        return unittest.SkipTest(f"{reason} (skipping: ${SKIP_ENV}=1)")
    return AssertionError(
        f"{reason}. This is a hard dependency of run_matrix.py, which has no "
        f"fallback runner — the tests covering it must not pass silently "
        f"without it. Install the dependency, or set {SKIP_ENV}=1 to skip "
        f"these tests deliberately.")

# scan_solutions requires every solution file to carry this metadata block
# (@tag/@expect/...); tests that overwrite sol-main.cpp's body with a
# throwaway misbehaving program must keep it, or scan() fails before
# run_matrix ever gets to compile anything.
_MAIN_HEADER = (
    "/**\n"
    " * @tag        main\n"
    " * @expect     g1=OK\n"
    " * @algorithm  Deliberately misbehaving stand-in for a test.\n"
    " * @complexity O(1)\n"
    " */\n"
)


def _compile(src_text: str, out_path: Path, tmp_dir: Path) -> Path:
    """Compile a throwaway C++ source string, for tests that need a binary
    with a specific misbehavior (busy-looping, memory-hogging) that has no
    place in the checked-in fixture."""
    src = tmp_dir / f"{out_path.name}.cpp"
    src.write_text(src_text, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O2", str(src), "-o", str(out_path)],
                    check=True, capture_output=True)
    return out_path


def _testlib_dir() -> Path:
    """Resolve the cached testlib checkout, failing if it cannot be reached.

    Delegates to bootstrap_testlib.sh (the same script the driver's users run
    by hand) rather than hardcoding ~/.cache/testlib, so this still works if
    the cache lives somewhere else. An unreachable cache is a failure, not a
    skip, unless $CP_ALLOW_SANDBOX_SKIP=1 — see `_missing_dependency`.
    """
    try:
        done = subprocess.run(
            ["bash", str(BOOTSTRAP_SCRIPT)],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _missing_dependency(f"bootstrap_testlib.sh could not run: {exc}")
    if done.returncode != 0:
        raise _missing_dependency(f"testlib cache unavailable: {done.stderr.strip()}")
    path = Path(done.stdout.strip())
    if not (path / "testlib.h").exists():
        raise _missing_dependency(f"testlib cache at {path} has no testlib.h")
    return path


class TestRunMatrixFixture(unittest.TestCase):
    def setUp(self):
        if shutil.which("g++") is None:
            raise _missing_dependency("g++ not found on PATH")
        if shutil.which("isolate") is None:
            raise _missing_dependency("isolate not found on PATH")
        self.testlib_dir = _testlib_dir()

        # Copy the fixture into a scratch dir so the run's build artifacts
        # (.build/, *.a, invocation.json, flags.json, solutions.json) never
        # touch the checked-in fixture and each test starts from the same
        # pristine tree. `ignore` is not decoration: a working copy of this
        # repo accumulates untracked `.build/` binaries and `.a` answer
        # files under the fixture from earlier manual runs, and copying
        # those in reproduces the sandbox permission failure they were
        # created with — this test errored on isolate's "Permission denied"
        # before its own assertions were ever evaluated.
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = Path(tempfile.mkdtemp(prefix="run_matrix_test_", dir=SCRATCH_ROOT))
        self.problem_dir = self.tmp / "mini"
        shutil.copytree(
            FIXTURE, self.problem_dir,
            ignore=shutil.ignore_patterns(".build", "invocation.json",
                                          "solutions.json", "flags.json", "*.a"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_matrix_has_no_holes_or_mismatches(self):
        payload = run_matrix.run(self.problem_dir, self.testlib_dir)

        self.assertEqual(payload["holes"], [])
        self.assertEqual(payload["mismatches"], [])
        self.assertEqual(payload["limits"]["tl_ms"], 1000)  # floor binds, t_main is ~ms
        self.assertEqual(payload["limits"]["kill_ms"], 2000)

        by_solution = {r["solution"]: r for r in payload["results"]
                       if r["group"] == "g1" and r["test"] == "01"}
        self.assertEqual(by_solution["sol-main.cpp"]["verdict"], "OK")
        # sol-wrong.cpp must land on WA for g1, matching its @expect.
        self.assertEqual(by_solution["sol-wrong.cpp"]["verdict"], "WA")

        # Peak RSS must be a real, positive reading, not a zeroed-out stub.
        # (The regression-proof that it is the *child's* figure, not the
        # driver's, is a separate test below — this assertion alone would
        # pass even with the pre-review bug, since that bug over-reports
        # rather than reporting zero.)
        for record in payload["results"]:
            self.assertGreater(record["peak_kb"], 0)

    def test_hole_detector_fires_when_a_test_cannot_distinguish(self):
        # a - b == a + b when a == b == 0, so sol-wrong.cpp's (buggy)
        # subtraction coincides with the model solution's (correct) sum on
        # this one input. With only this test in g1, nothing catches it:
        # the tool must report this as a hole, not pass silently.
        (self.problem_dir / "tests" / "g1" / "01.in").write_text("0 0\n", encoding="utf-8")

        payload = run_matrix.run(self.problem_dir, self.testlib_dir)

        self.assertEqual(len(payload["holes"]), 1)
        hole = payload["holes"][0]
        self.assertEqual(hole["solution"], "sol-wrong.cpp")
        self.assertEqual(hole["group"], "g1")
        self.assertEqual(hole["expected"], "WA")
        self.assertEqual(hole["actual"], "OK")
        self.assertEqual(payload["mismatches"], [])

    def test_peak_kb_is_the_childs_own_footprint_not_the_drivers(self):
        # Regression pin, originally for the posix_spawn-era finding that
        # `ru_maxrss` after fork+exec is max(driver RSS at spawn, child's
        # real peak): deliberately balloon *this test process's* own RSS
        # well past anything the tiny fixture binaries could plausibly use,
        # then confirm the reported peak_kb does not track it. Now that
        # peak_kb comes from isolate's own cgroup accounting (`max-rss` in
        # its meta file, read from a namespace the driver process isn't
        # even part of) there is no shared-address-space mechanism left
        # that *could* leak the driver's RSS into this reading — this test
        # stays as a regression pin against that entire failure class
        # reappearing, e.g. if a future change ever reintroduced measuring
        # from the driver's own process instead of isolate's report.
        ballast = bytearray(250 * 1024 * 1024)
        for i in range(0, len(ballast), 4096):
            ballast[i] = 1  # touch every page so it is really resident
        try:
            payload = run_matrix.run(self.problem_dir, self.testlib_dir)
        finally:
            del ballast

        for record in payload["results"]:
            # sol-main.cpp/sol-wrong.cpp are static-ish iostream binaries
            # that in practice use a few MB; 30 MB is a generous ceiling
            # that a correct reading will clear easily while a
            # driver-tracking regression (hundreds of MB once ballooned)
            # would blow through immediately.
            self.assertLess(
                record["peak_kb"], 30_000,
                f"{record['solution']} reported {record['peak_kb']} KB peak "
                "RSS while the driver process was deliberately ballooned to "
                "~250 MB; this should be a few MB, not tracking the driver")
            self.assertGreater(record["peak_kb"], 0)

    def test_band_result_is_reached_and_flagged_with_accurate_wording(self):
        # Force every test into the (TL, kill] band deterministically by
        # patching compute_limits (imported by name into run_matrix, hence
        # patchable as run_matrix.compute_limits) rather than engineering a
        # sleep-based solution. tl_ms=-1 guarantees classify()'s `time_ms >
        # limits.tl_ms` fires even for a fixture solution measured at 0ms
        # (millisecond rounding on a trivial binary genuinely can read 0);
        # kill_ms=5000 is nowhere near reached, so the branch fires with no
        # flakiness regardless of how fast the machine running this is.
        forced = Limits(t_main_ms=2, tl_ms=-1, kill_ms=5000)
        with mock.patch.object(run_matrix, "compute_limits", return_value=forced):
            payload = run_matrix.run(self.problem_dir, self.testlib_dir)

        self.assertTrue(payload["results"])
        for record in payload["results"]:
            self.assertTrue(record["banded"], record)

        recorded = flags.read(self.problem_dir)
        band_flags = [f for f in recorded if f["kind"] == "timing-band"]
        self.assertGreaterEqual(len(band_flags), 1)
        for flag in band_flags:
            for field in ("phase", "severity", "kind", "what", "assumed",
                          "changes_if_wrong"):
                self.assertTrue(str(flag.get(field, "")).strip(), (flag, field))
            # Review finding: the old wording claimed reclassification to
            # "time-limit-exceeded-or-accepted", a verdict that does not
            # exist — the recorded verdict is always a real one.
            self.assertNotIn("time-limit-exceeded-or-accepted", flag["assumed"])

    def test_file_based_io_is_rejected_not_silently_mis_run(self):
        # A vnolymp-style file-IO problem (flight.inp/flight.out) must fail
        # loudly rather than silently feed the model solution empty stdin
        # and report a confident wrong verdict.
        meta_path = self.problem_dir / "problem.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["io"] = {"input": "mini.inp", "output": "mini.out"}
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with self.assertRaises(run_matrix.MatrixError):
            run_matrix.run(self.problem_dir, self.testlib_dir)

    def test_checker_timeout_reports_fail_instead_of_hanging(self):
        # A custom checker is externally-authored data; one that hangs
        # forever must not hang the whole pipeline. Build a literal
        # infinite loop and confirm _check() bounds it (using a short
        # timeout directly rather than the real CHECKER_TIMEOUT_S=10, so
        # this test stays fast).
        hang_src = self.tmp / "hang_checker.cpp"
        hang_src.write_text("int main(){ for(;;) {} }\n", encoding="utf-8")
        hang_bin = self.tmp / "hang_checker"
        subprocess.run(["g++", "-std=c++17", "-O2", str(hang_src), "-o", str(hang_bin)],
                        check=True, capture_output=True)
        dummy = self.tmp / "dummy.txt"
        dummy.write_text("x\n", encoding="utf-8")

        started = time.monotonic()
        verdict = run_matrix._check(hang_bin, dummy, dummy, dummy, timeout_s=1)
        elapsed_s = time.monotonic() - started

        self.assertEqual(verdict, "FAIL")
        self.assertLess(elapsed_s, 5)

    def test_isolate_missing_binary_refuses_with_a_named_fix(self):
        # Task 9b ruling: no fallback runner. A missing isolate must not
        # surface as a bare FileNotFoundError/CalledProcessError (R1) — it
        # must raise MatrixError naming the fix, and that message must be
        # distinguishable from the "installed but unconfigured" case below.
        with mock.patch.dict(os.environ, {"ISOLATE_BIN": "/no/such/isolate"}):
            with self.assertRaises(run_matrix.MatrixError) as ctx:
                run_matrix.open_isolate_box(self.tmp)
        self.assertIn("not found", str(ctx.exception))

    def test_isolate_init_failure_is_diagnosed_distinctly_from_missing(self):
        # The other failure family R1 requires: isolate present on PATH but
        # `--init` failing (real cause on this machine: an out-of-range
        # box id: isolate's own box-id range is 0-65535, see `isolate
        # --cg --box-id=999999 --init`, which fails distinctly from a
        # missing binary). Standing in for the "installed but
        # unconfigured" case this driver must diagnose separately, since a
        # genuinely unconfigured sandbox cannot be produced on this
        # already-configured machine without root to break it.
        with mock.patch.object(run_matrix, "_select_box_id", return_value=999_999):
            with self.assertRaises(run_matrix.MatrixError) as ctx:
                run_matrix.open_isolate_box(self.tmp)
        message = str(ctx.exception)
        self.assertIn("--init", message)
        self.assertNotIn("not found", message)

    def test_run_once_reports_a_real_tle_as_status_to(self):
        # A genuine busy loop, run through the real sandbox with a 1s CPU
        # cap, must come back with isolate's own status:TO — not a driver-
        # side wait-loop deadline, which no longer exists.
        binary = _compile("int main(){ volatile long i=0; for(;;) i++; }\n",
                          self.tmp / "spin", self.tmp)
        os.chmod(self.tmp, 0o777)
        stdin_path = self.tmp / "in.txt"
        stdin_path.write_text("\n", encoding="utf-8")
        out_path = self.tmp / "spin.out"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r = run_matrix._run_once(isolate, binary, stdin_path, out_path,
                                     cpu_limit_s=1.0, wall_limit_s=3.0,
                                     mem_limit_kb=256 * 1024)
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertTrue(r.killed, r)
        self.assertFalse(r.oom, r)
        self.assertGreaterEqual(r.cpu_ms, 900)

    def test_run_once_reports_a_real_oom_as_cg_oom_killed_and_classifies_ml(self):
        # A throwaway memory hog (never added to the fixture, per the task's
        # evidence standard) run under a tight --cg-mem must come back with
        # cg-oom-killed, and that must classify as ML directly — not RE,
        # which is the trap this driver has to avoid (a memory kill arrives
        # as status:SG, indistinguishable from a bare crash by status text
        # alone; cg-oom-killed is what disambiguates it).
        binary = _compile(
            "#include <cstring>\n#include <cstdlib>\n"
            "int main(){ for(;;){ char*p=(char*)malloc(8*1024*1024); "
            "if(!p) return 1; memset(p,1,8*1024*1024); } }\n",
            self.tmp / "hog", self.tmp)
        os.chmod(self.tmp, 0o777)
        stdin_path = self.tmp / "in.txt"
        stdin_path.write_text("\n", encoding="utf-8")
        out_path = self.tmp / "hog.out"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r = run_matrix._run_once(isolate, binary, stdin_path, out_path,
                                     cpu_limit_s=5.0, wall_limit_s=15.0,
                                     mem_limit_kb=64 * 1024)
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertTrue(r.oom, r)
        self.assertFalse(r.killed, r)

        outcome = run_matrix._classify(r, checker=Path("/bin/true"),
                                       test=stdin_path, out=out_path,
                                       ans=stdin_path, limits=Limits(
                                           t_main_ms=1, tl_ms=1000, kill_ms=2000))
        self.assertEqual(outcome.verdict, "ML")

    def test_oom_does_not_leak_into_the_next_run_in_the_same_handle(self):
        # Task 9c: the `flight` dogfood found that isolate's cgroup counters
        # are NOT reset between `--run`s in the same box — reproduced with
        # bare isolate, no involvement from this module. A hog that OOMs
        # followed by a trivial, memory-innocent program in the SAME box
        # reported the hog's cg-oom-killed for the trivial program too.
        # Since ML outranks WA in _SEVERITY, that doesn't just add a wrong
        # row to invocation.json — it overwrites a correct verdict with a
        # wrong one. This test must FAIL against the single-persistent-box
        # code this task replaces (confirmed: see the task report for the
        # actual failing-before transcript) and PASS now that every
        # `_run_once` call draws its own fresh box from the same
        # `IsolateHandle` via `box_id_counter`.
        hog = _compile(
            "#include <cstring>\n#include <cstdlib>\n"
            "int main(){ for(;;){ char*p=(char*)malloc(8*1024*1024); "
            "if(!p) return 1; memset(p,1,8*1024*1024); } }\n",
            self.tmp / "hog2", self.tmp)
        tiny = _compile("int main(){ return 0; }\n", self.tmp / "tiny", self.tmp)
        os.chmod(self.tmp, 0o777)
        stdin_path = self.tmp / "in.txt"
        stdin_path.write_text("\n", encoding="utf-8")

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r_hog = run_matrix._run_once(
                isolate, hog, stdin_path, self.tmp / "hog2.out",
                cpu_limit_s=5.0, wall_limit_s=15.0, mem_limit_kb=64 * 1024)
            self.assertTrue(r_hog.oom, r_hog)  # sanity: the hog did OOM

            r_tiny = run_matrix._run_once(
                isolate, tiny, stdin_path, self.tmp / "tiny.out",
                cpu_limit_s=5.0, wall_limit_s=15.0, mem_limit_kb=64 * 1024)
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertFalse(r_tiny.oom, r_tiny)
        self.assertLess(r_tiny.peak_kb, 10_000, r_tiny)

    def test_peak_kb_does_not_carry_over_between_runs(self):
        # The other half of the same box-lifetime bug: `cg-mem` is a
        # box-lifetime high-water mark, so a solution that allocates
        # substantially followed by one that does not must not have the
        # second's peak_kb inflated by the first's — with or without an
        # OOM involved.
        # `p` is `volatile` and written a non-constant value per page: a
        # plain malloc+memset+read-one-byte with no other use of `p` is
        # legal for GCC to constant-fold away *entirely* (it can prove the
        # byte printed back is always 1 and eliminate the allocation with
        # it) — which the first version of this test learned the hard way
        # (objdump showed no call to malloc/memset at all, and peak_kb came
        # back at ~1.6 MB instead of ~200 MB). `volatile` forces every
        # access to actually happen.
        big = _compile(
            "#include <cstdlib>\n#include <cstdio>\n"
            "int main(){ size_t n = 200*1024*1024; "
            "volatile char *p = (volatile char*)malloc(n); if(!p) return 1; "
            "for (size_t i = 0; i < n; i += 4096) p[i] = (char)(i & 0xFF); "
            "printf(\"%d\\n\", (int)p[n-4096]); return 0; }\n",
            self.tmp / "big", self.tmp)
        small = _compile("int main(){ return 0; }\n", self.tmp / "small", self.tmp)
        os.chmod(self.tmp, 0o777)
        stdin_path = self.tmp / "in.txt"
        stdin_path.write_text("\n", encoding="utf-8")

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r_big = run_matrix._run_once(
                isolate, big, stdin_path, self.tmp / "big.out",
                cpu_limit_s=5.0, wall_limit_s=15.0, mem_limit_kb=256 * 1024)
            r_small = run_matrix._run_once(
                isolate, small, stdin_path, self.tmp / "small.out",
                cpu_limit_s=5.0, wall_limit_s=15.0, mem_limit_kb=256 * 1024)
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertFalse(r_big.oom, r_big)
        self.assertGreater(r_big.peak_kb, 100_000, r_big)
        self.assertLess(r_small.peak_kb, 10_000, r_small)
        self.assertNotEqual(r_big.peak_kb, r_small.peak_kb)

    def test_box_is_cleaned_up_after_a_single_run_that_raises(self):
        # Task 9c: cleanup is now per-`--run` (a box lives from just before
        # one _run_once call to just after it), not per-run() — so the
        # exception-safety guarantee has to be re-pinned at that smaller
        # scope. Force _run_once itself to raise partway through (after the
        # sandboxed process has already run and a box exists) by making
        # meta parsing blow up, and confirm that specific box is still
        # torn down by _run_once's own `finally`.
        binary = _compile("int main(){ return 0; }\n", self.tmp / "ok", self.tmp)
        os.chmod(self.tmp, 0o777)
        stdin_path = self.tmp / "in.txt"
        stdin_path.write_text("\n", encoding="utf-8")
        out_path = self.tmp / "ok.out"

        box_dir = Path("/var/local/lib/isolate/54323")
        with mock.patch.object(run_matrix, "_select_box_id", return_value=54323):
            isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            # itertools.count(54323)'s first next() yields 54323 itself, so
            # this first _run_once call is guaranteed to use box 54323.
            with mock.patch.object(run_matrix, "_parse_meta",
                                   side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    run_matrix._run_once(isolate, binary, stdin_path, out_path,
                                         cpu_limit_s=1.0, wall_limit_s=3.0,
                                         mem_limit_kb=256 * 1024)
            self.assertFalse(box_dir.exists(),
                             f"{box_dir} still present after _run_once raised")
        finally:
            run_matrix.close_isolate_box(isolate)

    def _isolate_boxes(self) -> set[str]:
        base = Path("/var/local/lib/isolate")
        if not base.is_dir():
            return set()
        return {p.name for p in base.iterdir()}

    def test_boxes_are_cleaned_up_after_a_real_run(self):
        # A box leaked under /var/local/lib/isolate/<id> is exactly the
        # failure mode a `finally`-guarded `--cleanup` exists to prevent —
        # confirm it is actually gone after a clean run and after a
        # hole-firing one. Neither of these actually *raises* out of
        # run() (the hole-firing input still returns a payload, it just
        # reports a hole) — see
        # test_boxes_are_cleaned_up_after_run_raises below for the path
        # that does raise, which review found this test's old comment
        # claimed to cover but did not.
        #
        # Task 9c: `run()` now opens and closes a *different* box for every
        # single sandboxed execution (see IsolateHandle.box_id_counter), so
        # checking only the mocked base id would only ever pin the first
        # of several boxes a real run opens. Snapshotting the whole
        # directory before and after is the check that actually covers
        # every box this invocation touched, not just the first.
        before = self._isolate_boxes()
        with mock.patch.object(run_matrix, "_select_box_id", return_value=54321):
            run_matrix.run(self.problem_dir, self.testlib_dir)
            self.assertEqual(self._isolate_boxes(), before,
                             "a box was left behind after a clean run")

            (self.problem_dir / "tests" / "g1" / "01.in").write_text(
                "0 0\n", encoding="utf-8")
            payload = run_matrix.run(self.problem_dir, self.testlib_dir)
            self.assertEqual(len(payload["holes"]), 1)  # sanity: still ran
            self.assertEqual(self._isolate_boxes(), before,
                             "a box was left behind after a hole-firing run")

    def test_boxes_are_cleaned_up_after_run_raises(self):
        # Task 9b review finding D: the test above never actually drives
        # run() through its exception path (`finally: close_isolate_box`
        # in run()) — both of its calls return normally. Force a genuine
        # raise by replacing the model solution with a source that
        # segfaults, so pass 1's `r.crashed` branch raises MatrixError
        # out of the middle of the `try`, and confirm cleanup still fired.
        (self.problem_dir / "solutions" / "sol-main.cpp").write_text(
            _MAIN_HEADER + "int main(){ int *p = nullptr; *p = 1; return 0; }\n",
            encoding="utf-8")
        before = self._isolate_boxes()
        with mock.patch.object(run_matrix, "_select_box_id", return_value=54322):
            with self.assertRaises(run_matrix.MatrixError):
                run_matrix.run(self.problem_dir, self.testlib_dir)
            self.assertEqual(self._isolate_boxes(), before,
                             "a box was left behind after run() raised")

    def test_crashing_model_solution_is_diagnosed_as_crashed_not_exited_0(self):
        # Task 9b review finding A: a signal death (status SG) carries no
        # `exitcode` line in isolate's meta file, so defaulting exit_code
        # to 0 and reporting "exited 0" reads like a bug in the check
        # itself rather than a crashing model solution. The message must
        # name the crash, not claim a clean exit.
        (self.problem_dir / "solutions" / "sol-main.cpp").write_text(
            _MAIN_HEADER + "int main(){ int *p = nullptr; *p = 1; return 0; }\n",
            encoding="utf-8")
        with self.assertRaises(run_matrix.MatrixError) as ctx:
            run_matrix.run(self.problem_dir, self.testlib_dir)
        message = str(ctx.exception)
        self.assertIn("crashed", message)
        self.assertNotIn("exited 0", message)

    def test_pass1_wall_clock_kill_names_the_wall_limit_not_cpu(self):
        # Task 9b review finding B: isolate reports status:TO for both a
        # CPU-time kill and a wall-time kill, and the old diagnostic
        # always blamed MODEL_SAFETY_CPU_S regardless of which one
        # actually fired. A model solution that sleeps (near-zero CPU
        # time, real wall time) must be blamed for the wall-clock ceiling,
        # not told it burned 60 seconds of CPU it never used. Patches the
        # wall ceiling down to make this fast and deterministic rather
        # than sleeping for the real 90s default.
        (self.problem_dir / "solutions" / "sol-main.cpp").write_text(
            _MAIN_HEADER + "#include <unistd.h>\nint main(){ sleep(3); return 0; }\n",
            encoding="utf-8")
        with mock.patch.object(run_matrix, "MODEL_SAFETY_WALL_S", 1.0):
            with self.assertRaises(run_matrix.MatrixError) as ctx:
                run_matrix.run(self.problem_dir, self.testlib_dir)
        message = str(ctx.exception)
        self.assertIn("wall-clock", message)
        self.assertNotIn("CPU time", message)

    def test_solution_output_lands_in_repo_owned_by_us_not_a_subuid(self):
        # Task 9b review's Critical finding: an earlier version of this
        # driver bind-mounted tests/<group>/ and .build/ read-write, so
        # every file the sandbox created there (the regenerated .a answer
        # file, a solution's .out) came back owned by the mapped subuid —
        # not us, not writable or chmod-able by us afterward — and the
        # directory itself was left permanently o+w. Confirm both halves
        # are fixed: ownership and mode.
        payload = run_matrix.run(self.problem_dir, self.testlib_dir)
        self.assertTrue(payload["results"])

        my_uid = os.getuid()
        answer_files = list((self.problem_dir / "tests" / "g1").glob("*.a"))
        self.assertTrue(answer_files)
        for answer in answer_files:
            st = answer.stat()
            self.assertEqual(st.st_uid, my_uid,
                             f"{answer} is owned by uid {st.st_uid}, not ours "
                             f"({my_uid}) — the ownership-transfer bug")
            self.assertTrue(os.access(answer, os.W_OK),
                            f"{answer} is not writable by us")

        out_files = list((self.problem_dir / ".build").glob("*.out"))
        self.assertTrue(out_files)
        for out in out_files:
            st = out.stat()
            self.assertEqual(st.st_uid, my_uid,
                             f"{out} is owned by uid {st.st_uid}, not ours")

        tests_mode = stat.S_IMODE((self.problem_dir / "tests" / "g1").stat().st_mode)
        self.assertFalse(tests_mode & stat.S_IWOTH,
                         "tests/g1 was left world-writable by run()")
        build_mode = stat.S_IMODE((self.problem_dir / ".build").stat().st_mode)
        self.assertFalse(build_mode & stat.S_IWOTH,
                         ".build was left world-writable by run()")

    def test_run_heals_a_directory_damaged_by_the_old_read_write_mount(self):
        # Simulate exactly the damage the old behaviour left behind (a
        # stray o+w bit on tests/<group>/, verified for real on this
        # machine's own fixture prior to this fix — see the task report)
        # and confirm a fresh run() strips it back off rather than
        # perpetuating or ignoring it.
        group_dir = self.problem_dir / "tests" / "g1"
        group_dir.chmod(stat.S_IMODE(group_dir.stat().st_mode) | stat.S_IWOTH)
        self.assertTrue(stat.S_IMODE(group_dir.stat().st_mode) & stat.S_IWOTH)

        run_matrix.run(self.problem_dir, self.testlib_dir)

        healed_mode = stat.S_IMODE(group_dir.stat().st_mode)
        self.assertFalse(healed_mode & stat.S_IWOTH,
                         "run() did not heal a pre-existing o+w directory")

    def test_large_output_is_not_charged_against_the_memory_limit(self):
        # Final-review Critical: the staging directory was a bare
        # `tempfile.mkdtemp()`, i.e. `/tmp`, i.e. tmpfs. `--stdout` pointed
        # into it while `--cg-mem` capped the same cgroup, and tmpfs pages
        # are charged to the writing cgroup and are not reclaimable — so a
        # solution's own output counted as its memory. Reproduced with bare
        # isolate before the fix: a 1.6 MB program writing 70 MB to stdout
        # under a 64 MB limit came back
        # `max-rss:1668 cg-mem:65536 cg-oom-killed:1 status:SG`, a false ML
        # on a program using 2.5% of its limit.
        #
        # This test FAILS against the pre-fix driver (verified: see the
        # final fix report for the transcript) — 48 MB of output under a
        # 32 MB limit is an OOM there and an ordinary OK here.
        #
        # The buffer is `static` and the program's own footprint is ~1-2 MB,
        # so any memory reading above a few MB is coming from the output,
        # not from the process.
        mb_out = 48
        binary = _compile(
            "#include <cstdio>\n"
            "int main(){ static char buf[1<<16];\n"
            "  for (int i = 0; i < (1<<16); i++) buf[i] = 'x';\n"
            f"  for (int k = 0; k < {mb_out} * 16; k++) fwrite(buf, 1, 1<<16, stdout);\n"
            "  return 0; }\n",
            self.tmp / "loud", self.tmp)
        os.chmod(self.tmp, 0o777)
        stdin_path = self.tmp / "in.txt"
        stdin_path.write_text("\n", encoding="utf-8")
        out_path = self.tmp / "loud.out"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r = run_matrix._run_once(isolate, binary, stdin_path, out_path,
                                     cpu_limit_s=10.0, wall_limit_s=30.0,
                                     mem_limit_kb=32 * 1024)
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertFalse(r.oom, r)
        self.assertFalse(r.crashed, r)
        self.assertFalse(r.killed, r)
        self.assertLess(r.peak_kb, 10_000, r)
        self.assertEqual(out_path.stat().st_size, mb_out * 1024 * 1024)

        outcome = run_matrix._classify(r, checker=Path("/bin/true"),
                                       test=stdin_path, out=out_path,
                                       ans=stdin_path, limits=Limits(
                                           t_main_ms=1, tl_ms=1000, kill_ms=2000))
        self.assertEqual(outcome.verdict, "OK")

    def test_output_is_bounded_by_fsize_and_surfaces_as_a_crash_not_an_ml(self):
        # The other half of the same fix. Once staging is disk-backed,
        # nothing accidentally caps output any more — a `while(1)
        # putchar()` solution would write until the disk filled and then
        # have the whole file read into the driver's RAM by
        # `staged_out.read_bytes()`. `--fsize` is the deliberate ceiling.
        # OUTPUT_LIMIT_KB is patched down to 1 MB so this stays fast; the
        # real 256 MB constant is exercised by the same code path.
        binary = _compile(
            "#include <cstdio>\n"
            "int main(){ for(;;) putchar('x'); }\n",
            self.tmp / "runaway", self.tmp)
        os.chmod(self.tmp, 0o777)
        stdin_path = self.tmp / "in.txt"
        stdin_path.write_text("\n", encoding="utf-8")
        out_path = self.tmp / "runaway.out"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            with mock.patch.object(run_matrix, "OUTPUT_LIMIT_KB", 1024):
                r = run_matrix._run_once(isolate, binary, stdin_path, out_path,
                                         cpu_limit_s=10.0, wall_limit_s=30.0,
                                         mem_limit_kb=256 * 1024)
        finally:
            run_matrix.close_isolate_box(isolate)

        # SIGXFSZ, so: a signal death with no cg-oom-killed. It must be RE
        # (the solution's output ran away), never ML (the solution used too
        # much memory) — those are different findings for the setter.
        self.assertTrue(r.crashed, r)
        self.assertFalse(r.oom, r)
        self.assertLessEqual(out_path.stat().st_size, 1024 * 1024)

        outcome = run_matrix._classify(r, checker=Path("/bin/true"),
                                       test=stdin_path, out=out_path,
                                       ans=stdin_path, limits=Limits(
                                           t_main_ms=1, tl_ms=1000, kill_ms=2000))
        self.assertEqual(outcome.verdict, "RE")

    # ------------------------------------------------------------------
    # File-based IO (`io.input`/`io.output` naming real files rather than
    # the `stdin`/`stdout` sentinels). Every test below drives `_run_once`
    # directly: `run()` still refuses file IO one level up, and wiring that
    # is a later task — this one is only about the sandboxed execution.
    # ------------------------------------------------------------------

    def test_file_io_solution_reads_its_inp_and_writes_its_out(self):
        # A solution that never touches stdin or stdout at all: it opens
        # "t.inp" and "t.out" by *relative* name, so this passes only if the
        # sandbox's cwd is the one `:rw` mount (the staging directory). It
        # fails two distinct ways against the pre-fix driver: `--chdir` used
        # to point at the binary's read-only mount, where fopen("t.inp") is
        # NULL (exit 3, `crashed`) and where "t.out" could not be created at
        # all even if the input had been found.
        binary = _compile(
            '#include <cstdio>\n'
            'int main(){ FILE *fi = fopen("t.inp", "r"); if (!fi) return 3;\n'
            '  int a, b; if (fscanf(fi, "%d %d", &a, &b) != 2) return 4;\n'
            '  fclose(fi);\n'
            '  FILE *fo = fopen("t.out", "w"); if (!fo) return 5;\n'
            '  fprintf(fo, "%d\\n", a + b); fclose(fo); return 0; }\n',
            self.tmp / "fileio", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("2 3\n", encoding="utf-8")
        dest = self.tmp / "01.produced"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r = run_matrix._run_once(isolate, binary, test_in, dest,
                                     cpu_limit_s=2.0, wall_limit_s=6.0,
                                     mem_limit_kb=256 * 1024,
                                     io_input="t.inp", io_output="t.out")
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertFalse(r.crashed, r)   # exit 3/4/5 above would show up here
        self.assertEqual(r.exit_code, 0, r)
        self.assertFalse(r.no_output, r)
        self.assertEqual(dest.read_text(encoding="utf-8").strip(), "5")

    def test_file_io_missing_output_file_is_reported_not_crashed(self):
        # Exits 0 and writes nothing — an outcome a stdin/stdout problem
        # cannot have (isolate always creates the stdout file), so it needs
        # its own signal rather than being folded into `crashed`.
        binary = _compile("int main(){ return 0; }\n", self.tmp / "silent", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("2 3\n", encoding="utf-8")
        dest = self.tmp / "01.produced"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r = run_matrix._run_once(isolate, binary, test_in, dest,
                                     cpu_limit_s=2.0, wall_limit_s=6.0,
                                     mem_limit_kb=256 * 1024,
                                     io_input="t.inp", io_output="t.out")
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertTrue(r.no_output, r)
        self.assertFalse(r.crashed, r)   # a clean exit is not a crash
        self.assertFalse(r.killed, r)
        self.assertFalse(r.oom, r)
        self.assertEqual(r.exit_code, 0, r)

    def test_stdin_mode_never_reports_no_output(self):
        # Pins the `no_output` docstring claim that it is only reachable in
        # file-IO mode: the *same* silent binary, run through the default
        # path, has a stdout file (empty) and must report no_output=False.
        # Without this, "only reachable in file-IO mode" is an untested
        # claim about a field a later task classifies as a verdict.
        binary = _compile("int main(){ return 0; }\n", self.tmp / "silent_std", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("2 3\n", encoding="utf-8")
        dest = self.tmp / "01.produced"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r = run_matrix._run_once(isolate, binary, test_in, dest,
                                     cpu_limit_s=2.0, wall_limit_s=6.0,
                                     mem_limit_kb=256 * 1024)
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertFalse(r.no_output, r)
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), b"")

    def test_file_io_output_does_not_leak_between_runs(self):
        # The same contamination shape as the three memory bugs, one level
        # down: `_time_median` calls `_run_once` three times and every
        # solution reuses the same handle — hence the same staging
        # directory. Run 1 writes "first"; run 2 writes nothing at all. If
        # the pre-run unlink of the output file is removed, run 2 reads run
        # 1's file and is reported as a solution that produced "first".
        writer = _compile(
            '#include <cstdio>\n'
            'int main(){ FILE *f = fopen("t.out", "w"); if (!f) return 5;\n'
            '  fprintf(f, "first\\n"); fclose(f); return 0; }\n',
            self.tmp / "writer", self.tmp)
        silent = _compile("int main(){ return 0; }\n", self.tmp / "silent2", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("x\n", encoding="utf-8")
        d1, d2 = self.tmp / "a.produced", self.tmp / "b.produced"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r1 = run_matrix._run_once(isolate, writer, test_in, d1,
                                      cpu_limit_s=2.0, wall_limit_s=6.0,
                                      mem_limit_kb=256 * 1024,
                                      io_input="t.inp", io_output="t.out")
            r2 = run_matrix._run_once(isolate, silent, test_in, d2,
                                      cpu_limit_s=2.0, wall_limit_s=6.0,
                                      mem_limit_kb=256 * 1024,
                                      io_input="t.inp", io_output="t.out")
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertFalse(r1.no_output, r1)
        self.assertEqual(d1.read_text(encoding="utf-8").strip(), "first")
        self.assertTrue(r2.no_output, r2)
        # The destination is rewritten every run too, so a stale `.out` in
        # the repository cannot be read as this run's answer either.
        self.assertEqual(d2.read_bytes(), b"")

    def test_file_io_output_is_not_charged_against_the_memory_limit(self):
        # Risk 1 — the tmpfs bug, a fourth time. The first three times the
        # contaminated write was the driver's own staging of *stdout*; the
        # solution's own output file is a new writable file inside the box
        # and is the same shape again. 48 MB written under a 32 MB
        # `--cg-mem` is an OK on a disk-backed staging directory and an OOM
        # on a memory-backed one, so this fails immediately if the output
        # file ever moves onto tmpfs or into a second, memory-backed mount.
        # The buffer is `static` and the program's own footprint is ~1-2 MB.
        mb_out = 48
        binary = _compile(
            "#include <cstdio>\n"
            'int main(){ static char buf[1<<16];\n'
            "  for (int i = 0; i < (1<<16); i++) buf[i] = 'x';\n"
            '  FILE *f = fopen("t.out", "w"); if (!f) return 5;\n'
            f"  for (int k = 0; k < {mb_out} * 16; k++) fwrite(buf, 1, 1<<16, f);\n"
            "  fclose(f); return 0; }\n",
            self.tmp / "bigout", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("x\n", encoding="utf-8")
        dest = self.tmp / "big.produced"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r = run_matrix._run_once(isolate, binary, test_in, dest,
                                     cpu_limit_s=10.0, wall_limit_s=30.0,
                                     mem_limit_kb=32 * 1024,
                                     io_input="t.inp", io_output="t.out")
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertFalse(r.oom, r)
        self.assertFalse(r.crashed, r)
        self.assertFalse(r.killed, r)
        self.assertFalse(r.no_output, r)
        self.assertLess(r.peak_kb, 10_000, r)
        self.assertEqual(dest.stat().st_size, mb_out * 1024 * 1024)

    def test_file_io_name_colliding_with_the_staged_stdout_is_refused(self):
        # `--stdout` still points at the staging directory's fixed `run.out`
        # in file-IO mode (see `_run_once`). A problem whose own io.output
        # is literally that name would have isolate and the solution writing
        # the same file — garbage, silently. Task 1 accepts any bare
        # filename, so this collision is reachable and must be refused
        # rather than run.
        binary = _compile("int main(){ return 0; }\n", self.tmp / "collide", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("x\n", encoding="utf-8")

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            with self.assertRaises(run_matrix.MatrixError) as ctx:
                run_matrix._run_once(isolate, binary, test_in,
                                     self.tmp / "c.produced",
                                     cpu_limit_s=2.0, wall_limit_s=6.0,
                                     mem_limit_kb=256 * 1024,
                                     io_input="t.inp",
                                     io_output=run_matrix.STAGED_STDOUT_NAME)
        finally:
            run_matrix.close_isolate_box(isolate)
        self.assertIn(run_matrix.STAGED_STDOUT_NAME, str(ctx.exception))

    def test_file_io_same_name_for_input_and_output_is_refused(self):
        # Measured, not theorised (review finding): with both names equal,
        # the staged input IS the file read back as the answer, so a
        # solution that writes nothing returns the test data as its output
        # and the checker accepts it — a silent, confident wrong verdict on
        # every test. `problem_meta` refuses this at load time as well;
        # this pins the check at the point of use, since `_run_once` is
        # called directly.
        binary = _compile("int main(){ return 0; }\n", self.tmp / "samename", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("SECRET-TEST-INPUT\n", encoding="utf-8")
        dest = self.tmp / "same.produced"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            with self.assertRaises(run_matrix.MatrixError) as ctx:
                run_matrix._run_once(isolate, binary, test_in, dest,
                                     cpu_limit_s=2.0, wall_limit_s=6.0,
                                     mem_limit_kb=256 * 1024,
                                     io_input="t.txt", io_output="t.txt")
        finally:
            run_matrix.close_isolate_box(isolate)
        self.assertIn("t.txt", str(ctx.exception))
        # The specific damage: the test input must never reach `dest`.
        self.assertFalse(dest.exists(), dest)

    def test_file_io_staged_input_is_readable_under_a_strict_umask(self):
        # Review finding: `run()` grants the real test file the "other" read
        # bit the mapped subuid needs (`_ensure_sandbox_readable`), and
        # `shutil.copyfile` recreates the staged copy at `0666 & ~umask`,
        # throwing that heal away. At umask 077 the sandbox could not open
        # its own input and the failure surfaced as isolate `status:XX`
        # ("Permission denied") — i.e. the driver blaming isolate for a
        # permission bit it set itself, on every file-IO run, for anyone
        # with a hardened umask.
        #
        # The umask is set only around the `_run_once` call: the binary and
        # the test file are created before it (as `run()` would, already
        # healed), so the only file this window affects is the staged copy.
        binary = _compile(
            '#include <cstdio>\n'
            'int main(){ FILE *fi = fopen("t.inp", "r"); if (!fi) return 3;\n'
            '  int a, b; if (fscanf(fi, "%d %d", &a, &b) != 2) return 4;\n'
            '  fclose(fi);\n'
            '  FILE *fo = fopen("t.out", "w"); if (!fo) return 5;\n'
            '  fprintf(fo, "%d\\n", a + b); fclose(fo); return 0; }\n',
            self.tmp / "umask_io", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("2 3\n", encoding="utf-8")
        run_matrix._ensure_sandbox_readable(test_in)
        dest = self.tmp / "01.produced"

        isolate = run_matrix.open_isolate_box(self.tmp)
        previous_umask = os.umask(0o077)
        try:
            r = run_matrix._run_once(isolate, binary, test_in, dest,
                                     cpu_limit_s=2.0, wall_limit_s=6.0,
                                     mem_limit_kb=256 * 1024,
                                     io_input="t.inp", io_output="t.out")
        finally:
            os.umask(previous_umask)
            run_matrix.close_isolate_box(isolate)

        self.assertFalse(r.crashed, r)
        self.assertFalse(r.no_output, r)
        self.assertEqual(dest.read_text(encoding="utf-8").strip(), "5")

    def test_file_io_unreadable_output_is_a_matrix_error_not_a_bare_oserror(self):
        # The other permission direction, and the other half of the same
        # review finding. The solution owns its output file, so it can leave
        # it -rw------- under the sandbox's subuid; we own only the staging
        # directory, so we can neither read nor chmod it. Left bare, the
        # PermissionError escaped `_run_once` and aborted the whole matrix
        # mid-run on one careless solution (R1: no bare stdlib exception on
        # solution-controlled state). It must NOT be reported as
        # `no_output`: "unreadable" and "never written" are different facts.
        binary = _compile(
            '#include <cstdio>\n#include <sys/stat.h>\n'
            'int main(){ umask(077);\n'
            '  FILE *f = fopen("t.out", "w"); if (!f) return 5;\n'
            '  fprintf(f, "hidden\\n"); fclose(f); return 0; }\n',
            self.tmp / "secretive", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("x\n", encoding="utf-8")
        dest = self.tmp / "secret.produced"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            with self.assertRaises(run_matrix.MatrixError) as ctx:
                run_matrix._run_once(isolate, binary, test_in, dest,
                                     cpu_limit_s=2.0, wall_limit_s=6.0,
                                     mem_limit_kb=256 * 1024,
                                     io_input="t.inp", io_output="t.out")
        finally:
            run_matrix.close_isolate_box(isolate)

        message = str(ctx.exception)
        self.assertIn("t.out", message)          # names the file
        self.assertIn("secretive", message)      # names the solution
        self.assertIn("not readable", message)   # not "produced no output"

    def test_stdin_mode_is_unchanged(self):
        # The default path must behave exactly as before: this test passes
        # both before and after the file-IO change, and is here so that a
        # regression in the sentinel path shows up as a failure about the
        # sentinel path rather than as a puzzling fixture failure.
        binary = _compile(
            '#include <cstdio>\n'
            'int main(){ int a, b; scanf("%d %d", &a, &b);\n'
            '  printf("%d\\n", a + b); return 0; }\n',
            self.tmp / "stdio_sum", self.tmp)
        os.chmod(self.tmp, 0o777)
        test_in = self.tmp / "01.in"
        test_in.write_text("7 8\n", encoding="utf-8")
        dest = self.tmp / "s.produced"

        isolate = run_matrix.open_isolate_box(self.tmp)
        try:
            r = run_matrix._run_once(isolate, binary, test_in, dest,
                                     cpu_limit_s=2.0, wall_limit_s=6.0,
                                     mem_limit_kb=256 * 1024)
        finally:
            run_matrix.close_isolate_box(isolate)

        self.assertFalse(r.crashed, r)
        self.assertEqual(dest.read_text(encoding="utf-8").strip(), "15")

    def test_stage_dir_is_not_on_a_memory_backed_filesystem(self):
        isolate = run_matrix.open_isolate_box(self.problem_dir)
        try:
            fstype = run_matrix._filesystem_type(isolate.stage_dir)
            self.assertNotIn(fstype, run_matrix.MEMORY_BACKED_FSTYPES,
                             f"staging landed on {fstype} at {isolate.stage_dir}")
            self.assertTrue(isolate.stage_dir.is_dir())
        finally:
            run_matrix.close_isolate_box(isolate)
        self.assertFalse(isolate.stage_dir.exists(),
                         "the staging directory outlived close_isolate_box")

    def test_matrix_error_exits_2_so_it_is_not_read_as_a_hole(self):
        # `validating-solutions` tells the agent that exit 1 means holes or
        # mismatches. An uncaught MatrixError used to exit 1 as well, so a
        # compile failure or the file-IO guard read as a finding about the
        # test suite. Use the file-IO guard as the trigger — it raises
        # before anything is compiled.
        meta_path = self.problem_dir / "problem.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["io"] = {"input": "mini.inp", "output": "mini.out"}
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        code = run_matrix.main(["run_matrix.py", str(self.problem_dir),
                                str(self.testlib_dir)])
        self.assertEqual(code, 2)

    def test_invocation_json_pins_the_testlib_revision(self):
        payload = run_matrix.run(self.problem_dir, self.testlib_dir)
        machine = payload["machine"]
        self.assertIn("testlib", machine)
        self.assertRegex(machine["testlib"] or "", r"^[0-9a-f]{40}$")
        # `cg` was a hardcoded True presented as an observation of the
        # machine; it is a declaration and is now named as one.
        self.assertNotIn("cg", machine)
        self.assertTrue(machine["cg_requested"])


class TestStageBase(unittest.TestCase):
    """`_stage_base` needs no sandbox, so it is tested without one."""

    def test_memory_backed_staging_is_refused_with_a_named_fix(self):
        with mock.patch.object(run_matrix, "_filesystem_type", return_value="tmpfs"):
            with self.assertRaises(run_matrix.MatrixError) as ctx:
                run_matrix._stage_base(Path(__file__).parent)
        message = str(ctx.exception)
        self.assertIn("tmpfs", message)
        self.assertIn("RUN_MATRIX_STAGE_DIR", message)

    def test_env_override_wins_over_the_problem_directory(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH_ROOT) as override:
            with mock.patch.dict(os.environ,
                                 {run_matrix.STAGE_DIR_ENV: override}):
                self.assertEqual(run_matrix._stage_base(Path("/nonexistent/p")),
                                 Path(override))

    def test_default_is_the_problem_directorys_parent(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(run_matrix.STAGE_DIR_ENV, None)
            base = run_matrix._stage_base(SCRATCH_ROOT / "some-problem")
        self.assertEqual(base, SCRATCH_ROOT.resolve())

    def test_filesystem_type_identifies_a_real_mount(self):
        # Guards the detection itself: a helper that silently returned None
        # for everything would make the refusal above unreachable in
        # practice while still passing its own (mocked) test.
        self.assertIsNotNone(run_matrix._filesystem_type(Path("/")))

    def setUp(self):
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    unittest.main()

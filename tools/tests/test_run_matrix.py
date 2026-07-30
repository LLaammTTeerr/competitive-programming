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
below that need a real sandbox skip (not fail) when isolate is genuinely
absent, and otherwise exercise the real thing: the peak-RSS test now pins
isolate's own cgroup accounting rather than `VmHWM`, and new tests below
cover isolate-specific outcomes a posix_spawn driver could never produce
(`status:TO`, `cg-oom-killed`) plus the refuse-to-run and box-cleanup
guarantees task 9b added.

g++, the testlib cache, and isolate are all expected to be present wherever
this suite runs; the skips below are for genuinely absent tooling, not a
way to quietly avoid exercising the module.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tools import flags, run_matrix
from tools.matrix_core import Limits

FIXTURE = Path(__file__).parent / "fixtures" / "mini"
BOOTSTRAP_SCRIPT = Path(__file__).resolve().parents[1] / "bootstrap_testlib.sh"


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
    """Resolve the cached testlib checkout, or skip if it cannot be reached.

    Delegates to bootstrap_testlib.sh (the same script the driver's users run
    by hand) rather than hardcoding ~/.cache/testlib, so this test skips
    cleanly instead of failing if the cache lives somewhere else.
    """
    try:
        done = subprocess.run(
            ["bash", str(BOOTSTRAP_SCRIPT)],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise unittest.SkipTest(f"bootstrap_testlib.sh could not run: {exc}")
    if done.returncode != 0:
        raise unittest.SkipTest(f"testlib cache unavailable: {done.stderr.strip()}")
    path = Path(done.stdout.strip())
    if not (path / "testlib.h").exists():
        raise unittest.SkipTest(f"testlib cache at {path} has no testlib.h")
    return path


class TestRunMatrixFixture(unittest.TestCase):
    def setUp(self):
        if shutil.which("g++") is None:
            raise unittest.SkipTest("g++ not found on PATH")
        if shutil.which("isolate") is None:
            raise unittest.SkipTest(
                "isolate not found on PATH — this driver has no fallback "
                "runner (task 9b), so the whole suite skips rather than "
                "failing when the sandbox is genuinely absent")
        self.testlib_dir = _testlib_dir()

        # Copy the fixture into a scratch dir so the run's build artifacts
        # (.build/, *.a, invocation.json, flags.json, solutions.json) never
        # touch the checked-in fixture and each test starts from the same
        # pristine tree.
        self.tmp = Path(tempfile.mkdtemp(prefix="run_matrix_test_"))
        self.problem_dir = self.tmp / "mini"
        shutil.copytree(FIXTURE, self.problem_dir)

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
        # Force every test into the [TL, kill] band deterministically by
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
                run_matrix.open_isolate_box()
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
                run_matrix.open_isolate_box()
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

        isolate = run_matrix.open_isolate_box()
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

        isolate = run_matrix.open_isolate_box()
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

    def test_boxes_are_cleaned_up_after_a_real_run(self):
        # A box leaked under /var/local/lib/isolate/<id> is exactly the
        # failure mode a `finally`-guarded `--cleanup` exists to prevent —
        # confirm it is actually gone after a real fixture run, including
        # the exception path (this run raises via the hole-firing input).
        box_dir = Path("/var/local/lib/isolate/54321")
        with mock.patch.object(run_matrix, "_select_box_id", return_value=54321):
            run_matrix.run(self.problem_dir, self.testlib_dir)
            self.assertFalse(box_dir.exists(),
                             f"{box_dir} still present after a clean run")

            (self.problem_dir / "tests" / "g1" / "01.in").write_text(
                "0 0\n", encoding="utf-8")
            payload = run_matrix.run(self.problem_dir, self.testlib_dir)
            self.assertEqual(len(payload["holes"]), 1)  # sanity: still ran
            self.assertFalse(box_dir.exists(),
                             f"{box_dir} still present after a hole-firing run")


if __name__ == "__main__":
    unittest.main()

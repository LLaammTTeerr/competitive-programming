"""Integration test for run_matrix.py against the mini fixture.

This wraps the fixture run described in Task 9's brief: build every
solution, run the matrix, and confirm both a clean pass (no holes, no
mismatches) and — the actual point of the tool — that the hole detector
fires when a test can no longer distinguish the wrong solution from the
model solution. It also pins down the fixes made during review: the
child's own peak RSS (not the driver's), the timing-band re-run path, the
checker timeout, and the file-IO guard.

Both g++ and the testlib cache are expected to be present wherever this
suite runs; the skips below are for genuinely absent tooling, not a way to
quietly avoid exercising the module.
"""

from __future__ import annotations

import json
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
        # Regression pin for the review finding that `ru_maxrss` after
        # posix_spawn/fork+exec is max(driver RSS at spawn, child's real
        # peak): deliberately balloon *this test process's* own RSS well
        # past anything the tiny fixture binaries could plausibly use, then
        # confirm the reported peak_kb does not track it. Before the fix
        # this ballooned ~1:1 with the driver's RSS (see task-9-report.md
        # for the measured before/after numbers); a bare `assertGreater(...,
        # 0)` can never catch that regression since the bug over-reports
        # rather than reporting zero.
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


if __name__ == "__main__":
    unittest.main()

"""Integration test for run_matrix.py against the mini fixture.

This wraps the fixture run described in Task 9's brief: build every
solution, run the matrix, and confirm both a clean pass (no holes, no
mismatches) and — the actual point of the tool — that the hole detector
fires when a test can no longer distinguish the wrong solution from the
model solution.

Both g++ and the testlib cache are expected to be present wherever this
suite runs; the skips below are for genuinely absent tooling, not a way to
quietly avoid exercising the module.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import run_matrix

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


if __name__ == "__main__":
    unittest.main()

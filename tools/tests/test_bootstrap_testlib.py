"""Offline contract tests for `tools/bootstrap_testlib.py` and the `.sh`
wrapper around it.

Every assertion here runs the real CLI entry points as subprocesses — never
`bootstrap()` in-process — because the contract callers actually depend on
(`skills/*/SKILL.md`'s `TESTLIB=$(bash ".../bootstrap_testlib.sh")`,
`tools/tests/test_run_matrix.py`'s `_testlib_dir()`) is "run this command,
read stdout", not "call this function". A test that imported `bootstrap()`
directly could pass while the `.sh` wrapper was broken, which is exactly the
bug the fork's own wrapper had (it computed the plugin root and never `cd`d
to it, so `python3 -m tools.bootstrap_testlib` failed from any cwd but the
plugin root).

No network access: `CP_TESTLIB_REPO` is pointed at a throwaway local git
repository built in `setUp`, standing in for qhhoj/testlib.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY_ENTRY = ["python3", "-m", "tools.bootstrap_testlib"]
SH_SCRIPT = ROOT / "tools" / "bootstrap_testlib.sh"


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=60,
    )


def _git(args: list[str], *, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                    capture_output=True, text=True)


class BootstrapTestlibTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bootstrap_testlib_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

        # A local repo standing in for qhhoj/testlib, entirely offline.
        self.src = self.tmp / "testlib-src"
        self.src.mkdir()
        _git(["init", "-q"], cwd=self.src)
        _git(["config", "user.email", "test@example.com"], cwd=self.src)
        _git(["config", "user.name", "test"], cwd=self.src)
        (self.src / "testlib.h").write_text("// testlib v1\n")
        _git(["add", "-A"], cwd=self.src)
        _git(["commit", "-q", "-m", "v1"], cwd=self.src)

        self.cache_home = self.tmp / "cache_home"
        self.cache_home.mkdir()

        self.env = dict(os.environ)
        self.env.pop("CP_TESTLIB", None)
        self.env["XDG_CACHE_HOME"] = str(self.cache_home)
        self.env["CP_TESTLIB_REPO"] = str(self.src)

    def test_clone_on_empty_cache_prints_the_path(self):
        done = _run(PY_ENTRY, cwd=ROOT, env=self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        target = Path(done.stdout.strip())
        self.assertEqual(target, self.cache_home / "testlib")
        self.assertTrue((target / "testlib.h").is_file())

    def test_second_run_pulls_upstream_changes_and_prints_the_same_path(self):
        first = _run(PY_ENTRY, cwd=ROOT, env=self.env)
        self.assertEqual(first.returncode, 0, first.stderr)

        # Advance "upstream" past what the first run cloned.
        (self.src / "testlib.h").write_text("// testlib v2\n")
        _git(["commit", "-aqm", "v2"], cwd=self.src)

        second = _run(PY_ENTRY, cwd=ROOT, env=self.env)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, first.stdout,
                          "the cache path must not move between runs")
        cached_header = Path(second.stdout.strip()) / "testlib.h"
        self.assertIn("v2", cached_header.read_text(),
                       "second run did not pull the upstream change")

    def test_cp_testlib_override_short_circuits_cloning(self):
        env = dict(self.env)
        env["CP_TESTLIB"] = str(self.src)
        # A bogus repo: if CP_TESTLIB short-circuits correctly, this is
        # never touched, so pointing it somewhere that would fail to clone
        # proves no network/clone path was taken.
        env["CP_TESTLIB_REPO"] = str(self.tmp / "does-not-exist")

        done = _run(PY_ENTRY, cwd=ROOT, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), str(self.src))

    def test_cp_testlib_pointing_at_a_dir_without_testlib_h_fails(self):
        baddir = self.tmp / "baddir"
        baddir.mkdir()
        env = dict(self.env)
        env["CP_TESTLIB"] = str(baddir)

        done = _run(PY_ENTRY, cwd=ROOT, env=env)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertIn("testlib.h", done.stderr)

    def test_sh_wrapper_from_a_different_cwd_matches_the_python_entry(self):
        py_done = _run(PY_ENTRY, cwd=ROOT, env=self.env)
        self.assertEqual(py_done.returncode, 0, py_done.stderr)

        sh_done = _run(["bash", str(SH_SCRIPT)], cwd=Path("/"), env=self.env)
        self.assertEqual(sh_done.returncode, 0, sh_done.stderr)
        self.assertEqual(sh_done.stdout, py_done.stdout)


if __name__ == "__main__":
    unittest.main()

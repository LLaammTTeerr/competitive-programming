import contextlib
import json, os, shutil, tempfile, unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from tools import problem_meta
from tools.package_status import PHASE_ORDER, _matrix, main, next_phase, status

# Anchored to this file, not to the process's working directory: the suite is
# documented to run from the repository root, but a fixture path that only
# resolves from there makes `cd` part of the contract for no reason, and the
# same suite run from anywhere else fails in `setUp` with FileNotFoundError
# rather than in the code under test. `test_run_matrix.py` already does this.
FIXTURE = Path(__file__).parent / "fixtures" / "mini"


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "p"
        shutil.copytree(FIXTURE, self.dir,
                        ignore=shutil.ignore_patterns(
                            ".build", "invocation.json", "solutions.json",
                            "flags.json", "*.a"))

    def phases(self):
        return {p.name: p for p in status(self.dir)}

    def test_reports_every_phase_in_order(self):
        names = [p.name for p in status(self.dir)]
        self.assertEqual(tuple(names), PHASE_ORDER)

    def test_a_package_with_problem_json_reports_that_phase_done(self):
        self.assertTrue(self.phases()["problem_json"].done)

    def test_a_missing_problem_json_does_not_raise(self):
        (self.dir / "problem.json").unlink()
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)
        self.assertIn("problem.json", phases["problem_json"].detail)

    def test_a_malformed_problem_json_does_not_raise(self):
        (self.dir / "problem.json").write_text("{ not json", encoding="utf-8")
        self.assertFalse(self.phases()["problem_json"].done)

    def test_tests_phase_needs_every_declared_group(self):
        self.assertTrue(self.phases()["tests"].done)
        shutil.rmtree(self.dir / "tests" / "g1")
        phases = self.phases()
        self.assertFalse(phases["tests"].done)
        self.assertIn("g1", phases["tests"].detail)

    def test_matrix_phase_is_not_done_without_invocation_json(self):
        self.assertFalse(self.phases()["matrix"].done)

    def test_matrix_phase_is_not_done_when_holes_remain(self):
        (self.dir / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": [{"solution": "x", "group": "g1"}],
                        "mismatches": []}), encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["matrix"].done)
        self.assertIn("hole", phases["matrix"].detail.lower())

    def test_matrix_phase_is_done_when_clean(self):
        (self.dir / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": [], "mismatches": []}),
            encoding="utf-8")
        self.assertTrue(self.phases()["matrix"].done)

    def test_samples_phase_needs_both_the_entry_and_the_files(self):
        self.assertFalse(self.phases()["samples"].done)
        problem = json.loads((self.dir / "problem.json").read_text(encoding="utf-8"))
        problem["examples"] = [{"test": "tests/samples/01", "note": "n"}]
        (self.dir / "problem.json").write_text(json.dumps(problem), encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["samples"].done)
        self.assertIn("tests/samples/01", phases["samples"].detail)

    def test_next_phase_is_the_first_incomplete_one(self):
        self.assertEqual(next_phase(status(self.dir)), "matrix")

    def test_next_phase_is_none_when_everything_is_done(self):
        done = [type(p)(name=p.name, done=True, detail="") for p in status(self.dir)]
        self.assertIsNone(next_phase(done))

    def test_hostile_problem_json_list_instead_of_dict_does_not_raise(self):
        (self.dir / "problem.json").write_text("[]", encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)

    def test_hostile_subtasks_string_instead_of_list_does_not_raise(self):
        # Start from a complete valid problem.json and mutate subtasks
        problem = json.loads((self.dir / "problem.json").read_text(encoding="utf-8"))
        problem["subtasks"] = "not a list"
        (self.dir / "problem.json").write_text(json.dumps(problem), encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)

    def test_hostile_examples_dict_instead_of_list_does_not_raise(self):
        # Start from a complete valid problem.json and mutate examples
        problem = json.loads((self.dir / "problem.json").read_text(encoding="utf-8"))
        problem["examples"] = {}
        (self.dir / "problem.json").write_text(json.dumps(problem), encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)

    def test_hostile_examples_entry_bare_string_does_not_raise(self):
        # Start from a complete valid problem.json and add a bare string example
        problem = json.loads((self.dir / "problem.json").read_text(encoding="utf-8"))
        problem["examples"] = ["bare_string"]
        (self.dir / "problem.json").write_text(json.dumps(problem), encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)

    def test_hostile_solutions_is_a_file_not_directory_does_not_raise(self):
        shutil.rmtree(self.dir / "solutions")
        (self.dir / "solutions").write_text("not a directory", encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["model_solution"].done)

    def test_hostile_tests_is_a_file_not_directory_does_not_raise(self):
        shutil.rmtree(self.dir / "tests")
        (self.dir / "tests").write_text("not a directory", encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["tests"].done)

    def test_hostile_problem_directory_does_not_exist_does_not_raise(self):
        shutil.rmtree(self.dir)
        # Should not raise even though directory is gone
        phases = status(self.dir)
        self.assertFalse(phases[0].done)

    def test_hostile_matrix_holes_not_array_does_not_raise(self):
        (self.dir / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": 5, "mismatches": []}),
            encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["matrix"].done)
        self.assertIn("array", phases["matrix"].detail.lower())

    def test_hostile_matrix_mismatches_not_array_does_not_raise(self):
        (self.dir / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": [], "mismatches": None}),
            encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["matrix"].done)
        self.assertIn("array", phases["matrix"].detail.lower())

    def test_hostile_matrix_top_level_is_array_does_not_raise(self):
        (self.dir / "invocation.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        phases = self.phases()
        self.assertFalse(phases["matrix"].done)
        self.assertIn("object", phases["matrix"].detail.lower())

    # --- hand-edit typos that used to escape `load` as a bare TypeError ------
    #
    # Each of the four below reached a consumer that does something a string
    # can do and a number cannot — a path join, a set membership test — and
    # raised from a module whose module docstring promises `status()` never
    # raises. `problem_meta._string()` turns each into a `ProblemMetaError`
    # at the boundary, which `_problem()` already wraps into a `[ ]` row.

    def _mutate(self, mutate):
        problem = json.loads((self.dir / "problem.json").read_text(encoding="utf-8"))
        mutate(problem)
        (self.dir / "problem.json").write_text(json.dumps(problem), encoding="utf-8")

    def test_hostile_subtask_id_is_a_number_does_not_raise(self):
        # `problem_dir / "tests" / s.id` -> TypeError before the loader fix.
        self._mutate(lambda p: p["subtasks"][0].__setitem__("id", 5))
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)
        self.assertIn("subtasks[0].id", phases["problem_json"].detail)

    def test_hostile_depends_on_entry_is_an_object_does_not_raise(self):
        # `dep not in seen_s` -> TypeError: unhashable type: 'dict'.
        self._mutate(lambda p: p["subtasks"][0].__setitem__("depends_on", [{"a": 1}]))
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)
        self.assertIn("depends_on[0]", phases["problem_json"].detail)

    def test_hostile_checker_name_is_null_does_not_raise(self):
        # `files / problem.checker_name` -> TypeError on None.
        self._mutate(lambda p: p["checker"].__setitem__("name", None))
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)
        self.assertIn("checker.name", phases["problem_json"].detail)

    def test_hostile_checker_name_is_a_number_does_not_raise(self):
        self._mutate(lambda p: p["checker"].__setitem__("name", 7))
        phases = self.phases()
        self.assertFalse(phases["problem_json"].done)
        self.assertIn("checker.name", phases["problem_json"].detail)


class MatrixFreshnessTest(unittest.TestCase):
    """`invocation.json` is evidence about a package state. When the package
    has moved on, the evidence does not become wrong — it becomes about
    something else, and the gate must not accept it.

    This is not only a crash concern. `run_matrix` writes the artifact at
    the very end of a successful run, so a crash leaves an older one in
    place; but a *clean* run followed by editing a solution leaves exactly
    the same stale-green state, and that is the commoner case.
    """

    def _package(self, *, holes=(), mismatches=()):
        d = Path(tempfile.mkdtemp()) / "p"
        shutil.copytree(FIXTURE, d,
                        ignore=shutil.ignore_patterns(
                            ".build", "invocation.json", "solutions.json",
                            "flags.json", "*.a"))
        (d / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": list(holes),
                        "mismatches": list(mismatches)}),
            encoding="utf-8")
        return d

    def _problem(self, d):
        """`_matrix` takes the already-loaded `Problem` the same way every
        other multi-arg phase function in this module does (see `_checker`,
        `_tests`) — it needs `checker_kind`/`checker_name` to know whether a
        custom checker is in scope. Loaded fresh per call so tests that
        mutate `problem.json` (none currently do in this class) would still
        see their own edit."""
        return problem_meta.load(d / "problem.json")

    def test_a_fresh_clean_matrix_passes(self):
        d = self._package()
        self.assertTrue(_matrix(d, self._problem(d)).done)

    def test_an_invocation_older_than_a_solution_is_stale(self):
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(d / "solutions" / "sol-main.cpp", (later, later))
        phase = _matrix(d, self._problem(d))
        self.assertFalse(phase.done)
        self.assertIn("stale", phase.detail.lower())

    def test_an_invocation_older_than_a_test_is_stale(self):
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        test_file = next((d / "tests").rglob("*.in"))
        os.utime(test_file, (later, later))
        self.assertFalse(_matrix(d, self._problem(d)).done)

    def test_an_invocation_older_than_problem_json_is_stale(self):
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(d / "problem.json", (later, later))
        self.assertFalse(_matrix(d, self._problem(d)).done)

    def test_staleness_is_reported_before_holes(self):
        # A stale artifact reporting zero holes must not read as "clean".
        # Order matters: the detail a reader sees has to name the reason
        # they cannot trust the number, not the number.
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(d / "problem.json", (later, later))
        self.assertIn("stale", _matrix(d, self._problem(d)).detail.lower())

    def test_a_stale_artifact_with_holes_still_fails(self):
        d = self._package(holes=[{"solution": "x", "group": "g1",
                                  "expected": "WA", "actual": "OK"}])
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(d / "problem.json", (later, later))
        self.assertFalse(_matrix(d, self._problem(d)).done)

    def test_an_equal_mtime_is_not_stale(self):
        # Boundary: a file written in the same second as the artifact is
        # not evidence of a later edit. Strictly-newer is the test, or a
        # fast clean run flags itself stale.
        d = self._package()
        stamp = (d / "invocation.json").stat().st_mtime
        os.utime(d / "problem.json", (stamp, stamp))
        self.assertTrue(_matrix(d, self._problem(d)).done)

    # --- coordinator review round: deletions, the custom checker, and the
    # two unguarded `.stat()` races the review's empirical coverage map
    # found ------------------------------------------------------------

    def test_a_deleted_test_is_stale(self):
        # A *removed* test file bumps no remaining file's mtime — only its
        # parent directory's. Missing that was a false "fresh": the gate
        # would report "clean" over a suite quietly made weaker than the
        # invocation.json on disk claims to have exercised.
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        test_file = next((d / "tests").rglob("*.in"))
        parent = test_file.parent
        test_file.unlink()
        os.utime(parent, (later, later))
        phase = _matrix(d, self._problem(d))
        self.assertFalse(phase.done)
        self.assertIn("stale", phase.detail.lower())

    def test_a_deleted_solution_is_stale(self):
        d = self._package()
        later = (d / "invocation.json").stat().st_mtime + 10
        sol_dir = d / "solutions"
        (sol_dir / "sol-wrong.cpp").unlink()
        os.utime(sol_dir, (later, later))
        self.assertFalse(_matrix(d, self._problem(d)).done)

    def test_an_edited_custom_checker_is_stale(self):
        # A custom checker decides OK vs WA on every cell of the matrix —
        # not covered by `problem.json`/`solutions/`/`tests/` at all, since
        # it lives under `files/`. Declare one, create it, then edit it
        # after `invocation.json` is written.
        d = self._package()
        meta_path = d / "problem.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["checker"] = {"kind": "custom", "name": "checker.cpp"}
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        checker = d / "files" / "checker.cpp"
        checker.write_text("// custom checker\n", encoding="utf-8")
        (d / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": [], "mismatches": []}),
            encoding="utf-8")
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(checker, (later, later))
        phase = _matrix(d, self._problem(d))
        self.assertFalse(phase.done)
        self.assertIn("stale", phase.detail.lower())

    def test_editing_files_other_than_a_custom_checker_is_not_stale(self):
        # The narrowness ruling, pinned rather than just commented: editing
        # `files/validator.cpp` does not change any recorded verdict until
        # the tests it produces are regenerated (already caught by the
        # `tests/` walk), so widening this check to all of `files/` would
        # add false-staleness for no gain. A prior version of this test
        # only confirmed a fresh package was fresh without ever touching
        # `files/` at all -- it could not have failed even if the walk
        # were widened to cover the whole directory, which is exactly the
        # kind of test this project's evidence standard rules out.
        d = self._package()
        self.assertEqual(self._problem(d).checker_kind, "stock")
        later = (d / "invocation.json").stat().st_mtime + 10
        os.utime(d / "files" / "validator.cpp", (later, later))
        self.assertTrue(_matrix(d, self._problem(d)).done)

    def test_a_vanishing_invocation_json_between_read_and_stat_does_not_raise(self):
        # `path.exists()` and `path.read_text()` already succeeded by the
        # time `_matrix` calls `path.stat()` for the artifact's own mtime —
        # a race in that microscopic window (something unlinks
        # invocation.json between the read and the stat) must not turn a
        # read-only status check into an uncaught OSError. Driven by
        # monkeypatching `Path.stat` to fail for exactly this path, real
        # `stat()` for everything else.
        d = self._package()
        target = d / "invocation.json"
        real_stat = Path.stat

        def flaky_stat(self, *args, **kwargs):
            if self == target:
                raise OSError("simulated race: invocation.json vanished")
            return real_stat(self, *args, **kwargs)

        with mock.patch.object(Path, "stat", flaky_stat):
            phase = _matrix(d, self._problem(d))
        self.assertFalse(phase.done)
        self.assertIn("unreadable", phase.detail.lower())

    def test_a_file_that_vanishes_during_the_source_walk_does_not_raise(self):
        # Same race, one level down: `newest_source_mtime`'s walk lists a
        # child via `rglob` and then `.stat()`s it — a file legitimately
        # unlinked in between (this is literally what `run_matrix` itself
        # does to `.a` files: `unlink(missing_ok=True)` then
        # `write_bytes`) must not raise either. `_mtime_or_zero` is what's
        # supposed to guard this; this exercises that guard directly rather
        # than trusting it was wired in everywhere it needed to be.
        d = self._package()
        victim = next((d / "tests").rglob("*.in"))
        real_stat = Path.stat

        def flaky_stat(self, *args, **kwargs):
            if self == victim:
                raise OSError("simulated race: unlinked mid-walk")
            return real_stat(self, *args, **kwargs)

        with mock.patch.object(Path, "stat", flaky_stat):
            phase = _matrix(d, self._problem(d))
        # A vanished file contributes 0.0, not a crash, and cannot itself
        # manufacture staleness -- the package is otherwise untouched.
        self.assertTrue(phase.done)


class TestMain(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "p"
        shutil.copytree(FIXTURE, self.dir,
                        ignore=shutil.ignore_patterns(
                            ".build", "invocation.json", "solutions.json",
                            "flags.json", "*.a"))

    def main(self, argv):
        """`main` prints the whole phase table; four of these tests together
        dumped 26 lines into the suite's own output, where they read as
        failures scrolling past. Capture it and return it, so the assertions
        can look at it instead of the operator having to."""
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = main(argv)
        return exit_code, buf.getvalue()

    def test_main_exits_1_when_phases_incomplete(self):
        exit_code, out = self.main([None, str(self.dir)])
        self.assertEqual(exit_code, 1)
        self.assertIn("next: matrix", out)

    def test_main_exits_0_when_all_phases_complete(self):
        # Add invocation.json to make matrix complete
        (self.dir / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": [], "mismatches": []}),
            encoding="utf-8")
        # Add example with sample files
        problem = json.loads((self.dir / "problem.json").read_text(encoding="utf-8"))
        problem["examples"] = [{"test": "tests/samples/01", "note": ""}]
        (self.dir / "problem.json").write_text(json.dumps(problem), encoding="utf-8")
        samples_dir = self.dir / "tests" / "samples"
        samples_dir.mkdir(exist_ok=True)
        (samples_dir / "01.in").write_text("test\n")
        exit_code, out = self.main([None, str(self.dir)])
        self.assertEqual(exit_code, 0)
        self.assertIn("complete", out)
        self.assertNotIn("next:", out)

    def test_main_exits_2_on_invalid_arguments(self):
        exit_code, _ = self.main([None])  # Missing problem_dir
        self.assertEqual(exit_code, 2)

    def test_main_exits_2_on_too_many_arguments(self):
        exit_code, _ = self.main([None, str(self.dir), "testlib", "extra"])
        self.assertEqual(exit_code, 2)

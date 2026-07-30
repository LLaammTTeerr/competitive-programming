import json, shutil, sys, tempfile, unittest
from io import StringIO
from pathlib import Path

from tools.package_status import PHASE_ORDER, main, next_phase, status

FIXTURE = Path("tools/tests/fixtures/mini")


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


class TestMain(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "p"
        shutil.copytree(FIXTURE, self.dir,
                        ignore=shutil.ignore_patterns(
                            ".build", "invocation.json", "solutions.json",
                            "flags.json", "*.a"))

    def test_main_exits_1_when_phases_incomplete(self):
        exit_code = main([None, str(self.dir)])
        self.assertEqual(exit_code, 1)

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
        exit_code = main([None, str(self.dir)])
        self.assertEqual(exit_code, 0)

    def test_main_exits_2_on_invalid_arguments(self):
        exit_code = main([None])  # Missing problem_dir
        self.assertEqual(exit_code, 2)

    def test_main_exits_2_on_too_many_arguments(self):
        exit_code = main([None, str(self.dir), "testlib", "extra"])
        self.assertEqual(exit_code, 2)

import json
import tempfile
import unittest
from pathlib import Path

from tools.problem_meta import ProblemMetaError, load

# Anchored to this file, not to the process's working directory — see
# test_run_matrix.py / test_package_status.py, which document why.
FIXTURE = Path(__file__).parent / "fixtures" / "mini"

VALID = {
    "schema": 1,
    "name": "flight",
    "title": {"vi": "Chuyến bay đầu tiên"},
    "tags": ["probability", "strings"],
    "limits": {"time_ms_published": 1000, "time_ms_computed": 740, "memory_mb": 256},
    "io": {"input": "stdin", "output": "stdout"},
    "checker": {"kind": "stock", "name": "rcmp6"},
    "constraints": [
        {"id": "len_a", "expr": "1 \\le |A| \\le 20", "min": 1, "max": 20},
        {"id": "len_b", "expr": "1 \\le |B| \\le 20", "min": 1, "max": 20},
    ],
    "subtasks": [
        {"id": "g1", "points": 40,
         "bounds": {"len_a": {"max": 6}, "len_b": {"max": 6}},
         "constraints_text": ["$|A| \\le 6$ và $|B| \\le 6$"],
         "depends_on": []},
        {"id": "g2", "points": 60, "bounds": {},
         "constraints_text": ["Không có ràng buộc gì thêm"],
         "depends_on": ["g1"]},
    ],
    "examples": [{"test": "sample-01", "note": "A thắng"}],
}


def write(payload):
    tmp = Path(tempfile.mkdtemp()) / "problem.json"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    return tmp


class TestLoad(unittest.TestCase):
    def test_loads_valid_document(self):
        problem = load(write(VALID))
        self.assertEqual(problem.name, "flight")
        self.assertEqual(problem.time_ms_published, 1000)
        self.assertEqual(problem.checker_name, "rcmp6")
        self.assertEqual([s.id for s in problem.subtasks], ["g1", "g2"])
        self.assertEqual(problem.subtasks[0].bounds["len_a"].max, 6)
        self.assertIsNone(problem.subtasks[0].bounds["len_a"].min)
        self.assertEqual(problem.constraints[0].max, 20)

    def test_rejects_unknown_schema(self):
        bad = dict(VALID, schema=2)
        with self.assertRaisesRegex(ProblemMetaError, "schema"):
            load(write(bad))

    def test_rejects_points_not_summing_to_100(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["points"] = 30
        with self.assertRaisesRegex(ProblemMetaError, "100"):
            load(write(bad))

    def test_rejects_duplicate_subtask_id(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][1]["id"] = "g1"
        with self.assertRaisesRegex(ProblemMetaError, "duplicate"):
            load(write(bad))

    def test_rejects_dependency_on_unknown_subtask(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][1]["depends_on"] = ["g9"]
        with self.assertRaisesRegex(ProblemMetaError, "g9"):
            load(write(bad))

    def test_rejects_subtask_bound_naming_unknown_constraint(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["bounds"] = {"len_z": {"max": 6}}
        with self.assertRaisesRegex(ProblemMetaError, "len_z"):
            load(write(bad))

    def test_rejects_unknown_checker_kind(self):
        bad = json.loads(json.dumps(VALID))
        bad["checker"]["kind"] = "magic"
        with self.assertRaisesRegex(ProblemMetaError, "magic"):
            load(write(bad))

    def test_rejects_missing_required_top_level_field(self):
        bad = json.loads(json.dumps(VALID))
        del bad["name"]
        with self.assertRaisesRegex(ProblemMetaError, "name"):
            load(write(bad))

    def test_rejects_subtask_missing_required_field(self):
        bad = json.loads(json.dumps(VALID))
        del bad["subtasks"][0]["points"]
        with self.assertRaisesRegex(ProblemMetaError, "points"):
            load(write(bad))


class TestLoadWrapsEveryFailure(unittest.TestCase):
    """Standing ruling R1, applied to *types* and not only missing keys.

    problem.json is hand-authored and is the pipeline's source of truth, so
    every one of these is an ordinary typo. Each case below was reproduced
    against the loader before the fix and raised the bare exception named
    in the comment — not a ProblemMetaError naming the field.
    """

    def test_null_limits(self):  # TypeError: 'NoneType' is not subscriptable
        bad = dict(VALID, limits=None)
        with self.assertRaisesRegex(ProblemMetaError, "limits"):
            load(write(bad))

    def test_null_checker(self):  # AttributeError: 'NoneType' has no 'get'
        bad = dict(VALID, checker=None)
        with self.assertRaisesRegex(ProblemMetaError, "checker"):
            load(write(bad))

    def test_null_io(self):
        bad = dict(VALID, io=None)
        with self.assertRaisesRegex(ProblemMetaError, "io"):
            load(write(bad))

    def test_points_as_a_string(self):  # TypeError on +, inside the sum
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["points"] = "100"
        with self.assertRaisesRegex(ProblemMetaError, "points"):
            load(write(bad))

    def test_scalar_bounds(self):  # AttributeError: 'int' has no 'get'
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["bounds"] = {"len_a": 5}
        with self.assertRaisesRegex(ProblemMetaError, "len_a"):
            load(write(bad))

    def test_top_level_array(self):  # AttributeError: 'list' has no 'get'
        with self.assertRaisesRegex(ProblemMetaError, "top level"):
            load(write([1, 2, 3]))

    def test_missing_file(self):  # FileNotFoundError
        missing = Path(tempfile.mkdtemp()) / "problem.json"
        with self.assertRaisesRegex(ProblemMetaError, "no such file"):
            load(missing)

    def test_constraints_not_an_array(self):
        bad = dict(VALID, constraints={"len_a": {"max": 20}})
        with self.assertRaisesRegex(ProblemMetaError, "constraints"):
            load(write(bad))

    def test_subtask_entry_not_an_object(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0] = "g1"
        with self.assertRaisesRegex(ProblemMetaError, r"subtasks\[0\]"):
            load(write(bad))


class TestRejectsNonIntegerBounds(unittest.TestCase):
    """gen_constraints_header f-strings a bound into

        static const long long N_MAX = <value>;

    so `"max": 2.9` emits `= 2.9;`, which C++ silently truncates to 2, and
    a probability bound `"max": 0.5` becomes 0 — after which the generated
    header makes the validator reject every legal test. The header exists
    to make validator/problem.json drift impossible; this was a path where
    they drifted silently, so the value must not load at all.
    """

    def test_float_global_bound(self):
        bad = json.loads(json.dumps(VALID))
        bad["constraints"][0]["max"] = 2.9
        with self.assertRaisesRegex(ProblemMetaError, "len_a"):
            load(write(bad))

    def test_probability_style_bound_that_would_truncate_to_zero(self):
        bad = json.loads(json.dumps(VALID))
        bad["constraints"][0]["min"] = 0.5
        with self.assertRaisesRegex(ProblemMetaError, "expected an integer"):
            load(write(bad))

    def test_float_subtask_bound(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["bounds"]["len_a"]["max"] = 6.5
        with self.assertRaisesRegex(ProblemMetaError, "len_a"):
            load(write(bad))

    def test_string_bound(self):
        bad = json.loads(json.dumps(VALID))
        bad["constraints"][0]["max"] = "20"
        with self.assertRaisesRegex(ProblemMetaError, "expected an integer"):
            load(write(bad))

    def test_boolean_bound_is_not_accepted_as_one(self):
        # bool is an int subclass in Python; `"max": true` must not load as 1.
        bad = json.loads(json.dumps(VALID))
        bad["constraints"][0]["max"] = True
        with self.assertRaisesRegex(ProblemMetaError, "expected an integer"):
            load(write(bad))

    def test_a_float_valued_integer_is_still_rejected(self):
        # 20.0 would render as `= 20.0;`, which is a `long long` initialized
        # from a double — legal C++, but not what the document says, and the
        # next edit to it is 20.5.
        bad = json.loads(json.dumps(VALID))
        bad["constraints"][0]["max"] = 20.0
        with self.assertRaisesRegex(ProblemMetaError, "expected an integer"):
            load(write(bad))


class TestRejectsCycles(unittest.TestCase):
    def test_rejects_a_self_dependency(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["depends_on"] = ["g1"]
        with self.assertRaisesRegex(ProblemMetaError, "g1"):
            load(write(bad))

    def test_rejects_a_two_node_cycle(self):
        bad = json.loads(json.dumps(VALID))
        bad["subtasks"][0]["depends_on"] = ["g2"]
        bad["subtasks"][1]["depends_on"] = ["g1"]
        with self.assertRaisesRegex(ProblemMetaError, "cycle"):
            load(write(bad))

    def test_accepts_a_diamond_which_is_not_a_cycle(self):
        ok = json.loads(json.dumps(VALID))
        ok["subtasks"].append({"id": "g3", "points": 0, "bounds": {},
                               "constraints_text": [], "depends_on": ["g1", "g2"]})
        ok["subtasks"][1]["depends_on"] = ["g1"]
        problem = load(write(ok))
        self.assertEqual(problem.subtask_ids(), ["g1", "g2", "g3"])

    def test_accepts_a_deep_reverse_chain_of_2000_subtasks(self):
        """Regression test: deep chain (g1→g2→...→g2000) raises RecursionError on pre-fix recursive code.

        This test builds a reverse-order dependency chain where each subtask depends on
        the next, with g1 declared first. When visit(g1) is called, it recursively
        walks g1→g2→...→g2000, which with the recursive implementation would exceed
        Python's ~1000 recursion limit. The iterative implementation must handle this.
        """
        ok = json.loads(json.dumps(VALID))
        ok["subtasks"] = []
        # Build reverse-order chain: g1 depends on g2, g2 depends on g3, ..., g1999 depends on g2000
        for i in range(2000):
            depends = [f"g{i + 2}"] if i < 1999 else []
            ok["subtasks"].append({
                "id": f"g{i + 1}",
                "points": 100 if i == 1999 else 0,
                "bounds": {},
                "constraints_text": [],
                "depends_on": depends
            })
        problem = load(write(ok))
        self.assertEqual(len(problem.subtask_ids()), 2000)

    def test_accepts_a_linear_chain_of_2000_subtasks_forward_order(self):
        """Large-input smoke test: forward-order chain (g1, g2→g1, g3→g2, ...).

        This variant does not trigger deep recursion because each subtask depends on
        an already-visited node, so it passes both pre-fix and post-fix code.
        Useful as a smoke test for large inputs but does NOT guard against recursion depth.
        """
        ok = json.loads(json.dumps(VALID))
        ok["subtasks"] = []
        for i in range(2000):
            depends = [] if i == 0 else [f"g{i}"]
            ok["subtasks"].append({
                "id": f"g{i + 1}",
                "points": 0 if i > 0 else 100,
                "bounds": {},
                "constraints_text": [],
                "depends_on": depends
            })
        problem = load(write(ok))
        self.assertEqual(len(problem.subtask_ids()), 2000)

    def test_rejects_a_cycle_at_depth_1500(self):
        """Regression test: cycle detected at depth 1500 raises ProblemMetaError, not RecursionError.

        Builds a deep reverse-order chain (g1→g2→...→g1500) with g1500 depending on itself.
        With the recursive implementation, detecting the self-loop at depth 1500 would
        require ~1500 nested calls before hitting the revisit check, exceeding Python's
        recursion limit. The iterative implementation must handle this.
        """
        ok = json.loads(json.dumps(VALID))
        ok["subtasks"] = []
        # Build reverse-order chain: g1 depends on g2, g2 depends on g3, ..., g1499 depends on g1500
        for i in range(1500):
            depends = [f"g{i + 2}"] if i < 1499 else [f"g{i + 1}"]  # g1500 depends on itself
            ok["subtasks"].append({
                "id": f"g{i + 1}",
                "points": 100 if i == 1499 else 0,
                "bounds": {},
                "constraints_text": [],
                "depends_on": depends
            })
        with self.assertRaisesRegex(ProblemMetaError, "cycle"):
            load(write(ok))

    def test_rejects_a_cycle_not_involving_first_visited_subtask(self):
        """A cycle among later subtasks must be detected."""
        ok = json.loads(json.dumps(VALID))
        # g1 has no dependencies (root)
        # g2, g3, g4 form a cycle not involving g1
        ok["subtasks"] = [
            {"id": "g1", "points": 50, "bounds": {}, "constraints_text": [], "depends_on": []},
            {"id": "g2", "points": 0, "bounds": {}, "constraints_text": [], "depends_on": ["g3"]},
            {"id": "g3", "points": 0, "bounds": {}, "constraints_text": [], "depends_on": ["g4"]},
            {"id": "g4", "points": 50, "bounds": {}, "constraints_text": [], "depends_on": ["g2"]},
        ]
        with self.assertRaisesRegex(ProblemMetaError, "cycle"):
            load(write(ok))

    def test_rejects_disjoint_components_one_cyclic(self):
        """Two disconnected graphs, one acyclic and one cyclic."""
        ok = json.loads(json.dumps(VALID))
        ok["subtasks"] = [
            {"id": "g1", "points": 50, "bounds": {}, "constraints_text": [], "depends_on": []},
            {"id": "g2", "points": 50, "bounds": {}, "constraints_text": [], "depends_on": ["g1"]},
            {"id": "g3", "points": 0, "bounds": {}, "constraints_text": [], "depends_on": ["g4"]},
            {"id": "g4", "points": 0, "bounds": {}, "constraints_text": [], "depends_on": ["g3"]},
        ]
        with self.assertRaisesRegex(ProblemMetaError, "cycle"):
            load(write(ok))

    def test_accepts_fan_in_that_is_not_a_cycle(self):
        """Multiple nodes depending on the same parent is not a cycle."""
        ok = json.loads(json.dumps(VALID))
        ok["subtasks"] = [
            {"id": "g1", "points": 20, "bounds": {}, "constraints_text": [], "depends_on": []},
            {"id": "g2", "points": 20, "bounds": {}, "constraints_text": [], "depends_on": ["g1"]},
            {"id": "g3", "points": 20, "bounds": {}, "constraints_text": [], "depends_on": ["g1"]},
            {"id": "g4", "points": 40, "bounds": {}, "constraints_text": [], "depends_on": ["g2", "g3"]},
        ]
        problem = load(write(ok))
        self.assertEqual(problem.subtask_ids(), ["g1", "g2", "g3", "g4"])


class TestIoValidation(unittest.TestCase):
    """`io.input`/`io.output` reach an isolate `--dir` mount and a filename
    join later in the pipeline, so a path separator or a dot-segment is a
    sandbox escape, not a style nit — these must never load."""

    def _load_with_io(self, io):
        problem = json.loads((FIXTURE / "problem.json").read_text(encoding="utf-8"))
        problem["io"] = io
        tmp = Path(tempfile.mkdtemp()) / "problem.json"
        tmp.write_text(json.dumps(problem), encoding="utf-8")
        return load(tmp)

    def test_io_input_rejects_path_separator(self):
        with self.assertRaises(ProblemMetaError) as ctx:
            self._load_with_io({"input": "sub/dir.inp", "output": "x.out"})
        self.assertIn("io.input", str(ctx.exception))

    def test_io_output_rejects_dot_segment(self):
        with self.assertRaises(ProblemMetaError) as ctx:
            self._load_with_io({"input": "x.inp", "output": "../escape.out"})
        self.assertIn("io.output", str(ctx.exception))

    def test_io_input_rejects_bare_dot_segment(self):
        # No "/" at all — this is the one case the separator check does not
        # already catch, so it is the only test that actually exercises the
        # dot-segment branch rather than the separator branch.
        with self.assertRaises(ProblemMetaError) as ctx:
            self._load_with_io({"input": "..", "output": "x.out"})
        self.assertIn("io.input", str(ctx.exception))

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


if __name__ == "__main__":
    unittest.main()

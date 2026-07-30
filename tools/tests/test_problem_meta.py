import json
import tempfile
import unittest
from pathlib import Path

from tools.problem_meta import ProblemMetaError, load

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


if __name__ == "__main__":
    unittest.main()

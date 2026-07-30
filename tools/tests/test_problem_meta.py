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


if __name__ == "__main__":
    unittest.main()

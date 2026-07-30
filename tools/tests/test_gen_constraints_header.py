import unittest

from tools.gen_constraints_header import identifier, render
from tools.problem_meta import Bound, Constraint, Problem, Subtask

PROBLEM = Problem(
    name="flight",
    title={"vi": "Chuyến bay đầu tiên"},
    tags=[],
    time_ms_published=1000,
    time_ms_computed=740,
    memory_mb=256,
    input="stdin",
    output="stdout",
    checker_kind="stock",
    checker_name="rcmp6",
    constraints=[
        Constraint(id="len_a", expr="1 \\le |A| \\le 20", min=1, max=20),
        Constraint(id="alphabet", expr="A in {0,1}*"),
    ],
    subtasks=[
        Subtask(id="g1", points=40, bounds={"len_a": Bound(max=6)},
                constraints_text=["$|A| \\le 6$"], depends_on=[]),
        Subtask(id="g2", points=60, bounds={}, constraints_text=[], depends_on=["g1"]),
    ],
    examples=[],
)


class TestIdentifier(unittest.TestCase):
    def test_upper_cases_and_replaces_punctuation(self):
        self.assertEqual(identifier("len_a"), "LEN_A")
        self.assertEqual(identifier("sum-n"), "SUM_N")


class TestRender(unittest.TestCase):
    def setUp(self):
        self.header = render(PROBLEM)

    def test_marks_itself_generated(self):
        self.assertIn("do not edit", self.header.lower())
        self.assertIn("gen_constraints_header.py", self.header)
        self.assertIn("#pragma once", self.header)

    def test_emits_global_bounds(self):
        self.assertIn("static const long long LEN_A_MIN = 1;", self.header)
        self.assertIn("static const long long LEN_A_MAX = 20;", self.header)

    def test_skips_constraints_without_numeric_bounds(self):
        self.assertNotIn("ALPHABET_MIN", self.header)
        self.assertNotIn("ALPHABET_MAX", self.header)

    def test_emits_narrowed_subtask_bounds(self):
        self.assertIn("static const long long G1_LEN_A_MAX = 6;", self.header)
        self.assertIn("static const long long G1_LEN_A_MIN = 1;", self.header)

    def test_subtask_without_override_inherits_global(self):
        self.assertIn("static const long long G2_LEN_A_MAX = 20;", self.header)

    def test_carries_the_expression_as_a_comment(self):
        self.assertIn("1 \\le |A| \\le 20", self.header)


if __name__ == "__main__":
    unittest.main()

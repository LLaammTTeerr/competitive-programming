import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.gen_constraints_header import identifier, render
from tools.problem_meta import Bound, Constraint, Problem, ProblemMetaError, Subtask

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

    def test_prefixes_numeric_ids_to_make_legal_identifier(self):
        self.assertEqual(identifier("1"), "C_1")
        self.assertEqual(identifier("2abc"), "C_2ABC")
        self.assertEqual(identifier("a1"), "A1")
        self.assertEqual(identifier("0"), "C_0")


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

    def test_subtask_only_bounds_are_emitted(self):
        """Regression: subtask-only bounds (no global min/max) must be emitted."""
        problem = Problem(
            name="test",
            title={},
            tags=[],
            time_ms_published=1000,
            time_ms_computed=None,
            memory_mb=256,
            input="stdin",
            output="stdout",
            checker_kind="stock",
            checker_name="cmp",
            constraints=[
                Constraint(id="special", expr="..."),  # no global min/max
            ],
            subtasks=[
                Subtask(id="g1", points=100,
                        bounds={"special": Bound(min=1, max=5)},
                        constraints_text=[], depends_on=[]),
            ],
            examples=[],
        )
        header = render(problem)
        self.assertIn("static const long long G1_SPECIAL_MIN = 1;", header)
        self.assertIn("static const long long G1_SPECIAL_MAX = 5;", header)

    def test_empty_problem_renders_valid_header(self):
        """Zero constraints and zero subtasks should still render a valid header."""
        problem = Problem(
            name="empty",
            title={},
            tags=[],
            time_ms_published=1000,
            time_ms_computed=None,
            memory_mb=256,
            input="stdin",
            output="stdout",
            checker_kind="stock",
            checker_name="cmp",
            constraints=[],
            subtasks=[],
            examples=[],
        )
        header = render(problem)
        self.assertIn("#pragma once", header)
        self.assertIn("do not edit", header.lower())
        self.assertIn("gen_constraints_header.py", header)

    def test_generated_header_compiles(self):
        """Verify the emitted header is syntactically valid C++."""
        try:
            result = subprocess.run(
                ["g++", "--version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise unittest.SkipTest("g++ not available")
        except FileNotFoundError:
            raise unittest.SkipTest("g++ not on PATH")

        header = render(PROBLEM)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".h", delete=False
        ) as f:
            f.write(header)
            temp_path = f.name

        try:
            result = subprocess.run(
                ["g++", "-std=c++17", "-Wno-pragma-once-outside-header", "-Wpedantic",
                 "-Werror", "-fsyntax-only", temp_path],
                capture_output=True,
                timeout=5,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"g++ failed to parse header: {result.stderr}",
            )
        finally:
            Path(temp_path).unlink()

    def test_collision_via_digit_prefix(self):
        """IDs that collide via digit prefix rule raise ProblemMetaError."""
        problem = Problem(
            name="collision",
            title={},
            tags=[],
            time_ms_published=1000,
            time_ms_computed=None,
            memory_mb=256,
            input="stdin",
            output="stdout",
            checker_kind="stock",
            checker_name="cmp",
            constraints=[
                Constraint(id="1", expr="...", min=1, max=5),
                Constraint(id="c_1", expr="...", min=1, max=5),
            ],
            subtasks=[],
            examples=[],
        )
        with self.assertRaises(ProblemMetaError) as ctx:
            render(problem)
        self.assertIn("Identifier collision", str(ctx.exception))
        self.assertIn("C_1", str(ctx.exception))

    def test_collision_via_punctuation_collapse(self):
        """IDs that collide via punctuation normalization raise ProblemMetaError."""
        problem = Problem(
            name="collision",
            title={},
            tags=[],
            time_ms_published=1000,
            time_ms_computed=None,
            memory_mb=256,
            input="stdin",
            output="stdout",
            checker_kind="stock",
            checker_name="cmp",
            constraints=[
                Constraint(id="len-a", expr="...", min=1, max=20),
                Constraint(id="len_a", expr="...", min=1, max=20),
            ],
            subtasks=[],
            examples=[],
        )
        with self.assertRaises(ProblemMetaError) as ctx:
            render(problem)
        self.assertIn("Identifier collision", str(ctx.exception))
        self.assertIn("LEN_A", str(ctx.exception))

    def test_distinct_ids_no_collision(self):
        """Normal problems with distinct IDs should render without error."""
        problem = Problem(
            name="normal",
            title={},
            tags=[],
            time_ms_published=1000,
            time_ms_computed=None,
            memory_mb=256,
            input="stdin",
            output="stdout",
            checker_kind="stock",
            checker_name="cmp",
            constraints=[
                Constraint(id="len_a", expr="...", min=1, max=20),
                Constraint(id="len_b", expr="...", min=1, max=30),
            ],
            subtasks=[
                Subtask(id="g1", points=100,
                        bounds={},
                        constraints_text=[], depends_on=[]),
            ],
            examples=[],
        )
        header = render(problem)
        self.assertIn("LEN_A_MIN", header)
        self.assertIn("LEN_B_MAX", header)


if __name__ == "__main__":
    unittest.main()

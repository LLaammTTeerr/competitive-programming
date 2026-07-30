import tempfile
import unittest
from pathlib import Path

from tools.drift_check import DriftCheckError, check, main, parse_tex
from tools.problem_meta import Constraint, Problem, Subtask

TEX = r"""
\documentclass[11pt, a4paper, oneside]{article}
\usepackage[vietnamese, color, standalone]{vnolymp}
\begin{document}
\begin{problem}[
  input  = stdin, output = stdout,
  time   = 1, memory = 256,
]{Chuyến bay đầu tiên}
Nội dung.
\begin{subtasks}
  \subtask{40}{$|A| \le 6$ và $|B| \le 6$}
  \subtask{60}{Không có ràng buộc gì thêm}
\end{subtasks}
\end{problem}
\end{document}
"""

PROBLEM = Problem(
    name="flight", title={}, tags=[], time_ms_published=1000, time_ms_computed=740,
    memory_mb=256, input="stdin", output="stdout",
    checker_kind="stock", checker_name="rcmp6",
    constraints=[Constraint(id="len_a", expr="x", min=1, max=20)],
    subtasks=[Subtask(id="g1", points=40), Subtask(id="g2", points=60)],
    examples=[],
)


class TestParseTex(unittest.TestCase):
    def test_reads_the_problem_key_list(self):
        parsed = parse_tex(TEX)
        self.assertEqual(parsed["time"], 1)
        self.assertEqual(parsed["memory"], 256)
        self.assertEqual(parsed["input"], "stdin")
        self.assertEqual(parsed["output"], "stdout")

    def test_reads_subtask_percentages_in_order(self):
        self.assertEqual(parse_tex(TEX)["subtask_points"], [40, 60])


class TestCheck(unittest.TestCase):
    def test_clean_document_reports_nothing(self):
        self.assertEqual(check(PROBLEM, TEX), [])

    def test_detects_time_mismatch(self):
        problems = check(PROBLEM, TEX.replace("time   = 1", "time   = 2"))
        self.assertEqual(len(problems), 1)
        self.assertIn("time", problems[0])

    def test_detects_memory_mismatch(self):
        problems = check(PROBLEM, TEX.replace("memory = 256", "memory = 512"))
        self.assertIn("memory", problems[0])

    def test_detects_subtask_points_mismatch(self):
        problems = check(PROBLEM, TEX.replace(r"\subtask{40}", r"\subtask{30}"))
        self.assertIn("subtask", problems[0].lower())

    def test_detects_subtask_count_mismatch(self):
        stripped = TEX.replace(
            "  \\subtask{60}{Không có ràng buộc gì thêm}\n", "")
        problems = check(PROBLEM, stripped)
        self.assertTrue(problems)

    def test_detects_io_mismatch(self):
        problems = check(PROBLEM, TEX.replace("input  = stdin", "input  = flight.inp"))
        self.assertIn("input", problems[0])


class TestMainErrorHandling(unittest.TestCase):
    def test_main_raises_drift_check_error_on_missing_statement_file(self):
        """R1: Missing file must raise DriftCheckError, not FileNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            problem_dir = Path(tmpdir) / "problem"
            problem_dir.mkdir()
            statement_file = problem_dir / "missing.tex"
            # Create a minimal problem.json
            problem_json = problem_dir / "problem.json"
            problem_json.write_text('{"schema": 1, "name": "test", "limits": {"time_ms_published": 1000, "memory_mb": 256}, "io": {"input": "stdin", "output": "stdout"}, "checker": {"kind": "stock", "name": "rcmp6"}, "subtasks": [{"id": "g1", "points": 100}], "constraints": []}')

            with self.assertRaises(DriftCheckError) as cm:
                main(["drift_check.py", str(problem_dir), str(statement_file)])
            self.assertIn("not found", str(cm.exception))

    def test_main_raises_drift_check_error_on_non_utf8_statement(self):
        """R1: Non-UTF-8 file must raise DriftCheckError, not UnicodeDecodeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            problem_dir = Path(tmpdir) / "problem"
            problem_dir.mkdir()
            statement_file = problem_dir / "statement.tex"
            # Write non-UTF-8 bytes
            statement_file.write_bytes(b'\xff\xfe invalid utf-8')
            # Create a minimal problem.json
            problem_json = problem_dir / "problem.json"
            problem_json.write_text('{"schema": 1, "name": "test", "limits": {"time_ms_published": 1000, "memory_mb": 256}, "io": {"input": "stdin", "output": "stdout"}, "checker": {"kind": "stock", "name": "rcmp6"}, "subtasks": [{"id": "g1", "points": 100}], "constraints": []}')

            with self.assertRaises(DriftCheckError) as cm:
                main(["drift_check.py", str(problem_dir), str(statement_file)])
            self.assertIn("UTF-8", str(cm.exception))


if __name__ == "__main__":
    unittest.main()

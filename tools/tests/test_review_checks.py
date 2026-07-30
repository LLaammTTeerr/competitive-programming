import json, shutil, tempfile, unittest
from pathlib import Path

from tools.review_checks import KINDS, run

FIXTURE = Path("tools/tests/fixtures/mini")


class TestRun(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "p"
        shutil.copytree(FIXTURE, self.dir,
                        ignore=shutil.ignore_patterns(
                            ".build", "invocation.json", "solutions.json",
                            "flags.json", "*.a"))

    def kinds(self, **kw):
        return {f.kind for f in run(self.dir, **kw)}

    def test_every_finding_uses_a_declared_kind_and_severity(self):
        for finding in run(self.dir):
            self.assertIn(finding.kind, KINDS)
            self.assertIn(finding.severity, ("high", "medium", "low"))

    def test_an_unfinished_package_reports_incomplete(self):
        self.assertIn("incomplete-package", self.kinds())

    def test_a_malformed_problem_json_does_not_raise(self):
        (self.dir / "problem.json").write_text("{ not json", encoding="utf-8")
        self.assertTrue(run(self.dir))

    def test_holes_in_invocation_json_are_reported(self):
        (self.dir / "invocation.json").write_text(json.dumps(
            {"schema": 1, "holes": [{"solution": "sol-wrong.cpp", "group": "g1",
                                     "expected": "WA", "actual": "OK"}],
             "mismatches": []}), encoding="utf-8")
        findings = [f for f in run(self.dir) if f.kind == "matrix-hole"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "high")
        self.assertIn("sol-wrong.cpp", findings[0].what)

    def test_mismatches_are_reported_separately_from_holes(self):
        (self.dir / "invocation.json").write_text(json.dumps(
            {"schema": 1, "holes": [],
             "mismatches": [{"solution": "sol-alt.cpp", "group": "g2",
                             "expected": "OK", "actual": "WA"}]}), encoding="utf-8")
        self.assertIn("matrix-mismatch", self.kinds())
        self.assertNotIn("matrix-hole", self.kinds())

    def test_a_solution_file_absent_from_the_scan_is_an_orphan(self):
        (self.dir / "solutions" / "notes.txt").write_text("x", encoding="utf-8")
        self.assertNotIn("orphan-solution", self.kinds())
        (self.dir / "solutions" / "sol-orphan.cpp").write_text(
            "int main(){}\n", encoding="utf-8")
        findings = [f for f in run(self.dir) if f.kind == "orphan-solution"]
        self.assertEqual(len(findings), 1)
        self.assertIn("sol-orphan.cpp", findings[0].what)

    def test_a_stale_constraints_header_is_reported(self):
        # Write a header that doesn't match render(problem)
        header = self.dir / "files" / "constraints.h"
        header.parent.mkdir(exist_ok=True)
        header.write_text("// wrong content\n", encoding="utf-8")
        self.assertIn("stale-constraints-header", self.kinds())

    def test_a_matching_constraints_header_is_not_reported(self):
        # Write the correct rendered header
        from tools.gen_constraints_header import render
        from tools.problem_meta import load
        problem = load(self.dir / "problem.json")
        header = self.dir / "files" / "constraints.h"
        header.parent.mkdir(exist_ok=True)
        header.write_text(render(problem), encoding="utf-8")
        self.assertNotIn("stale-constraints-header", self.kinds())

    def test_statement_drift_is_reported_when_a_tex_is_given(self):
        tex = self.dir / "mini.tex"
        tex.write_text(
            "\\begin{problem}[input = stdin, output = stdout,\n"
            "  time = 9, memory = 256,\n]{Mini}\n"
            "\\begin{subtasks}\\subtask{100}{x}\\end{subtasks}\n"
            "\\end{problem}\n", encoding="utf-8")
        findings = [f for f in run(self.dir, tex_path=tex)
                    if f.kind == "constraint-drift"]
        self.assertTrue(findings)
        self.assertEqual(findings[0].severity, "high")

    def test_invocation_json_with_holes_as_string_does_not_raise(self):
        (self.dir / "invocation.json").write_text(json.dumps(
            {"schema": 1, "holes": "not_a_list", "mismatches": []}), encoding="utf-8")
        result = run(self.dir)
        self.assertTrue(result)  # Should have findings, not raise

    def test_invocation_json_with_holes_as_int_does_not_raise(self):
        (self.dir / "invocation.json").write_text(json.dumps(
            {"schema": 1, "holes": 123, "mismatches": []}), encoding="utf-8")
        result = run(self.dir)
        self.assertTrue(result)  # Should have findings, not raise

    def test_invocation_json_with_top_level_list_does_not_raise(self):
        (self.dir / "invocation.json").write_text(json.dumps(
            [{"holes": []}]), encoding="utf-8")
        result = run(self.dir)
        self.assertTrue(result)  # Should have findings, not raise

    def test_nonexistent_problem_directory_does_not_raise(self):
        nonexistent = Path(tempfile.mkdtemp()) / "nonexistent"
        result = run(nonexistent)
        self.assertTrue(result)  # Should have findings, not raise

    def test_solutions_as_file_not_directory_does_not_raise(self):
        # Remove the solutions directory and replace with a file
        import shutil
        shutil.rmtree(self.dir / "solutions")
        (self.dir / "solutions").write_text("not a directory", encoding="utf-8")
        result = run(self.dir)
        self.assertTrue(result)  # Should have findings, not raise

    def test_tex_path_as_directory_does_not_raise(self):
        tex_dir = self.dir / "tex_dir"
        tex_dir.mkdir(parents=True, exist_ok=True)
        result = run(self.dir, tex_path=tex_dir)
        self.assertTrue(result)  # Should have findings, not raise

    def test_tex_path_with_invalid_utf8_does_not_raise(self):
        tex_path = self.dir / "bad.tex"
        tex_path.write_bytes(b"\xff\xfe")
        result = run(self.dir, tex_path=tex_path)
        self.assertTrue(result)  # Should have findings, not raise

    def test_constraints_h_without_problem_json_does_not_raise(self):
        (self.dir / "files").mkdir(exist_ok=True)
        (self.dir / "files" / "constraints.h").write_text("test", encoding="utf-8")
        # problem.json was not copied, so problem is None
        result = run(self.dir)
        self.assertTrue(result)  # Should have findings, not raise


class TestCleanPackageReturnsNoFindings(unittest.TestCase):
    """A known-good, complete package should produce zero findings."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()) / "p"
        # Copy the fixture, excluding incomplete phases
        shutil.copytree(FIXTURE, self.dir,
                        ignore=shutil.ignore_patterns(".build", ".pycache"))

    def test_complete_fixture_produces_no_findings(self):
        """A complete, clean package should produce zero findings."""
        # Add examples to problem.json to make it complete
        import json
        problem_path = self.dir / "problem.json"
        problem = json.loads(problem_path.read_text(encoding="utf-8"))
        problem["examples"] = [{"test": "01"}]
        problem_path.write_text(json.dumps(problem, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")

        # Create the sample files
        (self.dir / "01.in").write_text("1 2\n", encoding="utf-8")
        (self.dir / "01.a").write_text("3\n", encoding="utf-8")

        # Regenerate constraints.h to match problem.json
        from tools.gen_constraints_header import render
        from tools.problem_meta import load
        problem = load(self.dir / "problem.json")
        (self.dir / "files" / "constraints.h").write_text(render(problem), encoding="utf-8")

        # Write valid invocation.json with no holes/mismatches
        (self.dir / "invocation.json").write_text(
            json.dumps({"schema": 1, "holes": [], "mismatches": []}),
            encoding="utf-8")

        findings = run(self.dir)
        if findings:
            # If still findings, report them
            msg = "Complete fixture has findings:\n"
            for f in findings:
                msg += f"  {f.severity.upper()} {f.kind}: {f.what}\n"
            self.fail(msg)
        self.assertEqual(findings, [])

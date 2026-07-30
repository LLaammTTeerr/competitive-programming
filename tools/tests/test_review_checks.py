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

    def test_a_constraints_header_older_than_problem_json_is_stale(self):
        header = self.dir / "files" / "constraints.h"
        header.parent.mkdir(exist_ok=True)
        header.write_text("#pragma once\n", encoding="utf-8")
        import os, time
        old = time.time() - 3600
        os.utime(header, (old, old))
        self.assertIn("stale-constraints-header", self.kinds())

    def test_a_fresh_constraints_header_is_not_reported(self):
        header = self.dir / "files" / "constraints.h"
        header.parent.mkdir(exist_ok=True)
        header.write_text("#pragma once\n", encoding="utf-8")
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

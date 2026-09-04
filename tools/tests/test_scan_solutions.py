import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.problem_meta import Constraint, Problem, Subtask
from tools.scan_solutions import ScanError, parse_block, scan

MAIN = """\
/**
 * @tag        main
 * @expect     g1=OK g2=OK
 * @algorithm  Aho-Corasick over {A,B} plus a linear solve on the absorbing chain.
 * @complexity O((|A|+|B|)^3)
 */
int main() { return 0; }
"""

GREEDY = """\
/**
 * @tag        wrong-answer
 * @expect     g1=WA g2=WA
 * @algorithm  Compares first occurrence by START index rather than END index.
 * @why-wrong  Diverges from the model exactly when |A| != |B|.
 * @complexity O(|A| + |B|)
 */
int main() { return 0; }
"""

PROBLEM = Problem(
    name="flight", title={}, tags=[], time_ms_published=1000, time_ms_computed=None,
    memory_mb=256, input="stdin", output="stdout",
    checker_kind="stock", checker_name="rcmp6",
    constraints=[Constraint(id="len_a", expr="x", min=1, max=20)],
    subtasks=[Subtask(id="g1", points=40), Subtask(id="g2", points=60)],
    examples=[],
    format="oi",
)


class TestParseBlock(unittest.TestCase):
    def test_extracts_every_field(self):
        parsed = parse_block(GREEDY)
        self.assertEqual(parsed["tag"], "wrong-answer")
        self.assertEqual(parsed["expect"], {"g1": "WA", "g2": "WA"})
        self.assertTrue(parsed["algorithm"].startswith("Compares first occurrence"))
        self.assertIn("Diverges", parsed["why_wrong"])
        self.assertEqual(parsed["complexity"], "O(|A| + |B|)")

    def test_why_wrong_is_optional(self):
        self.assertIsNone(parse_block(MAIN)["why_wrong"])

    def test_rejects_missing_tag(self):
        with self.assertRaisesRegex(ScanError, "@tag"):
            parse_block("/**\n * @expect g1=OK\n */\n")

    def test_reads_metadata_under_a_preceding_block_comment(self):
        # The scan gates the entire invocation matrix, and it used to break
        # at the first line containing `*/` wherever it appeared — so a file
        # that plainly contains `@tag main` under an ordinary note reported
        # "metadata block is missing @tag", asserting the opposite of what
        # the file says.
        note = "/* Ported from the 2019 editorial; see notes.md. */\n"
        self.assertEqual(parse_block(note + MAIN)["tag"], "main")

    def test_reads_metadata_under_a_multi_line_licence_header(self):
        header = "/*\n * Copyright (c) 2026.\n * All rights reserved.\n */\n"
        parsed = parse_block(header + GREEDY)
        self.assertEqual(parsed["tag"], "wrong-answer")
        self.assertEqual(parsed["expect"], {"g1": "WA", "g2": "WA"})

    def test_reads_metadata_under_a_preceding_doc_block_without_fields(self):
        self.assertEqual(parse_block("/** A note. */\n" + MAIN)["tag"], "main")

    def test_ignores_a_trailing_block_comment_after_the_metadata(self):
        parsed = parse_block(MAIN + "\n/**\n * @tag failed\n */\n")
        self.assertEqual(parsed["tag"], "main")

    def test_rejects_an_unterminated_metadata_block(self):
        # Deferred minor T4-8: the old line scan read to end of file.
        with self.assertRaisesRegex(ScanError, "never closed"):
            parse_block("/**\n * @tag main\n * @expect g1=OK\nint main(){}\n")

    def test_rejects_a_file_with_no_metadata_block_at_all(self):
        with self.assertRaisesRegex(ScanError, "no `/\\*\\* \\.\\.\\. \\*/`"):
            parse_block("int main() { return 0; }\n")

    def test_rejects_unknown_tag(self):
        with self.assertRaisesRegex(ScanError, "sideways"):
            parse_block("/**\n * @tag sideways\n * @expect g1=OK\n"
                        " * @algorithm x\n * @complexity O(1)\n */\n")

    def test_rejects_unknown_verdict(self):
        with self.assertRaisesRegex(ScanError, "MAYBE"):
            parse_block("/**\n * @tag main\n * @expect g1=MAYBE\n"
                        " * @algorithm x\n * @complexity O(1)\n */\n")


class TestScan(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "solutions").mkdir()
        (self.dir / "solutions" / "sol-main.cpp").write_text(MAIN, encoding="utf-8")
        (self.dir / "solutions" / "sol-greedy.cpp").write_text(GREEDY, encoding="utf-8")

    def test_collects_every_solution_sorted_by_filename(self):
        payload = scan(self.dir, PROBLEM)
        self.assertEqual([s["file"] for s in payload["solutions"]],
                         ["sol-greedy.cpp", "sol-main.cpp"])
        self.assertEqual(payload["schema"], 1)

    def test_derives_an_updated_timestamp_for_each_solution(self):
        for entry in scan(self.dir, PROBLEM)["solutions"]:
            self.assertRegex(entry["updated"], r"^\d{4}-\d{2}-\d{2}T")

    def test_rejects_expect_naming_an_unknown_group(self):
        (self.dir / "solutions" / "sol-bad.cpp").write_text(
            MAIN.replace("g2=OK", "g9=OK"), encoding="utf-8")
        with self.assertRaisesRegex(ScanError, "g9"):
            scan(self.dir, PROBLEM)

    def test_rejects_expect_missing_a_group(self):
        (self.dir / "solutions" / "sol-bad.cpp").write_text(
            MAIN.replace(" g2=OK", ""), encoding="utf-8")
        with self.assertRaisesRegex(ScanError, "g2"):
            scan(self.dir, PROBLEM)

    def test_rejects_two_main_solutions(self):
        (self.dir / "solutions" / "sol-other.cpp").write_text(MAIN, encoding="utf-8")
        with self.assertRaisesRegex(ScanError, "exactly one"):
            scan(self.dir, PROBLEM)

    def test_rejects_no_main_solution(self):
        (self.dir / "solutions" / "sol-main.cpp").unlink()
        with self.assertRaisesRegex(ScanError, "exactly one"):
            scan(self.dir, PROBLEM)

    def test_rejects_invalid_utf8_with_scantError(self):
        """File with invalid UTF-8 raises ScanError, not UnicodeDecodeError."""
        bad_file = self.dir / "solutions" / "sol-bad.cpp"
        bad_file.write_bytes(b"/**\n * @tag main\n * @expect g1=OK g2=OK\n * @algorithm x\n * @complexity O(1)\n */\nint main() { return \xff; }\n")
        with self.assertRaisesRegex(ScanError, "sol-bad.cpp"):
            scan(self.dir, PROBLEM)

    def test_untracked_file_uses_mtime_timestamp(self):
        """Untracked file in git repo with history derives timestamp from mtime, not git log."""
        # Initialize a git repo in the temp directory
        git_dir = Path(tempfile.mkdtemp())

        # Initialize git repo and configure user
        subprocess.run(["git", "init"], cwd=git_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=git_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=git_dir, capture_output=True, check=True)

        # Create and commit an unrelated file to establish repo history
        # (without history, git log exits 128 which is indistinguishable from "no git repo")
        (git_dir / "README.md").write_text("# Test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=git_dir, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=git_dir, capture_output=True, check=True)

        # Now create solutions directory and write solution files WITHOUT adding them
        # (they will be untracked in a repo that has history)
        solutions_dir = git_dir / "solutions"
        solutions_dir.mkdir()
        (solutions_dir / "sol-main.cpp").write_text(MAIN, encoding="utf-8")
        (solutions_dir / "sol-greedy.cpp").write_text(GREEDY, encoding="utf-8")

        # Scan should succeed and produce mtime-derived timestamps
        payload = scan(git_dir, PROBLEM)
        for entry in payload["solutions"]:
            # Should have a valid timestamp (not empty, not error)
            self.assertRegex(entry["updated"], r"^\d{4}-\d{2}-\d{2}T")


if __name__ == "__main__":
    unittest.main()

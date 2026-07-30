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


if __name__ == "__main__":
    unittest.main()

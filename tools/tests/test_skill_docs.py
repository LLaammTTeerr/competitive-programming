"""Guard the prose the tools cannot guard.

`preparing-tests` and `reviewing-problems` both carry the reaching-check
recipe, and that duplication is deliberate: skills load independently, with no
include mechanism, so a reviewer who never opens `preparing-tests` still has to
find the recipe in front of them. What was *not* deliberate is the claim that
followed it — "byte-for-byte identical, so they cannot drift". That is an
observation about a moment in time, not a guarantee, and it was already false
when it was written: block 1's trailing comment read

    # first number is the shortest A in the group      (preparing-tests)
    # first line is the shortest value in the group    (reviewing-problems)

Two copies with no mechanism holding them together drift silently, and the
half that drifts is whichever one the next editor did not have open. This
module is that mechanism.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tools import run_matrix
from tools.matrix_core import _SEVERITY
from tools.scan_solutions import VERDICTS

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"

# A fenced block, tagged with its language. Non-greedy so each match is one
# complete fence rather than everything between the first and last one.
_FENCE = re.compile(r"^```(?P<lang>[a-zA-Z0-9_-]*)\n(?P<body>.*?)^```$",
                    re.DOTALL | re.MULTILINE)

# The two halves of the recipe, identified by content rather than by line
# number — line numbers move every time a paragraph above them is edited, and
# a test that has to be renumbered on every edit is a test that gets deleted.
RECIPE_MARKERS = {
    "per-test validator log loop": "--testOverviewLogFileName",
    "non-numeric bound fallback": "FNR==1",
}

DUPLICATED_IN = ("preparing-tests", "reviewing-problems")


def bash_blocks(skill: str) -> list[str]:
    path = SKILLS / skill / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    return [m.group("body") for m in _FENCE.finditer(text)
            if m.group("lang") == "bash"]


class TestFenceExtraction(unittest.TestCase):
    """The extractor itself, so a failure below is a real drift and not this
    module quietly matching nothing. A `find_recipe` that returned `None` for
    both files would otherwise make every comparison trivially pass — the same
    vacuous-guard shape this branch has already been bitten by twice."""

    def test_every_skill_file_exists(self):
        for skill in DUPLICATED_IN:
            self.assertTrue((SKILLS / skill / "SKILL.md").is_file(),
                            f"{skill}/SKILL.md is missing")

    def test_bash_blocks_are_found_in_both_files(self):
        for skill in DUPLICATED_IN:
            self.assertTrue(bash_blocks(skill),
                            f"no ```bash blocks extracted from {skill}")

    def test_a_fence_is_not_swallowed_into_its_neighbour(self):
        # Non-greedy matching: no extracted block may contain a fence marker.
        for skill in DUPLICATED_IN:
            for block in bash_blocks(skill):
                self.assertNotIn("```", block,
                                 f"{skill}: fence extraction ran past a block end")


class TestReachingCheckRecipeDoesNotDrift(unittest.TestCase):
    def recipe(self, skill: str, marker: str) -> str:
        matches = [b for b in bash_blocks(skill) if marker in b]
        self.assertEqual(
            len(matches), 1,
            f"{skill}: expected exactly one ```bash block containing "
            f"{marker!r}, found {len(matches)}")
        return matches[0]

    def test_both_copies_of_each_recipe_block_are_byte_identical(self):
        first, second = DUPLICATED_IN
        for name, marker in RECIPE_MARKERS.items():
            with self.subTest(block=name):
                self.assertEqual(
                    self.recipe(first, marker), self.recipe(second, marker),
                    f"the {name} block has drifted between {first} and "
                    f"{second}. The duplication is deliberate (skills load "
                    f"independently, there is no include mechanism), so the "
                    f"fix is to copy one over the other — not to delete "
                    f"either copy and not to relax this test.")

    def test_the_validator_loop_checks_the_validators_exit_code(self):
        # A validator that rejects a test writes an empty log, and an empty log
        # contributes nothing to the union — which reads back as "unreached",
        # the exact false finding the per-test-log fix removed. Losing the exit
        # check would reintroduce it silently.
        for skill in DUPLICATED_IN:
            with self.subTest(skill=skill):
                block = self.recipe(skill, "--testOverviewLogFileName")
                self.assertIn("REJECTED", block,
                              f"{skill}: the reaching-check loop ignores the "
                              f"validator's exit code")


class TestFileIOProseMatchesTheDriver(unittest.TestCase):
    """The IO-mode paragraphs, pinned to the code they describe.

    For two whole stages `preparing-tests`, `validating-solutions` and the
    README all said file IO was "rejected loudly by `run_matrix`". Nothing
    caught it when that stopped being true, because nothing was watching
    those sentences — three separate documents making the same claim, and
    no test naming any of them. This class is that mechanism, and it is
    deliberately written against *values imported from the code* rather
    than against a second copy of the prose: a test that only compares one
    string in this file to one string in a document goes green the moment
    someone edits both, which is precisely how the retired claim survived.
    """

    DOCUMENTS = {
        "README.md": ROOT / "README.md",
        "preparing-tests": SKILLS / "preparing-tests" / "SKILL.md",
        "validating-solutions": SKILLS / "validating-solutions" / "SKILL.md",
    }

    # Sentences that were true before file IO landed and are false now. They
    # are listed literally, because the failure mode being guarded is a
    # revert or a copy-paste from an old draft, not a paraphrase.
    RETIRED_CLAIMS = (
        "Only stdin/stdout problems are supported",
        "rejected loudly by",
        "the file-IO guard",
        "it is a later feature, not a silent partial mode",
    )

    def text(self, name: str) -> str:
        path = self.DOCUMENTS[name]
        self.assertTrue(path.is_file(), f"{path} is missing")
        body = path.read_text(encoding="utf-8")
        # The extractor guard, same role as TestFenceExtraction above: an
        # empty read would make every assertNotIn below trivially pass.
        self.assertGreater(len(body), 1000, f"{path} read back nearly empty")
        return body

    def test_no_document_still_claims_file_io_is_rejected(self):
        for name in self.DOCUMENTS:
            body = self.text(name)
            for claim in self.RETIRED_CLAIMS:
                with self.subTest(document=name, claim=claim):
                    self.assertNotIn(
                        claim, body,
                        f"{name} still carries a pre-file-IO claim. "
                        f"run_matrix.run() accepts file-IO problems — the "
                        f"refusal it describes was deleted.")

    def flat(self, name: str) -> str:
        """`text`, with every run of whitespace collapsed to one space.

        These documents are hard-wrapped at ~76 columns, so any phrase long
        enough to be worth pinning is split across a newline in at least one
        of them. Matching the raw text would make this test pass or fail on
        where a paragraph happened to wrap.
        """
        return re.sub(r"\s+", " ", self.text(name))

    def test_every_document_states_what_file_io_does_not_change(self):
        # The two facts a setter most needs and most doubts. Duplicated
        # across all three documents on purpose (skills load independently,
        # there is no include mechanism), which is exactly why they need a
        # test holding them together.
        required = (
            "enerators and validators are unaffected",
            "three file paths",
        )
        for name in self.DOCUMENTS:
            body = self.flat(name)
            for phrase in required:
                with self.subTest(document=name, phrase=phrase):
                    self.assertIn(
                        phrase, body,
                        f"{name} describes file IO without saying that "
                        f"{phrase!r} — the question every setter asks first.")

    def test_prose_names_the_drivers_real_staged_stdout_file(self):
        # `validating-solutions` tells a reader their `io.output` may not
        # collide with the driver's staged stdout, and names it. Rename
        # STAGED_STDOUT_NAME and that instruction silently starts naming a
        # file that no longer exists.
        self.assertIn(f"(`{run_matrix.STAGED_STDOUT_NAME}`)",
                      self.flat("validating-solutions"),
                      "the collision warning names a file the driver no "
                      "longer stages to")

    def test_the_declarable_verdicts_in_prose_are_the_ones_the_scanner_takes(self):
        # `validating-solutions` claims @expect accepts exactly
        # `OK WA TL ML PE RE`. That list lives in scan_solutions.VERDICTS,
        # and the whole NO_OUTPUT-is-a-mismatch-not-a-hole explanation
        # around it is only true while NO_OUTPUT stays out of it.
        body = self.flat("validating-solutions")
        match = re.search(r"`([A-Z][A-Z ]+)` \(`scan_solutions\.VERDICTS`\)", body)
        self.assertIsNotNone(
            match, "validating-solutions no longer quotes the declarable "
                   "verdict list next to `scan_solutions.VERDICTS`")
        self.assertEqual(match.group(1).split(), list(VERDICTS),
                         "the verdict list in validating-solutions has "
                         "drifted from scan_solutions.VERDICTS")
        self.assertNotIn("NO_OUTPUT", VERDICTS,
                         "NO_OUTPUT became declarable, so the prose calling "
                         "it 'not declarable' is now wrong")
        self.assertIn("NO_OUTPUT", _SEVERITY,
                      "NO_OUTPUT left the severity table the prose ranks it in")

    def test_no_output_is_documented_as_ranked_next_to_FAIL(self):
        # The ranking claim in prose, checked against the table itself:
        # NO_OUTPUT must sit immediately after FAIL, above every verdict a
        # solution can earn on its own merits.
        self.assertEqual(_SEVERITY[:2], ["FAIL", "NO_OUTPUT"], _SEVERITY)
        self.assertIn("NO_OUTPUT", self.text("validating-solutions"))


if __name__ == "__main__":
    unittest.main()

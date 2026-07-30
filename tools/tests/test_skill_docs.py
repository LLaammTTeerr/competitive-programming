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

SKILLS = Path(__file__).resolve().parents[2] / "skills"

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


if __name__ == "__main__":
    unittest.main()

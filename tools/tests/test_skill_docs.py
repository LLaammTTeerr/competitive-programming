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

import inspect
import re
import unittest
from pathlib import Path

from tools import box_pool, run_matrix
from tools.matrix_core import _SEVERITY
from tools.package_status import PHASE_ORDER
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


def skill_text(skill: str) -> str:
    return (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")


def flatten(text: str) -> str:
    """Collapse every run of whitespace to one space.

    These files are hard-wrapped at ~76 columns, so any phrase long enough to
    be worth pinning is split across a newline. Matching raw text would make a
    test pass or fail on where a paragraph happened to wrap.
    """
    return re.sub(r"\s+", " ", text)


def skill_dirs() -> set[str]:
    return {p.name for p in SKILLS.iterdir() if (p / "SKILL.md").is_file()}


def bash_blocks(skill: str) -> list[str]:
    text = skill_text(skill)
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
    # Each one is the phrase as it actually stood, not a shortened key: the
    # substring `"rejected loudly by"` on its own also matches a future
    # document legitimately writing "rejected loudly by the validator", and a
    # guard that fires on true sentences gets deleted rather than obeyed.
    RETIRED_CLAIMS = (
        "Only stdin/stdout problems are supported",
        "rejected loudly by `run_matrix",
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
        # Matched against `flat`, not `text`: these documents are hard-wrapped
        # at ~76 columns, and the claims above are long enough that the
        # originals were split across a newline in both skills that carried
        # them — so a raw match would silently stop catching them the moment a
        # phrase got specific enough to be worth pinning.
        for name in self.DOCUMENTS:
            body = self.flat(name)
            for claim in self.RETIRED_CLAIMS:
                with self.subTest(document=name, claim=claim):
                    # `assertTrue`, not `assertNotIn`: unittest renders the
                    # container in an assertIn/assertNotIn failure with no
                    # length cap, and these containers are whole normalized
                    # documents (~10 KB of noise around the one fact that
                    # matters, which is the claim named here).
                    self.assertTrue(
                        claim not in body,
                        f"{name} still carries a pre-file-IO claim "
                        f"{claim!r}. run_matrix.run() accepts file-IO "
                        f"problems — the refusal it describes was deleted.")

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
                    # `assertTrue`, not `assertIn` — see above: `assertIn`
                    # would print the whole ~10 KB normalized document into
                    # the failure, burying the one line that says what is
                    # wrong and which file to open.
                    self.assertTrue(
                        phrase in body,
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


class TestWritingStatementsRoutingTable(unittest.TestCase):
    """The routing table `writing-statements` carries, pinned to the things
    outside it that it names.

    That file spent two stages as the terminus of every "the prose belongs
    elsewhere" row in the other skills' boundary tables, with no table of its
    own and no statement of where control went next. The table it now carries
    names sibling skills and `PHASE_ORDER` phases — both of which live in
    other files and can be renamed by someone who never opens this one. A
    table naming a skill that cannot be loaded is worse than no table at all:
    a router that finds nothing falls back to asking, while a router handed a
    dead name follows it.

    Every assertion below reads the filesystem or imports from
    `package_status`, so it fails on a rename rather than on a second copy of
    the same prose kept in this file.
    """

    SKILL = "writing-statements"
    SECTIONS = ("## Am I the right skill?", "## Two passes, and where each one exits")

    # Named in the `Use` column of the boundary table.
    TABLE_NEIGHBOURS = ("shaping-problems", "preparing-tests",
                        "reviewing-problems", "creating-problems",
                        "solving-problems")
    # Named in the routing prose but not offered as a pre-load alternative.
    ALSO_REFERENCED = ("validating-solutions",)

    # The reciprocal direction. "check my statement" appears verbatim in
    # `reviewing-problems`' own description, so a router can land there for a
    # request that means `writing-statements` — and mediating the collision
    # from one side only leaves the other side with no prompt to ask at all.
    # `(skill, boundary-table heading)`.
    RECIPROCAL = ("reviewing-problems", "## Am I the right skill?")

    # Phases the exit prose names, in the order it claims they run.
    CLAIMED_PHASE_ORDER = ("statement", "constraints_header", "model_solution")

    def body(self, skill: str | None = None) -> str:
        skill = skill or self.SKILL
        text = skill_text(skill)
        # Extractor guard: an empty or truncated read would make several
        # assertions below trivially pass.
        self.assertGreater(len(text), 4000,
                           f"{skill}/SKILL.md read back nearly empty")
        return text

    def section(self, heading: str, skill: str | None = None) -> str:
        skill = skill or self.SKILL
        text = self.body(skill)
        start = text.find(heading)
        self.assertNotEqual(start, -1, f"{skill} has no {heading!r} section")
        end = text.find("\n## ", start + len(heading))
        return text[start:end if end != -1 else len(text)]

    def use_cells(self, skill: str | None = None,
                  heading: str | None = None) -> list[str]:
        """The right-hand column of the boundary table, header and rule
        dropped."""
        rows = []
        for line in self.section(heading or self.SECTIONS[0], skill).splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) != 2 or set(cells[0]) <= set("-: "):
                continue
            if cells == ["If it's really about", "Use"]:
                continue
            rows.append(cells[1])
        return rows

    def test_the_boundary_table_parses_into_rows(self):
        # Guard for every table assertion below: a heading with no table
        # under it, or a parser that matched nothing, would make them vacuous.
        self.assertGreaterEqual(
            len(self.use_cells()), 4,
            f"{self.SKILL}'s boundary table did not parse into rows — either "
            f"the table was removed or its shape changed")

    def test_every_use_cell_names_a_skill_that_exists_on_disk(self):
        real = skill_dirs()
        for cell in self.use_cells():
            names = re.findall(r"competitive-programming:([a-z][a-z-]*)", cell)
            with self.subTest(row=cell):
                self.assertTrue(
                    names,
                    f"{self.SKILL}: boundary table row routes somewhere "
                    f"unnamed — every `Use` cell must name a "
                    f"`competitive-programming:<skill>` destination")
                for name in names:
                    self.assertIn(
                        name, real,
                        f"{self.SKILL}'s boundary table routes to "
                        f"{name!r}, which is not a skill directory. Skills "
                        f"on disk: {sorted(real)}")

    def test_the_table_offers_every_neighbour_a_statement_request_can_mean(self):
        cells = " ".join(self.use_cells())
        real = skill_dirs()
        for name in self.TABLE_NEIGHBOURS:
            with self.subTest(neighbour=name):
                self.assertIn(name, real,
                              f"{name} is no longer a skill directory — the "
                              f"routing table and this list both need updating")
                self.assertIn(f"competitive-programming:{name}", cells,
                              f"{self.SKILL}'s boundary table dropped the row "
                              f"routing to {name}")

        # And the same offer, back the other way. `reviewing-problems` claims
        # "check my statement" verbatim in its own description, so it is a
        # live destination for a request that means this skill; a router that
        # lands there must be prompted to ask, exactly as one that lands here
        # is prompted about `reviewing-problems`. The fix for that collision
        # shipped in one direction only, and nothing was watching the other.
        back_skill, back_heading = self.RECIPROCAL
        self.assertIn(back_skill, real,
                      f"{back_skill} is no longer a skill directory")
        back_rows = self.use_cells(back_skill, back_heading)
        # Same vacuity guard as `test_the_boundary_table_parses_into_rows`:
        # a heading with no table under it must not pass silently.
        self.assertGreaterEqual(
            len(back_rows), 3,
            f"{back_skill}'s boundary table under {back_heading!r} did not "
            f"parse into rows — the table was removed or its shape changed")
        self.assertIn(
            f"competitive-programming:{self.SKILL}", " ".join(back_rows),
            f"{back_skill}'s boundary table has no row routing back to "
            f"{self.SKILL}, so the 'check my statement' collision — which "
            f"{back_skill}'s own description claims verbatim — is mediated "
            f"in one direction only")

    def test_no_stale_skill_name_survives_anywhere_in_the_file(self):
        # Bare backticked names in the exit prose (`preparing-tests`,
        # `solving-problems`, ...) are not caught by the table check above.
        # A token shaped like one of this plugin's skill names must be one:
        # `sol-main`, `gen-max`, `ff-only` and `kitchen-sink` do not match,
        # because their prefixes are not skill-name prefixes.
        real = skill_dirs()
        prefixes = {name.split("-")[0] for name in real}
        shaped = re.compile(r"`((?:%s)-[a-z]+)`" % "|".join(sorted(prefixes)))
        found = set(shaped.findall(self.body()))
        self.assertTrue(found, f"{self.SKILL} names no sibling skill at all")
        for name in sorted(found):
            with self.subTest(reference=name):
                self.assertIn(name, real,
                              f"{self.SKILL} refers to `{name}`, which is not "
                              f"a skill directory")

    def test_every_referenced_skill_is_loadable(self):
        real = skill_dirs()
        text = self.body()
        for name in self.TABLE_NEIGHBOURS + self.ALSO_REFERENCED:
            with self.subTest(skill=name):
                self.assertIn(name, real, f"{name} is not a skill directory")
                self.assertIn(f"`{name}`", text,
                              f"{self.SKILL} no longer names {name}, which its "
                              f"routing depends on")

    def test_the_exit_prose_names_phases_the_driver_actually_has(self):
        prose = self.section(self.SECTIONS[1])
        for phase in self.CLAIMED_PHASE_ORDER + ("samples",):
            with self.subTest(phase=phase):
                self.assertIn(phase, PHASE_ORDER,
                              f"{phase!r} left package_status.PHASE_ORDER")
                self.assertIn(f"`{phase}`", prose,
                              f"{self.SKILL}'s exit prose no longer names the "
                              f"{phase!r} phase")

    def test_the_claimed_phase_sequence_matches_PHASE_ORDER(self):
        # The exact failure this branch has already shipped once: a skill
        # enumerating the phases in an order the driver does not use. The
        # prose claims statement -> constraints_header -> model_solution, and
        # that `samples` is the pipeline's last phase.
        indices = [PHASE_ORDER.index(p) for p in self.CLAIMED_PHASE_ORDER]
        self.assertEqual(
            indices, sorted(indices),
            f"{self.SKILL} claims the phases run in the order "
            f"{self.CLAIMED_PHASE_ORDER}, but PHASE_ORDER is {PHASE_ORDER}")
        self.assertEqual(
            PHASE_ORDER[-1], "samples",
            f"{self.SKILL} says the samples pass is the last phase before the "
            f"audit; PHASE_ORDER now ends with {PHASE_ORDER[-1]!r}")

    def test_the_statement_ambiguity_stop_is_not_reopened(self):
        # Stage 2 shipped `creating-problems` drawing this as a STOP while
        # `validating-solutions` routed onward to `writing-statements` and
        # kept going. All four documents must keep saying the same thing, and
        # the newest one is the one pointed at.
        agree = {
            "writing-statements":
                "is a STOP, and it does not route here",
            "validating-solutions":
                "Do **not** hand off to `writing-statements` and carry on "
                "validating",
            "reviewing-problems": "## The one hard stop",
            "creating-problems": "STOP: unresolvable HIGH",
        }
        for skill, claim in agree.items():
            with self.subTest(skill=skill):
                self.assertIn(
                    claim, flatten(skill_text(skill)),
                    f"{skill} no longer states the unresolvable HIGH "
                    f"statement-ambiguity stop the same way the other three "
                    f"do. This single edge is what the gate model hangs on — "
                    f"fix the disagreement, do not relax this test.")


class TestParallelSafetyDocs(unittest.TestCase):
    """`run_matrix` stopped deriving box ids from `pid` (Tasks 1-5): it now
    leases them from a per-user pool and runs pass 2 concurrently. The old
    "run it alone" warning trained readers to serialise work that no longer
    needs it, and a stale safety warning is worse than none — these guard
    against it creeping back in.

    Pinned against the code's own names, not string literals copied from
    prose: renaming `box_pool.POOL_ENV`/`LOCK_DIR_ENV` or the
    `"retimed_serially"` payload key should fail these tests, the same way
    `test_prose_names_the_drivers_real_staged_stdout_file` above is pinned
    to `run_matrix.STAGED_STDOUT_NAME` rather than a copy of the string.
    """

    def test_readme_no_longer_claims_the_tools_are_serial_only(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("not parallel-safe", readme)
        self.assertIn(box_pool.POOL_ENV, readme)
        self.assertIn(box_pool.LOCK_DIR_ENV, readme)

    def test_validating_solutions_documents_the_worker_knob(self):
        skill = skill_text("validating-solutions")
        self.assertIn(box_pool.POOL_ENV, skill)
        self.assertIn("retimed_serially", skill)
        # The payload field the doc's promise actually depends on: a reader
        # parsing invocation.json needs this exact key to still exist.
        self.assertIn('"retimed_serially"', inspect.getsource(run_matrix),
                      "run_matrix.py no longer writes a literal "
                      "'retimed_serially' payload key; the docs still "
                      "promise readers can look for one")


class TestTestGenerationReference(unittest.TestCase):
    """`preparing-tests` delegates its generator-design doctrine to a
    reference file, the same way `solving-problems` delegates the black-magic
    toolbox and `running-contests` the judge registry.

    A pointer to a file that does not exist reads as authoritative and
    delivers nothing, so the pointer and the file are pinned to each other.
    The seven sections are pinned in order: they are a sequence — kill policy
    decides what the rest of the doctrine is even for — and a section quietly
    dropped from the middle would otherwise leave the pointer's one-sentence
    summary promising content that is gone.
    """

    REFERENCE = SKILLS / "preparing-tests" / "references" / "test-generation.md"
    POINTER = "references/test-generation.md"

    # A stable phrase from each section, in the order the file must carry
    # them. Matched against the flattened text, since these files are
    # hard-wrapped and a heading's neighbours move whenever a paragraph above
    # them is reflowed.
    SECTIONS = (
        "## Kill policy by format",
        "## Subtask separation",
        "## Parameter saturation",
        "## Brute-kill table",
        "## Shape catalogue",
        "## Corners present but rare",
        "## Multi-test `T` policy",
    )

    # Claims inside those sections that the brief's correctness turns on, and
    # which a later editor could plausibly "simplify" back into being wrong.
    CLAIMS = (
        # OI-style partial credit is the half that gets lost first.
        '"Kill everything" is wrong here',
        # The undersized-group leak, stated concretely.
        "never exceed `n = 5000`",
        # Saturation and the reaching check are different properties.
        "Saturation is not the reaching check",
        # The fork claimed a random tree is ~log N tall. Both facts, and the
        # conclusion that a bamboo is needed regardless, are load-bearing.
        "has height `Θ(√N)`",
        "a bamboo is required either way",
        # The one rule that cannot be softened into a convenience.
        "Never invent a Σ-constraint the statement does not state",
    )

    def body(self) -> str:
        self.assertTrue(self.REFERENCE.is_file(),
                        f"{self.REFERENCE} is missing, but "
                        f"preparing-tests/SKILL.md tells the reader to open it")
        text = self.REFERENCE.read_text(encoding="utf-8")
        # Extractor guard, as elsewhere in this module: a truncated read must
        # not make the ordering assertion below trivially pass.
        self.assertGreater(len(text), 1000,
                           f"{self.REFERENCE} read back nearly empty")
        return text

    def test_the_skill_points_at_the_reference(self):
        self.assertIn(self.POINTER, flatten(skill_text("preparing-tests")),
                      "preparing-tests/SKILL.md no longer sends the reader to "
                      "the generator-design reference before it lists the "
                      "five families")

    def test_the_reference_carries_every_section_in_order(self):
        text = self.body()
        positions = []
        for heading in self.SECTIONS:
            with self.subTest(section=heading):
                # `assertNotEqual` on `find`, not `assertIn`: an assertIn
                # failure would print the whole reference around the one
                # heading that is missing.
                where = text.find(heading)
                self.assertNotEqual(
                    where, -1,
                    f"{self.REFERENCE.name} no longer carries the "
                    f"{heading!r} section, which SKILL.md's pointer promises")
                positions.append(where)
        self.assertEqual(
            positions, sorted(positions),
            f"the sections of {self.REFERENCE.name} have been reordered; "
            f"the doctrine reads as a sequence, so keep them in the order "
            f"{list(self.SECTIONS)}")

    def test_the_corrected_claims_survive(self):
        flat = flatten(self.body())
        for claim in self.CLAIMS:
            with self.subTest(claim=claim):
                self.assertTrue(
                    flatten(claim) in flat,
                    f"{self.REFERENCE.name} no longer states {claim!r}. Each "
                    f"of these is a correction over the doctrine as it was "
                    f"first written — fix the prose, do not relax this test.")

    def test_the_reference_reinforces_the_reaching_check(self):
        # The doctrine this reference was adapted from downgraded the
        # reaching check to optional. Pinned positively — the sentence that
        # hands authority back to SKILL.md's loop — rather than as a
        # blacklist of softening words: a substring guard that also fires on
        # a future *true* sentence gets deleted rather than obeyed, which is
        # the lesson RETIRED_CLAIMS above is annotated with.
        self.assertIn(
            "treat its output as the answer", flatten(self.body()),
            f"{self.REFERENCE.name} no longer defers to SKILL.md's "
            f"reaching-check loop as the authority on which bounds are "
            f"reached. Saturation is a design target; the union of the "
            f"per-test logs is the evidence, and the reference must not "
            f"leave a reader thinking the first substitutes for the second.")

    def test_the_reference_does_not_grow_its_own_copy_of_the_recipe(self):
        # The recipe is pinned byte-for-byte between two SKILL.md files by
        # TestReachingCheckRecipeDoesNotDrift. A third copy here would drift
        # out from under that pin, since nothing would be holding it. Scoped
        # to ```bash blocks — the same shape `recipe()` uses — so that prose
        # naming the flag, which the reference legitimately does, is fine.
        for block in [m.group("body")
                      for m in _FENCE.finditer(self.body())
                      if m.group("lang") == "bash"]:
            self.assertNotIn(
                "--testOverviewLogFileName", block,
                f"{self.REFERENCE.name} carries a runnable copy of the "
                f"reaching-check recipe. That recipe is pinned "
                f"byte-for-byte between preparing-tests and "
                f"reviewing-problems; a third copy is held by nothing. "
                f"Link to ../SKILL.md#reaching-check instead.")


if __name__ == "__main__":
    unittest.main()


class TestReadmeLayoutMatchesDisk(unittest.TestCase):
    """The root README's layout tree is a claim about what is on disk.

    It drifted once already: `tools/box_pool.py` was added, discussed at
    length in the README's own prose, and never entered the tree. Nothing
    held the two together, so this does.
    """

    README = (ROOT / "README.md").read_text(encoding="utf-8")

    def _layout_block(self) -> str:
        blocks = [m.group("body") for m in _FENCE.finditer(self.README)
                  if "competitive-programming/" in m.group("body")]
        self.assertEqual(len(blocks), 1, "expected exactly one layout tree in README.md")
        return blocks[0]

    def test_every_tools_module_is_in_the_layout_tree(self):
        tree = self._layout_block()
        modules = sorted(p.name for p in (ROOT / "tools").iterdir()
                         if p.suffix in {".py", ".sh"} and p.name != "__init__.py")
        self.assertTrue(modules)
        missing = [m for m in modules if m not in tree]
        self.assertEqual(missing, [], f"tools files absent from README layout: {missing}")

    def test_every_skill_directory_is_in_the_layout_tree(self):
        tree = self._layout_block()
        skills = sorted(p.name for p in SKILLS.iterdir() if (p / "SKILL.md").is_file())
        self.assertEqual(len(skills), 8)
        missing = [s for s in skills if f"{s}/SKILL.md" not in tree]
        self.assertEqual(missing, [], f"skills absent from README layout: {missing}")

    def test_the_layout_tree_names_nothing_that_is_not_on_disk(self):
        tree = self._layout_block()
        named = re.findall(r"\b([a-z_]+\.(?:py|sh))\b", tree)
        ghosts = [n for n in named if not (ROOT / "tools" / n).exists()
                  and not (ROOT / "mcp-server" / n).exists()]
        self.assertEqual(ghosts, [], f"README layout names files that do not exist: {ghosts}")


class TestServerEnvTableMatchesConfig(unittest.TestCase):
    """The root README says `mcp-server/README.md` owns the environment-variable
    table and `.env.example` mirrors it. Both are claims about `config.py`, which
    is the only thing that actually reads the environment, so check all three
    against each other. `CF_MCP_TIMEOUT` had been read by config.py and listed in
    `.env.example` while absent from the README table.
    """

    SERVER = ROOT / "mcp-server"
    CONFIG = (SERVER / "src" / "cf_mcp" / "config.py").read_text(encoding="utf-8")
    README = (SERVER / "README.md").read_text(encoding="utf-8")
    ENV_EXAMPLE = (SERVER / ".env.example").read_text(encoding="utf-8")

    _NAME = r"(?:CODEFORCES|CF_MCP|CF)_[A-Z_]+"

    def _config_names(self) -> set[str]:
        return set(re.findall(rf'"({self._NAME})"', self.CONFIG))

    def _table_names(self) -> set[str]:
        return set(re.findall(rf"^\| `({self._NAME})` \|", self.README, re.MULTILINE))

    def _env_example_names(self) -> set[str]:
        return set(re.findall(rf"^#? ?({self._NAME})=", self.ENV_EXAMPLE, re.MULTILINE))

    def test_every_name_config_reads_is_mentioned_in_the_server_readme(self):
        missing = sorted(n for n in self._config_names() if n not in self.README)
        self.assertEqual(missing, [], f"config.py reads variables the README never mentions: {missing}")

    def test_the_readme_table_and_env_example_list_the_same_variables(self):
        self.assertEqual(self._table_names(), self._env_example_names())

    def test_the_readme_table_lists_only_variables_config_reads(self):
        ghosts = sorted(self._table_names() - self._config_names())
        self.assertEqual(ghosts, [], f"README documents variables config.py does not read: {ghosts}")

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools import flags

FIXED = datetime(2026, 7, 30, 14, 2, 11, tzinfo=timezone(timedelta(hours=7)))


class TestAppend(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def append(self, **overrides):
        payload = dict(
            phase="prepare-tests",
            severity="high",
            kind="statement-ambiguity",
            what='"xâu con" reads as substring or as subsequence',
            assumed="substring (contiguous)",
            changes_if_wrong="sol-main, gen-boundary, 3 tests in g1",
            now=FIXED,
        )
        payload.update(overrides)
        return flags.append(self.dir, **payload)

    def test_writes_record_with_derived_id_and_timestamp(self):
        record = self.append()
        self.assertEqual(record["id"], "amb-001")
        self.assertEqual(record["at"], "2026-07-30T14:02:11+07:00")
        self.assertEqual(record["severity"], "high")

    def test_numbers_within_a_prefix_independently(self):
        self.append()
        self.append()
        third = self.append(kind="algorithm-choice", severity="medium")
        fourth = self.append()
        self.assertEqual(third["id"], "alg-001")
        self.assertEqual(fourth["id"], "amb-003")

    def test_read_returns_every_record_in_order(self):
        self.append()
        self.append(kind="timing-band", severity="low")
        ids = [r["id"] for r in flags.read(self.dir)]
        self.assertEqual(ids, ["amb-001", "tim-001"])

    def test_file_is_valid_json_with_generated_at(self):
        self.append()
        payload = json.loads((self.dir / "flags.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], 1)
        self.assertIn("generated_at", payload)
        self.assertEqual(len(payload["flags"]), 1)

    def test_rejects_unknown_kind(self):
        with self.assertRaisesRegex(flags.FlagError, "vibes"):
            self.append(kind="vibes")

    def test_rejects_unknown_severity(self):
        with self.assertRaisesRegex(flags.FlagError, "catastrophic"):
            self.append(severity="catastrophic")

    def test_rejects_empty_changes_if_wrong(self):
        with self.assertRaisesRegex(flags.FlagError, "changes_if_wrong"):
            self.append(changes_if_wrong="")

    def test_read_rejects_non_dict_top_level(self):
        (self.dir / "flags.json").write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(flags.FlagError, "top-level must be dict"):
            flags.read(self.dir)

    def test_append_rejects_corrupted_record_missing_id(self):
        payload = {
            "schema": 1,
            "flags": [{"phase": "x"}],
            "generated_at": "2026-07-30T14:02:11+07:00",
        }
        (self.dir / "flags.json").write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(flags.FlagError, "id"):
            self.append()

    def test_append_creates_missing_problem_directory(self):
        new_dir = self.dir / "nonexistent" / "path"
        self.assertFalse(new_dir.exists())
        record = flags.append(
            new_dir,
            phase="test",
            severity="low",
            kind="statement-ambiguity",
            what="test",
            assumed="test",
            changes_if_wrong="test",
            now=FIXED,
        )
        self.assertTrue(new_dir.exists())
        self.assertEqual(record["id"], "amb-001")

    def test_corrupt_json_is_a_flag_error_not_a_json_decode_error(self):
        # R1: this register is read after arbitrary interruptions and is
        # small enough that a human edits it.
        (self.dir / "flags.json").write_text('{"schema": 1, "flags": [',
                                             encoding="utf-8")
        with self.assertRaisesRegex(flags.FlagError, "not valid JSON"):
            flags.read(self.dir)

    def test_non_string_id_is_a_flag_error_not_an_attribute_error(self):
        payload = {"schema": 1, "generated_at": "x", "flags": [{"id": 7}]}
        (self.dir / "flags.json").write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(flags.FlagError, "expected a string"):
            flags.read(self.dir)


_APPENDER = """
import sys
sys.path.insert(0, {root!r})
from tools import flags
for i in range({n}):
    flags.append({dir!r}, phase="p", severity="low", kind="review-judgement",
                 what="w%d" % i, assumed="a", changes_if_wrong="c")
"""


class TestConcurrentAppend(unittest.TestCase):
    """Two processes appending at once must not lose records.

    Measured against the previous implementation (a fixed
    `flags.json.tmp` shared by every writer, and an unguarded
    read-modify-write): 2 processes x 40 appends produced
    `FileNotFoundError: 'flags.json.tmp' -> 'flags.json'` and 51 of 80
    records surviving. Both skills that write here instruct
    `superpowers:dispatching-parallel-agents`, and
    `validating-solutions` asks agents to record skipped zoo rows as
    flags — a register that exists to make judgement calls durable
    cannot drop 36% of them.
    """

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_two_processes_forty_appends_each_lose_nothing(self):
        root = str(Path(__file__).resolve().parents[2])
        n, procs = 40, 4
        script = _APPENDER.format(root=root, n=n, dir=str(self.dir))
        children = [subprocess.Popen([sys.executable, "-c", script],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
                    for _ in range(procs)]
        for child in children:
            _, err = child.communicate(timeout=120)
            self.assertEqual(child.returncode, 0, err.decode())

        recorded = flags.read(self.dir)
        self.assertEqual(len(recorded), n * procs)
        # Ids must also be unique: two writers that both read the same
        # `existing` would each number their record identically.
        self.assertEqual(len(({r["id"] for r in recorded})), n * procs)

    def test_no_temp_file_is_left_behind(self):
        flags.append(self.dir, phase="p", severity="low",
                     kind="review-judgement", what="w", assumed="a",
                     changes_if_wrong="c")
        leftovers = [p.name for p in self.dir.iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()

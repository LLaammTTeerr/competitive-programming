import json
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


if __name__ == "__main__":
    unittest.main()

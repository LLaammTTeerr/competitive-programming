import json
import tempfile
import unittest
from pathlib import Path

from tools.polygon_ref import (FILENAME, SCHEMA, PolygonRef, PolygonRefError,
                               load, path_for, save)

GOOD = {
    "schema": SCHEMA,
    "id": 123456,
    "owner": "setter",
    "url": "https://polygon.codeforces.com/p/setter/sample-problem",
    "committed_at": None,
}


class PolygonRefTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, payload) -> Path:
        path = self.dir / FILENAME
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


class TestLoadAbsent(PolygonRefTestCase):
    """Absent is the ordinary state, and the only one that reads as None."""

    def test_no_file_reads_as_none(self):
        self.assertIsNone(load(self.dir))

    def test_a_directory_that_does_not_exist_reads_as_none(self):
        # A caller may hold a path to a package that was never created; that
        # is "not on Polygon", not a crash on the way to a stop-or-resync
        # question.
        self.assertIsNone(load(self.dir / "no-such-package"))


class TestLoadValid(PolygonRefTestCase):
    def test_a_valid_record_loads(self):
        self.write(GOOD)
        ref = load(self.dir)
        self.assertEqual(ref.id, 123456)
        self.assertEqual(ref.owner, "setter")
        self.assertEqual(ref.url, GOOD["url"])
        # Absent until a revision has actually been committed.
        self.assertIsNone(ref.committed_at)

    def test_a_missing_committed_at_key_is_the_same_as_null(self):
        payload = dict(GOOD)
        del payload["committed_at"]
        self.write(payload)
        self.assertIsNone(load(self.dir).committed_at)

    def test_committed_at_loads_with_an_offset(self):
        for stamp in ("2026-09-04T11:22:33Z",
                      "2026-09-04T11:22:33+00:00",
                      "2026-09-04T18:22:33+07:00"):
            with self.subTest(committed_at=stamp):
                self.write(dict(GOOD, committed_at=stamp))
                self.assertEqual(load(self.dir).committed_at, stamp)


class TestLoadRejects(PolygonRefTestCase):
    """Every malformed shape raises, naming the field.

    A record read as absent because it was malformed would send the upload
    skill off to create a second Polygon problem for a package that already
    has one — the one failure this file exists to prevent.
    """

    def test_rejects_a_file_that_is_not_json(self):
        (self.dir / FILENAME).write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(PolygonRefError, "not valid JSON"):
            load(self.dir)

    def test_rejects_a_top_level_that_is_not_an_object(self):
        for bad in (123456, "123456", [123456], None):
            with self.subTest(value=bad):
                self.write(bad)
                with self.assertRaisesRegex(PolygonRefError, "expected an object"):
                    load(self.dir)

    def test_rejects_a_wrong_or_missing_schema(self):
        for bad in (SCHEMA + 1, "1", None):
            with self.subTest(schema=bad):
                self.write(dict(GOOD, schema=bad))
                with self.assertRaisesRegex(PolygonRefError, "schema"):
                    load(self.dir)
        payload = dict(GOOD)
        del payload["schema"]
        self.write(payload)
        with self.assertRaisesRegex(PolygonRefError, "schema"):
            load(self.dir)

    def test_rejects_a_missing_field(self):
        for field in ("id", "owner", "url"):
            with self.subTest(missing=field):
                payload = dict(GOOD)
                del payload[field]
                self.write(payload)
                with self.assertRaisesRegex(PolygonRefError, f"{field} is missing"):
                    load(self.dir)

    def test_rejects_a_non_positive_id(self):
        for bad in (0, -1, -123456):
            with self.subTest(id=bad):
                self.write(dict(GOOD, id=bad))
                with self.assertRaisesRegex(PolygonRefError, "id is"):
                    load(self.dir)

    def test_rejects_wrong_types(self):
        for field, bad in (("id", "123456"), ("id", 1.5), ("id", True),
                            ("id", None), ("owner", 7), ("owner", None),
                            ("url", 7), ("url", None),
                            ("committed_at", 1717171717)):
            with self.subTest(field=field, value=bad):
                self.write(dict(GOOD, **{field: bad}))
                with self.assertRaisesRegex(PolygonRefError, field):
                    load(self.dir)

    def test_rejects_an_empty_owner_or_url(self):
        for field in ("owner", "url"):
            for bad in ("", "   "):
                with self.subTest(field=field, value=bad):
                    self.write(dict(GOOD, **{field: bad}))
                    with self.assertRaisesRegex(PolygonRefError, field):
                        load(self.dir)

    def test_rejects_a_committed_at_that_is_not_rfc_3339(self):
        for bad in ("yesterday", "2026-13-04T11:22:33Z", "1717171717"):
            with self.subTest(committed_at=bad):
                self.write(dict(GOOD, committed_at=bad))
                with self.assertRaisesRegex(PolygonRefError, "committed_at"):
                    load(self.dir)

    def test_rejects_a_committed_at_with_no_offset(self):
        # It is compared against file mtimes, possibly on another machine,
        # so "some local time somewhere" would silently skip a changed file.
        self.write(dict(GOOD, committed_at="2026-09-04T11:22:33"))
        with self.assertRaisesRegex(PolygonRefError, "offset"):
            load(self.dir)


class TestSave(PolygonRefTestCase):
    def test_save_then_load_round_trips(self):
        ref = PolygonRef(id=99, owner="setter", url="https://example/p/99",
                         committed_at="2026-09-04T11:22:33Z")
        save(self.dir, ref)
        self.assertEqual(load(self.dir), ref)

    def test_save_writes_the_schema_and_every_field(self):
        save(self.dir, PolygonRef(id=99, owner="setter",
                                  url="https://example/p/99"))
        payload = json.loads(path_for(self.dir).read_text(encoding="utf-8"))
        self.assertEqual(payload, {"schema": SCHEMA, "id": 99,
                                   "owner": "setter",
                                   "url": "https://example/p/99",
                                   "committed_at": None})

    def test_save_replaces_an_earlier_record(self):
        save(self.dir, PolygonRef(id=99, owner="setter", url="https://example/p/99"))
        save(self.dir, PolygonRef(id=99, owner="setter", url="https://example/p/99",
                                  committed_at="2026-09-04T11:22:33Z"))
        self.assertEqual(load(self.dir).committed_at, "2026-09-04T11:22:33Z")

    def test_save_refuses_what_load_would_refuse(self):
        # `save` validating by `load`'s rules is what keeps the two from
        # drifting into a file this module writes and then cannot read.
        for ref in (PolygonRef(id=0, owner="setter", url="https://example/p/0"),
                     PolygonRef(id=99, owner="", url="https://example/p/99"),
                     PolygonRef(id=99, owner="setter", url=""),
                     PolygonRef(id=99, owner="setter", url="https://example/p/99",
                                committed_at="yesterday")):
            with self.subTest(ref=ref):
                with self.assertRaises(PolygonRefError):
                    save(self.dir, ref)

    def test_a_refused_save_leaves_no_temp_file_behind(self):
        with self.assertRaises(PolygonRefError):
            save(self.dir, PolygonRef(id=0, owner="setter", url="https://x/p"))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [])

    def test_save_leaves_no_temp_file_behind_on_success(self):
        save(self.dir, PolygonRef(id=99, owner="setter", url="https://example/p/99"))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [FILENAME])

    def test_the_written_file_is_utf8_and_not_ascii_escaped(self):
        save(self.dir, PolygonRef(id=99, owner="đặt-đề", url="https://example/p/99"))
        self.assertIn("đặt-đề", path_for(self.dir).read_text(encoding="utf-8"))
        self.assertEqual(load(self.dir).owner, "đặt-đề")


if __name__ == "__main__":
    unittest.main()
